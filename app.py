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

PAID = "تم التحصيل"
PENDING = "معلق"
AVAILABLE = "متاح"
CLAIMED = "مستلم"
DELIVERED = "تم التوصيل"
ORDER_STATUSES = [AVAILABLE, CLAIMED, DELIVERED]
# حالات حجز المندوب
WAITING = "بانتظار الاستلام"
PICKED = "استلمها المندوب"
CLAIM_DONE = "تم التوصيل"
CANCELLED = "ملغي"
CLAIM_STATUSES = [WAITING, PICKED, CLAIM_DONE, CANCELLED]
DEFAULT_MIN_LEFT = 10
EXPENSE_TYPES = ["بترول", "أكل", "صيانة", "أخرى"]
UNSPECIFIED = "غير محدد"
MAX_BULK = 500

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
WILAYAT = [w for ws in OMAN.values() for w in ws]
WILAYA_TO_GOV = {w: g for g, ws in OMAN.items() for w in ws}

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_ref TEXT,
    customer_phone TEXT,
    governorate TEXT,
    wilaya TEXT NOT NULL,
    driver TEXT NOT NULL DEFAULT '',
    fee REAL NOT NULL,
    payment_status TEXT NOT NULL,
    order_date TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'متاح',
    claimed_at TEXT,
    delivered_at TEXT,
    claim_id INTEGER
);
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
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
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
    name TEXT NOT NULL UNIQUE,
    pin_hash TEXT,
    phone TEXT
);
"""

ORDER_COLUMNS_AR = {
    "id": "رقم", "order_ref": "رقم الطلب", "customer_phone": "هاتف الزبون",
    "governorate": "المحافظة", "wilaya": "الولاية", "driver": "المندوب",
    "fee": "سعر التوصيل", "payment_status": "حالة الدفع", "order_date": "التاريخ",
    "notes": "ملاحظات / العنوان", "status": "حالة الطلب",
    "claimed_at": "وقت الاستلام", "delivered_at": "وقت التوصيل",
}
CLAIM_COLUMNS_AR = {
    "id": "رقم الحجز", "driver": "المندوب", "phone": "الهاتف", "governorate": "المحافظة",
    "wilaya": "الولاية", "qty": "العدد", "pickup_time": "موعد الاستلام",
    "created_at": "وقت الحجز", "status": "الحالة", "forced": "أُجبر على الباقي",
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
  nav a,nav span{color:#fff;text-decoration:none;font-weight:bold}
  .wrap{padding:20px;max-width:1200px;margin:auto}
  .card{background:#fff;border-radius:10px;padding:16px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08);overflow-x:auto}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:20px}
  .kpi{background:#fff;border-radius:10px;padding:14px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.08)}
  .kpi b{display:block;font-size:22px;margin-top:6px}
  form.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;align-items:end}
  input,select,button{padding:9px;border:1px solid #ccc;border-radius:6px;font-size:15px;width:100%;box-sizing:border-box}
  button{background:#1f3a5f;color:#fff;border:0;cursor:pointer}
  .btn-link{background:#2e8b57;color:#fff;padding:9px 14px;border-radius:6px;text-decoration:none;display:inline-block}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{padding:8px;border-bottom:1px solid #eee;text-align:right;vertical-align:middle}
  th{background:#f0f3f8}
  .pos{color:#0a7d32}.neg{color:#c0392b}
  .small-btn{width:auto;padding:5px 10px;font-size:13px;margin:2px}
  .green{background:#2e8b57}.red{background:#c0392b}.gray{background:#7f8c8d}
  .flash{background:#fff3cd;padding:10px;border-radius:6px;margin-bottom:12px}
  .top{background:#e8f7ee}
  .badge{padding:3px 8px;border-radius:10px;font-size:12px;color:#fff;white-space:nowrap}
  .b-متاح{background:#f0ad4e}.b-مستلم{background:#337ab7}.b-تم{background:#2e8b57}
  .gov{background:#eef3fb;font-weight:bold}
  .qty{display:flex;gap:6px;align-items:center}.qty input{width:80px}.qty button{width:auto}
  .big{font-size:20px;font-weight:bold}
  details summary{cursor:pointer;color:#1f3a5f}
  .tabs a{display:inline-block;margin-left:10px}
  .warn{background:#fdecea;color:#a12;padding:10px;border-radius:6px;font-weight:bold}
  .ok{background:#e8f7ee;color:#0a6;padding:10px;border-radius:6px}
  .b-بانتظار{background:#f0ad4e}.b-استلمها{background:#337ab7}.b-ملغي{background:#999}
</style>
</head>
<body>
<nav>
  {% if session.get('role') == 'admin' %}
    <a href="{{ url_for('dashboard') }}">لوحة التحكم</a>
    <a href="{{ url_for('orders') }}">الطلبيات</a>
    <a href="{{ url_for('claims') }}">حجوزات المندوبين</a>
    <a href="{{ url_for('expenses') }}">المصروفات</a>
    <a href="{{ url_for('drivers') }}">المندوبين</a>
    <a href="{{ url_for('export_excel') }}">تصدير Excel</a>
    <a href="{{ url_for('logout') }}" style="margin-right:auto">خروج</a>
  {% elif session.get('role') == 'driver' %}
    <span>👤 {{ session.get('driver') }}</span>
    <a href="{{ url_for('d_home') }}">استلام طلبيات</a>
    <a href="{{ url_for('d_mine') }}">حجوزاتي</a>
    <a href="{{ url_for('logout') }}" style="margin-right:auto">خروج</a>
  {% else %}
    <span>نظام توزيع الطلبيات</span>
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

    "gov_select.html": """
    <select name="governorate" id="gov" required onchange="fillWilayat()">
      <option value="">— المحافظة —</option>
      {% for g in oman %}<option>{{ g }}</option>{% endfor %}
    </select>
    <select name="wilaya" id="wil" required><option value="">— الولاية —</option></select>
    <script>
      const OMAN = {{ oman|tojson }};
      function fillWilayat() {
        const w = document.getElementById('wil');
        const list = OMAN[document.getElementById('gov').value] || [];
        w.innerHTML = '<option value="">— الولاية —</option>' +
          list.map(x => '<option>' + x + '</option>').join('');
      }
    </script>
""",

    "orders.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>تسجيل طلبيات جديدة</h3>
  <form method="post" action="{{ url_for('add_order') }}" class="grid">
    {% include "gov_select.html" %}
    <div><label>عدد الطلبيات</label>
      <input name="count" type="number" min="1" max="{{ max_bulk }}" value="1" required></div>
    <input name="fee" type="number" step="0.001" min="0" placeholder="سعر التوصيل للطلب (ر.ع)" required>
    <input name="notes" placeholder="العنوان / المكان بالتفصيل">
    <input name="customer_phone" placeholder="هاتف الزبون (اختياري)">
    <input name="order_ref" placeholder="رقم الطلب (اختياري)">
    <select name="payment_status">
      <option>معلق</option>
      <option>تم التحصيل</option>
    </select>
    <input name="order_date" type="date" value="{{ today }}" required>
    <select name="driver">
      <option value="">— متاحة لكل المندوبين —</option>
      {% for d in driver_names %}<option>{{ d }}</option>{% endfor %}
    </select>
    <button type="submit">حفظ</button>
  </form>
</div>

<div class="kpis">
  <div class="kpi">متاحة للاستلام<b>{{ totals[AVAILABLE] }}</b></div>
  <div class="kpi">مستلمة مع المندوبين<b>{{ totals[CLAIMED] }}</b></div>
  <div class="kpi">تم توصيلها<b>{{ totals[DELIVERED] }}</b></div>
</div>

<div class="card">
  <h3>التوزيع حسب المحافظة والولاية</h3>
  <table>
    <tr><th>المحافظة / الولاية</th><th>متاحة</th><th>مستلمة</th><th>تم التوصيل</th></tr>
    {% for g in summary %}
      <tr class="gov"><td>{{ g.name }}</td><td>{{ g[AVAILABLE] }}</td><td>{{ g[CLAIMED] }}</td><td>{{ g[DELIVERED] }}</td></tr>
      {% for w in g.wilayat %}
      <tr><td>&nbsp;&nbsp;&nbsp;{{ w.name }}</td><td>{{ w[AVAILABLE] }}</td><td>{{ w[CLAIMED] }}</td><td>{{ w[DELIVERED] }}</td></tr>
      {% endfor %}
    {% else %}
      <tr><td colspan="4">لا توجد طلبيات بعد</td></tr>
    {% endfor %}
  </table>
</div>

<div class="card">
  <h3>حسب المندوب</h3>
  <table>
    <tr><th>المندوب</th><th>مستلمة حالياً</th><th>تم التوصيل</th><th>الولايات</th></tr>
    {% for d in by_driver %}
    <tr><td>{{ d.driver }}</td><td>{{ d.claimed }}</td><td>{{ d.delivered }}</td><td>{{ d.wilayat }}</td></tr>
    {% else %}
    <tr><td colspan="4">لم يستلم أي مندوب طلبيات بعد</td></tr>
    {% endfor %}
  </table>
</div>

<div class="card">
  <h3>قائمة الطلبيات</h3>
  <form method="get" class="grid" style="margin-bottom:12px">
    <select name="status">
      <option value="">كل الحالات</option>
      {% for s in statuses %}<option {% if s == f_status %}selected{% endif %}>{{ s }}</option>{% endfor %}
    </select>
    <select name="gov">
      <option value="">كل المحافظات</option>
      {% for g in oman %}<option {% if g == f_gov %}selected{% endif %}>{{ g }}</option>{% endfor %}
    </select>
    <button type="submit">تصفية</button>
  </form>
  <table>
    <tr><th>#</th><th>التاريخ</th><th>المحافظة</th><th>الولاية</th><th>العنوان</th><th>الزبون</th>
        <th>السعر</th><th>الحالة</th><th>المندوب</th><th>الدفع</th><th>إجراءات</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{ r.id }}</td>
      <td>{{ r.order_date }}</td>
      <td>{{ r.governorate or '' }}</td>
      <td>{{ r.wilaya }}</td>
      <td>{{ r.notes or '' }}</td>
      <td>{{ r.customer_phone or '' }}</td>
      <td>{{ '%.3f'|format(r.fee) }}</td>
      <td><span class="badge b-{{ r.status.split()[0] }}">{{ r.status }}</span></td>
      <td>{{ r.driver or '—' }}</td>
      <td>{{ r.payment_status }}</td>
      <td>
        <form method="post" action="{{ url_for('toggle_payment', oid=r.id) }}" style="display:inline">
          <button class="small-btn">تغيير الدفع</button>
        </form>
        {% if r.status == CLAIMED %}
        <form method="post" action="{{ url_for('unassign_order', oid=r.id) }}" style="display:inline">
          <button class="small-btn gray">سحب من المندوب</button>
        </form>
        {% endif %}
        <form method="post" action="{{ url_for('delete_order', oid=r.id) }}" style="display:inline"
              onsubmit="return confirm('هل تريد الحذف؟')">
          <button class="small-btn red">حذف</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="11">لا توجد طلبيات</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "d_home.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>📦 استلام طلبيات</h3>
  {% if avail %}
  <form method="post" action="{{ url_for('d_claim') }}" class="grid" id="claimForm">
    <div><label>المحافظة</label>
      <select name="governorate" id="gov" required onchange="fillWil()">
        <option value="">— اختر —</option>
        {% for g in avail %}<option value="{{ g }}">{{ g }} ({{ avail[g].values()|sum }})</option>{% endfor %}
      </select></div>
    <div><label>الولاية</label>
      <select name="wilaya" id="wil" required onchange="check()"><option value="">— اختر المحافظة أولاً —</option></select></div>
    <div><label>كم طلبية تستلم؟</label>
      <input name="qty" id="qty" type="number" min="1" required oninput="check()"></div>
    <div><label>متى تجي تستلم؟</label>
      <input name="pickup_time" type="datetime-local" min="{{ now_local }}" required></div>
    <div><label>رقم هاتفك</label>
      <input name="phone" value="{{ phone }}" inputmode="tel" required></div>
    <button type="submit" class="green">تأكيد الاستلام</button>
  </form>
  <div id="msg" style="margin-top:10px"></div>
  <p style="color:#666">ملاحظة: إذا بقي في الولاية أقل من {{ min_left }} طلبيات بعد استلامك، يجب أن تستلم الباقي كله.</p>
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
        msg.innerHTML = '<div class="warn">سيبقى ' + left + ' فقط — يجب أن تستلم الكل: ' + avail + ' طلبية</div>';
        qtyEl.value = avail;
      } else if (q > 0) {
        msg.innerHTML = '<div class="ok">ستستلم ' + q + ' من ' + w + '، ويبقى ' + left + '</div>';
      } else {
        msg.innerHTML = '<div class="ok">المتاح في ' + w + ': ' + avail + '</div>';
      }
    }
  </script>
  {% else %}
    <p class="big">لا توجد طلبيات متاحة حالياً 👍</p>
  {% endif %}
</div>

<div class="card">
  <h3>المتاح الآن حسب المحافظة والولاية</h3>
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
              onsubmit="return confirm('تأكيد توصيل كل طلبيات هذا الحجز؟')">
          <button class="small-btn green">✓ وصّلت الكل</button>
        </form>
        {% endif %}
        {% if c.status == WAITING %}
        <form method="post" action="{{ url_for('d_claim_cancel', cid=c.id) }}" style="display:inline"
              onsubmit="return confirm('إلغاء الحجز وإرجاع الطلبيات؟')">
          <button class="small-btn gray">إلغاء الحجز</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% if c.orders %}
    <tr><td></td><td colspan="6">
      <details><summary>تفاصيل الطلبيات ({{ c.orders|length }})</summary>
        <table>
          {% for o in c.orders %}
          <tr><td>#{{ o.id }}</td><td>{{ o.notes or '' }}</td>
              <td>{% if o.customer_phone %}<a href="tel:{{ o.customer_phone }}">{{ o.customer_phone }}</a>{% endif %}</td>
              <td>{{ o.status }}</td></tr>
          {% endfor %}
        </table>
      </details>
    </td></tr>
    {% endif %}
    {% else %}
    <tr><td colspan="7">ليس عندك حجوزات — <a href="{{ url_for('d_home') }}">استلم من هنا</a></td></tr>
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
  <div class="kpi">طلبيات بانتظار الاستلام<b>{{ waiting_qty }}</b></div>
  <div class="kpi">مع المندوبين الآن<b>{{ picked_qty }}</b></div>
</div>

<div class="card">
  <form method="post" action="{{ url_for('set_min_left') }}" class="qty">
    <label>إجبار المندوب على استلام الباقي إذا بقي أقل من</label>
    <input name="min_left" type="number" min="0" value="{{ min_left }}" required>
    <span>طلبيات في الولاية</span>
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
      <td class="big">{{ c.qty }}{% if c.forced %} <small title="أُجبر على استلام الباقي">⚠️</small>{% endif %}</td>
      <td class="big">{{ c.pickup_time }}</td>
      <td>{{ c.created_at }}</td>
      <td><span class="badge b-{{ c.status.split()[0] }}">{{ c.status }}</span></td>
      <td>
        {% if c.status == WAITING %}
        <form method="post" action="{{ url_for('claim_picked', cid=c.id) }}" style="display:inline">
          <button class="small-btn green">سلّمته الطلبيات</button>
        </form>
        {% endif %}
        {% if c.status in (WAITING, PICKED) %}
        <form method="post" action="{{ url_for('claim_cancel', cid=c.id) }}" style="display:inline"
              onsubmit="return confirm('إلغاء الحجز وإرجاع الطلبيات للمتاح؟')">
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
          <button class="small-btn red">حذف</button>
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
  <h3>إضافة مندوب</h3>
  <form method="post" action="{{ url_for('add_driver') }}" class="grid">
    <input name="name" placeholder="اسم المندوب أو رقم السيارة" required>
    <input name="phone" inputmode="tel" placeholder="رقم الهاتف" required>
    <input name="pin" inputmode="numeric" pattern="[0-9]{4,8}" placeholder="رمز PIN للدخول (4 أرقام أو أكثر)" required>
    <button type="submit">إضافة</button>
  </form>
  <p style="color:#666">أعطِ كل مندوب اسمه ورمز PIN ليدخل من نفس رابط الموقع ويستلم الطلبيات.</p>
</div>

<div class="card">
  <h3>قائمة المندوبين</h3>
  <table>
    <tr><th>#</th><th>الاسم</th><th>الهاتف</th><th>مستلمة حالياً</th><th>تم التوصيل</th><th>تغيير PIN</th><th>إجراءات</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{ r.id }}</td>
      <td>{{ r.name }}{% if not r.pin_hash %} <span class="badge b-متاح">بدون PIN</span>{% endif %}</td>
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
              onsubmit="return confirm('حذف المندوب؟ طلبياته المستلمة سترجع متاحة.')">
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
app.jinja_env.globals.update(AVAILABLE=AVAILABLE, CLAIMED=CLAIMED, DELIVERED=DELIVERED,
                             WAITING=WAITING, PICKED=PICKED)


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    # ترقية قاعدة بيانات النسخة السابقة
    cols = _columns(conn, "orders")
    for col, typ in (("governorate", "TEXT"), ("claimed_at", "TEXT"),
                     ("delivered_at", "TEXT"), ("claim_id", "INTEGER")):
        if col not in cols:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {col} {typ}")
    if "status" not in cols:
        conn.execute(f"ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT '{AVAILABLE}'")
        # الطلبات القديمة كانت مسجلة باسم المندوب مباشرة
        conn.execute("UPDATE orders SET status = ? WHERE driver <> ''", (CLAIMED,))
    for wilaya, gov in WILAYA_TO_GOV.items():
        conn.execute("UPDATE orders SET governorate = ? WHERE governorate IS NULL AND wilaya = ?",
                     (gov, wilaya))
    driver_cols = _columns(conn, "drivers")
    for col in ("pin_hash", "phone"):
        if col not in driver_cols:
            conn.execute(f"ALTER TABLE drivers ADD COLUMN {col} TEXT")

    # نقل أسماء المندوبين المكتوبة سابقاً إلى القائمة الثابتة
    conn.execute(
        """INSERT OR IGNORE INTO drivers (name)
           SELECT driver FROM orders WHERE driver <> ''
           UNION SELECT driver FROM expenses""")
    conn.execute("DELETE FROM drivers WHERE name = ?", (UNSPECIFIED,))
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


def db_exec_many(sql, rows):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def db_df(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def get_min_left():
    """إذا بقي في الولاية أقل من هذا العدد يُجبَر المندوب على استلام الباقي."""
    row = db_df("SELECT value FROM settings WHERE key = 'min_left'")
    return int(row["value"][0]) if not row.empty else DEFAULT_MIN_LEFT


def driver_names():
    return db_df("SELECT name FROM drivers ORDER BY name")["name"].tolist()


def valid_driver(name):
    """يعيد اسم المندوب إذا كان من القائمة، وإلا None."""
    name = (name or "").strip()
    return name if name in driver_names() else None


def today_oman():
    return datetime.now(TZ).date()


def now_oman():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


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
            return redirect(url_for("dashboard"))
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
    return redirect(url_for("dashboard"))


# ----------------------------------------------------------------------
# 1) الطلبيات (المدير)
# ----------------------------------------------------------------------
def build_summary(df):
    """تجميع عدد الطلبيات لكل محافظة وولاية حسب الحالة."""
    summary = []
    if df.empty:
        return summary
    df = df.assign(governorate=df["governorate"].fillna(UNSPECIFIED))
    counts = df.groupby(["governorate", "wilaya", "status"]).size()
    for gov in sorted(df["governorate"].unique(), key=lambda g: list(OMAN).index(g) if g in OMAN else 99):
        gdf = df[df["governorate"] == gov]
        g = {"name": gov, "wilayat": []}
        for s in ORDER_STATUSES:
            g[s] = int((gdf["status"] == s).sum())
        for wil in sorted(gdf["wilaya"].unique()):
            w = {"name": wil}
            for s in ORDER_STATUSES:
                w[s] = int(counts.get((gov, wil, s), 0))
            g["wilayat"].append(w)
        summary.append(g)
    return summary


@app.route("/orders")
def orders():
    f_status = request.args.get("status", "")
    f_gov = request.args.get("gov", "")
    clauses, params = [], []
    if f_status:
        clauses.append("status = ?")
        params.append(f_status)
    if f_gov:
        clauses.append("governorate = ?")
        params.append(f_gov)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db_df("SELECT * FROM orders" + where + " ORDER BY id DESC LIMIT 300", params).to_dict("records")

    all_df = db_df("SELECT id, governorate, wilaya, status, driver FROM orders")
    totals = {s: int((all_df["status"] == s).sum()) for s in ORDER_STATUSES}
    by_driver = db_df(
        """SELECT driver,
                  SUM(status = ?) AS claimed,
                  SUM(status = ?) AS delivered,
                  GROUP_CONCAT(DISTINCT CASE WHEN status = ? THEN wilaya END) AS wilayat
           FROM orders WHERE driver <> '' GROUP BY driver ORDER BY claimed DESC""",
        (CLAIMED, DELIVERED, CLAIMED)).fillna("").to_dict("records")

    return render_template("orders.html", title="الطلبيات",
                           rows=rows, oman=OMAN, driver_names=driver_names(),
                           totals=totals, summary=build_summary(all_df), by_driver=by_driver,
                           statuses=ORDER_STATUSES, f_status=f_status, f_gov=f_gov,
                           max_bulk=MAX_BULK, today=today_oman().isoformat())


@app.route("/orders/add", methods=["POST"])
def add_order():
    try:
        fee = float(request.form.get("fee", ""))
        count = int(request.form.get("count", "1"))
        if fee < 0 or not 1 <= count <= MAX_BULK:
            raise ValueError
    except ValueError:
        flash("السعر أو العدد غير صحيح")
        return redirect(url_for("orders"))

    gov = request.form.get("governorate", "").strip()
    wilaya = request.form.get("wilaya", "").strip()
    if wilaya not in OMAN.get(gov, []):
        flash("اختر المحافظة والولاية")
        return redirect(url_for("orders"))

    driver = ""
    if request.form.get("driver"):
        driver = valid_driver(request.form.get("driver"))
        if not driver:
            flash("اختر المندوب من القائمة")
            return redirect(url_for("orders"))

    status = request.form.get("payment_status", PENDING)
    if status not in (PAID, PENDING):
        status = PENDING

    row = (
        request.form.get("order_ref", "").strip(),
        request.form.get("customer_phone", "").strip(),
        gov, wilaya, driver, fee, status,
        request.form.get("order_date") or today_oman().isoformat(),
        request.form.get("notes", "").strip(),
        CLAIMED if driver else AVAILABLE,
        now_oman() if driver else None,
    )
    db_exec_many(
        """INSERT INTO orders (order_ref, customer_phone, governorate, wilaya, driver, fee,
                               payment_status, order_date, notes, status, claimed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [row] * count,
    )
    flash(f"تم حفظ {count} طلبية في {wilaya} ({gov})")
    return redirect(url_for("orders"))


@app.route("/orders/<int:oid>/toggle", methods=["POST"])
def toggle_payment(oid):
    db_exec(
        """UPDATE orders SET payment_status =
               CASE WHEN payment_status = ? THEN ? ELSE ? END
           WHERE id = ?""",
        (PAID, PENDING, PAID, oid),
    )
    return redirect(request.referrer or url_for("orders"))


@app.route("/orders/<int:oid>/unassign", methods=["POST"])
def unassign_order(oid):
    # إنقاص عدد الحجز المرتبط بالطلبية قبل فكّها عنه
    db_exec("UPDATE claims SET qty = qty - 1 WHERE id = (SELECT claim_id FROM orders WHERE id = ? AND status = ?)",
            (oid, CLAIMED))
    db_exec("UPDATE orders SET driver = '', status = ?, claimed_at = NULL, claim_id = NULL "
            "WHERE id = ? AND status = ?", (AVAILABLE, oid, CLAIMED))
    flash("رجعت الطلبية متاحة للمندوبين")
    return redirect(request.referrer or url_for("orders"))


@app.route("/orders/<int:oid>/delete", methods=["POST"])
def delete_order(oid):
    db_exec("DELETE FROM orders WHERE id = ?", (oid,))
    flash("تم الحذف")
    return redirect(request.referrer or url_for("orders"))


# ----------------------------------------------------------------------
# 2) صفحات المندوب
# ----------------------------------------------------------------------
def available_map():
    """{المحافظة: {الولاية: عدد الطلبيات المتاحة}} مرتبة حسب المحافظات."""
    df = db_df("SELECT governorate, wilaya, COUNT(*) AS n FROM orders WHERE status = ? "
               "GROUP BY governorate, wilaya ORDER BY n DESC", (AVAILABLE,))
    df["governorate"] = df["governorate"].fillna(UNSPECIFIED)
    result = {}
    for gov in sorted(df["governorate"].unique(), key=lambda g: list(OMAN).index(g) if g in OMAN else 99):
        gdf = df[df["governorate"] == gov]
        result[gov] = {r.wilaya: int(r.n) for r in gdf.itertuples()}
    return result


def release_claim(conn, cid):
    """يرجع طلبيات الحجز التي لم توصَّل إلى المتاح."""
    conn.execute("UPDATE orders SET driver = '', status = ?, claimed_at = NULL, claim_id = NULL "
                 "WHERE claim_id = ? AND status = ?", (AVAILABLE, cid, CLAIMED))
    conn.execute("UPDATE claims SET status = ? WHERE id = ?", (CANCELLED, cid))


@app.route("/driver")
def d_home():
    phone = db_df("SELECT phone FROM drivers WHERE name = ?", (session["driver"],))["phone"][0] or ""
    return render_template("d_home.html", title="استلام طلبيات", avail=available_map(),
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

    gov_clause = "governorate IS NULL" if gov == UNSPECIFIED else "governorate = ?"
    gov_params = () if gov == UNSPECIFIED else (gov,)
    min_left = get_min_left()

    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        # قفل الكتابة حتى لا يحجز مندوبان نفس الطلبيات في نفس اللحظة
        conn.execute("BEGIN IMMEDIATE")
        avail = conn.execute(f"SELECT COUNT(*) FROM orders WHERE status = ? AND wilaya = ? AND {gov_clause}",
                             (AVAILABLE, wilaya, *gov_params)).fetchone()[0]
        if avail == 0:
            conn.execute("ROLLBACK")
            flash("لم تعد هناك طلبيات متاحة في هذه الولاية")
            return redirect(url_for("d_home"))
        qty = min(qty, avail)
        forced = 0 < avail - qty < min_left
        if forced:
            qty = avail
        cid = conn.execute(
            """INSERT INTO claims (driver, phone, governorate, wilaya, qty, pickup_time, created_at, status, forced)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (me, phone, None if gov == UNSPECIFIED else gov, wilaya, qty, pickup, now_oman(), WAITING, int(forced)),
        ).lastrowid
        conn.execute(
            f"""UPDATE orders SET driver = ?, status = ?, claimed_at = ?, claim_id = ?
                WHERE id IN (SELECT id FROM orders WHERE status = ? AND wilaya = ? AND {gov_clause}
                             ORDER BY id LIMIT ?)""",
            (me, CLAIMED, now_oman(), cid, AVAILABLE, wilaya, *gov_params, qty),
        )
        conn.execute("UPDATE drivers SET phone = ? WHERE name = ?", (phone, me))
        conn.execute("COMMIT")
    finally:
        conn.close()

    msg = f"✅ تم حجز {qty} طلبية في {wilaya} — موعد الاستلام {pickup}"
    if forced:
        msg += f" (أُضيف الباقي لأنه أقل من {min_left})"
    flash(msg)
    return redirect(url_for("d_mine"))


@app.route("/driver/mine")
def d_mine():
    me = session["driver"]
    claims_list = db_df("SELECT * FROM claims WHERE driver = ? AND status <> ? ORDER BY id DESC LIMIT 50",
                        (me, CANCELLED)).to_dict("records")
    for c in claims_list:
        c["orders"] = db_df("SELECT id, notes, customer_phone, status FROM orders WHERE claim_id = ? ORDER BY id",
                            (c["id"],)).to_dict("records")
    return render_template("d_mine.html", title="حجوزاتي", claims=claims_list)


@app.route("/driver/claims/<int:cid>/cancel", methods=["POST"])
def d_claim_cancel(cid):
    conn = sqlite3.connect(DB_PATH)
    try:
        if conn.execute("SELECT 1 FROM claims WHERE id = ? AND driver = ? AND status = ?",
                        (cid, session["driver"], WAITING)).fetchone():
            release_claim(conn, cid)
            conn.commit()
            flash("تم إلغاء الحجز ورجعت الطلبيات متاحة")
    finally:
        conn.close()
    return redirect(url_for("d_mine"))


@app.route("/driver/claims/<int:cid>/done", methods=["POST"])
def d_claim_done(cid):
    conn = sqlite3.connect(DB_PATH)
    try:
        if conn.execute("SELECT 1 FROM claims WHERE id = ? AND driver = ? AND status = ?",
                        (cid, session["driver"], PICKED)).fetchone():
            conn.execute("UPDATE orders SET status = ?, delivered_at = ? WHERE claim_id = ? AND status = ?",
                         (DELIVERED, now_oman(), cid, CLAIMED))
            conn.execute("UPDATE claims SET status = ? WHERE id = ?", (CLAIM_DONE, cid))
            conn.commit()
            flash("✅ تم تسجيل التوصيل")
    finally:
        conn.close()
    return redirect(url_for("d_mine"))


# ----------------------------------------------------------------------
# حجوزات المندوبين (المدير)
# ----------------------------------------------------------------------
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
    flash("تم تسجيل تسليم الطلبيات للمندوب")
    return redirect(request.referrer or url_for("claims"))


@app.route("/claims/<int:cid>/cancel", methods=["POST"])
def claim_cancel(cid):
    conn = sqlite3.connect(DB_PATH)
    try:
        release_claim(conn, cid)
        conn.commit()
    finally:
        conn.close()
    flash("تم إلغاء الحجز ورجعت الطلبيات متاحة")
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
    flash(f"تم الحفظ: إذا بقي أقل من {value} يُجبَر المندوب على استلام الباقي")
    return redirect(url_for("claims"))


# ----------------------------------------------------------------------
# 3) المصروفات
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
def valid_pin(pin):
    return pin.isdigit() and 4 <= len(pin) <= 8


@app.route("/drivers")
def drivers():
    rows = db_df(
        """SELECT d.id, d.name, d.pin_hash, d.phone,
                  COALESCE(SUM(o.status = ?), 0) AS claimed,
                  COALESCE(SUM(o.status = ?), 0) AS delivered
           FROM drivers d LEFT JOIN orders o ON o.driver = d.name
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
    row = db_df("SELECT name FROM drivers WHERE id = ?", (did,))
    if not row.empty:
        # الطلبيات التي لم توصَّل ترجع متاحة لغيره
        db_exec("UPDATE orders SET driver = '', status = ?, claimed_at = NULL, claim_id = NULL "
                "WHERE driver = ? AND status = ?", (AVAILABLE, row["name"][0], CLAIMED))
        db_exec("UPDATE claims SET status = ? WHERE driver = ? AND status IN (?, ?)",
                (CANCELLED, row["name"][0], WAITING, PICKED))
        db_exec("DELETE FROM drivers WHERE id = ?", (did,))
        flash("تم حذف المندوب")
    return redirect(url_for("drivers"))


# ----------------------------------------------------------------------
# 4) التقارير ولوحة التحكم (Pandas)
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

    # حسب المندوب / السيارة (بدون الطلبيات التي لم يستلمها أحد)
    assigned = orders_df[orders_df["driver"] != ""]
    drv = pd.DataFrame({
        "orders_count": assigned.groupby("driver")["id"].count(),
        "collected": paid[paid["driver"] != ""].groupby("driver")["fee"].sum(),
        "pending": pending[pending["driver"] != ""].groupby("driver")["fee"].sum(),
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
# 5) تصدير Excel
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
        db_df("SELECT * FROM claims ORDER BY id").rename(columns=CLAIM_COLUMNS_AR).to_excel(
            writer, sheet_name="حجوزات المندوبين", index=False)
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
