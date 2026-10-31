import json
import os
import secrets
import shutil
import sqlite3
import urllib.parse
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.utils import secure_filename

# ----------------------------------------------------------------------
# الإعدادات
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)          # على Railway: /data (الـ Volume)
DB_PATH = os.path.join(DATA_DIR, "store.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")    # بدونها تبقى لوحة التحكم مقفلة
STORE_NAME = os.environ.get("STORE_NAME", "أبو ميثه")
TZ = ZoneInfo("Asia/Muscat")
ALLOWED_IMAGES = {"jpg", "jpeg", "png", "webp"}
# صور إضافية للمعرض: لقطات مقرّبة من صورة المنتج الأصلية
EXTRA_GALLERY = {"ghee-bottles.jpg": [("img/detail-label.jpg", "الملصق"), ("img/bottle-tall.jpg", "الغرشة"),
                                      ("img/detail-caps.jpg", "اللون الذهبي")]}

# حالات الطلب بالترتيب
PENDING = "بانتظار التحويل"
PAID = "تم استلام التحويل"
PREPARING = "قيد التجهيز"
SHIPPED = "خرج للتوصيل"
DELIVERED = "تم التسليم"
CANCELLED = "ملغي"
STATUSES = [PENDING, PAID, PREPARING, SHIPPED, DELIVERED, CANCELLED]
STATUS_KEY = {PENDING: "pending", PAID: "paid", PREPARING: "preparing",
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
    "iban": "",
    "delivery_default": "2000",                       # بالبيسة
    "delivery_fees": json.dumps({"مسقط": 1500}, ensure_ascii=False),
    "free_over": "20000",                             # توصيل مجاني فوق ٢٠ ر.ع (٠ = بدون)
}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024


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
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    # أول تشغيل: السمن العماني بحجمين وأسعار إعلان المتجر، مع صورة الغراش الحقيقية
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        image = "ghee-bottles.jpg"
        shutil.copyfile(os.path.join(BASE_DIR, "static", "img", image), os.path.join(UPLOAD_DIR, image))
        pid = conn.execute(
            "INSERT INTO products (name, tagline, description, image, sort) VALUES (?, ?, ?, ?, 0)",
            ("سمن عُماني أصلي", "ميه بالميه ولذيذ، والريحة خيال",
             "سمن عُماني أصلي ١٠٠٪ من أرض عُمان. طعم لذيذ وجودة عالية، ومناسب لجميع الأكلات: "
             "العرسية والهريس واللقيمات والخبز والعيش.", image),
        ).lastrowid
        for i, (label, price) in enumerate([("غرشة كبيرة (فيمتو أو تانج)", 5000), ("غرشة صغيرة", 3000)]):
            conn.execute("INSERT INTO variants (product_id, label, price, sort) VALUES (?, ?, ?, ?)", (pid, label, price, i))
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
    if request.method == "POST" and request.form.get("csrf") != session.get("csrf"):
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
    extras = [(url_for("static", filename=f), cap) for f, cap in EXTRA_GALLERY.get(products[0]["image"], [])] if products else []
    return render_template("home.html", products=products, extras=extras)


@app.route("/p/<int:pid>")
def product(pid):
    p = next((p for p in products_with_variants() if p["id"] == pid), None)
    if not p:
        abort(404)
    gallery = ([(url_for("media", name=p["image"]), p["name"])] if p["image"] else []) + \
              [(url_for("static", filename=f), cap) for f, cap in EXTRA_GALLERY.get(p["image"], [])]
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
            oid = conn.execute(
                """INSERT INTO orders (created_at, name, phone, governorate, wilaya, address, notes,
                   subtotal, delivery, total, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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
    bank = {k: setting(k) for k in ("bank_name", "account_name", "account_number", "iban")}
    wa = wa_link(setting("whatsapp"), receipt_message(order, items)) if setting("whatsapp") else ""
    return render_template("order_done.html", order=order, items=items, code=order_code(oid), bank=bank, wa=wa)


@app.route("/track", methods=["GET", "POST"])
def track():
    order, items, code = None, [], request.values.get("code", "")
    if request.method == "POST":
        oid = code_to_id(code)
        found, found_items = load_order(oid) if oid else (None, [])
        # رقم الطلب + آخر ٤ أرقام من الهاتف، حتى لا يطّلع أحد على طلب غيره
        if found and clean_phone(found["phone"])[-4:] == clean_phone(request.form.get("phone", ""))[-4:]:
            order, items = found, found_items
        else:
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
        if ADMIN_PASSWORD and secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(url_for("admin_orders"))
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
        sql += " AND (name LIKE ? OR phone LIKE ? OR id = ?)"
        params += [f"%{q}%", f"%{q}%", oid or -1]
    orders = db().execute(sql + " ORDER BY id DESC LIMIT 300", params).fetchall()
    counts = {s: db().execute("SELECT COUNT(*) FROM orders WHERE status = ?", (s,)).fetchone()[0] for s in STATUSES}
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    stats = {
        "today": db().execute("SELECT COUNT(*) FROM orders WHERE created_at LIKE ?", (today + "%",)).fetchone()[0],
        "sales": db().execute("SELECT COALESCE(SUM(total), 0) FROM orders WHERE status NOT IN (?, ?)",
                              (PENDING, CANCELLED)).fetchone()[0],
    }
    return render_template("admin/orders.html", orders=orders, counts=counts, status=status, q=q,
                           statuses=STATUSES, stats=stats, code=order_code, setup_missing=not setting("whatsapp"))


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
                           wa_customer=wa_link(order["phone"], customer_msg))


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
        for key in ("whatsapp", "bank_name", "account_name", "account_number", "iban"):
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
