import hashlib
import io
import json
import os
import re
import secrets
import shutil
import time
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from werkzeug.utils import secure_filename

# ----------------------------------------------------------------------
# الإعدادات
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)          # على Railway: /data (الـ Volume)
DB_PATH = os.path.join(DATA_DIR, "store.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
RECEIPT_DIR = os.path.join(DATA_DIR, "receipts")         # خارج /media: لا يفتحها إلا صاحب المتجر
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")    # بدونها تبقى لوحة التحكم مقفلة
STORE_NAME = os.environ.get("STORE_NAME", "أبو ميثه")
TZ = ZoneInfo("Asia/Muscat")
ALLOWED_IMAGES = {"jpg", "jpeg", "png", "webp"}
ALLOWED_RECEIPTS = ALLOWED_IMAGES | {"heic", "pdf"}
# صور إضافية للمعرض: لقطات مقرّبة من صورة المنتج الأصلية
# صور إضافية لمعرض المنتج الأول (السمن): صورة الغراش الأربع ولقطات مقرّبة
EXTRA_GALLERY = [("img/hero-kitchen.webp", "من المطبخ العماني"), ("img/hero-group.webp", "الغراش"),
                 ("img/close-tray.webp", "السمن على الصينية"), ("img/close-label.webp", "الملصق")]

# حالات الطلب بالترتيب
PENDING = "بانتظار التحويل"
RECEIPT = "تم إرسال الإيصال"
PAID = "تم استلام التحويل"
PREPARING = "قيد التجهيز"
SHIPPED = "خرج للتوصيل"
DELIVERED = "تم التسليم"
CANCELLED = "ملغي"
STATUSES = [PENDING, RECEIPT, PAID, PREPARING, SHIPPED, DELIVERED, CANCELLED]
CONFIRMED = (PAID, PREPARING, SHIPPED, DELIVERED)
STATUS_KEY = {PENDING: "pending", RECEIPT: "receipt", PAID: "paid", PREPARING: "preparing",
              SHIPPED: "shipped", DELIVERED: "delivered", CANCELLED: "cancelled"}

OMAN = {
    "مسقط": ["مسقط", "مطرح", "بوشر", "السيب", "العامرات", "قريات"],
    "ظفار": ["صلالة", "طاقة", "مرباط", "رخيوت", "ثمريت", "ضلكوت", "المزيونة", "مقشن", "شليم وجزر الحلانيات", "سدح"],
    "مسندم": ["خصب", "دبا", "بخا", "مدحاء"],
    "البريمي": ["البريمي", "محضة", "السنينة"],
    "الداخلية": ["نزوى", "بهلا", "منح", "الحمراء", "أدم", "إزكي", "سمائل", "بدبد", "الجبل الأخضر"],
    "شمال الباطنة": ["صحار", "شناص", "لوى", "صحم", "الخابورة", "السويق"],
    "جنوب الباطنة": ["الرستاق", "العوابي", "نخل", "وادي المعاول", "بركاء", "المصنعة"],
    "جنوب الشرقية": ["صور", "الكامل والوافي", "جعلان بني بو حسن", "جعلان بني بو علي", "مصيرة"],
    "شمال الشرقية": ["إبراء", "المضيبي", "بدية", "القابل", "وادي بني خالد", "دماء والطائيين"],
    "الظاهرة": ["عبري", "ينقل", "ضنك"],
    "الوسطى": ["هيما", "محوت", "الدقم", "الجازر"],
}

# قيم البداية: كلها قابلة للتعديل من لوحة التحكم ← الإعدادات
DEFAULT_SETTINGS = {
    "whatsapp": "",
    "bank_name": "",
    "account_name": "",
    "account_number": "",
    "transfer_phone": "",                             # رقم الهاتف المسجّل للتحويل من تطبيق البنك
    "delivery_default": "2000",                       # بالبيسة
    "delivery_fees": json.dumps({"مسقط": 1500}, ensure_ascii=False),
    "free_over": "20000",                             # توصيل مجاني فوق ٢٠ ر.ع (٠ = بدون)
}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
# الكوكي عبر HTTPS فقط على Railway، ولا تُرسل من مواقع ثانية
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=bool(os.environ.get("RAILWAY_ENVIRONMENT")))


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Frame-Options", "DENY")                  # ما ينعرض المتجر داخل موقع ثاني
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if app.config["SESSION_COOKIE_SECURE"]:                              # على Railway: المتصفح يفتح المتجر عبر HTTPS دائماً
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


# حد للمحاولات الخاطئة (دخول الإدارة وتتبّع الطلب) حتى ما ينخمّن الرمز بالتكرار
_failures = {}


def too_many(kind, limit=5, window=15 * 60):
    key = (kind, request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip())
    now = time.time()
    _failures[key] = [t for t in _failures.get(key, []) if now - t < window]
    return len(_failures[key]) >= limit, key


def record_failure(key):
    _failures.setdefault(key, []).append(time.time())


def safe_back(url, fallback):
    """يرجّع للصفحة اللي جا منها الزبون، بس داخل المتجر فقط"""
    return url if url and url.startswith("/") and not url.startswith("//") and "\\" not in url else fallback


# ----------------------------------------------------------------------
# قاعدة البيانات
# ----------------------------------------------------------------------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(RECEIPT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, tagline TEXT DEFAULT '',
            description TEXT DEFAULT '', image TEXT DEFAULT '', active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS variants (
            id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            label TEXT NOT NULL, price INTEGER NOT NULL, stock INTEGER, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,
            governorate TEXT NOT NULL, wilaya TEXT NOT NULL, address TEXT DEFAULT '', notes TEXT DEFAULT '',
            subtotal INTEGER NOT NULL, delivery INTEGER NOT NULL, total INTEGER NOT NULL,
            status TEXT NOT NULL, admin_note TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            variant_id INTEGER, product_name TEXT NOT NULL, variant_label TEXT NOT NULL,
            price INTEGER NOT NULL, qty INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    """)
    # أعمدة الإيصال (تُضاف لقواعد البيانات القديمة بدون ما تضيع الطلبات)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
    for col in ("receipt", "receipt_at", "sender_name", "receipt_hash", "transfer_ref"):
        if col not in cols:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {col} TEXT DEFAULT ''")
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    # أول تشغيل: السمن العماني بحجمين وأسعار إعلان المتجر، مع صورة الغراش الحقيقية
    # الصورة تنسخ لمجلد الرفع باسم فيه رقم نسخة، نغيّره كل ما تتحدث صورة الغرشة عشان المتصفحات ما تعرض القديمة
    seed_src, image = os.path.join(BASE_DIR, "static", "img", "product-single.webp"), "product-single-2.webp"
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        shutil.copyfile(seed_src, os.path.join(UPLOAD_DIR, image))
        pid = conn.execute(
            "INSERT INTO products (name, tagline, description, image, sort) VALUES (?, ?, ?, ?, 0)",
            ("سمن عُماني أصلي", "ميه بالميه ولذيذ، والريحة خيال",
             "سمن عُماني أصلي ١٠٠٪ من أرض عُمان. طعم لذيذ وجودة عالية، ومناسب لجميع الأكلات: "
             "العرسية والهريس واللقيمات والخبز والعيش.", image),
        ).lastrowid
        for i, (label, price) in enumerate([("غرشة كبيرة (فيمتو أو تانج)", 5000), ("غرشة صغيرة", 3000)]):
            conn.execute("INSERT INTO variants (product_id, label, price, sort) VALUES (?, ?, ?, ?)", (pid, label, price, i))
    # متجر قائم بصورة الغرشة القديمة (الافتراضية أو نفس الصورة القديمة مرفوعة من اللوحة): بدّلها بالجديدة.
    # المطابقة بالبصمة، فأي صورة ثانية يرفعها التاجر ما تنلمس
    else:
        old_photos = {"4494cc8484776d436375ccf837d008f0ebd3057693c97208c94b62628bd1273d"}
        for pid, img in conn.execute("SELECT id, image FROM products").fetchall():
            path = os.path.join(UPLOAD_DIR, img or "")
            if img == "product-single.webp" or (img and os.path.isfile(path) and
                                                hashlib.sha256(open(path, "rb").read()).hexdigest() in old_photos):
                if not os.path.isfile(os.path.join(UPLOAD_DIR, image)):
                    shutil.copyfile(seed_src, os.path.join(UPLOAD_DIR, image))
                conn.execute("UPDATE products SET image = ? WHERE id = ?", (image, pid))
    conn.commit()
    conn.close()


def setting(key):
    row = db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def delivery_fee(gov, subtotal):
    free_over = int(setting("free_over") or 0)
    if free_over and subtotal >= free_over:
        return 0
    fees = json.loads(setting("delivery_fees") or "{}")
    return int(fees.get(gov, setting("delivery_default") or 0))


def now_oman():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def order_code(oid):
    return f"AM-{1000 + oid}"


def code_to_id(code):
    code = (code or "").strip().upper().replace(" ", "")
    if code.startswith("AM-"):
        code = code[3:]
    return int(code) - 1000 if code.isdigit() else None


def clean_phone(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 8:
        digits = "968" + digits
    return digits


def wa_link(number, text):
    return f"https://wa.me/{clean_phone(number)}?text={urllib.parse.quote(text)}"


# ----------------------------------------------------------------------
# القوالب: دوال مساعدة
# ----------------------------------------------------------------------
@app.template_filter("omr")
def omr(baisa):
    """البيسة إلى ريال عماني بثلاث خانات: 6500 → 6.500"""
    return f"{(baisa or 0) / 1000:,.3f}"


@app.context_processor
def common():
    return {"store_name": STORE_NAME, "cart_count": sum(session.get("cart", {}).values()),
            "STATUS_KEY": STATUS_KEY, "csrf": csrf_token(), "free_over": int(setting("free_over") or 0),
            "store_wa": clean_phone(setting("whatsapp")) if setting("whatsapp") else ""}


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        token, expected = request.form.get("csrf"), session.get("csrf")
        if not token or not expected or not secrets.compare_digest(token, expected):   # الاثنين لازم موجودين ومتطابقين
            abort(400)


# ----------------------------------------------------------------------
# السلة
# ----------------------------------------------------------------------
def cart_lines():
    cart = session.get("cart", {})
    if not cart:
        return [], 0
    ids = [int(k) for k in cart]
    rows = db().execute(
        f"""SELECT v.id, v.label, v.price, v.stock, p.name, p.image FROM variants v
            JOIN products p ON p.id = v.product_id
            WHERE v.id IN ({','.join('?' * len(ids))}) AND v.active = 1 AND p.active = 1""", ids).fetchall()
    lines = []
    for r in rows:
        qty = cart[str(r["id"])]
        lines.append({"id": r["id"], "name": r["name"], "label": r["label"], "price": r["price"],
                      "image": r["image"], "stock": r["stock"], "qty": qty, "total": r["price"] * qty})
    return lines, sum(line["total"] for line in lines)


def wants_json():
    return request.headers.get("X-Requested-With") == "fetch"


def cart_json(message=""):
    """رد السلة الجانبية: العدد وHTML المحتوى"""
    lines, subtotal = cart_lines()
    return jsonify(count=sum(session.get("cart", {}).values()), message=message,
                   html=render_template("_drawer.html", lines=lines, subtotal=subtotal))


app.jinja_env.globals["cart_lines"] = cart_lines


@app.route("/cart/drawer")
def cart_drawer():
    return cart_json()


@app.route("/cart/add", methods=["POST"])
def cart_add():
    vid = request.form.get("variant", "")
    qty = max(1, min(50, int(request.form.get("qty", "1") or 1)))
    if not db().execute("SELECT 1 FROM variants WHERE id = ? AND active = 1", (vid,)).fetchone():
        if wants_json():
            return jsonify(error="اختر الحجم أولاً"), 400
        flash("اختر الحجم أولاً")
        return redirect(request.referrer or url_for("home"))
    cart = session.get("cart", {})
    cart[vid] = min(50, cart.get(vid, 0) + qty)
    session["cart"] = cart
    go = request.form.get("go")
    if go == "checkout":
        return redirect(url_for("checkout"))
    if wants_json():
        return cart_json("أُضيف إلى السلة")
    flash("أُضيف إلى السلة")
    return redirect(url_for("cart") if go == "cart" else (request.referrer or url_for("home")))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    cart = session.get("cart", {})
    vid = request.form.get("variant", "")
    qty = int(request.form.get("qty", "0") or 0)
    if qty <= 0:
        cart.pop(vid, None)
    else:
        cart[vid] = min(50, qty)
    session["cart"] = cart
    if wants_json():
        return cart_json()
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    lines, subtotal = cart_lines()
    return render_template("cart.html", lines=lines, subtotal=subtotal)


# ----------------------------------------------------------------------
# المتجر
# ----------------------------------------------------------------------
def products_with_variants(only_active=True):
    where = "WHERE active = 1" if only_active else ""
    products = [dict(p) for p in db().execute(f"SELECT * FROM products {where} ORDER BY sort, id")]
    for p in products:
        vwhere = "AND active = 1" if only_active else ""
        p["variants"] = [dict(v) for v in db().execute(
            f"SELECT * FROM variants WHERE product_id = ? {vwhere} ORDER BY sort, id", (p["id"],))]
        prices = [v["price"] for v in p["variants"]]
        p["from_price"] = min(prices) if prices else 0
    return products


@app.route("/")
def home():
    products = products_with_variants()
    extras = [(url_for("static", filename=f), cap) for f, cap in EXTRA_GALLERY]
    return render_template("home.html", products=products, extras=extras)


@app.route("/p/<int:pid>")
def product(pid):
    p = next((p for p in products_with_variants() if p["id"] == pid), None)
    if not p:
        abort(404)
    gallery = ([(url_for("media", name=p["image"]), p["name"])] if p["image"] else []) + \
              ([(url_for("static", filename=f), cap) for f, cap in EXTRA_GALLERY] if p == products_with_variants()[0] else [])
    return render_template("product.html", p=p, gallery=gallery)


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    lines, subtotal = cart_lines()
    if not lines:
        return redirect(url_for("cart"))
    form = request.form
    if request.method == "POST":
        if form.get("website"):                      # حقل مخفي يملؤه السبام فقط
            abort(400)
        name, phone = form.get("name", "").strip(), form.get("phone", "").strip()
        gov, wilaya = form.get("governorate", ""), form.get("wilaya", "")
        address, notes = form.get("address", "").strip(), form.get("notes", "").strip()
        error = None
        if not name or len(clean_phone(phone)) < 11:
            error = "اكتب اسمك ورقم هاتف عماني صحيح (٨ أرقام)"
        elif gov not in OMAN or wilaya not in OMAN[gov]:
            error = "اختر المحافظة والولاية"
        elif not address:
            error = "اكتب عنوان التوصيل (المنطقة، رقم البيت أو أقرب معلم)"
        for line in lines:
            if line["stock"] is not None and line["qty"] > line["stock"]:
                error = f"الكمية المتوفرة من {line['name']} ({line['label']}) هي {line['stock']} فقط"
        if error:
            flash(error)
        else:
            delivery = delivery_fee(gov, subtotal)
            conn = db()
            # الرقم يكمل بعد أكبر رقم انحذف، عشان رقم طلب قديم محفوظ عند أحد ما يفتح طلب زبون جديد
            oid = conn.execute(
                """INSERT INTO orders (id, created_at, name, phone, governorate, wilaya, address, notes,
                   subtotal, delivery, total, status) VALUES (
                   MAX(COALESCE((SELECT MAX(id) FROM orders), 0),
                       COALESCE((SELECT CAST(value AS INTEGER) FROM settings WHERE key = 'last_order_id'), 0)) + 1,
                   ?,?,?,?,?,?,?,?,?,?,?)""",
                (now_oman(), name, phone, gov, wilaya, address, notes, subtotal, delivery, subtotal + delivery, PENDING),
            ).lastrowid
            for line in lines:
                conn.execute("""INSERT INTO order_items (order_id, variant_id, product_name, variant_label, price, qty)
                                VALUES (?,?,?,?,?,?)""",
                             (oid, line["id"], line["name"], line["label"], line["price"], line["qty"]))
                conn.execute("UPDATE variants SET stock = stock - ? WHERE id = ? AND stock IS NOT NULL",
                             (line["qty"], line["id"]))
            conn.commit()
            session["cart"] = {}
            session.setdefault("my_orders", [])
            session["my_orders"] = (session["my_orders"] + [oid])[-20:]
            return redirect(url_for("order_done", code=order_code(oid)))
    fees = {g_: delivery_fee(g_, subtotal) for g_ in OMAN}
    return render_template("checkout.html", lines=lines, subtotal=subtotal, oman=OMAN, fees=fees, form=form)


def load_order(oid):
    order = db().execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if not order:
        return None, []
    items = db().execute("SELECT * FROM order_items WHERE order_id = ?", (oid,)).fetchall()
    return dict(order), items


def receipt_message(order, items):
    lines = [f"السلام عليكم، هذا إيصال التحويل لطلبي رقم {order_code(order['id'])}",
             f"الاسم: {order['name']}", f"المبلغ: {omr(order['total'])} ر.ع", ""]
    lines += [f"• {i['product_name']} ({i['variant_label']}) × {i['qty']}" for i in items]
    lines += ["", f"التوصيل إلى: {order['wilaya']}، {order['governorate']}"]
    return "\n".join(lines)


@app.route("/order/<code>")
def order_done(code):
    oid = code_to_id(code)
    if oid is None or oid not in session.get("my_orders", []):
        return redirect(url_for("track", code=code))
    order, items = load_order(oid)
    if not order:
        abort(404)
    bank = {k: setting(k) for k in ("bank_name", "account_name", "account_number", "transfer_phone")}
    wa = wa_link(setting("whatsapp"), receipt_message(order, items)) if setting("whatsapp") else ""
    return render_template("order_done.html", order=order, items=items, code=order_code(oid), bank=bank, wa=wa)


def clean_ref(ref):
    return re.sub(r"[^0-9A-Za-z]", "", ref or "").upper()


def receipt_conflicts(order):
    """طلبات ثانية لها نفس الإيصال: نفس رقم العملية أو نفس الملف بالضبط"""
    if not order.get("receipt"):
        return []
    found = []
    rows = db().execute("SELECT id, status, receipt_hash, transfer_ref FROM orders "
                        "WHERE id != ? AND receipt != ''", (order["id"],)).fetchall()
    for r in rows:
        if order.get("transfer_ref") and r["transfer_ref"] == order["transfer_ref"]:
            found.append((r["id"], r["status"], "نفس رقم العملية"))
        elif order.get("receipt_hash") and r["receipt_hash"] == order["receipt_hash"]:
            found.append((r["id"], r["status"], "نفس ملف الإيصال"))
    return found


@app.route("/order/<code>/receipt", methods=["POST"])
def upload_receipt(code):
    """الزبون يرفق صورة الإيصال، فتنربط بالطلب وتتغير حالته إلى «تم إرسال الإيصال»"""
    oid = code_to_id(code)
    if oid is None or oid not in session.get("my_orders", []):
        abort(403)
    order, _ = load_order(oid)
    if not order:
        abort(404)
    back = safe_back(request.form.get("back"), url_for("order_done", code=order_code(oid)))
    file = request.files.get("receipt")
    ext = file.filename.rsplit(".", 1)[-1].lower() if file and "." in file.filename else ""
    if not file or not file.filename:
        flash("اختر صورة الإيصال أولاً")
        return redirect(back)
    if ext not in ALLOWED_RECEIPTS:
        flash("الإيصال لازم يكون صورة (JPG أو PNG) أو ملف PDF")
        return redirect(back)
    ref = clean_ref(request.form.get("transfer_ref"))
    if len(ref) < 4:
        flash("اكتب رقم العملية (Reference) اللي في الإيصال")
        return redirect(back)
    data = file.read()
    digest = hashlib.sha256(data).hexdigest()
    # نفس رقم العملية أو نفس الملف على طلب ثاني = نفس التحويل، فما نقبله مرتين
    taken = db().execute("SELECT id FROM orders WHERE id != ? AND receipt != '' AND (transfer_ref = ? OR receipt_hash = ?)",
                         (oid, ref, digest)).fetchone()
    if taken:
        flash(f"هذا الإيصال مستخدم في طلب ثاني ({order_code(taken['id'])}). كل طلب يحتاج تحويل خاص فيه. "
              "إذا تبي تدفع طلبين بتحويل واحد، راسلنا على واتساب.")
        return redirect(back)
    name = f"{order_code(oid)}-{secrets.token_hex(6)}.{ext}"
    with open(os.path.join(RECEIPT_DIR, name), "wb") as fh:
        fh.write(data)
    new_status = RECEIPT if order["status"] == PENDING else order["status"]
    db().execute("""UPDATE orders SET receipt = ?, receipt_at = ?, sender_name = ?, status = ?,
                    receipt_hash = ?, transfer_ref = ? WHERE id = ?""",
                 (name, now_oman(), request.form.get("sender_name", "").strip()[:80], new_status, digest, ref, oid))
    db().commit()
    flash("استلمنا الإيصال، بنراجع التحويل ونأكد طلبك قريباً")
    return redirect(back)


@app.route("/order/<code>/invoice")
def invoice(code):
    """فاتورة الطلب: صفحة مهيأة للطباعة وحفظها PDF (للزبون صاحب الطلب أو صاحب المتجر)"""
    oid = code_to_id(code)
    if oid is None or not (session.get("admin") or oid in session.get("my_orders", [])):
        abort(403)
    order, items = load_order(oid)
    if not order:
        abort(404)
    paid = order["status"] in CONFIRMED
    return render_template("invoice.html", order=order, items=items, code=order_code(oid), paid=paid,
                           cancelled=order["status"] == CANCELLED, issued=now_oman(),
                           store_wa=clean_phone(setting("whatsapp")))


@app.route("/track", methods=["GET", "POST"])
def track():
    order, items, code = None, [], request.values.get("code", "")
    if request.method == "POST":
        blocked, key = too_many("track", limit=10)
        if blocked:
            flash("محاولات كثيرة. انتظر ربع ساعة وحاول مرة ثانية، أو راسلنا على واتساب.")
            return render_template("track.html", order=None, items=[], code=code,
                                   steps=STATUSES[:-1], wa_store=clean_phone(setting("whatsapp")))
        oid = code_to_id(code)
        found, found_items = load_order(oid) if oid else (None, [])
        # رقم الطلب + آخر ٤ أرقام من الهاتف، حتى لا يطّلع أحد على طلب غيره
        if found and clean_phone(found["phone"])[-4:] == clean_phone(request.form.get("phone", ""))[-4:]:
            order, items = found, found_items
            session["my_orders"] = (session.get("my_orders", []) + [oid])[-20:]   # يقدر يرفق الإيصال من هنا
        else:
            record_failure(key)
            flash("ما لقينا طلب بهذا الرقم والهاتف. تأكد من رقم الطلب (مثل AM-1001) ورقم الهاتف اللي طلبت فيه.")
    return render_template("track.html", order=order, items=items, code=code,
                           steps=STATUSES[:-1], wa_store=clean_phone(setting("whatsapp")))


# ----------------------------------------------------------------------
# لوحة التحكم
# ----------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        blocked, key = too_many("admin")
        if blocked:
            flash("محاولات خاطئة كثيرة. انتظر ربع ساعة وحاول مرة ثانية.")
        elif ADMIN_PASSWORD and secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin_orders"))
        else:
            record_failure(key)
            flash("كلمة المرور غير صحيحة")
    return render_template("admin/login.html", locked=not ADMIN_PASSWORD)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("home"))


@app.route("/admin")
@admin_required
def admin_orders():
    status = request.args.get("status", "")
    q = request.args.get("q", "").strip()
    sql, params = "SELECT * FROM orders WHERE 1=1", []
    if status in STATUSES:
        sql += " AND status = ?"
        params.append(status)
    if q:
        oid = code_to_id(q)
        sql += " AND (name LIKE ? OR phone LIKE ? OR id = ? OR transfer_ref LIKE ?)"
        params += [f"%{q}%", f"%{q}%", oid or -1, f"%{clean_ref(q)}%"]
    orders = db().execute(sql + " ORDER BY id DESC LIMIT 300", params).fetchall()
    dup_ids = {o["id"] for o in orders if o["receipt"] and receipt_conflicts(dict(o))}
    counts = {s: db().execute("SELECT COUNT(*) FROM orders WHERE status = ?", (s,)).fetchone()[0] for s in STATUSES}
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    stats = {
        "today": db().execute("SELECT COUNT(*) FROM orders WHERE created_at LIKE ?", (today + "%",)).fetchone()[0],
        "sales": db().execute("SELECT COALESCE(SUM(total), 0) FROM orders WHERE status NOT IN (?, ?)",
                              (PENDING, CANCELLED)).fetchone()[0],
    }
    return render_template("admin/orders.html", orders=orders, counts=counts, status=status, q=q,
                           statuses=STATUSES, stats=stats, code=order_code, setup_missing=not setting("whatsapp"),
                           dup_ids=dup_ids)


@app.route("/admin/order/<int:oid>", methods=["GET", "POST"])
@admin_required
def admin_order(oid):
    order, items = load_order(oid)
    if not order:
        abort(404)
    if request.method == "POST":
        new = request.form.get("status", order["status"])
        if new in STATUSES:
            conn = db()
            # الإلغاء يرجّع الكميات للمخزون، والتراجع عن الإلغاء يخصمها من جديد
            if new == CANCELLED and order["status"] != CANCELLED:
                for i in items:
                    conn.execute("UPDATE variants SET stock = stock + ? WHERE id = ? AND stock IS NOT NULL", (i["qty"], i["variant_id"]))
            elif order["status"] == CANCELLED and new != CANCELLED:
                for i in items:
                    conn.execute("UPDATE variants SET stock = stock - ? WHERE id = ? AND stock IS NOT NULL", (i["qty"], i["variant_id"]))
            conn.execute("UPDATE orders SET status = ?, admin_note = ? WHERE id = ?",
                         (new, request.form.get("admin_note", "").strip(), oid))
            conn.commit()
            flash(f"تم تحديث الطلب {order_code(oid)}: {new}")
        return redirect(url_for("admin_order", oid=oid))
    code = order_code(oid)
    customer_msg = (f"مرحباً {order['name']}، معك {STORE_NAME}. بخصوص طلبك رقم {code}: "
                    f"حالته الآن «{order['status']}». شكراً لثقتك.")
    return render_template("admin/order.html", order=order, items=items, code=code, statuses=STATUSES,
                           conflicts=receipt_conflicts(order), code_of=order_code,
                           wa_customer=wa_link(order["phone"], customer_msg))


# حذف الطلب يرجّع الكمية للمخزون إذا الغرشة ما طلعت من عندك بعد
RESTOCK_ON_DELETE = (PENDING, RECEIPT, PAID, PREPARING)


def purge_orders(ids):
    """حذف نهائي للطلبات مع أصنافها وصور إيصالاتها، ويحفظ أكبر رقم انحذف عشان الترقيم ما يرجع"""
    conn = db()
    rows = conn.execute(f"SELECT id, status, receipt FROM orders WHERE id IN ({','.join('?' * len(ids))})",
                        ids).fetchall() if ids else []
    for r in rows:
        if r["status"] in RESTOCK_ON_DELETE:
            for i in conn.execute("SELECT variant_id, qty FROM order_items WHERE order_id = ?", (r["id"],)).fetchall():
                conn.execute("UPDATE variants SET stock = stock + ? WHERE id = ? AND stock IS NOT NULL",
                             (i["qty"], i["variant_id"]))
        conn.execute("DELETE FROM order_items WHERE order_id = ?", (r["id"],))
        conn.execute("DELETE FROM orders WHERE id = ?", (r["id"],))
    if rows:
        top = max([r["id"] for r in rows] + [int(setting("last_order_id") or 0)])
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_order_id', ?)", (str(top),))
    conn.commit()
    for r in rows:   # الملفات بعد ما ينحفظ الحذف
        if r["receipt"]:
            try:
                os.remove(os.path.join(RECEIPT_DIR, os.path.basename(r["receipt"])))
            except OSError:
                pass
    return len(rows)


@app.route("/admin/order/<int:oid>/delete", methods=["POST"])
@admin_required
def admin_order_delete(oid):
    if purge_orders([oid]):
        flash(f"انحذف الطلب {order_code(oid)} نهائياً")
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/delete-all", methods=["POST"])
@admin_required
def admin_orders_delete_all():
    if request.form.get("confirm", "").strip() != "حذف":
        flash("ما انحذف شي. اكتب كلمة «حذف» في الخانة للتأكيد")
        return redirect(url_for("admin_settings"))
    n = purge_orders([r["id"] for r in db().execute("SELECT id FROM orders").fetchall()])
    flash(f"انحذفت كل الطلبات ({n})")
    return redirect(url_for("admin_orders"))


@app.route("/admin/stats")
@admin_required
def admin_stats():
    """لوحة المبيعات: آخر ٣٠ يوم، المحافظات، الأحجام، وحالات الطلبات"""
    today = datetime.now(TZ).date()
    start = today - timedelta(days=29)
    q = ",".join("?" * len(CONFIRMED))
    rows = db().execute(f"SELECT substr(created_at, 1, 10) AS d, SUM(total) AS rev, COUNT(*) AS n FROM orders "
                        f"WHERE status IN ({q}) AND created_at >= ? GROUP BY d", (*CONFIRMED, start.isoformat())).fetchall()
    by_day = {r["d"]: (r["rev"], r["n"]) for r in rows}
    days = []
    for i in range(30):
        d = start + timedelta(days=i)
        rev, n = by_day.get(d.isoformat(), (0, 0))
        days.append({"date": d, "rev": rev or 0, "n": n})
    peak = max([d["rev"] for d in days] + [1])
    # مقياس محور مدوّر لأعلى (١، ٢، ٥ × ١٠ⁿ بالريال) حتى تكون خطوط الشبكة أرقام سهلة
    peak_omr = peak / 1000
    step = 1
    for m in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if peak_omr / m <= 4:
            step = m
            break
    top = max(step * 4, step * -(-peak_omr // step)) * 1000
    ticks = [int(top / 4 * k) for k in range(5)]
    for d in days:
        d["h"] = d["rev"] / top if top else 0

    gov = db().execute("SELECT governorate AS g, COUNT(*) AS n, SUM(total) AS rev FROM orders WHERE status != ? "
                       "GROUP BY g ORDER BY n DESC, rev DESC", (CANCELLED,)).fetchall()
    sizes = db().execute("SELECT i.product_name AS p, i.variant_label AS v, SUM(i.qty) AS q, SUM(i.qty * i.price) AS rev "
                         "FROM order_items i JOIN orders o ON o.id = i.order_id WHERE o.status != ? "
                         "GROUP BY p, v ORDER BY q DESC", (CANCELLED,)).fetchall()
    status = [(st, db().execute("SELECT COUNT(*) FROM orders WHERE status = ?", (st,)).fetchone()[0]) for st in STATUSES]
    month = [d for d in days]
    kpi = {
        "rev": sum(d["rev"] for d in month),
        "orders": db().execute(f"SELECT COUNT(*) FROM orders WHERE status IN ({q}) AND created_at >= ?",
                               (*CONFIRMED, start.isoformat())).fetchone()[0],
        "waiting": db().execute("SELECT COUNT(*) FROM orders WHERE status IN (?, ?)", (PENDING, RECEIPT)).fetchone()[0],
    }
    kpi["avg"] = kpi["rev"] // kpi["orders"] if kpi["orders"] else 0
    return render_template("admin/stats.html", days=days, ticks=ticks, kpi=kpi, gov=gov, sizes=sizes, status=status,
                           gov_max=max([r["n"] for r in gov] + [1]), size_max=max([r["q"] for r in sizes] + [1]),
                           status_max=max([n for _, n in status] + [1]))


def orders_workbook(orders, items_by_order):
    """ملف Excel للطلبات: ورقة الطلبات مع صف إجمالي بمعادلات، وورقة تفاصيل الأصناف"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_font = Font(name="Arial", bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2A1A0E")
    body_font = Font(name="Arial")
    bold = Font(name="Arial", bold=True)
    thin = Border(bottom=Side(style="thin", color="E7D9BD"))
    money = '#,##0.000;-#,##0.000;"-"'

    def sheet(ws, headers, widths):
        ws.sheet_view.rightToLeft = True
        ws.append(headers)
        for col, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = w
            c = ws.cell(row=1, column=col)
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 30
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "الطلبات"
    sheet(ws, ["رقم الطلب", "التاريخ", "العميل", "الهاتف", "المحافظة", "الولاية", "العنوان", "المنتجات",
               "المجموع (ر.ع)", "التوصيل (ر.ع)", "الإجمالي (ر.ع)", "الحالة", "رقم العملية"],
          [12, 17, 20, 14, 14, 14, 30, 38, 14, 14, 14, 18, 18])
    for o in orders:
        items = "، ".join(f"{i['variant_label']} × {i['qty']}" for i in items_by_order.get(o["id"], []))
        r = ws.max_row + 1
        ws.append([order_code(o["id"]), o["created_at"], o["name"], o["phone"], o["governorate"], o["wilaya"],
                   o["address"], items, o["subtotal"] / 1000, o["delivery"] / 1000, None, o["status"], o["transfer_ref"] or ""])
        ws.cell(row=r, column=11, value=f"=I{r}+J{r}")           # الإجمالي = المجموع + التوصيل
        for col in range(1, 14):
            c = ws.cell(row=r, column=col)
            c.font, c.border = body_font, thin
            c.alignment = Alignment(vertical="top", wrap_text=col in (7, 8))
        for col in (9, 10, 11):
            ws.cell(row=r, column=col).number_format = money
        ws.cell(row=r, column=4).number_format = "@"
    last = ws.max_row
    ws.auto_filter.ref = f"A1:M{max(last, 2)}"
    total = last + 2
    ws.cell(row=total, column=8, value="الإجمالي").font = bold
    for col in (9, 10, 11):
        L = get_column_letter(col)
        c = ws.cell(row=total, column=col, value=f"=SUBTOTAL(9,{L}2:{L}{last})" if last >= 2 else 0)
        c.font, c.number_format = bold, money
    ws.cell(row=total + 1, column=1, value=f"المبالغ بالريال العماني (١ ر.ع = ١٠٠٠ بيسة). المصدر: طلبات متجر {STORE_NAME}، "
                                          f"صُدّر {now_oman()}. صف الإجمالي يتبع الفلتر.").font = Font(name="Arial", italic=True, color="7D6A55")

    wi = wb.create_sheet("الأصناف")
    sheet(wi, ["رقم الطلب", "التاريخ", "الحالة", "المنتج", "الحجم", "الكمية", "سعر الوحدة (ر.ع)", "المبلغ (ر.ع)"],
          [12, 17, 18, 22, 26, 10, 16, 14])
    for o in orders:
        for i in items_by_order.get(o["id"], []):
            r = wi.max_row + 1
            wi.append([order_code(o["id"]), o["created_at"], o["status"], i["product_name"], i["variant_label"],
                       i["qty"], i["price"] / 1000, None])
            wi.cell(row=r, column=8, value=f"=F{r}*G{r}")
            for col in range(1, 9):
                wi.cell(row=r, column=col).font = body_font
            for col in (7, 8):
                wi.cell(row=r, column=col).number_format = money
    li = wi.max_row
    wi.auto_filter.ref = f"A1:H{max(li, 2)}"
    t = li + 2
    wi.cell(row=t, column=5, value="الإجمالي").font = bold
    for col, L in ((6, "F"), (8, "H")):
        c = wi.cell(row=t, column=col, value=f"=SUBTOTAL(9,{L}2:{L}{li})" if li >= 2 else 0)
        c.font = bold
        if col == 8:
            c.number_format = money
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@app.route("/admin/export.xlsx")
@admin_required
def admin_export():
    status = request.args.get("status", "")
    if status in STATUSES:
        orders = db().execute("SELECT * FROM orders WHERE status = ? ORDER BY id", (status,)).fetchall()
    else:
        orders = db().execute("SELECT * FROM orders ORDER BY id").fetchall()
    items_by_order = {}
    for i in db().execute("SELECT * FROM order_items ORDER BY id").fetchall():
        items_by_order.setdefault(i["order_id"], []).append(i)
    name = f"orders-{datetime.now(TZ).strftime('%Y-%m-%d')}" + (f"-{STATUS_KEY[status]}" if status in STATUSES else "") + ".xlsx"
    return send_file(orders_workbook(orders, items_by_order), as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/admin/products")
@admin_required
def admin_products():
    return render_template("admin/products.html", products=products_with_variants(only_active=False))


def save_image(file):
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGES:
        flash("الصورة لازم تكون JPG أو PNG أو WEBP")
        return None
    name = f"{secrets.token_hex(8)}.{ext}"
    file.save(os.path.join(UPLOAD_DIR, secure_filename(name)))
    return name


@app.route("/admin/product/new", methods=["GET", "POST"])
@app.route("/admin/product/<int:pid>", methods=["GET", "POST"])
@admin_required
def admin_product(pid=None):
    p = None
    if pid:
        p = next((x for x in products_with_variants(only_active=False) if x["id"] == pid), None)
        if not p:
            abort(404)
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        if not name:
            flash("اكتب اسم المنتج")
            return redirect(request.url)
        conn = db()
        image = save_image(request.files.get("image"))
        fields = (name, f.get("tagline", "").strip(), f.get("description", "").strip(),
                  1 if f.get("active") else 0, int(f.get("sort") or 0))
        if p:
            conn.execute("UPDATE products SET name=?, tagline=?, description=?, active=?, sort=? WHERE id=?", fields + (pid,))
            if image:
                conn.execute("UPDATE products SET image = ? WHERE id = ?", (image, pid))
        else:
            pid = conn.execute("INSERT INTO products (name, tagline, description, active, sort, image) VALUES (?,?,?,?,?,?)",
                               fields + (image or "",)).lastrowid
        # الأحجام: صفوف بنفس الترتيب (معرّف، الاسم، السعر، المخزون، مفعّل)
        for vid, label, price, stock, active in zip(f.getlist("v_id"), f.getlist("v_label"), f.getlist("v_price"),
                                                    f.getlist("v_stock"), f.getlist("v_active")):
            label = label.strip()
            try:
                price_b = round(float(price) * 1000)
            except ValueError:
                price_b = None
            stock_v = int(stock) if stock.strip().isdigit() else None
            if vid and (not label or price_b is None):
                conn.execute("DELETE FROM variants WHERE id = ? AND product_id = ?", (vid, pid))
            elif vid:
                conn.execute("UPDATE variants SET label=?, price=?, stock=?, active=? WHERE id=? AND product_id=?",
                             (label, price_b, stock_v, 1 if active == "1" else 0, vid, pid))
            elif label and price_b is not None:
                conn.execute("INSERT INTO variants (product_id, label, price, stock, active) VALUES (?,?,?,?,1)",
                             (pid, label, price_b, stock_v))
        conn.commit()
        flash(f"تم حفظ {name}")
        return redirect(url_for("admin_product", pid=pid))
    return render_template("admin/product.html", p=p)


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        f = request.form
        conn = db()
        for key in ("whatsapp", "bank_name", "account_name", "account_number", "transfer_phone"):
            conn.execute("UPDATE settings SET value = ? WHERE key = ?", (f.get(key, "").strip(), key))

        def baisa(v):
            try:
                return str(round(float(v or 0) * 1000))
            except ValueError:
                return "0"
        conn.execute("UPDATE settings SET value = ? WHERE key = 'delivery_default'", (baisa(f.get("delivery_default")),))
        conn.execute("UPDATE settings SET value = ? WHERE key = 'free_over'", (baisa(f.get("free_over")),))
        fees = {gov: int(baisa(f.get(f"fee_{gov}"))) for gov in OMAN if f.get(f"fee_{gov}", "").strip() != ""}
        conn.execute("UPDATE settings SET value = ? WHERE key = 'delivery_fees'", (json.dumps(fees, ensure_ascii=False),))
        conn.commit()
        flash("تم حفظ الإعدادات")
        return redirect(url_for("admin_settings"))
    values = {k: setting(k) for k in DEFAULT_SETTINGS}
    return render_template("admin/settings.html", s=values, oman=OMAN,
                           fees=json.loads(values["delivery_fees"] or "{}"))


@app.route("/admin/receipt/<path:name>")
@admin_required
def admin_receipt(name):
    return send_from_directory(RECEIPT_DIR, name)


@app.route("/media/<path:name>")
def media(name):
    return send_from_directory(UPLOAD_DIR, name, max_age=7 * 24 * 3600)


@app.errorhandler(404)
def not_found(_e):
    return render_template("message.html", title="الصفحة غير موجودة",
                           text="الرابط اللي فتحته غير موجود. ارجع للمتجر وتصفّح المنتجات."), 404


@app.errorhandler(400)
def bad_request(_e):
    return render_template("message.html", title="انتهت صلاحية الصفحة",
                           text="حدّث الصفحة وحاول مرة ثانية."), 400


init_db()

if __name__ == "__main__":
    app.run(debug=True)
