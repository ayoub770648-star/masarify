import io
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from flask import (Flask, flash, redirect, render_template, request,
                   send_file, session, url_for)
from jinja2 import DictLoader

# ----------------------------------------------------------------------
# الإعدادات
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)      # على Railway سنضبطه على /data
DB_PATH = os.path.join(DATA_DIR, "delivery.db")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "1234")  # غيّرها من متغيرات Railway
TZ = ZoneInfo("Asia/Muscat")

PAID = "تم التحصيل"
PENDING = "معلق"
EXPENSE_TYPES = ["بترول", "أكل", "صيانة", "أخرى"]
UNSPECIFIED = "غير محدد"
WILAYAT = [
    "مسقط", "مطرح", "السيب", "بوشر", "العامرات", "قريات", "صحار", "صور",
    "نزوى", "صلالة", "البريمي", "إبراء", "عبري", "بركاء", "شناص", "صحم",
    "الرستاق", "سمائل", "إزكي", "بهلا", "ضنك", "محوت", "مرمول", "الحمراء",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_ref TEXT,
    customer_phone TEXT,
    wilaya TEXT NOT NULL,
    driver TEXT NOT NULL,
    fee REAL NOT NULL,
    payment_status TEXT NOT NULL,
    order_date TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver TEXT NOT NULL,
    expense_date TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    wilaya TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
"""

ORDER_COLUMNS_AR = {
    "id": "رقم", "order_ref": "رقم الطلب", "customer_phone": "هاتف الزبون",
    "wilaya": "الولاية", "driver": "المندوب", "fee": "سعر التوصيل",
    "payment_status": "حالة الدفع", "order_date": "التاريخ", "notes": "ملاحظات",
}
EXPENSE_COLUMNS_AR = {
    "id": "رقم", "driver": "السيارة/المندوب", "expense_date": "التاريخ",
    "amount": "القيمة", "category": "النوع", "wilaya": "الولاية",
    "notes": "ملاحظات",
}

# ----------------------------------------------------------------------
# القوالب (مدمجة داخل الملف لتسهيل النشر)
# ----------------------------------------------------------------------
TEMPLATES = {
    "base.html": """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} | نظام التوصيل</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
  body{font-family:Tahoma,Arial,sans-serif;background:#f4f6fa;margin:0;color:#222}
  nav{background:#1f3a5f;padding:12px 20px;display:flex;gap:18px;flex-wrap:wrap;align-items:center}
  nav a{color:#fff;text-decoration:none;font-weight:bold}
  .wrap{padding:20px;max-width:1200px;margin:auto}
  .card{background:#fff;border-radius:10px;padding:16px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:20px}
  .kpi{background:#fff;border-radius:10px;padding:14px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.08)}
  .kpi b{display:block;font-size:22px;margin-top:6px}
  form.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;align-items:end}
  input,select,button{padding:9px;border:1px solid #ccc;border-radius:6px;font-size:15px;width:100%;box-sizing:border-box}
  button{background:#1f3a5f;color:#fff;border:0;cursor:pointer}
  .btn-link{background:#2e8b57;color:#fff;padding:9px 14px;border-radius:6px;text-decoration:none;display:inline-block}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{padding:8px;border-bottom:1px solid #eee;text-align:right}
  th{background:#f0f3f8}
  .pos{color:#0a7d32}.neg{color:#c0392b}
  .small-btn{width:auto;padding:4px 10px;font-size:13px;margin:0 2px}
  .flash{background:#fff3cd;padding:10px;border-radius:6px;margin-bottom:12px}
  .top{background:#e8f7ee}
</style>
</head>
<body>
<nav>
  {% if session.get('ok') %}
    <a href="{{ url_for('dashboard') }}">لوحة التحكم</a>
    <a href="{{ url_for('orders') }}">الطلبات الواردة</a>
    <a href="{{ url_for('expenses') }}">المصروفات</a>
    <a href="{{ url_for('drivers') }}">المندوبين</a>
    <a href="{{ url_for('export_excel') }}">تصدير Excel</a>
    <a href="{{ url_for('logout') }}" style="margin-right:auto">خروج</a>
  {% endif %}
</nav>
<div class="wrap">
  {% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}
  {% block content %}{% endblock %}
</div>
</body>
</html>
""",

    "login.html": """
{% extends "base.html" %}
{% block content %}
<div class="card" style="max-width:360px;margin:60px auto">
  <h3>تسجيل الدخول</h3>
  <form method="post">
    <input type="password" name="password" placeholder="كلمة المرور" required>
    <br><br>
    <button type="submit">دخول</button>
  </form>
</div>
{% endblock %}
""",

    "orders.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>إدخال طلب جديد</h3>
  <form method="post" action="{{ url_for('add_order') }}" class="grid">
    <input name="order_ref" placeholder="رقم الطلب (اختياري)">
    <input name="customer_phone" placeholder="هاتف الزبون" required>
    <input name="wilaya" list="wilayat" placeholder="الولاية / الوجهة" required>
    <datalist id="wilayat">{% for w in wilayat %}<option value="{{ w }}">{% endfor %}</datalist>
    {% include "driver_select.html" %}
    <input name="fee" type="number" step="0.001" min="0" placeholder="سعر التوصيل (ر.ع)" required>
    <select name="payment_status">
      <option>تم التحصيل</option>
      <option>معلق</option>
    </select>
    <input name="order_date" type="date" value="{{ today }}" required>
    <input name="notes" placeholder="ملاحظات">
    <button type="submit">حفظ الطلب</button>
  </form>
</div>

<div class="card">
  <h3>آخر الطلبات</h3>
  <table>
    <tr><th>#</th><th>التاريخ</th><th>الزبون</th><th>الولاية</th><th>المندوب</th>
        <th>السعر</th><th>الحالة</th><th>إجراءات</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{ r.id }}</td>
      <td>{{ r.order_date }}</td>
      <td>{{ r.customer_phone }}</td>
      <td>{{ r.wilaya }}</td>
      <td>{{ r.driver }}</td>
      <td>{{ '%.3f'|format(r.fee) }}</td>
      <td>{{ r.payment_status }}</td>
      <td>
        <form method="post" action="{{ url_for('toggle_payment', oid=r.id) }}" style="display:inline">
          <button class="small-btn">تغيير الحالة</button>
        </form>
        <form method="post" action="{{ url_for('delete_order', oid=r.id) }}" style="display:inline"
              onsubmit="return confirm('هل تريد الحذف؟')">
          <button class="small-btn" style="background:#c0392b">حذف</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="8">لا توجد طلبات بعد</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "expenses.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>تسجيل مصروف</h3>
  <form method="post" action="{{ url_for('add_expense') }}" class="grid">
    {% include "driver_select.html" %}
    <input name="expense_date" type="date" value="{{ today }}" required>
    <input name="amount" type="number" step="0.001" min="0" placeholder="قيمة المصروف (ر.ع)" required>
    <select name="category">
      {% for t in types %}<option>{{ t }}</option>{% endfor %}
    </select>
    <input name="wilaya" list="wilayat" placeholder="الولاية (اختياري)">
    <datalist id="wilayat">{% for w in wilayat %}<option value="{{ w }}">{% endfor %}</datalist>
    <input name="notes" placeholder="ملاحظات">
    <button type="submit">حفظ المصروف</button>
  </form>
</div>

<div class="card">
  <h3>آخر المصروفات</h3>
  <table>
    <tr><th>#</th><th>التاريخ</th><th>السيارة/المندوب</th><th>النوع</th>
        <th>الولاية</th><th>القيمة</th><th>ملاحظات</th><th>إجراءات</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{ r.id }}</td>
      <td>{{ r.expense_date }}</td>
      <td>{{ r.driver }}</td>
      <td>{{ r.category }}</td>
      <td>{{ r.wilaya or '' }}</td>
      <td>{{ '%.3f'|format(r.amount) }}</td>
      <td>{{ r.notes or '' }}</td>
      <td>
        <form method="post" action="{{ url_for('delete_expense', eid=r.id) }}" style="display:inline"
              onsubmit="return confirm('هل تريد الحذف؟')">
          <button class="small-btn" style="background:#c0392b">حذف</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="8">لا توجد مصروفات بعد</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "driver_select.html": """
{% if driver_names %}
    <select name="driver" required>
      <option value="">— اختر المندوب / السيارة —</option>
      {% for d in driver_names %}<option>{{ d }}</option>{% endfor %}
    </select>
{% else %}
    <a class="btn-link" href="{{ url_for('drivers') }}">أضف مندوباً أولاً</a>
{% endif %}
""",

    "drivers.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>إضافة مندوب / سيارة</h3>
  <form method="post" action="{{ url_for('add_driver') }}" class="grid">
    <input name="name" placeholder="اسم المندوب أو رقم السيارة" required>
    <button type="submit">إضافة</button>
  </form>
</div>

<div class="card">
  <h3>قائمة المندوبين</h3>
  <table>
    <tr><th>#</th><th>الاسم</th><th>عدد الطلبات</th><th>إجراءات</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{ r.id }}</td>
      <td>{{ r.name }}</td>
      <td>{{ r.orders_count }}</td>
      <td>
        <form method="post" action="{{ url_for('delete_driver', did=r.id) }}" style="display:inline"
              onsubmit="return confirm('حذف المندوب من القائمة؟ (لن تُحذف طلباته أو مصروفاته)')">
          <button class="small-btn" style="background:#c0392b">حذف</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="4">لا يوجد مندوبون بعد</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "dashboard.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <form method="get" class="grid">
    <div><label>من تاريخ</label><input type="date" name="d_from" value="{{ d_from }}"></div>
    <div><label>إلى تاريخ</label><input type="date" name="d_to" value="{{ d_to }}"></div>
    <div><button type="submit">عرض التقرير</button></div>
    <div><a class="btn-link" href="{{ url_for('export_excel', d_from=d_from, d_to=d_to) }}">تصدير Excel</a></div>
  </form>
</div>

<div class="kpis">
  <div class="kpi">إجمالي المحصّل (ر.ع)<b>{{ '%.3f'|format(k.collected) }}</b></div>
  <div class="kpi">معلّق لم يُحصَّل (ر.ع)<b>{{ '%.3f'|format(k.pending) }}</b></div>
  <div class="kpi">إجمالي المصروفات (ر.ع)<b>{{ '%.3f'|format(k.expenses) }}</b></div>
  <div class="kpi">صافي الربح (ر.ع)
    <b class="{{ 'pos' if k.net >= 0 else 'neg' }}">{{ '%.3f'|format(k.net) }}</b>
  </div>
</div>

<div class="card">
  <h3>صافي ربح كل مندوب / سيارة</h3>
  <canvas id="drvChart" height="90"></canvas>
  <table>
    <tr><th>المندوب</th><th>عدد الطلبات</th><th>المحصّل</th><th>المعلق</th>
        <th>المصروفات</th><th>صافي الربح</th></tr>
    {% for r in drv %}
    <tr>
      <td>{{ r.driver }}</td>
      <td>{{ r.orders_count|int }}</td>
      <td>{{ '%.3f'|format(r.collected) }}</td>
      <td>{{ '%.3f'|format(r.pending) }}</td>
      <td>{{ '%.3f'|format(r.expenses) }}</td>
      <td class="{{ 'pos' if r.net >= 0 else 'neg' }}">{{ '%.3f'|format(r.net) }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6">لا توجد بيانات في هذه الفترة</td></tr>
    {% endfor %}
  </table>
</div>

<div class="card">
  <h3>الأرباح حسب الولاية (خطوط السير)</h3>
  <canvas id="wilChart" height="90"></canvas>
  <table>
    <tr><th>الولاية</th><th>عدد الطلبات</th><th>المحصّل</th><th>المعلق</th>
        <th>المصروفات</th><th>صافي الربح</th></tr>
    {% for r in wil %}
    <tr class="{{ 'top' if loop.first and r.net > 0 }}">
      <td>{{ r.wilaya }}{% if loop.first and r.net > 0 %} 🏆{% endif %}</td>
      <td>{{ r.orders_count|int }}</td>
      <td>{{ '%.3f'|format(r.collected) }}</td>
      <td>{{ '%.3f'|format(r.pending) }}</td>
      <td>{{ '%.3f'|format(r.expenses) }}</td>
      <td class="{{ 'pos' if r.net >= 0 else 'neg' }}">{{ '%.3f'|format(r.net) }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6">لا توجد بيانات في هذه الفترة</td></tr>
    {% endfor %}
  </table>
</div>

<script>
  const mk = (id, labels, data, label) => new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels: labels, datasets: [{ label: label, data: data }] },
    options: { responsive: true }
  });
  mk('drvChart', {{ drv_labels|tojson }}, {{ drv_net|tojson }}, 'صافي الربح');
  mk('wilChart', {{ wil_labels|tojson }}, {{ wil_net|tojson }}, 'صافي الربح حسب الولاية');
</script>
{% endblock %}
""",
}

# ----------------------------------------------------------------------
# التطبيق وقاعدة البيانات
# ----------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.jinja_loader = DictLoader(TEMPLATES)


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # نقل أسماء المندوبين المكتوبة سابقاً إلى القائمة الثابتة
    conn.execute(
        """INSERT OR IGNORE INTO drivers (name)
           SELECT driver FROM orders UNION SELECT driver FROM expenses""")
    conn.execute("DELETE FROM drivers WHERE name = ?", (UNSPECIFIED,))
    conn.commit()
    conn.close()


def db_exec(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def db_df(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def driver_names():
    return db_df("SELECT name FROM drivers ORDER BY name")["name"].tolist()


def valid_driver(name):
    """يعيد اسم المندوب إذا كان من القائمة، وإلا None."""
    name = (name or "").strip()
    return name if name in driver_names() else None


def today_oman():
    return datetime.now(TZ).date()


def date_filter(column, d_from, d_to):
    clauses, params = [], []
    if d_from:
        clauses.append(f"{column} >= ?")
        params.append(d_from)
    if d_to:
        clauses.append(f"{column} <= ?")
        params.append(d_to)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


init_db()


@app.before_request
def require_login():
    if request.endpoint in ("login", "static"):
        return None
    if not session.get("ok"):
        return redirect(url_for("login"))
    return None


# ----------------------------------------------------------------------
# الدخول
# ----------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["ok"] = True
            return redirect(url_for("dashboard"))
        flash("كلمة المرور غير صحيحة")
    return render_template("login.html", title="دخول")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


# ----------------------------------------------------------------------
# 1) الطلبات الواردة
# ----------------------------------------------------------------------
@app.route("/orders")
def orders():
    rows = db_df("SELECT * FROM orders ORDER BY id DESC LIMIT 200").to_dict("records")
    return render_template("orders.html", title="الطلبات",
                           rows=rows, wilayat=WILAYAT, driver_names=driver_names(),
                           today=today_oman().isoformat())


@app.route("/orders/add", methods=["POST"])
def add_order():
    try:
        fee = float(request.form.get("fee", ""))
        if fee < 0:
            raise ValueError
    except ValueError:
        flash("سعر التوصيل غير صحيح")
        return redirect(url_for("orders"))

    driver = valid_driver(request.form.get("driver"))
    if not driver:
        flash("اختر المندوب من القائمة")
        return redirect(url_for("orders"))

    status = request.form.get("payment_status", PENDING)
    if status not in (PAID, PENDING):
        status = PENDING

    db_exec(
        """INSERT INTO orders (order_ref, customer_phone, wilaya, driver, fee,
                               payment_status, order_date, notes)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            request.form.get("order_ref", "").strip(),
            request.form.get("customer_phone", "").strip(),
            request.form.get("wilaya", "").strip() or UNSPECIFIED,
            driver,
            fee,
            status,
            request.form.get("order_date") or today_oman().isoformat(),
            request.form.get("notes", "").strip(),
        ),
    )
    flash("تم حفظ الطلب")
    return redirect(url_for("orders"))


@app.route("/orders/<int:oid>/toggle", methods=["POST"])
def toggle_payment(oid):
    db_exec(
        """UPDATE orders SET payment_status =
               CASE WHEN payment_status = ? THEN ? ELSE ? END
           WHERE id = ?""",
        (PAID, PENDING, PAID, oid),
    )
    return redirect(url_for("orders"))


@app.route("/orders/<int:oid>/delete", methods=["POST"])
def delete_order(oid):
    db_exec("DELETE FROM orders WHERE id = ?", (oid,))
    flash("تم الحذف")
    return redirect(url_for("orders"))


# ----------------------------------------------------------------------
# 2) المصروفات
# ----------------------------------------------------------------------
@app.route("/expenses")
def expenses():
    rows = db_df("SELECT * FROM expenses ORDER BY id DESC LIMIT 200").to_dict("records")
    return render_template("expenses.html", title="المصروفات", rows=rows,
                           types=EXPENSE_TYPES, wilayat=WILAYAT, driver_names=driver_names(),
                           today=today_oman().isoformat())


@app.route("/expenses/add", methods=["POST"])
def add_expense():
    try:
        amount = float(request.form.get("amount", ""))
        if amount < 0:
            raise ValueError
    except ValueError:
        flash("قيمة المصروف غير صحيحة")
        return redirect(url_for("expenses"))

    driver = valid_driver(request.form.get("driver"))
    if not driver:
        flash("اختر المندوب من القائمة")
        return redirect(url_for("expenses"))

    category = request.form.get("category", "أخرى")
    if category not in EXPENSE_TYPES:
        category = "أخرى"

    db_exec(
        """INSERT INTO expenses (driver, expense_date, amount, category, wilaya, notes)
           VALUES (?,?,?,?,?,?)""",
        (
            driver,
            request.form.get("expense_date") or today_oman().isoformat(),
            amount,
            category,
            request.form.get("wilaya", "").strip() or UNSPECIFIED,
            request.form.get("notes", "").strip(),
        ),
    )
    flash("تم حفظ المصروف")
    return redirect(url_for("expenses"))


@app.route("/expenses/<int:eid>/delete", methods=["POST"])
def delete_expense(eid):
    db_exec("DELETE FROM expenses WHERE id = ?", (eid,))
    flash("تم الحذف")
    return redirect(url_for("expenses"))


# ----------------------------------------------------------------------
# المندوبين / السيارات
# ----------------------------------------------------------------------
@app.route("/drivers")
def drivers():
    rows = db_df(
        """SELECT d.id, d.name, COUNT(o.id) AS orders_count
           FROM drivers d LEFT JOIN orders o ON o.driver = d.name
           GROUP BY d.id ORDER BY d.name""").to_dict("records")
    return render_template("drivers.html", title="المندوبين", rows=rows)


@app.route("/drivers/add", methods=["POST"])
def add_driver():
    name = request.form.get("name", "").strip()
    if not name or name == UNSPECIFIED:
        flash("اكتب اسم المندوب")
    elif name in driver_names():
        flash("هذا الاسم موجود مسبقاً")
    else:
        db_exec("INSERT INTO drivers (name) VALUES (?)", (name,))
        flash("تمت إضافة المندوب")
    return redirect(url_for("drivers"))


@app.route("/drivers/<int:did>/delete", methods=["POST"])
def delete_driver(did):
    db_exec("DELETE FROM drivers WHERE id = ?", (did,))
    flash("تم حذف المندوب من القائمة")
    return redirect(url_for("drivers"))


# ----------------------------------------------------------------------
# 3) التقارير ولوحة التحكم (Pandas)
# ----------------------------------------------------------------------
def load_data(d_from="", d_to=""):
    w, p = date_filter("order_date", d_from, d_to)
    orders_df = db_df("SELECT * FROM orders" + w + " ORDER BY order_date", p)

    w, p = date_filter("expense_date", d_from, d_to)
    expenses_df = db_df("SELECT * FROM expenses" + w + " ORDER BY expense_date", p)
    # المصروفات بدون ولاية تُصنَّف "غير محدد"
    expenses_df["wilaya"] = expenses_df["wilaya"].fillna("").replace("", UNSPECIFIED)
    return orders_df, expenses_df


def build_reports(orders_df, expenses_df):
    paid = orders_df[orders_df["payment_status"] == PAID]
    pending = orders_df[orders_df["payment_status"] == PENDING]

    # الإجماليات
    k = {
        "collected": float(paid["fee"].sum()),
        "pending": float(pending["fee"].sum()),
        "expenses": float(expenses_df["amount"].sum()),
    }
    k["net"] = k["collected"] - k["expenses"]

    # حسب المندوب / السيارة
    drv = pd.DataFrame({
        "orders_count": orders_df.groupby("driver")["id"].count(),
        "collected": paid.groupby("driver")["fee"].sum(),
        "pending": pending.groupby("driver")["fee"].sum(),
        "expenses": expenses_df.groupby("driver")["amount"].sum(),
    }).astype(float).fillna(0)
    drv["net"] = drv["collected"] - drv["expenses"]
    drv.index.name = "driver"
    drv = drv.sort_values("net", ascending=False).reset_index()

    # حسب الولاية (خطوط السير)
    wil = pd.DataFrame({
        "orders_count": orders_df.groupby("wilaya")["id"].count(),
        "collected": paid.groupby("wilaya")["fee"].sum(),
        "pending": pending.groupby("wilaya")["fee"].sum(),
        "expenses": expenses_df.groupby("wilaya")["amount"].sum(),
    }).astype(float).fillna(0)
    wil["net"] = wil["collected"] - wil["expenses"]
    wil.index.name = "wilaya"
    wil = wil.sort_values("net", ascending=False).reset_index()

    return k, drv, wil


@app.route("/dashboard")
def dashboard():
    d_from = request.args.get("d_from", "")
    d_to = request.args.get("d_to", "")
    orders_df, expenses_df = load_data(d_from, d_to)
    k, drv, wil = build_reports(orders_df, expenses_df)

    return render_template(
        "dashboard.html",
        title="لوحة التحكم",
        d_from=d_from,
        d_to=d_to,
        k=k,
        drv=drv.to_dict("records"),
        wil=wil.to_dict("records"),
        drv_labels=drv["driver"].astype(str).tolist(),
        drv_net=drv["net"].round(3).tolist(),
        wil_labels=wil["wilaya"].astype(str).tolist(),
        wil_net=wil["net"].round(3).tolist(),
    )


# ----------------------------------------------------------------------
# 4) تصدير Excel
# ----------------------------------------------------------------------
@app.route("/export")
def export_excel():
    d_from = request.args.get("d_from", "")
    d_to = request.args.get("d_to", "")
    orders_df, expenses_df = load_data(d_from, d_to)
    k, drv, wil = build_reports(orders_df, expenses_df)

    summary = pd.DataFrame([
        {"البند": "إجمالي المحصّل (ر.ع)", "القيمة": round(k["collected"], 3)},
        {"البند": "معلّق (ر.ع)", "القيمة": round(k["pending"], 3)},
        {"البند": "إجمالي المصروفات (ر.ع)", "القيمة": round(k["expenses"], 3)},
        {"البند": "صافي الربح (ر.ع)", "القيمة": round(k["net"], 3)},
        {"البند": "الفترة من", "القيمة": d_from or "الكل"},
        {"البند": "الفترة إلى", "القيمة": d_to or "الكل"},
    ])

    drv_out = drv.rename(columns={
        "driver": "المندوب/السيارة", "orders_count": "عدد الطلبات",
        "collected": "المحصّل", "pending": "المعلق",
        "expenses": "المصروفات", "net": "صافي الربح",
    })
    wil_out = wil.rename(columns={
        "wilaya": "الولاية", "orders_count": "عدد الطلبات",
        "collected": "المحصّل", "pending": "المعلق",
        "expenses": "المصروفات", "net": "صافي الربح",
    })
    orders_out = orders_df.rename(columns=ORDER_COLUMNS_AR)
    expenses_out = expenses_df.rename(columns=EXPENSE_COLUMNS_AR)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="الملخص", index=False)
        drv_out.to_excel(writer, sheet_name="حسب المندوب", index=False)
        wil_out.to_excel(writer, sheet_name="حسب الولاية", index=False)
        orders_out.to_excel(writer, sheet_name="الطلبات", index=False)
        expenses_out.to_excel(writer, sheet_name="المصروفات", index=False)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"report_{today_oman().isoformat()}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ----------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
