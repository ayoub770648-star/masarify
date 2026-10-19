import io
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from flask import (Flask, flash, redirect, render_template, request,
                   send_file, session, url_for)
from jinja2 import DictLoader
from werkzeug.security import check_password_hash, generate_password_hash

# ----------------------------------------------------------------------
# الإعدادات
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)      # على Railway سنضبطه على /data
DB_PATH = os.path.join(DATA_DIR, "delivery.db")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "1234")  # غيّرها من متغيرات Railway
TZ = ZoneInfo("Asia/Muscat")

# حالات الشحنة
AVAILABLE = "متاح"
CLAIMED = "محجوز"
DELIVERED = "تم التوصيل"
# حالات حجز المندوب
WAITING = "بانتظار الاستلام"
PICKED = "استلمها المندوب"
CLAIM_DONE = "تم التوصيل"
CANCELLED = "ملغي"
CLAIM_STATUSES = [WAITING, PICKED, CLAIM_DONE, CANCELLED]
DEFAULT_MIN_LEFT = 10
MAX_BULK = 2000
UNSPECIFIED = "غير محدد"

# محافظات وولايات سلطنة عُمان
OMAN = {
    "مسقط": ["مسقط", "مطرح", "بوشر", "السيب", "العامرات", "قريات"],
    "ظفار": ["صلالة", "طاقة", "مرباط", "رخيوت", "ثمريت", "ضلكوت", "المزيونة",
             "مقشن", "شليم وجزر الحلانيات", "سدح"],
    "مسندم": ["خصب", "دبا", "بخا", "مدحاء"],
    "البريمي": ["البريمي", "محضة", "السنينة"],
    "الداخلية": ["نزوى", "بهلا", "منح", "الحمراء", "أدم", "إزكي", "سمائل",
                 "بدبد", "الجبل الأخضر"],
    "شمال الباطنة": ["صحار", "شناص", "لوى", "صحم", "الخابورة", "السويق"],
    "جنوب الباطنة": ["الرستاق", "العوابي", "نخل", "وادي المعاول", "بركاء", "المصنعة"],
    "جنوب الشرقية": ["صور", "الكامل والوافي", "جعلان بني بو حسن",
                     "جعلان بني بو علي", "مصيرة"],
    "شمال الشرقية": ["إبراء", "المضيبي", "بدية", "القابل", "وادي بني خالد",
                     "دماء والطائيين"],
    "الظاهرة": ["عبري", "ينقل", "ضنك"],
    "الوسطى": ["هيما", "محوت", "الدقم", "الجازر"],
}
WILAYA_TO_GOV = {w: g for g, ws in OMAN.items() for w in ws}

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    governorate TEXT NOT NULL,
    wilaya TEXT NOT NULL,
    status TEXT NOT NULL,
    driver TEXT NOT NULL DEFAULT '',
    claim_id INTEGER,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_shipments_place ON shipments (status, governorate, wilaya);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver TEXT NOT NULL,
    phone TEXT NOT NULL,
    governorate TEXT,
    wilaya TEXT NOT NULL,
    qty INTEGER NOT NULL,
    pickup_time TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    forced INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    pin_hash TEXT,
    phone TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

CLAIM_COLUMNS_AR = {
    "id": "رقم الحجز", "driver": "المندوب", "phone": "الهاتف", "governorate": "المحافظة",
    "wilaya": "الولاية", "qty": "العدد", "pickup_time": "موعد الاستلام",
    "created_at": "وقت الحجز", "status": "الحالة", "forced": "أُجبر على الباقي",
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
<title>{{ title }} | توزيع الشحنات</title>
<style>
  body{font-family:Tahoma,Arial,sans-serif;background:#f4f6fa;margin:0;color:#222}
  nav{background:#1f3a5f;padding:12px 20px;display:flex;gap:18px;flex-wrap:wrap;align-items:center}
  nav a,nav span{color:#fff;text-decoration:none;font-weight:bold}
  .wrap{padding:20px;max-width:1100px;margin:auto}
  .card{background:#fff;border-radius:10px;padding:16px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08);overflow-x:auto}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}
  .kpi{background:#fff;border-radius:10px;padding:14px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.08)}
  .kpi b{display:block;font-size:24px;margin-top:6px}
  form.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;align-items:end}
  input,select,button{padding:9px;border:1px solid #ccc;border-radius:6px;font-size:15px;width:100%;box-sizing:border-box}
  button{background:#1f3a5f;color:#fff;border:0;cursor:pointer}
  .btn-link{background:#2e8b57;color:#fff;padding:9px 14px;border-radius:6px;text-decoration:none;display:inline-block}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{padding:8px;border-bottom:1px solid #eee;text-align:right;vertical-align:middle}
  th{background:#f0f3f8}
  .small-btn{width:auto;padding:5px 10px;font-size:13px;margin:2px}
  .green{background:#2e8b57}.red{background:#c0392b}.gray{background:#7f8c8d}
  .flash{background:#fff3cd;padding:10px;border-radius:6px;margin-bottom:12px}
  .badge{padding:3px 8px;border-radius:10px;font-size:12px;color:#fff;white-space:nowrap}
  .b-بانتظار{background:#f0ad4e}.b-استلمها{background:#337ab7}.b-تم{background:#2e8b57}.b-ملغي{background:#999}
  .gov{background:#eef3fb;font-weight:bold}
  .qty{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.qty input{width:90px}.qty button{width:auto}
  .big{font-size:18px;font-weight:bold}
  .warn{background:#fdecea;color:#a12;padding:10px;border-radius:6px;font-weight:bold}
  .ok{background:#e8f7ee;color:#0a6;padding:10px;border-radius:6px}
</style>
</head>
<body>
<nav>
  {% if session.get('role') == 'admin' %}
    <a href="{{ url_for('shipments') }}">الشحنات</a>
    <a href="{{ url_for('claims') }}">حجوزات المندوبين</a>
    <a href="{{ url_for('drivers') }}">المندوبين</a>
    <a href="{{ url_for('export_excel') }}">تصدير Excel</a>
    <a href="{{ url_for('logout') }}" style="margin-right:auto">خروج</a>
  {% elif session.get('role') == 'driver' %}
    <span>👤 {{ session.get('driver') }}</span>
    <a href="{{ url_for('d_home') }}">حجز شحنات</a>
    <a href="{{ url_for('d_mine') }}">حجوزاتي</a>
    <a href="{{ url_for('logout') }}" style="margin-right:auto">خروج</a>
  {% else %}
    <span>نظام توزيع الشحنات</span>
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
<div class="card" style="max-width:380px;margin:40px auto">
  <h3>دخول المندوب</h3>
  <form method="post" action="{{ url_for('d_login') }}">
    <select name="name" required>
      <option value="">— اختر اسمك —</option>
      {% for d in driver_names %}<option>{{ d }}</option>{% endfor %}
    </select>
    <br><br>
    <input type="password" name="pin" inputmode="numeric" placeholder="رمز PIN" required>
    <br><br>
    <button type="submit">دخول</button>
  </form>
</div>
<div class="card" style="max-width:380px;margin:20px auto">
  <h3>دخول المدير</h3>
  <form method="post" action="{{ url_for('login') }}">
    <input type="password" name="password" placeholder="كلمة المرور" required>
    <br><br>
    <button type="submit" class="gray">دخول المدير</button>
  </form>
</div>
{% endblock %}
""",

    "shipments.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>➕ إضافة شحنات</h3>
  <form method="post" action="{{ url_for('add_shipments') }}" class="grid">
    <div><label>المحافظة</label>
      <select name="governorate" id="gov" required onchange="fillWilayat()">
        <option value="">— اختر —</option>
        {% for g in oman %}<option>{{ g }}</option>{% endfor %}
      </select></div>
    <div><label>الولاية</label>
      <select name="wilaya" id="wil" required><option value="">— اختر المحافظة أولاً —</option></select></div>
    <div><label>عدد الشحنات</label>
      <input name="count" type="number" min="1" max="{{ max_bulk }}" required></div>
    <button type="submit">إضافة</button>
  </form>
  <script>
    const OMAN = {{ oman|tojson }};
    function fillWilayat() {
      const list = OMAN[document.getElementById('gov').value] || [];
      document.getElementById('wil').innerHTML = '<option value="">— اختر —</option>' +
        list.map(x => '<option>' + x + '</option>').join('');
    }
  </script>
</div>

<div class="kpis">
  <div class="kpi">متاحة للحجز<b>{{ totals[AVAILABLE] }}</b></div>
  <div class="kpi">محجوزة للمندوبين<b>{{ totals[CLAIMED] }}</b></div>
  <div class="kpi">تم توصيلها<b>{{ totals[DELIVERED] }}</b></div>
</div>

<div class="card">
  <h3>الشحنات حسب المحافظة والولاية</h3>
  <table>
    <tr><th>المحافظة / الولاية</th><th>متاحة</th><th>محجوزة</th><th>تم التوصيل</th><th>إنقاص المتاح</th></tr>
    {% for g in summary %}
      <tr class="gov"><td>{{ g.name }}</td><td>{{ g[AVAILABLE] }}</td><td>{{ g[CLAIMED] }}</td><td>{{ g[DELIVERED] }}</td><td></td></tr>
      {% for w in g.wilayat %}
      <tr>
        <td>&nbsp;&nbsp;&nbsp;{{ w.name }}</td>
        <td class="big">{{ w[AVAILABLE] }}</td><td>{{ w[CLAIMED] }}</td><td>{{ w[DELIVERED] }}</td>
        <td>
          {% if w[AVAILABLE] %}
          <form method="post" action="{{ url_for('remove_shipments') }}" class="qty"
                onsubmit="return confirm('حذف هذا العدد من الشحنات المتاحة؟')">
            <input type="hidden" name="governorate" value="{{ g.name }}">
            <input type="hidden" name="wilaya" value="{{ w.name }}">
            <input name="count" type="number" min="1" max="{{ w[AVAILABLE] }}" placeholder="العدد" required>
            <button class="small-btn red">حذف</button>
          </form>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    {% else %}
      <tr><td colspan="5">لا توجد شحنات بعد</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "claims.html": """
{% extends "base.html" %}
{% block content %}
<div class="kpis">
  <div class="kpi">حجوزات بانتظار الاستلام<b>{{ waiting_count }}</b></div>
  <div class="kpi">شحنات بانتظار الاستلام<b>{{ waiting_qty }}</b></div>
  <div class="kpi">مع المندوبين الآن<b>{{ picked_qty }}</b></div>
</div>

<div class="card">
  <form method="post" action="{{ url_for('set_min_left') }}" class="qty">
    <label>إجبار المندوب على أخذ الباقي إذا بقي أقل من</label>
    <input name="min_left" type="number" min="0" value="{{ min_left }}" required>
    <span>شحنات في الولاية</span>
    <button class="small-btn">حفظ</button>
  </form>
</div>

<div class="card">
  <h3>حجوزات المندوبين</h3>
  <form method="get" class="qty" style="margin-bottom:10px">
    <select name="status" style="width:auto">
      <option value="">كل الحالات</option>
      {% for s in statuses %}<option {% if s == f_status %}selected{% endif %}>{{ s }}</option>{% endfor %}
    </select>
    <button class="small-btn">تصفية</button>
  </form>
  <table>
    <tr><th>#</th><th>المندوب</th><th>الهاتف</th><th>المحافظة</th><th>الولاية</th><th>العدد</th>
        <th>موعد الاستلام</th><th>وقت الحجز</th><th>الحالة</th><th>إجراءات</th></tr>
    {% for c in rows %}
    <tr>
      <td>{{ c.id }}</td>
      <td class="big">{{ c.driver }}</td>
      <td><a href="tel:{{ c.phone }}">{{ c.phone }}</a></td>
      <td>{{ c.governorate or '' }}</td>
      <td>{{ c.wilaya }}</td>
      <td class="big">{{ c.qty }}{% if c.forced %} <small title="أُجبر على أخذ الباقي">⚠️</small>{% endif %}</td>
      <td class="big">{{ c.pickup_time }}</td>
      <td>{{ c.created_at }}</td>
      <td><span class="badge b-{{ c.status.split()[0] }}">{{ c.status }}</span></td>
      <td>
        {% if c.status == WAITING %}
        <form method="post" action="{{ url_for('claim_picked', cid=c.id) }}" style="display:inline">
          <button class="small-btn green">سلّمته الشحنات</button>
        </form>
        {% endif %}
        {% if c.status in (WAITING, PICKED) %}
        <form method="post" action="{{ url_for('claim_cancel', cid=c.id) }}" style="display:inline"
              onsubmit="return confirm('إلغاء الحجز وإرجاع الشحنات للمتاح؟')">
          <button class="small-btn red">إلغاء</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% else %}
    <tr><td colspan="10">لا توجد حجوزات</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "drivers.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>إضافة مندوب</h3>
  <form method="post" action="{{ url_for('add_driver') }}" class="grid">
    <input name="name" placeholder="اسم المندوب" required>
    <input name="phone" inputmode="tel" placeholder="رقم الهاتف" required>
    <input name="pin" inputmode="numeric" pattern="[0-9]{4,8}" placeholder="رمز PIN للدخول (4 أرقام أو أكثر)" required>
    <button type="submit">إضافة</button>
  </form>
  <p style="color:#666">أعطِ كل مندوب اسمه ورمز PIN ليدخل من نفس رابط الموقع ويحجز الشحنات.</p>
</div>

<div class="card">
  <h3>قائمة المندوبين</h3>
  <table>
    <tr><th>#</th><th>الاسم</th><th>الهاتف</th><th>محجوزة حالياً</th><th>تم التوصيل</th><th>تغيير PIN</th><th>إجراءات</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{ r.id }}</td>
      <td>{{ r.name }}{% if not r.pin_hash %} <span class="badge b-بانتظار">بدون PIN</span>{% endif %}</td>
      <td>{% if r.phone %}<a href="tel:{{ r.phone }}">{{ r.phone }}</a>{% endif %}</td>
      <td>{{ r.claimed }}</td>
      <td>{{ r.delivered }}</td>
      <td>
        <form method="post" action="{{ url_for('set_pin', did=r.id) }}" class="qty">
          <input name="pin" inputmode="numeric" pattern="[0-9]{4,8}" placeholder="PIN جديد" required style="width:120px">
          <button class="small-btn">حفظ</button>
        </form>
      </td>
      <td>
        <form method="post" action="{{ url_for('delete_driver', did=r.id) }}" style="display:inline"
              onsubmit="return confirm('حذف المندوب؟ حجوزاته المفتوحة سترجع متاحة.')">
          <button class="small-btn red">حذف</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="7">لا يوجد مندوبون بعد</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "d_home.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>📦 حجز شحنات</h3>
  {% if avail %}
  <form method="post" action="{{ url_for('d_claim') }}" class="grid">
    <div><label>المحافظة</label>
      <select name="governorate" id="gov" required onchange="fillWil()">
        <option value="">— اختر —</option>
        {% for g in avail %}<option value="{{ g }}">{{ g }} ({{ avail[g].values()|sum }})</option>{% endfor %}
      </select></div>
    <div><label>الولاية</label>
      <select name="wilaya" id="wil" required onchange="check()"><option value="">— اختر المحافظة أولاً —</option></select></div>
    <div><label>كم شحنة تستلم؟</label>
      <input name="qty" id="qty" type="number" min="1" required oninput="check()"></div>
    <div><label>متى تجي تستلم؟</label>
      <input name="pickup_time" type="datetime-local" min="{{ now_local }}" required></div>
    <div><label>رقم هاتفك</label>
      <input name="phone" value="{{ phone }}" inputmode="tel" required></div>
    <button type="submit" class="green">تأكيد الحجز</button>
  </form>
  <div id="msg" style="margin-top:10px"></div>
  <p style="color:#666">ملاحظة: إذا بقي في الولاية أقل من {{ min_left }} شحنات بعد حجزك، يجب أن تأخذ الباقي كله.</p>
  <script>
    const AVAIL = {{ avail|tojson }}, MIN_LEFT = {{ min_left }};
    function fillWil(g) {
      const gov = document.getElementById('gov');
      if (g) gov.value = g;
      const ws = AVAIL[gov.value] || {};
      document.getElementById('wil').innerHTML = '<option value="">— اختر —</option>' +
        Object.keys(ws).map(w => '<option value="' + w + '">' + w + ' (' + ws[w] + ')</option>').join('');
      check();
    }
    function pick(g, w) {
      fillWil(g);
      document.getElementById('wil').value = w;
      check();
      document.getElementById('qty').focus();
      window.scrollTo(0, 0);
    }
    function check() {
      const g = document.getElementById('gov').value, w = document.getElementById('wil').value;
      const qtyEl = document.getElementById('qty'), msg = document.getElementById('msg');
      const avail = (AVAIL[g] || {})[w] || 0, q = parseInt(qtyEl.value) || 0;
      qtyEl.max = avail || '';
      if (!avail) { msg.innerHTML = ''; return; }
      const left = avail - q;
      if (q > avail) {
        msg.innerHTML = '<div class="warn">المتاح في ' + w + ' فقط ' + avail + '</div>';
      } else if (q > 0 && left > 0 && left < MIN_LEFT) {
        msg.innerHTML = '<div class="warn">سيبقى ' + left + ' فقط — يجب أن تأخذ الكل: ' + avail + ' شحنة</div>';
        qtyEl.value = avail;
      } else if (q > 0) {
        msg.innerHTML = '<div class="ok">ستحجز ' + q + ' من ' + w + '، ويبقى ' + left + '</div>';
      } else {
        msg.innerHTML = '<div class="ok">المتاح في ' + w + ': ' + avail + '</div>';
      }
    }
  </script>
  {% else %}
    <p class="big">لا توجد شحنات متاحة حالياً 👍</p>
  {% endif %}
</div>

{% if avail %}
<div class="card">
  <h3>المتاح الآن</h3>
  <table>
    <tr><th>المحافظة</th><th>الولاية</th><th>العدد المتاح</th><th></th></tr>
    {% for g, ws in avail.items() %}
      {% for w, n in ws.items() %}
      <tr>
        <td>{{ g }}</td><td class="big">{{ w }}</td><td class="big">{{ n }}</td>
        <td><button class="small-btn green" onclick="pick({{ g|tojson }}, {{ w|tojson }})">اختر</button></td>
      </tr>
      {% endfor %}
    {% endfor %}
  </table>
</div>
{% endif %}
{% endblock %}
""",

    "d_mine.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>حجوزاتي</h3>
  <table>
    <tr><th>#</th><th>المحافظة</th><th>الولاية</th><th>العدد</th><th>موعد الاستلام</th><th>الحالة</th><th></th></tr>
    {% for c in claims %}
    <tr>
      <td>{{ c.id }}</td>
      <td>{{ c.governorate or '' }}</td>
      <td class="big">{{ c.wilaya }}</td>
      <td class="big">{{ c.qty }}</td>
      <td>{{ c.pickup_time }}</td>
      <td><span class="badge b-{{ c.status.split()[0] }}">{{ c.status }}</span></td>
      <td>
        {% if c.status == PICKED %}
        <form method="post" action="{{ url_for('d_claim_done', cid=c.id) }}" style="display:inline"
              onsubmit="return confirm('تأكيد توصيل كل شحنات هذا الحجز؟')">
          <button class="small-btn green">✓ وصّلت الكل</button>
        </form>
        {% endif %}
        {% if c.status == WAITING %}
        <form method="post" action="{{ url_for('d_claim_cancel', cid=c.id) }}" style="display:inline"
              onsubmit="return confirm('إلغاء الحجز وإرجاع الشحنات؟')">
          <button class="small-btn gray">إلغاء الحجز</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% else %}
    <tr><td colspan="7">ليس عندك حجوزات — <a href="{{ url_for('d_home') }}">احجز من هنا</a></td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",
}

# ----------------------------------------------------------------------
# التطبيق وقاعدة البيانات
# ----------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.jinja_loader = DictLoader(TEMPLATES)
app.jinja_env.globals.update(AVAILABLE=AVAILABLE, CLAIMED=CLAIMED, DELIVERED=DELIVERED,
                             WAITING=WAITING, PICKED=PICKED)


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # ترقية جدول المندوبين من النسخ السابقة
    driver_cols = _columns(conn, "drivers")
    for col in ("pin_hash", "phone"):
        if col not in driver_cols:
            conn.execute(f"ALTER TABLE drivers ADD COLUMN {col} TEXT")
    conn.commit()
    conn.close()


def db_exec(sql, params=()):
    """ينفّذ أمراً ويعيد عدد الصفوف المتأثرة."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def db_df(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def get_min_left():
    """إذا بقي في الولاية أقل من هذا العدد يُجبَر المندوب على أخذ الباقي."""
    row = db_df("SELECT value FROM settings WHERE key = 'min_left'")
    return int(row["value"][0]) if not row.empty else DEFAULT_MIN_LEFT


def driver_names():
    return db_df("SELECT name FROM drivers ORDER BY name")["name"].tolist()


def now_oman():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def gov_order(gov):
    return list(OMAN).index(gov) if gov in OMAN else 99


init_db()

PUBLIC_ENDPOINTS = {"login", "d_login", "static"}


@app.before_request
def require_login():
    endpoint = request.endpoint or ""
    if endpoint in PUBLIC_ENDPOINTS:
        return None
    role = session.get("role")
    if endpoint.startswith("d_"):
        # صفحات المندوب: يجب أن يكون المندوب ما زال موجوداً في القائمة
        if role == "driver" and session.get("driver") in driver_names():
            return None
        session.clear()
        return redirect(url_for("login"))
    if endpoint == "logout" and role:
        return None
    if role == "admin":
        return None
    if role == "driver":
        return redirect(url_for("d_home"))
    return redirect(url_for("login"))


# ----------------------------------------------------------------------
# الدخول
# ----------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session.clear()
            session["role"] = "admin"
            return redirect(url_for("shipments"))
        flash("كلمة المرور غير صحيحة")
    return render_template("login.html", title="دخول", driver_names=driver_names())


@app.route("/driver/login", methods=["POST"])
def d_login():
    name = request.form.get("name", "").strip()
    pin = request.form.get("pin", "").strip()
    row = db_df("SELECT pin_hash FROM drivers WHERE name = ?", (name,))
    if not row.empty and row["pin_hash"][0] and check_password_hash(row["pin_hash"][0], pin):
        session.clear()
        session["role"] = "driver"
        session["driver"] = name
        return redirect(url_for("d_home"))
    flash("الاسم أو رمز PIN غير صحيح")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("shipments"))


# ----------------------------------------------------------------------
# 1) الشحنات (المدير)
# ----------------------------------------------------------------------
@app.route("/shipments")
def shipments():
    df = db_df("SELECT governorate, wilaya, status, COUNT(*) AS n FROM shipments "
               "GROUP BY governorate, wilaya, status")
    totals = {s: int(df.loc[df["status"] == s, "n"].sum()) for s in (AVAILABLE, CLAIMED, DELIVERED)}
    summary = []
    for gov in sorted(df["governorate"].unique(), key=gov_order):
        gdf = df[df["governorate"] == gov]
        g = {"name": gov, "wilayat": []}
        for s in (AVAILABLE, CLAIMED, DELIVERED):
            g[s] = int(gdf.loc[gdf["status"] == s, "n"].sum())
        for wil in sorted(gdf["wilaya"].unique()):
            wdf = gdf[gdf["wilaya"] == wil]
            g["wilayat"].append({"name": wil, **{s: int(wdf.loc[wdf["status"] == s, "n"].sum())
                                                 for s in (AVAILABLE, CLAIMED, DELIVERED)}})
        summary.append(g)
    return render_template("shipments.html", title="الشحنات", oman=OMAN,
                           totals=totals, summary=summary, max_bulk=MAX_BULK)


@app.route("/shipments/add", methods=["POST"])
def add_shipments():
    gov = request.form.get("governorate", "").strip()
    wilaya = request.form.get("wilaya", "").strip()
    try:
        count = int(request.form.get("count", ""))
        if not 1 <= count <= MAX_BULK:
            raise ValueError
    except ValueError:
        flash(f"اكتب عدداً من 1 إلى {MAX_BULK}")
        return redirect(url_for("shipments"))
    if wilaya not in OMAN.get(gov, []):
        flash("اختر المحافظة والولاية")
        return redirect(url_for("shipments"))

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executemany("INSERT INTO shipments (governorate, wilaya, status, created_at) VALUES (?,?,?,?)",
                         [(gov, wilaya, AVAILABLE, now_oman())] * count)
        conn.commit()
    finally:
        conn.close()
    flash(f"✅ تمت إضافة {count} شحنة في {wilaya} ({gov})")
    return redirect(url_for("shipments"))


@app.route("/shipments/remove", methods=["POST"])
def remove_shipments():
    try:
        count = int(request.form.get("count", ""))
        if count < 1:
            raise ValueError
    except ValueError:
        flash("اكتب عدداً صحيحاً")
        return redirect(url_for("shipments"))
    removed = db_exec(
        """DELETE FROM shipments WHERE id IN (
               SELECT id FROM shipments WHERE status = ? AND governorate = ? AND wilaya = ?
               ORDER BY id DESC LIMIT ?)""",
        (AVAILABLE, request.form.get("governorate", ""), request.form.get("wilaya", ""), count))
    flash(f"تم حذف {removed} شحنة متاحة")
    return redirect(url_for("shipments"))


# ----------------------------------------------------------------------
# 2) حجوزات المندوبين (المدير)
# ----------------------------------------------------------------------
def release_claim(conn, cid):
    """يرجع شحنات الحجز التي لم توصَّل إلى المتاح."""
    conn.execute("UPDATE shipments SET driver = '', status = ?, claim_id = NULL "
                 "WHERE claim_id = ? AND status = ?", (AVAILABLE, cid, CLAIMED))
    conn.execute("UPDATE claims SET status = ? WHERE id = ?", (CANCELLED, cid))


@app.route("/claims")
def claims():
    f_status = request.args.get("status", "")
    where, params = ("WHERE status = ?", (f_status,)) if f_status else ("", ())
    rows = db_df(f"SELECT * FROM claims {where} ORDER BY "
                 f"CASE status WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END, pickup_time LIMIT 300",
                 (*params, WAITING, PICKED)).to_dict("records")
    stats = db_df("SELECT status, COUNT(*) AS n, COALESCE(SUM(qty), 0) AS q FROM claims GROUP BY status")
    stat = {r.status: (int(r.n), int(r.q)) for r in stats.itertuples()}
    return render_template("claims.html", title="حجوزات المندوبين", rows=rows,
                           statuses=CLAIM_STATUSES, f_status=f_status, min_left=get_min_left(),
                           waiting_count=stat.get(WAITING, (0, 0))[0],
                           waiting_qty=stat.get(WAITING, (0, 0))[1],
                           picked_qty=stat.get(PICKED, (0, 0))[1])


@app.route("/claims/<int:cid>/picked", methods=["POST"])
def claim_picked(cid):
    db_exec("UPDATE claims SET status = ? WHERE id = ? AND status = ?", (PICKED, cid, WAITING))
    flash("تم تسجيل تسليم الشحنات للمندوب")
    return redirect(request.referrer or url_for("claims"))


@app.route("/claims/<int:cid>/cancel", methods=["POST"])
def claim_cancel(cid):
    conn = sqlite3.connect(DB_PATH)
    try:
        release_claim(conn, cid)
        conn.commit()
    finally:
        conn.close()
    flash("تم إلغاء الحجز ورجعت الشحنات متاحة")
    return redirect(request.referrer or url_for("claims"))


@app.route("/settings/min-left", methods=["POST"])
def set_min_left():
    try:
        value = int(request.form.get("min_left", ""))
        if value < 0:
            raise ValueError
    except ValueError:
        flash("اكتب رقماً صحيحاً")
        return redirect(url_for("claims"))
    db_exec("INSERT OR REPLACE INTO settings (key, value) VALUES ('min_left', ?)", (str(value),))
    flash(f"تم الحفظ: إذا بقي أقل من {value} يُجبَر المندوب على أخذ الباقي")
    return redirect(url_for("claims"))


# ----------------------------------------------------------------------
# 3) المندوبين (المدير)
# ----------------------------------------------------------------------
def valid_pin(pin):
    return pin.isdigit() and 4 <= len(pin) <= 8


@app.route("/drivers")
def drivers():
    rows = db_df(
        """SELECT d.id, d.name, d.pin_hash, d.phone,
                  COALESCE(SUM(s.status = ?), 0) AS claimed,
                  COALESCE(SUM(s.status = ?), 0) AS delivered
           FROM drivers d LEFT JOIN shipments s ON s.driver = d.name
           GROUP BY d.id ORDER BY d.name""", (CLAIMED, DELIVERED)).to_dict("records")
    for r in rows:
        r["claimed"], r["delivered"] = int(r["claimed"]), int(r["delivered"])
    return render_template("drivers.html", title="المندوبين", rows=rows)


@app.route("/drivers/add", methods=["POST"])
def add_driver():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    pin = request.form.get("pin", "").strip()
    if not name or name == UNSPECIFIED:
        flash("اكتب اسم المندوب")
    elif not phone:
        flash("اكتب رقم هاتف المندوب")
    elif not valid_pin(pin):
        flash("رمز PIN يجب أن يكون من 4 إلى 8 أرقام")
    elif name in driver_names():
        flash("هذا الاسم موجود مسبقاً")
    else:
        db_exec("INSERT INTO drivers (name, pin_hash, phone) VALUES (?, ?, ?)",
                (name, generate_password_hash(pin), phone))
        flash(f"تمت إضافة {name} — يدخل باسمه ورمز PIN")
    return redirect(url_for("drivers"))


@app.route("/drivers/<int:did>/pin", methods=["POST"])
def set_pin(did):
    pin = request.form.get("pin", "").strip()
    if not valid_pin(pin):
        flash("رمز PIN يجب أن يكون من 4 إلى 8 أرقام")
    else:
        db_exec("UPDATE drivers SET pin_hash = ? WHERE id = ?", (generate_password_hash(pin), did))
        flash("تم تغيير رمز PIN")
    return redirect(url_for("drivers"))


@app.route("/drivers/<int:did>/delete", methods=["POST"])
def delete_driver(did):
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute("SELECT name FROM drivers WHERE id = ?", (did,)).fetchone()
        if row:
            # الحجوزات المفتوحة ترجع شحناتها متاحة لغيره
            for (cid,) in conn.execute("SELECT id FROM claims WHERE driver = ? AND status IN (?, ?)",
                                       (row[0], WAITING, PICKED)).fetchall():
                release_claim(conn, cid)
            conn.execute("DELETE FROM drivers WHERE id = ?", (did,))
            conn.commit()
            flash("تم حذف المندوب")
    finally:
        conn.close()
    return redirect(url_for("drivers"))


# ----------------------------------------------------------------------
# 4) صفحات المندوب
# ----------------------------------------------------------------------
def available_map():
    """{المحافظة: {الولاية: عدد الشحنات المتاحة}} مرتبة حسب المحافظات."""
    df = db_df("SELECT governorate, wilaya, COUNT(*) AS n FROM shipments WHERE status = ? "
               "GROUP BY governorate, wilaya ORDER BY n DESC", (AVAILABLE,))
    result = {}
    for gov in sorted(df["governorate"].unique(), key=gov_order):
        gdf = df[df["governorate"] == gov]
        result[gov] = {r.wilaya: int(r.n) for r in gdf.itertuples()}
    return result


@app.route("/driver")
def d_home():
    phone = db_df("SELECT phone FROM drivers WHERE name = ?", (session["driver"],))["phone"][0] or ""
    return render_template("d_home.html", title="حجز شحنات", avail=available_map(),
                           min_left=get_min_left(), phone=phone,
                           now_local=datetime.now(TZ).strftime("%Y-%m-%dT%H:%M"))


@app.route("/driver/claim", methods=["POST"])
def d_claim():
    me = session["driver"]
    gov = request.form.get("governorate", "")
    wilaya = request.form.get("wilaya", "")
    phone = request.form.get("phone", "").strip()
    pickup = request.form.get("pickup_time", "").strip().replace("T", " ")
    try:
        qty = int(request.form.get("qty", "0"))
        if qty < 1:
            raise ValueError
    except ValueError:
        flash("اكتب عدداً صحيحاً")
        return redirect(url_for("d_home"))
    if not phone or not pickup:
        flash("اكتب رقم هاتفك وموعد الاستلام")
        return redirect(url_for("d_home"))

    min_left = get_min_left()
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        # قفل الكتابة حتى لا يحجز مندوبان نفس الشحنات في نفس اللحظة
        conn.execute("BEGIN IMMEDIATE")
        avail = conn.execute("SELECT COUNT(*) FROM shipments WHERE status = ? AND governorate = ? AND wilaya = ?",
                             (AVAILABLE, gov, wilaya)).fetchone()[0]
        if avail == 0:
            conn.execute("ROLLBACK")
            flash("لم تعد هناك شحنات متاحة في هذه الولاية")
            return redirect(url_for("d_home"))
        qty = min(qty, avail)
        forced = 0 < avail - qty < min_left
        if forced:
            qty = avail
        cid = conn.execute(
            """INSERT INTO claims (driver, phone, governorate, wilaya, qty, pickup_time, created_at, status, forced)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (me, phone, gov, wilaya, qty, pickup, now_oman(), WAITING, int(forced)),
        ).lastrowid
        conn.execute(
            """UPDATE shipments SET driver = ?, status = ?, claim_id = ?
               WHERE id IN (SELECT id FROM shipments WHERE status = ? AND governorate = ? AND wilaya = ?
                            ORDER BY id LIMIT ?)""",
            (me, CLAIMED, cid, AVAILABLE, gov, wilaya, qty),
        )
        conn.execute("UPDATE drivers SET phone = ? WHERE name = ?", (phone, me))
        conn.execute("COMMIT")
    finally:
        conn.close()

    msg = f"✅ تم حجز {qty} شحنة في {wilaya} — موعد الاستلام {pickup}"
    if forced:
        msg += f" (أُضيف الباقي لأنه أقل من {min_left})"
    flash(msg)
    return redirect(url_for("d_mine"))


@app.route("/driver/mine")
def d_mine():
    claims_list = db_df("SELECT * FROM claims WHERE driver = ? AND status <> ? ORDER BY id DESC LIMIT 50",
                        (session["driver"], CANCELLED)).to_dict("records")
    return render_template("d_mine.html", title="حجوزاتي", claims=claims_list)


@app.route("/driver/claims/<int:cid>/cancel", methods=["POST"])
def d_claim_cancel(cid):
    conn = sqlite3.connect(DB_PATH)
    try:
        if conn.execute("SELECT 1 FROM claims WHERE id = ? AND driver = ? AND status = ?",
                        (cid, session["driver"], WAITING)).fetchone():
            release_claim(conn, cid)
            conn.commit()
            flash("تم إلغاء الحجز ورجعت الشحنات متاحة")
    finally:
        conn.close()
    return redirect(url_for("d_mine"))


@app.route("/driver/claims/<int:cid>/done", methods=["POST"])
def d_claim_done(cid):
    conn = sqlite3.connect(DB_PATH)
    try:
        if conn.execute("SELECT 1 FROM claims WHERE id = ? AND driver = ? AND status = ?",
                        (cid, session["driver"], PICKED)).fetchone():
            conn.execute("UPDATE shipments SET status = ?, delivered_at = ? WHERE claim_id = ? AND status = ?",
                         (DELIVERED, now_oman(), cid, CLAIMED))
            conn.execute("UPDATE claims SET status = ? WHERE id = ?", (CLAIM_DONE, cid))
            conn.commit()
            flash("✅ تم تسجيل التوصيل")
    finally:
        conn.close()
    return redirect(url_for("d_mine"))


# ----------------------------------------------------------------------
# 5) تصدير Excel
# ----------------------------------------------------------------------
@app.route("/export")
def export_excel():
    places = db_df(
        """SELECT governorate AS "المحافظة", wilaya AS "الولاية",
                  SUM(status = ?) AS "متاحة", SUM(status = ?) AS "محجوزة", SUM(status = ?) AS "تم التوصيل"
           FROM shipments GROUP BY governorate, wilaya ORDER BY governorate, wilaya""",
        (AVAILABLE, CLAIMED, DELIVERED))
    claims_df = db_df("SELECT * FROM claims ORDER BY id").rename(columns=CLAIM_COLUMNS_AR)
    drivers_df = db_df('SELECT name AS "الاسم", phone AS "الهاتف" FROM drivers ORDER BY name')

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        places.to_excel(writer, sheet_name="الشحنات", index=False)
        claims_df.to_excel(writer, sheet_name="حجوزات المندوبين", index=False)
        drivers_df.to_excel(writer, sheet_name="المندوبين", index=False)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"shipments_{datetime.now(TZ).date().isoformat()}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ----------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
