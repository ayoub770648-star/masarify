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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#f4f6fb; --surface:#fff; --ink:#0f172a; --muted:#64748b; --line:#e6eaf2;
    --brand:#4338ca; --brand-soft:#eef2ff; --side:#0b1224; --side-ink:#a5b0c8;
    --ok:#059669; --ok-soft:#ecfdf5; --warn:#d97706; --warn-soft:#fffbeb;
    --info:#2563eb; --info-soft:#eff6ff; --bad:#dc2626; --bad-soft:#fef2f2;
    --radius:14px; --shadow:0 1px 2px rgba(15,23,42,.04),0 4px 16px rgba(15,23,42,.06);
  }
  *{box-sizing:border-box}
  body{font-family:'IBM Plex Sans Arabic',Tahoma,sans-serif;background:var(--bg);margin:0;color:var(--ink);font-size:15px}
  a{color:var(--brand)}
  /* التخطيط */
  .layout{display:flex;min-height:100vh}
  .side{width:250px;background:var(--side);color:#fff;padding:22px 14px;position:sticky;top:0;height:100vh;display:flex;flex-direction:column}
  .logo{display:flex;align-items:center;gap:10px;padding:0 10px 22px;font-weight:700;font-size:17px}
  .logo-mark{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#6366f1,#06b6d4);display:grid;place-items:center}
  .side a{display:flex;align-items:center;gap:12px;color:var(--side-ink);text-decoration:none;padding:11px 12px;border-radius:10px;margin-bottom:4px;font-weight:500}
  .side a:hover{background:rgba(255,255,255,.06);color:#fff}
  .side a.active{background:rgba(99,102,241,.18);color:#fff}
  .side svg{width:19px;height:19px;flex:none}
  .side .bottom{margin-top:auto;border-top:1px solid rgba(255,255,255,.08);padding-top:14px}
  .user{display:flex;align-items:center;gap:10px;padding:8px 12px;color:#fff;font-weight:600}
  .avatar{width:32px;height:32px;border-radius:50%;background:#1e293b;display:grid;place-items:center;font-size:14px}
  .main{flex:1;min-width:0;padding:28px 32px}
  .page-head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:22px;gap:12px;flex-wrap:wrap}
  .page-head h1{margin:0;font-size:24px;font-weight:700}
  .page-head p{margin:4px 0 0;color:var(--muted)}
  /* البطاقات */
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px;margin-bottom:20px;box-shadow:var(--shadow);overflow-x:auto}
  .card h3{margin:0 0 16px;font-size:16px;font-weight:700;display:flex;align-items:center;gap:8px}
  .card h4{margin:18px 0 8px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:20px}
  .kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:18px;box-shadow:var(--shadow);color:var(--muted);font-weight:500;position:relative;overflow:hidden}
  .kpi b{display:block;font-size:30px;margin-top:6px;color:var(--ink);font-weight:700}
  .kpi::before{content:"";position:absolute;inset-inline-start:0;top:0;bottom:0;width:4px;background:var(--brand)}
  .kpi.k-ok::before{background:var(--ok)}.kpi.k-warn::before{background:var(--warn)}.kpi.k-info::before{background:var(--info)}
  /* النماذج */
  form.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;align-items:end}
  label{display:block;font-size:13px;color:var(--muted);margin-bottom:6px;font-weight:500}
  input,select,button{font-family:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:10px;font-size:15px;width:100%;background:#fff;color:var(--ink)}
  input:focus,select:focus{outline:none;border-color:#818cf8;box-shadow:0 0 0 3px rgba(99,102,241,.15)}
  button{background:var(--brand);color:#fff;border:0;cursor:pointer;font-weight:600;transition:filter .15s}
  button:hover{filter:brightness(1.08)}
  .btn-link{background:var(--ok);color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block}
  /* الجداول */
  table{width:100%;border-collapse:separate;border-spacing:0;font-size:14px}
  th{background:#f8fafc;color:var(--muted);font-weight:600;font-size:13px;padding:11px 12px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
  td{padding:12px;border-bottom:1px solid var(--line);text-align:right;vertical-align:middle}
  tr:last-child td{border-bottom:0}
  tbody tr:hover td,table tr:hover td{background:#fafbff}
  .gov td{background:#f8fafc !important;font-weight:700}
  .small-btn{width:auto;padding:7px 12px;font-size:13px;margin:2px;border-radius:8px}
  .green{background:var(--ok)}.red{background:var(--bad)}.gray{background:#475569}
  .flash{background:var(--brand-soft);color:#3730a3;border:1px solid #c7d2fe;padding:12px 14px;border-radius:12px;margin-bottom:16px;font-weight:500}
  .badge{display:inline-block;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
  .b-بانتظار{background:var(--warn-soft);color:var(--warn)}.b-استلمها{background:var(--info-soft);color:var(--info)}
  .b-تم{background:var(--ok-soft);color:var(--ok)}.b-ملغي{background:#f1f5f9;color:#64748b}
  .qty{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.qty input{width:100px}.qty button{width:auto}
  .qty label{margin:0}
  .big{font-size:17px;font-weight:700}
  .muted{color:var(--muted)}
  .num{font-variant-numeric:tabular-nums;font-weight:700}
  .warn{background:var(--bad-soft);color:var(--bad);padding:12px;border-radius:10px;font-weight:600}
  .ok{background:var(--ok-soft);color:var(--ok);padding:12px;border-radius:10px;font-weight:600}
  .time{display:inline-flex;align-items:center;gap:6px;background:var(--warn-soft);color:#92400e;padding:5px 10px;border-radius:8px;font-weight:600;white-space:nowrap}
  .empty{color:var(--muted);text-align:center;padding:24px}
  /* صفحة الدخول */
  .auth{min-height:100vh;display:grid;grid-template-columns:1fr 1fr}
  .auth-hero{background:linear-gradient(150deg,#0b1224 0%,#1e1b4b 60%,#0e7490 140%);color:#fff;padding:56px;display:flex;flex-direction:column;justify-content:center}
  .auth-hero h1{font-size:34px;margin:18px 0 10px}
  .auth-hero p{color:#c7d2fe;font-size:17px;line-height:1.8;max-width:420px}
  .auth-forms{display:flex;flex-direction:column;justify-content:center;padding:40px;gap:18px;max-width:480px;width:100%;margin:auto}
  @media (max-width:900px){
    .layout{flex-direction:column}
    .side{width:100%;height:auto;position:static;flex-direction:row;align-items:center;overflow-x:auto;padding:10px;gap:4px}
    .logo{padding:0 6px}.logo span{display:none}
    .side a{margin:0;white-space:nowrap;padding:9px 10px}
    .side a span{font-size:14px}
    .side .bottom{margin:0;border:0;padding:0;display:flex}
    .user{display:none}
    .main{padding:16px}
    .auth{grid-template-columns:1fr}.auth-hero{padding:28px}.auth-hero h1{font-size:24px}
  }
</style>
</head>
<body>
{% set ep = request.endpoint %}
{% macro icon(name) -%}
  {%- if name == 'box' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/></svg>
  {%- elif name == 'cal' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/></svg>
  {%- elif name == 'users' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6"/><path d="M17 11a3 3 0 100-6M22 21c0-3-2-5-5-5.5"/></svg>
  {%- elif name == 'file' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9z"/><path d="M14 3v6h6M9 15l2 2 4-4"/></svg>
  {%- elif name == 'out' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l-5-5 5-5M5 12h12"/></svg>
  {%- elif name == 'truck' -%}<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M1 4h14v12H1zM15 9h4l4 4v3h-8"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/></svg>
  {%- endif -%}
{%- endmacro %}
{% if session.get('role') %}
<div class="layout">
  <aside class="side">
    <div class="logo"><div class="logo-mark">{{ icon('truck') }}</div><span>توزيع الشحنات</span></div>
    {% if session.get('role') == 'admin' %}
      <a href="{{ url_for('shipments') }}" class="{{ 'active' if ep == 'shipments' }}">{{ icon('box') }}<span>الشحنات</span></a>
      <a href="{{ url_for('claims') }}" class="{{ 'active' if ep == 'claims' }}">{{ icon('cal') }}<span>حجوزات المندوبين</span></a>
      <a href="{{ url_for('drivers') }}" class="{{ 'active' if ep == 'drivers' }}">{{ icon('users') }}<span>المندوبين</span></a>
      <a href="{{ url_for('export_excel') }}">{{ icon('file') }}<span>تصدير Excel</span></a>
      <div class="bottom">
        <div class="user"><div class="avatar">م</div>المدير</div>
        <a href="{{ url_for('logout') }}">{{ icon('out') }}<span>خروج</span></a>
      </div>
    {% else %}
      <a href="{{ url_for('d_home') }}" class="{{ 'active' if ep == 'd_home' }}">{{ icon('box') }}<span>حجز شحنات</span></a>
      <a href="{{ url_for('d_mine') }}" class="{{ 'active' if ep == 'd_mine' }}">{{ icon('cal') }}<span>حجوزاتي</span></a>
      <div class="bottom">
        <div class="user"><div class="avatar">{{ session.get('driver', '')[:1] }}</div>{{ session.get('driver') }}</div>
        <a href="{{ url_for('logout') }}">{{ icon('out') }}<span>خروج</span></a>
      </div>
    {% endif %}
  </aside>
  <main class="main">
    <div class="page-head"><div><h1>{{ title }}</h1>{% if subtitle %}<p>{{ subtitle }}</p>{% endif %}</div></div>
    {% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}
    {% block content %}{% endblock %}
  </main>
</div>
{% else %}
<div class="auth">
  <div class="auth-hero">
    <div class="logo-mark" style="width:54px;height:54px;border-radius:14px">{{ icon('truck') }}</div>
    <h1>نظام توزيع الشحنات</h1>
    <p>إدارة الشحنات في جميع محافظات وولايات السلطنة، وحجوزات المندوبين ومواعيد الاستلام في مكان واحد.</p>
  </div>
  <div class="auth-forms">
    {% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}
    {% block auth %}{% endblock %}
  </div>
</div>
{% endif %}
</body>
</html>
""",

    "login.html": """
{% extends "base.html" %}
{% block auth %}
<div class="card">
  <h3>دخول المندوب</h3>
  <form method="post" action="{{ url_for('d_login') }}">
    <label>الاسم</label>
    <select name="name" required>
      <option value="">— اختر اسمك —</option>
      {% for d in driver_names %}<option>{{ d }}</option>{% endfor %}
    </select>
    <br><br>
    <label>رمز PIN</label>
    <input type="password" name="pin" inputmode="numeric" placeholder="••••" required>
    <br><br>
    <button type="submit">دخول</button>
  </form>
</div>
<div class="card">
  <h3>دخول الإدارة</h3>
  <form method="post" action="{{ url_for('login') }}">
    <label>كلمة المرور</label>
    <input type="password" name="password" required>
    <br><br>
    <button type="submit" class="gray">دخول الإدارة</button>
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
  <div class="kpi k-warn">بانتظار الاستلام<b>{{ totals[WAITING] }}</b></div>
  <div class="kpi k-info">مع المندوبين<b>{{ totals[PICKED] }}</b></div>
  <div class="kpi k-ok">تم توصيلها<b>{{ totals[DELIVERED] }}</b></div>
</div>

<div class="card">
  <h3>🕒 مواعيد الاستلام القادمة</h3>
  <table>
    <tr><th>موعد الاستلام</th><th>المندوب</th><th>الهاتف</th><th>المحافظة / الولاية</th><th>العدد</th><th></th></tr>
    {% for c in upcoming %}
    <tr>
      <td><span class="time">{{ c.pickup_time }}</span></td>
      <td class="big">{{ c.driver }}</td>
      <td><a href="tel:{{ c.phone }}">{{ c.phone }}</a></td>
      <td>{{ c.governorate }} / {{ c.wilaya }}</td>
      <td class="num">{{ c.qty }}{% if c.forced %} <small title="أُجبر على أخذ الباقي">⚠️</small>{% endif %}</td>
      <td>
        <form method="post" action="{{ url_for('claim_picked', cid=c.id) }}" style="display:inline"
              onsubmit='return confirm({{ ("تأكيد أن " ~ c.driver ~ " استلم " ~ c.qty ~ " شحنة؟")|tojson }})'>
          <button class="small-btn green">✓ تأكيد الاستلام</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="6" class="empty">لا يوجد مندوب بانتظار الاستلام</td></tr>
    {% endfor %}
  </table>
</div>

<div class="card">
  <h3>الشحنات حسب المحافظة والولاية</h3>
  <table>
    <tr><th>المحافظة / الولاية</th><th>متاحة</th><th>بانتظار الاستلام</th><th>مع المندوبين</th><th>تم التوصيل</th><th>إنقاص المتاح</th></tr>
    {% for g in summary %}
      <tr class="gov"><td>{{ g.name }}</td><td>{{ g[AVAILABLE] }}</td><td>{{ g[WAITING] }}</td><td>{{ g[PICKED] }}</td><td>{{ g[DELIVERED] }}</td><td></td></tr>
      {% for w in g.wilayat %}
      <tr>
        <td>&nbsp;&nbsp;&nbsp;{{ w.name }}</td>
        <td class="big">{{ w[AVAILABLE] }}</td><td>{{ w[WAITING] }}</td><td>{{ w[PICKED] }}</td><td>{{ w[DELIVERED] }}</td>
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
      <tr><td colspan="6" class="empty">لا توجد شحنات بعد</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "claims.html": """
{% extends "base.html" %}
{% block content %}
<div class="kpis">
  <div class="kpi k-warn">حجوزات بانتظار الاستلام<b>{{ waiting_count }}</b></div>
  <div class="kpi k-warn">شحنات بانتظار الاستلام<b>{{ waiting_qty }}</b></div>
  <div class="kpi k-info">مع المندوبين الآن<b>{{ picked_qty }}</b></div>
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
      <td><span class="time">{{ c.pickup_time }}</span></td>
      <td class="muted">{{ c.created_at }}</td>
      <td><span class="badge b-{{ c.status.split()[0] }}">{{ c.status }}</span></td>
      <td>
        {% if c.status == WAITING %}
        <form method="post" action="{{ url_for('claim_picked', cid=c.id) }}" style="display:inline"
              onsubmit='return confirm({{ ("تأكيد أن " ~ c.driver ~ " استلم " ~ c.qty ~ " شحنة؟")|tojson }})'>
          <button class="small-btn green">✓ تأكيد الاستلام</button>
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
      <td><span class="time">{{ c.pickup_time }}</span></td>
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
    # الشحنة المحجوزة تأخذ حالة حجزها: بانتظار الاستلام أو مع المندوب
    df = db_df(
        """SELECT s.governorate, s.wilaya,
                  CASE WHEN s.status = ? THEN COALESCE(c.status, ?) ELSE s.status END AS status,
                  COUNT(*) AS n
           FROM shipments s LEFT JOIN claims c ON c.id = s.claim_id
           GROUP BY 1, 2, 3""", (CLAIMED, WAITING))
    columns = (AVAILABLE, WAITING, PICKED, DELIVERED)
    totals = {s: int(df.loc[df["status"] == s, "n"].sum()) for s in columns}
    summary = []
    for gov in sorted(df["governorate"].unique(), key=gov_order):
        gdf = df[df["governorate"] == gov]
        g = {"name": gov, "wilayat": []}
        for s in columns:
            g[s] = int(gdf.loc[gdf["status"] == s, "n"].sum())
        for wil in sorted(gdf["wilaya"].unique()):
            wdf = gdf[gdf["wilaya"] == wil]
            g["wilayat"].append({"name": wil, **{s: int(wdf.loc[wdf["status"] == s, "n"].sum())
                                                 for s in columns}})
        summary.append(g)
    upcoming = db_df("SELECT * FROM claims WHERE status = ? ORDER BY pickup_time", (WAITING,)).to_dict("records")
    return render_template("shipments.html", title="الشحنات",
                           subtitle="أضف الشحنات لكل محافظة وولاية وتابع مواعيد استلام المندوبين",
                           oman=OMAN, totals=totals, summary=summary, upcoming=upcoming, max_bulk=MAX_BULK)


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
    return render_template("claims.html", title="حجوزات المندوبين",
                           subtitle="من حجز، وكم، ومن أي ولاية، ومتى سيأتي للاستلام", rows=rows,
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
    return render_template("drivers.html", title="المندوبين", subtitle="أضف المندوبين وأعطِ كل واحد رمز PIN للدخول", rows=rows)


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
    return render_template("d_home.html", title="حجز شحنات", subtitle="اختر الولاية وعدد الشحنات وموعد الاستلام", avail=available_map(),
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
    return render_template("d_mine.html", title="حجوزاتي", subtitle="حجوزاتك ومواعيد استلامها", claims=claims_list)


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
