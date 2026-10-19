import io
import json
import os
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from flask import (Flask, Response, flash, make_response, redirect, render_template,
                   request, send_file, session, url_for)
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
BRAND_EN = os.environ.get("BRAND_NAME", "Parcel Express")
BRAND_AR = os.environ.get("BRAND_SUBTITLE", "نظام توزيع الشحنات")

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
MAX_UPLOAD_TOTAL = 50000
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

# أسماء الأماكن بالإنجليزية (للعرض فقط — القيم المخزنة تبقى بالعربي)
PLACES_EN = {
    "مسقط": "Muscat", "ظفار": "Dhofar", "مسندم": "Musandam", "البريمي": "Al Buraimi",
    "الداخلية": "Ad Dakhiliyah", "شمال الباطنة": "North Al Batinah", "جنوب الباطنة": "South Al Batinah",
    "جنوب الشرقية": "South Ash Sharqiyah", "شمال الشرقية": "North Ash Sharqiyah",
    "الظاهرة": "Ad Dhahirah", "الوسطى": "Al Wusta",
    "مطرح": "Muttrah", "بوشر": "Bawshar", "السيب": "Seeb", "العامرات": "Al Amerat", "قريات": "Qurayyat",
    "صلالة": "Salalah", "طاقة": "Taqah", "مرباط": "Mirbat", "رخيوت": "Rakhyut", "ثمريت": "Thumrait",
    "ضلكوت": "Dhalkut", "المزيونة": "Al Mazyunah", "مقشن": "Muqshin",
    "شليم وجزر الحلانيات": "Shalim & Hallaniyat Islands", "سدح": "Sadah",
    "خصب": "Khasab", "دبا": "Dibba", "بخا": "Bukha", "مدحاء": "Madha",
    "محضة": "Mahdah", "السنينة": "As Sunaynah",
    "نزوى": "Nizwa", "بهلا": "Bahla", "منح": "Manah", "الحمراء": "Al Hamra", "أدم": "Adam",
    "إزكي": "Izki", "سمائل": "Samail", "بدبد": "Bidbid", "الجبل الأخضر": "Al Jabal Al Akhdar",
    "صحار": "Sohar", "شناص": "Shinas", "لوى": "Liwa", "صحم": "Saham", "الخابورة": "Al Khaburah",
    "السويق": "As Suwayq",
    "الرستاق": "Rustaq", "العوابي": "Al Awabi", "نخل": "Nakhal", "وادي المعاول": "Wadi Al Maawil",
    "بركاء": "Barka", "المصنعة": "Al Musanaah",
    "صور": "Sur", "الكامل والوافي": "Al Kamil Wal Wafi", "جعلان بني بو حسن": "Jalan Bani Bu Hassan",
    "جعلان بني بو علي": "Jalan Bani Bu Ali", "مصيرة": "Masirah",
    "إبراء": "Ibra", "المضيبي": "Al Mudhaibi", "بدية": "Bidiyah", "القابل": "Al Qabil",
    "وادي بني خالد": "Wadi Bani Khalid", "دماء والطائيين": "Dima Wa Al Taiyin",
    "عبري": "Ibri", "ينقل": "Yanqul", "ضنك": "Dhank",
    "هيما": "Haima", "محوت": "Mahout", "الدقم": "Duqm", "الجازر": "Al Jazir",
}
PLACES_AR = {en.lower(): ar for ar, en in PLACES_EN.items()}

# ترجمة الواجهة إلى الإنجليزية (المفتاح هو النص العربي)
EN = {
    # عام
    "نظام توزيع الشحنات": "Shipment Distribution System",
    "القائمة": "Menu", "الأدوات": "Tools", "خروج": "Logout", "الإدارة": "Admin",
    "مندوب": "Driver", "مشرف": "Supervisor", "حفظ": "Save", "حذف": "Delete", "إلغاء": "Cancel",
    "دخول": "Login", "الاسم": "Name", "الهاتف": "Phone", "المحافظة": "Governorate",
    "الولاية": "Wilaya", "العدد": "Qty", "الحالة": "Status", "إجراءات": "Actions",
    "موعد الاستلام": "Pickup time", "وقت الحجز": "Booked at", "المندوب": "Driver",
    "المشرف": "Supervisor", "الكل": "All", "— اختر —": "— Select —",
    "— اختر المحافظة أولاً —": "— Select governorate first —", "بحث": "Search",
    "مسح": "Clear", "كل المحافظات": "All governorates",
    # الحالات
    "متاح": "Available", "محجوز": "Booked", "تم التوصيل": "Delivered",
    "بانتظار الاستلام": "Awaiting pickup", "استلمها المندوب": "Picked up", "ملغي": "Cancelled",
    "متأخر": "Late",
    # القائمة الجانبية
    "اليوم": "Today", "متأخرة": "Late", "الشحنات": "Shipments", "حجوزات المندوبين": "Driver bookings",
    "المندوبين": "Drivers", "مشرفو المحافظات": "Supervisors", "رفع من Excel": "Upload Excel",
    "تصدير Excel": "Export Excel", "حجز شحنات": "Book shipments", "حجوزاتي": "My bookings",
    "حجوزات محافظتي": "My governorate",
    # الدخول
    "مرحباً بعودتك": "Welcome back",
    "سجّل دخولك لإدارة الشحنات وحجوزات المندوبين": "Sign in to manage shipments and driver bookings",
    "— اختر اسمك —": "— Select your name —", "رمز PIN": "PIN", "أدخل الرمز...": "Enter PIN...",
    "كلمة المرور": "Password", "أدخل كلمة المرور...": "Enter password...",
    "— اختر محافظتك —": "— Select your governorate —",
    "كلمة المرور غير صحيحة": "Wrong password", "الاسم أو رمز PIN غير صحيح": "Wrong name or PIN",
    "المحافظة أو رمز PIN غير صحيح": "Wrong governorate or PIN",
    # اليوم
    "مواعيد استلام اليوم والمتأخرون": "Today's pickups and late drivers",
    "مواعيد اليوم": "Today's pickups", "تم استلامها": "Picked up", "متأخرون": "Late",
    "⚠️ متأخرون عن موعد الاستلام": "⚠️ Late for pickup", "🕒 مواعيد استلام اليوم": "🕒 Today's pickups",
    "📅 المواعيد القادمة": "📅 Upcoming pickups", "لا توجد مواعيد اليوم": "No pickups today",
    "لا توجد مواعيد قادمة": "No upcoming pickups", "✓ تأكيد الاستلام": "✓ Confirm pickup",
    "تأكيد أن {d} استلم {n} شحنة؟": "Confirm {d} picked up {n} shipments?",
    "إلغاء الحجز وإرجاع الشحنات للمتاح؟": "Cancel booking and return shipments?",
    "المتاح في {g}": "Available in {g}", "لا توجد شحنات متاحة": "No available shipments",
    "متاحة للحجز": "Available", "مع المندوبين": "With drivers", "تم توصيلها": "Delivered",
    "تأخر {m} دقيقة": "{m} min late", "تأخر {h} ساعة": "{h} h late",
    # الشحنات
    "أضف الشحنات لكل محافظة وولاية وتابع مواعيد استلام المندوبين":
        "Add shipments per governorate and wilaya and track driver pickups",
    "➕ إضافة شحنات": "➕ Add shipments", "عدد الشحنات": "Number of shipments",
    "＋ إضافة الشحنات": "＋ Add shipments", "الشحنات حسب المحافظة والولاية": "Shipments by governorate & wilaya",
    "المحافظة / الولاية": "Governorate / Wilaya", "متاحة": "Available", "إنقاص المتاح": "Reduce available",
    "حذف هذا العدد من الشحنات المتاحة؟": "Remove this many available shipments?",
    "لا توجد شحنات بعد": "No shipments yet",
    # رفع Excel
    "أضف شحنات كثيرة دفعة واحدة من ملف Excel": "Add many shipments at once from an Excel file",
    "1. حمّل ملف النموذج": "1. Download the template", "⬇️ تحميل النموذج": "⬇️ Download template",
    "الأعمدة: المحافظة، الولاية، العدد. يمكن كتابة الأسماء بالعربي أو الإنجليزي.":
        "Columns: Governorate, Wilaya, Qty. Names can be in Arabic or English.",
    "2. ارفع الملف بعد تعبئته": "2. Upload the filled file", "رفع وإضافة": "Upload & add",
    "لم يُضَف شيء — صحّح الأخطاء التالية ثم ارفع الملف مرة ثانية:":
        "Nothing was added — fix these errors and upload again:",
    "سطر": "Row",
    # الحجوزات
    "من حجز، وكم، ومن أي ولاية، ومتى سيأتي للاستلام": "Who booked, how many, from where, and when they'll pick up",
    "حجوزات بانتظار الاستلام": "Bookings awaiting pickup", "شحنات بانتظار الاستلام": "Shipments awaiting pickup",
    "مع المندوبين الآن": "With drivers now",
    "إجبار المندوب على أخذ الباقي إذا بقي أقل من": "Force the driver to take the rest if fewer than",
    "شحنات في الولاية": "shipments remain in the wilaya",
    "اسم المندوب أو الهاتف": "Driver name or phone", "لا توجد حجوزات": "No bookings",
    "✓ تم الإبلاغ": "✓ Notified", "لم يُبلَّغ": "Not notified", "أُجبر على أخذ الباقي": "Forced to take the rest",
    # المندوبين
    "أضف المندوبين وأعطِ كل واحد رمز PIN للدخول": "Add drivers and give each a login PIN",
    "إضافة مندوب": "Add driver", "اسم المندوب": "Driver name", "رقم الهاتف": "Phone number",
    "رمز PIN للدخول (4 أرقام أو أكثر)": "Login PIN (4+ digits)", "إضافة": "Add",
    "أعطِ كل مندوب اسمه ورمز PIN ليدخل من نفس رابط الموقع ويحجز الشحنات.":
        "Give each driver their name and PIN to log in from the same link and book shipments.",
    "قائمة المندوبين": "Drivers", "محجوزة حالياً": "Currently booked", "تغيير PIN": "Change PIN",
    "PIN جديد": "New PIN", "بدون PIN": "No PIN", "لا يوجد مندوبون بعد": "No drivers yet",
    "حذف المندوب؟ حجوزاته المفتوحة سترجع متاحة.": "Delete driver? Their open bookings will be returned.",
    # المشرفين
    "يستلم المشرف رسالة واتساب عند كل حجز في محافظته، ويدخل بحسابه ليؤكد الاستلام":
        "Supervisors get a WhatsApp message for each booking and log in to confirm pickups",
    "مشرف كل محافظة": "Supervisor per governorate", "اسم المشرف": "Supervisor name",
    "رقم الواتساب": "WhatsApp number", "رمز دخول المشرف": "Supervisor PIN",
    "اتركه فارغاً لعدم التغيير": "Leave empty to keep", "مفعّل": "Enabled",
    "يدخل المشرف من صفحة الدخول باختيار «مشرف» ثم محافظته ورمزه.":
        "Supervisors log in by choosing “Supervisor”, then their governorate and PIN.",
    # المندوب
    "اختر الولاية وعدد الشحنات وموعد الاستلام": "Choose the wilaya, quantity and pickup time",
    "📦 حجز شحنات": "📦 Book shipments", "كم شحنة تستلم؟": "How many shipments?",
    "متى تجي تستلم؟": "When will you pick up?", "رقم هاتفك": "Your phone", "تأكيد الحجز": "Confirm booking",
    "ملاحظة: إذا بقي في الولاية أقل من {n} شحنات بعد حجزك، يجب أن تأخذ الباقي كله.":
        "Note: if fewer than {n} shipments would remain in the wilaya, you must take them all.",
    "لا توجد شحنات متاحة حالياً 👍": "No shipments available right now 👍", "المتاح الآن": "Available now",
    "العدد المتاح": "Available", "اختر": "Choose",
    "حجوزاتك ومواعيد استلامها": "Your bookings and pickup times",
    "📲 خطوة أخيرة: بلّغ مشرف {g}": "📲 Last step: notify the {g} supervisor",
    "سيُفتح واتساب والرسالة جاهزة إلى المشرف": "WhatsApp will open with the message ready for supervisor",
    "اضغط «إرسال» في واتساب فقط.": "Just tap “Send” in WhatsApp.",
    "📲 أرسل للمشرف عبر واتساب": "📲 Send to supervisor on WhatsApp",
    "لم يُضَف مشرف لمحافظة {g} بعد — أبلغ الإدارة.": "No supervisor set for {g} yet — tell the admin.",
    "📲 بلّغ المشرف": "📲 Notify supervisor", "📲 أعد الإرسال": "📲 Send again",
    "✓ وصّلت الكل": "✓ Delivered all", "إلغاء الحجز": "Cancel booking",
    "تأكيد توصيل كل شحنات هذا الحجز؟": "Confirm all shipments in this booking were delivered?",
    "إلغاء الحجز وإرجاع الشحنات؟": "Cancel booking and return the shipments?",
    "ليس عندك حجوزات": "You have no bookings", "احجز من هنا": "Book here",
    # رسائل جافاسكربت للمندوب
    "المتاح في {w} فقط {n}": "Only {n} available in {w}",
    "سيبقى {l} فقط — يجب أن تأخذ الكل: {n} شحنة": "Only {l} would remain — you must take all {n}",
    "ستحجز {q} من {w}، ويبقى {l}": "You'll book {q} from {w}; {l} remain",
    "المتاح في {w}: {n}": "Available in {w}: {n}",
    "اليوم صباحاً": "Today AM", "اليوم العصر": "Today PM", "بكرة صباحاً": "Tomorrow AM",
    # رسائل النظام
    "تم حجز {n} شحنة في {w} — موعد الاستلام {t}": "Booked {n} shipments in {w} — pickup {t}",
    " (أُضيف الباقي لأنه أقل من {m})": " (the rest was added because fewer than {m} remained)",
    "لم تعد هناك شحنات متاحة في هذه الولاية": "No shipments left in this wilaya",
    "اكتب عدداً صحيحاً": "Enter a valid number", "اكتب رقم هاتفك وموعد الاستلام": "Enter your phone and pickup time",
    "تم إلغاء الحجز ورجعت الشحنات متاحة": "Booking cancelled and shipments returned",
    "✅ تم تسجيل التوصيل": "✅ Delivery recorded", "تم تسجيل تسليم الشحنات للمندوب": "Pickup confirmed",
    "لا يوجد مشرف لمحافظة {g}": "No supervisor for {g}",
}

CLAIM_COLUMNS_AR = {
    "id": "رقم الحجز", "driver": "المندوب", "phone": "الهاتف", "governorate": "المحافظة",
    "wilaya": "الولاية", "qty": "العدد", "pickup_time": "موعد الاستلام",
    "created_at": "وقت الحجز", "status": "الحالة", "forced": "أُجبر على الباقي",
    "notified_at": "وقت إبلاغ المشرف", "picked_at": "وقت الاستلام الفعلي", "picked_by": "أكّد الاستلام",
}

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
    forced INTEGER NOT NULL DEFAULT 0,
    notified_at TEXT,
    picked_at TEXT,
    picked_by TEXT
);
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    pin_hash TEXT,
    phone TEXT
);
CREATE TABLE IF NOT EXISTS supervisors (
    governorate TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    pin_hash TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# ----------------------------------------------------------------------
# القوالب (مدمجة داخل الملف لتسهيل النشر)
# ----------------------------------------------------------------------
TEMPLATES = {
    "base.html": """
<!doctype html>
<html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{{ t(title) }} | {{ brand_en|join(' ') }}</title>
<link rel="manifest" href="{{ url_for('manifest') }}">
<meta name="theme-color" content="#1e3a8a">
<link rel="icon" href="{{ url_for('static', filename='icon-192.png') }}">
<link rel="apple-touch-icon" href="{{ url_for('static', filename='apple-touch-icon.png') }}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="{{ brand_en|join(' ') }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#f8fafc; --surface:#fff; --ink:#0f172a; --text:#334155; --muted:#64748b; --line:#e5e7eb;
    --navy:#1e3a8a; --navy-dark:#0f172a; --orange:#f7941d; --orange-dark:#ea580c; --orange-soft:#fff7ed;
    --blue:#2563eb; --blue-soft:#eff6ff;
    --ok:#16a34a; --ok-soft:#f0fdf4; --warn:#ea580c; --warn-soft:#fff7ed;
    --bad:#e11d48; --bad-soft:#fff1f2; --gray-soft:#f1f5f9;
    --radius:12px;
  }
  *{box-sizing:border-box}
  body{font-family:'IBM Plex Sans Arabic',Tahoma,sans-serif;background:var(--bg);margin:0;color:var(--text);font-size:15px}
  a{color:var(--blue)}
  /* التخطيط */
  .layout{display:flex;min-height:100vh}
  .side{width:272px;background:var(--surface);border-inline-end:1px solid var(--line);padding:16px 12px;position:sticky;top:0;height:100vh;display:flex;flex-direction:column;overflow-y:auto}
  .brand{display:flex;align-items:center;gap:10px;padding:6px 6px 16px;border-bottom:1px solid var(--line);margin-bottom:12px}
  .brand-mark{width:42px;height:42px;border-radius:10px;background:var(--navy);display:grid;place-items:center;flex:none}
  .brand-mark svg{width:22px;height:22px}
  .brand-name{font-weight:700;font-size:16px;line-height:1.2;direction:ltr;text-align:start}
  .brand-name .p{color:var(--orange)} .brand-name .e{color:var(--navy)}
  .brand-sub{font-size:12.5px;color:var(--muted)}
  .menu-label{font-size:12px;color:var(--muted);padding:10px 10px 6px;font-weight:600}
  .side a{display:flex;align-items:center;gap:12px;color:var(--text);text-decoration:none;padding:10px 12px;border-radius:10px;margin-bottom:2px;font-weight:500}
  .side a:hover{background:var(--gray-soft)}
  .side a.active{background:var(--blue-soft);color:var(--navy-dark);font-weight:600;box-shadow:inset -3px 0 0 var(--orange)}
  [dir=ltr] .side a.active{box-shadow:inset 3px 0 0 var(--orange)}
  .side a.late{color:var(--bad)}
  .side svg{width:19px;height:19px;flex:none}
  .chip{margin-inline-start:auto;background:var(--orange-soft);color:var(--orange-dark);font-size:12px;font-weight:700;padding:2px 9px;border-radius:999px}
  .chip.gray{background:var(--gray-soft);color:var(--muted)}
  .chip.red{background:var(--bad-soft);color:var(--bad)}
  .side .bottom{margin-top:auto;border-top:1px solid var(--line);padding-top:12px}
  .user{display:flex;align-items:center;gap:10px;padding:8px 10px;color:var(--ink);font-weight:600}
  .avatar{width:34px;height:34px;border-radius:8px;background:var(--gray-soft);display:grid;place-items:center;font-size:13px;font-weight:700;color:var(--navy);flex:none}
  .langs{display:flex;gap:6px;padding:4px 10px 8px}
  .langs a{flex:1;justify-content:center;padding:6px;border:1px solid var(--line);border-radius:8px;font-size:13px;margin:0}
  .langs a.on{background:var(--navy-dark);color:#fff;border-color:var(--navy-dark)}
  .main{flex:1;min-width:0}
  .topbar{height:64px;background:var(--surface);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:center;padding:0 24px;position:sticky;top:0;z-index:5}
  .topbar .tab{color:var(--blue);font-weight:600;border-bottom:2px solid var(--blue);padding:20px 8px 18px}
  .content{padding:24px 32px}
  .page-head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:20px;gap:12px;flex-wrap:wrap}
  .page-head h1{margin:0;font-size:28px;font-weight:700;color:var(--ink)}
  .page-head p{margin:4px 0 0;color:var(--muted)}
  /* تبويبات الحالات */
  .tabs{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
  .tabs a{display:inline-flex;align-items:center;gap:10px;padding:8px 14px;border:1px solid var(--line);border-radius:999px;background:var(--surface);color:var(--text);text-decoration:none;font-weight:500;font-size:14px}
  .tabs a .n{background:var(--gray-soft);color:var(--ink);font-weight:700;font-size:12px;padding:2px 8px;border-radius:999px}
  .tabs a.on{background:var(--navy-dark);color:#fff;border-color:var(--navy-dark)}
  .tabs a.on .n{background:rgba(255,255,255,.18);color:#fff}
  /* البطاقات */
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px;margin-bottom:20px;overflow-x:auto}
  .card h3{margin:0 0 16px;font-size:16px;font-weight:700;color:var(--ink);display:flex;align-items:center;gap:8px}
  .card.alert{border:2px solid #fecdd3}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:20px}
  .kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;color:var(--muted);font-weight:500;font-size:14px}
  .kpi b{display:block;font-size:28px;margin-top:6px;color:var(--ink);font-weight:700}
  .kpi.k-warn b{color:var(--orange-dark)}.kpi.k-info b{color:var(--blue)}.kpi.k-ok b{color:var(--ok)}.kpi.k-bad b{color:var(--bad)}
  /* النماذج */
  form.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;align-items:end}
  label{display:block;font-size:13.5px;color:var(--ink);margin-bottom:6px;font-weight:600}
  input,select,button{font-family:inherit;padding:11px 14px;border:1px solid #d1d5db;border-radius:10px;font-size:15px;width:100%;background:#fff;color:var(--ink)}
  input:focus,select:focus{outline:none;border:2px solid var(--navy-dark);padding:10px 13px}
  input[type=file]{padding:9px}
  button{background:var(--blue);color:#fff;border:0;cursor:pointer;font-weight:600}
  button:hover{filter:brightness(1.07)}
  .btn-dark{background:var(--navy-dark)}
  .btn-link{background:var(--blue);color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block;font-weight:600;text-align:center}
  .btn-ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
  /* الجداول */
  table{width:100%;border-collapse:separate;border-spacing:0;font-size:14.5px}
  th{background:#f8fafc;color:var(--ink);font-weight:600;font-size:13.5px;padding:13px 14px;text-align:start;border-bottom:1px solid var(--line);white-space:nowrap}
  td{padding:14px;border-bottom:1px solid var(--line);text-align:start;vertical-align:middle}
  tr:last-child td{border-bottom:0}
  table tr:hover td{background:#fafafa}
  .gov td{background:#f8fafc !important;font-weight:700;color:var(--ink)}
  .small-btn{width:auto;padding:7px 12px;font-size:13px;margin:2px;border-radius:8px}
  .green{background:var(--ok)}.red{background:var(--bad)}.gray{background:#475569}.wa{background:#25d366}
  a.small-btn{color:#fff;text-decoration:none;display:inline-block}
  .flash{background:var(--blue-soft);color:var(--navy);border:1px solid #bfdbfe;padding:12px 14px;border-radius:10px;margin-bottom:16px;font-weight:500}
  .badge{display:inline-block;padding:6px 14px;border-radius:999px;font-size:13px;font-weight:600;white-space:nowrap;border:1px solid transparent}
  .b-بانتظار{background:var(--warn-soft);color:var(--warn);border-color:#fed7aa}
  .b-استلمها{background:var(--blue-soft);color:var(--blue);border-color:#bfdbfe}
  .b-تم{background:var(--ok-soft);color:var(--ok);border-color:#bbf7d0}
  .b-ملغي,.b-late{background:var(--bad-soft);color:var(--bad);border-color:#fecdd3}
  .qty{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.qty input{width:100px}.qty button{width:auto}
  .qty label{margin:0}
  .big{font-size:16px;font-weight:700;color:var(--ink)}
  .muted{color:var(--muted)} td.muted{white-space:nowrap}
  .num{font-variant-numeric:tabular-nums;font-weight:700;color:var(--ink)}
  .warn{background:var(--bad-soft);color:var(--bad);padding:12px;border-radius:10px;font-weight:600}
  .ok{background:var(--ok-soft);color:var(--ok);padding:12px;border-radius:10px;font-weight:600}
  .time{display:inline-flex;align-items:center;gap:6px;background:var(--orange-soft);color:var(--orange-dark);border:1px solid #fed7aa;padding:5px 12px;border-radius:999px;font-weight:600;white-space:nowrap;direction:ltr}
  .time.late{background:var(--bad-soft);color:var(--bad);border-color:#fecdd3}
  .phone{display:inline-flex;align-items:center;gap:6px;color:var(--text);text-decoration:none;direction:ltr;white-space:nowrap}
  .empty{color:var(--muted);text-align:center !important;padding:28px}
  .filters{display:grid;grid-template-columns:2fr 1.3fr 1fr auto auto;gap:10px;margin-bottom:14px}
  .filters button,.filters a{width:auto}
  .quick{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
  .quick button{width:auto;background:var(--gray-soft);color:var(--ink);padding:7px 12px;font-size:13px}
  pre.msg{background:#f8fafc;border:1px solid var(--line);border-radius:10px;padding:12px;white-space:pre-wrap;font-family:inherit}
  /* صفحة الدخول */
  .auth{min-height:100vh;display:grid;grid-template-columns:1fr 1fr;background:#fff}
  .auth-forms{display:flex;flex-direction:column;justify-content:center;padding:48px;max-width:520px;width:100%;margin:auto;position:relative}
  .auth-forms h1{font-size:32px;color:var(--ink);margin:28px 0 6px}
  .auth-forms .lead{color:var(--muted);margin:0 0 28px}
  .seg{display:flex;background:var(--gray-soft);border-radius:10px;padding:4px;margin-bottom:22px}
  .seg button{background:transparent;color:var(--muted);padding:9px}
  .seg button.on{background:#fff;color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.08)}
  .auth-lang{display:flex;gap:6px;justify-content:flex-end;margin-bottom:24px}
  .auth-lang a{background:#fff;border:1px solid var(--line);border-radius:8px;padding:6px 12px;text-decoration:none;color:var(--ink);font-size:13px}
  .auth-hero{position:relative;overflow:hidden;background:linear-gradient(160deg,#fbb040 0%,#f7941d 45%,#f26522 100%);display:flex;align-items:center;justify-content:center}
  .auth-hero .word{font-size:84px;font-weight:700;font-style:italic;color:#fff;line-height:.95;text-align:center;direction:ltr;letter-spacing:1px;text-shadow:0 6px 24px rgba(0,0,0,.12);transform:rotate(-6deg)}
  .auth-hero .corner{position:absolute;top:0;inset-inline-end:0;background:#fff;border-end-start-radius:110px;padding:26px 30px 34px 40px}
  .shape{position:absolute;border:3px solid rgba(255,255,255,.85)}
  .s1{width:44px;height:44px;border-radius:50%;top:16%;right:28%}
  .s2{width:44px;height:44px;border-radius:50%;bottom:30%;left:22%}
  .plus{position:absolute;color:#fff;font-size:44px;font-weight:300}
  .arc{position:absolute;bottom:-120px;left:-10%;right:-10%;height:260px;border-radius:50%;background:rgba(255,255,255,.18)}
  @media (max-width:900px){
    .layout{flex-direction:column}
    .side{width:100%;height:auto;position:static;flex-direction:row;align-items:center;overflow-x:auto;padding:8px;gap:4px;border:0;border-bottom:1px solid var(--line)}
    .brand{border:0;padding:0 6px;margin:0}.brand-text,.menu-label{display:none}
    .side a{margin:0;white-space:nowrap;padding:9px 10px}
    .side .bottom{margin:0;border:0;padding:0;display:flex;align-items:center}
    .user,.topbar{display:none}
    .langs{padding:0}
    .content{padding:16px}
    .filters{grid-template-columns:1fr 1fr}
    table.stack tr:first-child{display:none}
    table.stack tr{display:block;border:1px solid var(--line);border-radius:12px;margin-bottom:12px;padding:6px 4px}
    table.stack td{display:flex;justify-content:space-between;align-items:center;gap:10px;border:0;padding:7px 10px}
    table.stack td::before{content:attr(data-label);color:var(--muted);font-size:13px;font-weight:600}
    table.stack td.acts{justify-content:stretch;gap:8px}
    table.stack td.acts::before{display:none}
    table.stack td.acts form{flex:1}
    table.stack td.acts button{width:100%;padding:11px}
    table.stack td.empty{justify-content:center}
    table.stack td.empty::before{display:none}
    .auth{grid-template-columns:1fr}.auth-hero{min-height:200px;order:-1}.auth-hero .word{font-size:46px}.auth-hero .corner{display:none}
    .auth-forms{padding:24px}
  }
</style>
</head>
<body>
{% set ep = request.endpoint %}
{% macro icon(name) -%}
  {%- if name == 'box' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/></svg>
  {%- elif name == 'cal' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/></svg>
  {%- elif name == 'clock' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
  {%- elif name == 'bell' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/></svg>
  {%- elif name == 'users' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6"/><path d="M17 11a3 3 0 100-6M22 21c0-3-2-5-5-5.5"/></svg>
  {%- elif name == 'shield' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>
  {%- elif name == 'up' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 002 2h12a2 2 0 002-2v-3"/></svg>
  {%- elif name == 'file' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9z"/><path d="M14 3v6h6M9 15l2 2 4-4"/></svg>
  {%- elif name == 'out' -%}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l-5-5 5-5M5 12h12"/></svg>
  {%- elif name == 'mark' -%}<svg viewBox="0 0 24 24" fill="none" stroke="#f7941d" stroke-width="2.2"><path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8" stroke="#fff"/><path d="M12 13v8" stroke="#fff"/></svg>
  {%- endif -%}
{%- endmacro %}
{% macro brandblock() -%}
  <div class="brand">
    <div class="brand-mark">{{ icon('mark') }}</div>
    <div class="brand-text">
      <div class="brand-name"><span class="p">{{ brand_en[0] }}</span> <span class="e">{{ brand_en[1] }}</span></div>
      <div class="brand-sub">{{ t(brand_ar) }}</div>
    </div>
  </div>
{%- endmacro %}
{% macro navlink(endpoint, ic, label, count=0, chip='', cls='') -%}
  <a href="{{ url_for(endpoint) }}" class="{{ cls }} {{ 'active' if ep == endpoint }}">{{ icon(ic) }}<span>{{ t(label) }}</span>
    {%- if count %}<span class="chip {{ chip }}">{{ count }}</span>{% endif %}</a>
{%- endmacro %}
{% set role = session.get('role') %}
{% if role %}
<div class="layout">
  <aside class="side">
    {{ brandblock() }}
    {% if role == 'admin' %}
      {% if nav_late %}{{ navlink('today', 'bell', 'متأخرة', nav_late, 'red', 'late') }}{% endif %}
      <div class="menu-label">{{ t('القائمة') }}</div>
      {{ navlink('today', 'clock', 'اليوم', nav_today) }}
      {{ navlink('shipments', 'box', 'الشحنات', nav_available, 'gray') }}
      {{ navlink('claims', 'cal', 'حجوزات المندوبين') }}
      {{ navlink('drivers', 'users', 'المندوبين') }}
      {{ navlink('supervisors', 'shield', 'مشرفو المحافظات') }}
      <div class="menu-label">{{ t('الأدوات') }}</div>
      {{ navlink('upload_page', 'up', 'رفع من Excel') }}
      {{ navlink('export_excel', 'file', 'تصدير Excel') }}
      {% set who, initials = t('الإدارة'), 'PE' %}
    {% elif role == 'supervisor' %}
      {% if nav_late %}{{ navlink('s_home', 'bell', 'متأخرة', nav_late, 'red', 'late') }}{% endif %}
      <div class="menu-label">{{ t('القائمة') }}</div>
      {{ navlink('s_home', 'clock', 'حجوزات محافظتي', nav_today) }}
      {% set who, initials = t('مشرف') ~ ' ' ~ place(session.get('gov')), session.get('gov', '')[:1] %}
    {% else %}
      <div class="menu-label">{{ t('القائمة') }}</div>
      {{ navlink('d_home', 'box', 'حجز شحنات') }}
      {{ navlink('d_mine', 'cal', 'حجوزاتي') }}
      {% set who, initials = session.get('driver'), session.get('driver', '')[:1] %}
    {% endif %}
    <div class="bottom">
      <div class="user"><div class="avatar">{{ initials }}</div>{{ who }}</div>
      <div class="langs">
        <a href="{{ url_for('set_lang', code='ar') }}" class="{{ 'on' if lang == 'ar' }}">عربي</a>
        <a href="{{ url_for('set_lang', code='en') }}" class="{{ 'on' if lang == 'en' }}">English</a>
      </div>
      <a href="{{ url_for('logout') }}">{{ icon('out') }}<span>{{ t('خروج') }}</span></a>
    </div>
  </aside>
  <main class="main">
    <div class="topbar"><span class="tab">{{ t(title) }}</span></div>
    <div class="content">
      <div class="page-head"><div><h1>{{ t(title) }}</h1>{% if subtitle %}<p>{{ t(subtitle) }}</p>{% endif %}</div></div>
      {% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}
      {% block content %}{% endblock %}
    </div>
  </main>
</div>
{% else %}
<div class="auth">
  <div class="auth-forms">
    <div class="auth-lang">
      <a href="{{ url_for('set_lang', code='ar') }}">عربي</a><a href="{{ url_for('set_lang', code='en') }}">English</a>
    </div>
    {{ brandblock() }}
    {% block auth %}{% endblock %}
  </div>
  <div class="auth-hero">
    <div class="corner">
      <div class="brand-name" style="font-size:26px"><span class="p">{{ brand_en[0] }}</span> <span class="e">{{ brand_en[1] }}</span></div>
      <div class="brand-sub" style="font-size:15px">{{ t(brand_ar) }}</div>
    </div>
    <span class="shape s1"></span><span class="shape s2"></span>
    <span class="plus" style="top:30%;left:20%">+</span><span class="plus" style="top:42%;right:16%">+</span>
    <div class="arc"></div>
    <div class="word">{{ brand_en[0]|upper }}<br>{{ brand_en[1]|upper }}</div>
  </div>
</div>
{% endif %}
<script>
  if ('serviceWorker' in navigator) { navigator.serviceWorker.register('{{ url_for("service_worker") }}'); }
</script>
</body>
</html>
""",

    "macros.html": """
{% macro status_badge(c) -%}
  {%- if c.status == WAITING and c.is_late -%}
    <span class="badge b-late">{{ t('متأخر') }}</span>
  {%- else -%}
    <span class="badge b-{{ c.status.split()[0] }}">{{ t(c.status) }}</span>
  {%- endif -%}
{%- endmacro %}

{% macro pickup(c) -%}
  <span class="time {{ 'late' if c.is_late }}">{{ c.pickup_time }}</span>
  {%- if c.late_label %}<div class="muted" style="font-size:12.5px;margin-top:4px">{{ c.late_label }}</div>{% endif -%}
{%- endmacro %}

{% macro actions(c, pick_ep, cancel_ep) -%}
  {% if c.status == WAITING %}
  <form method="post" action="{{ url_for(pick_ep, cid=c.id) }}" style="display:inline"
        onsubmit='return confirm({{ t("تأكيد أن {d} استلم {n} شحنة؟").format(d=c.driver, n=c.qty)|tojson }})'>
    <button class="small-btn green">{{ t('✓ تأكيد الاستلام') }}</button>
  </form>
  {% endif %}
  {% if c.status in (WAITING, PICKED) %}
  <form method="post" action="{{ url_for(cancel_ep, cid=c.id) }}" style="display:inline"
        onsubmit='return confirm({{ t("إلغاء الحجز وإرجاع الشحنات للمتاح؟")|tojson }})'>
    <button class="small-btn red">{{ t('إلغاء') }}</button>
  </form>
  {% endif %}
{%- endmacro %}

{% macro claims_table(rows, pick_ep, cancel_ep, empty, show_gov=True) -%}
  <table class="stack">
    <tr><th>{{ t('موعد الاستلام') }}</th><th>{{ t('المندوب') }}</th><th>{{ t('الهاتف') }}</th>
        <th>{{ t('المحافظة / الولاية') if show_gov else t('الولاية') }}</th><th>{{ t('العدد') }}</th>
        <th>{{ t('المشرف') }}</th><th>{{ t('الحالة') }}</th><th></th></tr>
    {% for c in rows %}
    <tr>
      <td data-label="{{ t('موعد الاستلام') }}">{{ pickup(c) }}</td>
      <td data-label="{{ t('المندوب') }}" class="big">{{ c.driver }}</td>
      <td data-label="{{ t('الهاتف') }}"><a class="phone" href="tel:{{ c.phone }}">📞 {{ c.phone }}</a></td>
      <td data-label="{{ t('الولاية') }}">{% if show_gov %}{{ place(c.governorate) }} / {% endif %}{{ place(c.wilaya) }}</td>
      <td data-label="{{ t('العدد') }}" class="num">{{ c.qty }}{% if c.forced %} <small title="{{ t('أُجبر على أخذ الباقي') }}">⚠️</small>{% endif %}</td>
      <td data-label="{{ t('المشرف') }}">{% if c.notified_at %}<span class="badge b-تم" title="{{ c.notified_at }}">{{ t('✓ تم الإبلاغ') }}</span>
          {% else %}<span class="badge b-ملغي">{{ t('لم يُبلَّغ') }}</span>{% endif %}</td>
      <td data-label="{{ t('الحالة') }}">{{ status_badge(c) }}</td>
      <td class="acts" style="white-space:nowrap">{{ actions(c, pick_ep, cancel_ep) }}</td>
    </tr>
    {% else %}
    <tr><td colspan="8" class="empty">{{ t(empty) }}</td></tr>
    {% endfor %}
  </table>
{%- endmacro %}
""",

    "login.html": """
{% extends "base.html" %}
{% block auth %}
<h1>{{ t('مرحباً بعودتك') }}</h1>
<p class="lead">{{ t('سجّل دخولك لإدارة الشحنات وحجوزات المندوبين') }}</p>
{% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}
<div class="seg">
  <button type="button" id="t-driver" class="on" onclick="showForm('driver')">{{ t('مندوب') }}</button>
  <button type="button" id="t-sup" onclick="showForm('sup')">{{ t('مشرف') }}</button>
  <button type="button" id="t-admin" onclick="showForm('admin')">{{ t('الإدارة') }}</button>
</div>
<form method="post" action="{{ url_for('d_login') }}" id="f-driver">
  <label>{{ t('الاسم') }}</label>
  <select name="name" required>
    <option value="">{{ t('— اختر اسمك —') }}</option>
    {% for d in driver_names %}<option>{{ d }}</option>{% endfor %}
  </select>
  <br><br>
  <label>{{ t('رمز PIN') }}</label>
  <input type="password" name="pin" inputmode="numeric" placeholder="{{ t('أدخل الرمز...') }}" required>
  <br><br>
  <button type="submit" class="btn-dark">{{ t('دخول') }}</button>
</form>
<form method="post" action="{{ url_for('s_login') }}" id="f-sup" style="display:none">
  <label>{{ t('المحافظة') }}</label>
  <select name="governorate" required>
    <option value="">{{ t('— اختر محافظتك —') }}</option>
    {% for g in sup_govs %}<option value="{{ g }}">{{ place(g) }}</option>{% endfor %}
  </select>
  <br><br>
  <label>{{ t('رمز PIN') }}</label>
  <input type="password" name="pin" inputmode="numeric" placeholder="{{ t('أدخل الرمز...') }}" required>
  <br><br>
  <button type="submit" class="btn-dark">{{ t('دخول') }}</button>
</form>
<form method="post" action="{{ url_for('login') }}" id="f-admin" style="display:none">
  <label>{{ t('كلمة المرور') }}</label>
  <input type="password" name="password" placeholder="{{ t('أدخل كلمة المرور...') }}" required>
  <br><br>
  <button type="submit" class="btn-dark">{{ t('دخول') }}</button>
</form>
<script>
  function showForm(which) {
    ['driver', 'sup', 'admin'].forEach(function (k) {
      document.getElementById('f-' + k).style.display = k === which ? '' : 'none';
      document.getElementById('t-' + k).classList.toggle('on', k === which);
    });
  }
  {% if show_form %}showForm({{ show_form|tojson }});{% endif %}
</script>
{% endblock %}
""",

    "today.html": """
{% extends "base.html" %}
{% from "macros.html" import claims_table with context %}
{% block content %}
<div class="kpis">
  <div class="kpi">{{ t('مواعيد اليوم') }}<b>{{ k.today }}</b></div>
  <div class="kpi k-warn">{{ t('بانتظار الاستلام') }}<b>{{ k.waiting }}</b></div>
  <div class="kpi k-ok">{{ t('تم استلامها') }}<b>{{ k.picked }}</b></div>
  <div class="kpi k-bad">{{ t('متأخرون') }}<b>{{ k.late }}</b></div>
</div>

{% if late %}
<div class="card alert">
  <h3>{{ t('⚠️ متأخرون عن موعد الاستلام') }}</h3>
  {{ claims_table(late, pick_ep, cancel_ep, '', show_gov) }}
</div>
{% endif %}

<div class="card">
  <h3>{{ t('🕒 مواعيد استلام اليوم') }}</h3>
  {{ claims_table(today_rows, pick_ep, cancel_ep, 'لا توجد مواعيد اليوم', show_gov) }}
</div>

<div class="card">
  <h3>{{ t('📅 المواعيد القادمة') }}</h3>
  {{ claims_table(upcoming, pick_ep, cancel_ep, 'لا توجد مواعيد قادمة', show_gov) }}
</div>

{% if avail is not none %}
<div class="card">
  <h3>{{ t('المتاح في {g}').format(g=place(gov)) }}</h3>
  <table>
    <tr><th>{{ t('الولاية') }}</th><th>{{ t('العدد المتاح') }}</th></tr>
    {% for w, n in avail.items() %}
    <tr><td class="big">{{ place(w) }}</td><td class="num">{{ n }}</td></tr>
    {% else %}
    <tr><td colspan="2" class="empty">{{ t('لا توجد شحنات متاحة') }}</td></tr>
    {% endfor %}
  </table>
</div>
{% endif %}
{% endblock %}
""",

    "shipments.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>{{ t('➕ إضافة شحنات') }}</h3>
  <form method="post" action="{{ url_for('add_shipments') }}" class="grid">
    <div><label>{{ t('المحافظة') }}</label>
      <select name="governorate" id="gov" required onchange="fillWilayat()">
        <option value="">{{ t('— اختر —') }}</option>
        {% for g in oman %}<option value="{{ g }}">{{ place(g) }}</option>{% endfor %}
      </select></div>
    <div><label>{{ t('الولاية') }}</label>
      <select name="wilaya" id="wil" required><option value="">{{ t('— اختر المحافظة أولاً —') }}</option></select></div>
    <div><label>{{ t('عدد الشحنات') }}</label>
      <input name="count" type="number" min="1" max="{{ max_bulk }}" required></div>
    <button type="submit">{{ t('＋ إضافة الشحنات') }}</button>
  </form>
  <script>
    const OMAN = {{ oman|tojson }}, PLACE = {{ place_map|tojson }}, PICK = {{ t('— اختر —')|tojson }};
    function fillWilayat() {
      const list = OMAN[document.getElementById('gov').value] || [];
      document.getElementById('wil').innerHTML = '<option value="">' + PICK + '</option>' +
        list.map(x => '<option value="' + x + '">' + (PLACE[x] || x) + '</option>').join('');
    }
  </script>
</div>

<div class="kpis">
  <div class="kpi">{{ t('متاحة للحجز') }}<b>{{ totals[AVAILABLE] }}</b></div>
  <div class="kpi k-warn">{{ t('بانتظار الاستلام') }}<b>{{ totals[WAITING] }}</b></div>
  <div class="kpi k-info">{{ t('مع المندوبين') }}<b>{{ totals[PICKED] }}</b></div>
  <div class="kpi k-ok">{{ t('تم توصيلها') }}<b>{{ totals[DELIVERED] }}</b></div>
</div>

<div class="card">
  <h3>{{ t('الشحنات حسب المحافظة والولاية') }}</h3>
  <table>
    <tr><th>{{ t('المحافظة / الولاية') }}</th><th>{{ t('متاحة') }}</th><th>{{ t('بانتظار الاستلام') }}</th>
        <th>{{ t('مع المندوبين') }}</th><th>{{ t('تم التوصيل') }}</th><th>{{ t('إنقاص المتاح') }}</th></tr>
    {% for g in summary %}
      <tr class="gov"><td>{{ place(g.name) }}</td><td>{{ g[AVAILABLE] }}</td><td>{{ g[WAITING] }}</td><td>{{ g[PICKED] }}</td><td>{{ g[DELIVERED] }}</td><td></td></tr>
      {% for w in g.wilayat %}
      <tr>
        <td>&nbsp;&nbsp;&nbsp;{{ place(w.name) }}</td>
        <td class="big">{{ w[AVAILABLE] }}</td><td>{{ w[WAITING] }}</td><td>{{ w[PICKED] }}</td><td>{{ w[DELIVERED] }}</td>
        <td>
          {% if w[AVAILABLE] %}
          <form method="post" action="{{ url_for('remove_shipments') }}" class="qty"
                onsubmit='return confirm({{ t("حذف هذا العدد من الشحنات المتاحة؟")|tojson }})'>
            <input type="hidden" name="governorate" value="{{ g.name }}">
            <input type="hidden" name="wilaya" value="{{ w.name }}">
            <input name="count" type="number" min="1" max="{{ w[AVAILABLE] }}" placeholder="{{ t('العدد') }}" required>
            <button class="small-btn red">{{ t('حذف') }}</button>
          </form>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    {% else %}
      <tr><td colspan="6" class="empty">{{ t('لا توجد شحنات بعد') }}</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "upload.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>{{ t('1. حمّل ملف النموذج') }}</h3>
  <p class="muted">{{ t('الأعمدة: المحافظة، الولاية، العدد. يمكن كتابة الأسماء بالعربي أو الإنجليزي.') }}</p>
  <a class="btn-link btn-ghost" href="{{ url_for('upload_template') }}">{{ t('⬇️ تحميل النموذج') }}</a>
</div>
<div class="card">
  <h3>{{ t('2. ارفع الملف بعد تعبئته') }}</h3>
  <form method="post" action="{{ url_for('upload_shipments') }}" enctype="multipart/form-data" class="grid">
    <input type="file" name="file" accept=".xlsx,.xls,.csv" required>
    <button type="submit">{{ t('رفع وإضافة') }}</button>
  </form>
</div>
{% if errors %}
<div class="card alert">
  <h3>{{ t('لم يُضَف شيء — صحّح الأخطاء التالية ثم ارفع الملف مرة ثانية:') }}</h3>
  <table>
    {% for row, msg in errors %}<tr><td class="num">{{ t('سطر') }} {{ row }}</td><td>{{ msg }}</td></tr>{% endfor %}
  </table>
</div>
{% endif %}
{% endblock %}
""",

    "claims.html": """
{% extends "base.html" %}
{% from "macros.html" import claims_table with context %}
{% block content %}
<div class="kpis">
  <div class="kpi k-warn">{{ t('حجوزات بانتظار الاستلام') }}<b>{{ waiting_count }}</b></div>
  <div class="kpi k-warn">{{ t('شحنات بانتظار الاستلام') }}<b>{{ waiting_qty }}</b></div>
  <div class="kpi k-info">{{ t('مع المندوبين الآن') }}<b>{{ picked_qty }}</b></div>
</div>

<div class="card">
  <form method="post" action="{{ url_for('set_min_left') }}" class="qty">
    <label>{{ t('إجبار المندوب على أخذ الباقي إذا بقي أقل من') }}</label>
    <input name="min_left" type="number" min="0" value="{{ min_left }}" required>
    <span>{{ t('شحنات في الولاية') }}</span>
    <button class="small-btn">{{ t('حفظ') }}</button>
  </form>
</div>

<div class="card">
  <form method="get" class="filters">
    <input type="hidden" name="status" value="{{ f.status }}">
    <input name="q" value="{{ f.q }}" placeholder="{{ t('اسم المندوب أو الهاتف') }}">
    <select name="gov">
      <option value="">{{ t('كل المحافظات') }}</option>
      {% for g in oman %}<option value="{{ g }}" {% if g == f.gov %}selected{% endif %}>{{ place(g) }}</option>{% endfor %}
    </select>
    <input name="date" type="date" value="{{ f.date }}">
    <button type="submit">{{ t('بحث') }}</button>
    <a class="btn-link btn-ghost" href="{{ url_for('claims') }}">{{ t('مسح') }}</a>
  </form>
  <div class="tabs">
    <a href="{{ url_for('claims', q=f.q, gov=f.gov, date=f.date) }}" class="{{ 'on' if not f.status }}">{{ t('الكل') }} <span class="n">{{ counts.values()|sum }}</span></a>
    {% for s in statuses %}
    <a href="{{ url_for('claims', status=s, q=f.q, gov=f.gov, date=f.date) }}" class="{{ 'on' if s == f.status }}">{{ t(s) }} <span class="n">{{ counts.get(s, 0) }}</span></a>
    {% endfor %}
  </div>
  {{ claims_table(rows, 'claim_picked', 'claim_cancel', 'لا توجد حجوزات') }}
</div>
{% endblock %}
""",

    "drivers.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>{{ t('إضافة مندوب') }}</h3>
  <form method="post" action="{{ url_for('add_driver') }}" class="grid">
    <input name="name" placeholder="{{ t('اسم المندوب') }}" required>
    <input name="phone" inputmode="tel" placeholder="{{ t('رقم الهاتف') }}" required>
    <input name="pin" inputmode="numeric" pattern="[0-9]{4,8}" placeholder="{{ t('رمز PIN للدخول (4 أرقام أو أكثر)') }}" required>
    <button type="submit">{{ t('إضافة') }}</button>
  </form>
  <p class="muted">{{ t('أعطِ كل مندوب اسمه ورمز PIN ليدخل من نفس رابط الموقع ويحجز الشحنات.') }}</p>
</div>

<div class="card">
  <h3>{{ t('قائمة المندوبين') }}</h3>
  <table>
    <tr><th>#</th><th>{{ t('الاسم') }}</th><th>{{ t('الهاتف') }}</th><th>{{ t('محجوزة حالياً') }}</th>
        <th>{{ t('تم التوصيل') }}</th><th>{{ t('تغيير PIN') }}</th><th>{{ t('إجراءات') }}</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{ r.id }}</td>
      <td class="big">{{ r.name }}{% if not r.pin_hash %} <span class="badge b-بانتظار">{{ t('بدون PIN') }}</span>{% endif %}</td>
      <td>{% if r.phone %}<a class="phone" href="tel:{{ r.phone }}">📞 {{ r.phone }}</a>{% endif %}</td>
      <td class="num">{{ r.claimed }}</td>
      <td class="num">{{ r.delivered }}</td>
      <td>
        <form method="post" action="{{ url_for('set_pin', did=r.id) }}" class="qty">
          <input name="pin" inputmode="numeric" pattern="[0-9]{4,8}" placeholder="{{ t('PIN جديد') }}" required style="width:120px">
          <button class="small-btn">{{ t('حفظ') }}</button>
        </form>
      </td>
      <td>
        <form method="post" action="{{ url_for('delete_driver', did=r.id) }}" style="display:inline"
              onsubmit='return confirm({{ t("حذف المندوب؟ حجوزاته المفتوحة سترجع متاحة.")|tojson }})'>
          <button class="small-btn red">{{ t('حذف') }}</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="7" class="empty">{{ t('لا يوجد مندوبون بعد') }}</td></tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "supervisors.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>{{ t('مشرف كل محافظة') }}</h3>
  <p class="muted" style="margin-top:-8px">{{ t('يدخل المشرف من صفحة الدخول باختيار «مشرف» ثم محافظته ورمزه.') }}</p>
  <table>
    <tr><th>{{ t('المحافظة') }}</th><th>{{ t('اسم المشرف') }}</th><th>{{ t('رقم الواتساب') }}</th>
        <th>{{ t('رمز دخول المشرف') }}</th><th></th></tr>
    {% for g in oman %}
    {% set s = sups.get(g, {}) %}
    <tr>
      <form method="post" action="{{ url_for('save_supervisor') }}">
        <td class="big">{{ place(g) }}<input type="hidden" name="governorate" value="{{ g }}"></td>
        <td><input name="name" value="{{ s.get('name', '') }}" placeholder="{{ t('اسم المشرف') }}"></td>
        <td><input name="phone" value="{{ s.get('phone', '') }}" inputmode="tel" placeholder="99123456" style="direction:ltr"></td>
        <td><input name="pin" inputmode="numeric" pattern="[0-9]{4,8}"
                   placeholder="{{ t('اتركه فارغاً لعدم التغيير') if s.get('pin_hash') else 'PIN' }}">
            {% if s.get('pin_hash') %}<span class="badge b-تم" style="margin-top:6px">{{ t('مفعّل') }}</span>{% endif %}</td>
        <td style="white-space:nowrap">
          <button class="small-btn">{{ t('حفظ') }}</button>
          {% if s %}<button class="small-btn red" name="clear" value="1" formnovalidate>{{ t('حذف') }}</button>{% endif %}
        </td>
      </form>
    </tr>
    {% endfor %}
  </table>
</div>
{% endblock %}
""",

    "d_home.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h3>{{ t('📦 حجز شحنات') }}</h3>
  {% if avail %}
  <form method="post" action="{{ url_for('d_claim') }}" class="grid">
    <div><label>{{ t('المحافظة') }}</label>
      <select name="governorate" id="gov" required onchange="fillWil()">
        <option value="">{{ t('— اختر —') }}</option>
        {% for g in avail %}<option value="{{ g }}">{{ place(g) }} ({{ avail[g].values()|sum }})</option>{% endfor %}
      </select></div>
    <div><label>{{ t('الولاية') }}</label>
      <select name="wilaya" id="wil" required onchange="check()"><option value="">{{ t('— اختر المحافظة أولاً —') }}</option></select></div>
    <div><label>{{ t('كم شحنة تستلم؟') }}</label>
      <input name="qty" id="qty" type="number" min="1" required oninput="check()"></div>
    <div><label>{{ t('متى تجي تستلم؟') }}</label>
      <input name="pickup_time" id="pickup" type="datetime-local" min="{{ now_local }}" required>
      <div class="quick">
        {% for label, value in quick_times %}<button type="button" onclick="document.getElementById('pickup').value='{{ value }}'">{{ t(label) }}</button>{% endfor %}
      </div></div>
    <div><label>{{ t('رقم هاتفك') }}</label>
      <input name="phone" value="{{ phone }}" inputmode="tel" required></div>
    <button type="submit" class="green">{{ t('تأكيد الحجز') }}</button>
  </form>
  <div id="msg" style="margin-top:10px"></div>
  <p class="muted">{{ t('ملاحظة: إذا بقي في الولاية أقل من {n} شحنات بعد حجزك، يجب أن تأخذ الباقي كله.').format(n=min_left) }}</p>
  <script>
    const AVAIL = {{ avail|tojson }}, MIN_LEFT = {{ min_left }}, PLACE = {{ place_map|tojson }};
    const T = {{ js_text|tojson }};
    const fmt = (s, o) => s.replace(/\\{(\\w+)\\}/g, (_, k) => o[k]);
    const name = w => PLACE[w] || w;
    function fillWil(g) {
      const gov = document.getElementById('gov');
      if (g) gov.value = g;
      const ws = AVAIL[gov.value] || {};
      document.getElementById('wil').innerHTML = '<option value="">' + T.pick + '</option>' +
        Object.keys(ws).map(w => '<option value="' + w + '">' + name(w) + ' (' + ws[w] + ')</option>').join('');
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
      const left = avail - q, o = {w: name(w), n: avail, q: q, l: left};
      if (q > avail) {
        msg.innerHTML = '<div class="warn">' + fmt(T.only, o) + '</div>';
      } else if (q > 0 && left > 0 && left < MIN_LEFT) {
        msg.innerHTML = '<div class="warn">' + fmt(T.forced, o) + '</div>';
        qtyEl.value = avail;
      } else if (q > 0) {
        msg.innerHTML = '<div class="ok">' + fmt(T.will, o) + '</div>';
      } else {
        msg.innerHTML = '<div class="ok">' + fmt(T.avail, o) + '</div>';
      }
    }
  </script>
  {% else %}
    <p class="big">{{ t('لا توجد شحنات متاحة حالياً 👍') }}</p>
  {% endif %}
</div>

{% if avail %}
<div class="card">
  <h3>{{ t('المتاح الآن') }}</h3>
  <table>
    <tr><th>{{ t('المحافظة') }}</th><th>{{ t('الولاية') }}</th><th>{{ t('العدد المتاح') }}</th><th></th></tr>
    {% for g, ws in avail.items() %}
      {% for w, n in ws.items() %}
      <tr>
        <td>{{ place(g) }}</td><td class="big">{{ place(w) }}</td><td class="num">{{ n }}</td>
        <td><button class="small-btn green" onclick="pick({{ g|tojson }}, {{ w|tojson }})">{{ t('اختر') }}</button></td>
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
{% if notify %}
<div class="card" style="border:2px solid #25d366">
  <h3>{{ t('📲 خطوة أخيرة: بلّغ مشرف {g}').format(g=place(notify.governorate)) }}</h3>
  {% if notify.wa %}
  <p class="muted">{{ t('سيُفتح واتساب والرسالة جاهزة إلى المشرف') }} <b>{{ notify.sup_name }}</b>. {{ t('اضغط «إرسال» في واتساب فقط.') }}</p>
  <pre class="msg">{{ notify.text }}</pre>
  <a class="btn-link wa" style="font-size:17px;padding:14px 22px" href="{{ url_for('d_notify', cid=notify.id) }}" target="_blank">{{ t('📲 أرسل للمشرف عبر واتساب') }}</a>
  {% else %}
  <p class="warn">{{ t('لم يُضَف مشرف لمحافظة {g} بعد — أبلغ الإدارة.').format(g=place(notify.governorate)) }}</p>
  {% endif %}
</div>
{% endif %}
<div class="card">
  <h3>{{ t('حجوزاتي') }}</h3>
  <table>
    <tr><th>#</th><th>{{ t('المحافظة') }}</th><th>{{ t('الولاية') }}</th><th>{{ t('العدد') }}</th>
        <th>{{ t('موعد الاستلام') }}</th><th>{{ t('الحالة') }}</th><th></th></tr>
    {% for c in claims %}
    <tr>
      <td>{{ c.id }}</td>
      <td>{{ place(c.governorate) }}</td>
      <td class="big">{{ place(c.wilaya) }}</td>
      <td class="num">{{ c.qty }}</td>
      <td><span class="time">{{ c.pickup_time }}</span></td>
      <td><span class="badge b-{{ c.status.split()[0] }}">{{ t(c.status) }}</span></td>
      <td style="white-space:nowrap">
        {% if c.status == PICKED %}
        <form method="post" action="{{ url_for('d_claim_done', cid=c.id) }}" style="display:inline"
              onsubmit='return confirm({{ t("تأكيد توصيل كل شحنات هذا الحجز؟")|tojson }})'>
          <button class="small-btn green">{{ t('✓ وصّلت الكل') }}</button>
        </form>
        {% endif %}
        {% if c.status == WAITING and has_sup.get(c.governorate) %}
        <a class="small-btn wa" href="{{ url_for('d_notify', cid=c.id) }}" target="_blank">{{ t('📲 أعد الإرسال') if c.notified_at else t('📲 بلّغ المشرف') }}</a>
        {% endif %}
        {% if c.status == WAITING %}
        <form method="post" action="{{ url_for('d_claim_cancel', cid=c.id) }}" style="display:inline"
              onsubmit='return confirm({{ t("إلغاء الحجز وإرجاع الشحنات؟")|tojson }})'>
          <button class="small-btn gray">{{ t('إلغاء الحجز') }}</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% else %}
    <tr><td colspan="7" class="empty">{{ t('ليس عندك حجوزات') }} — <a href="{{ url_for('d_home') }}">{{ t('احجز من هنا') }}</a></td></tr>
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
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # حد حجم ملف Excel
app.jinja_loader = DictLoader(TEMPLATES)


def current_lang():
    return "en" if request.cookies.get("lang") == "en" else "ar"


def tr(text):
    """يترجم نص الواجهة حسب لغة المستخدم."""
    return EN.get(text, text) if current_lang() == "en" else text


def place(name):
    """اسم المحافظة أو الولاية بلغة المستخدم."""
    if not name:
        return ""
    return PLACES_EN.get(name, name) if current_lang() == "en" else name


app.jinja_env.globals.update(AVAILABLE=AVAILABLE, CLAIMED=CLAIMED, DELIVERED=DELIVERED,
                             WAITING=WAITING, PICKED=PICKED, t=tr, place=place,
                             brand_en=(BRAND_EN.split(" ", 1) + [""])[:2], brand_ar=BRAND_AR)


def connect(**kwargs):
    # الانتظار حتى 15 ثانية إذا كانت قاعدة البيانات مشغولة بدل إظهار خطأ
    return sqlite3.connect(DB_PATH, timeout=15, **kwargs)


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = connect()
    # وضع WAL: القراءة لا تنتظر الكتابة، فيتحمل عدة مستخدمين في نفس الوقت
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # ترقية الجداول من النسخ السابقة
    for table, cols in (("drivers", ("pin_hash", "phone")),
                        ("claims", ("notified_at", "picked_at", "picked_by")),
                        ("supervisors", ("pin_hash",))):
        existing = _columns(conn, table)
        for col in cols:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
    conn.commit()
    conn.close()


def db_exec(sql, params=()):
    """ينفّذ أمراً ويعيد عدد الصفوف المتأثرة."""
    conn = connect()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def db_df(sql, params=()):
    conn = connect()
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


def today_oman():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def gov_order(gov):
    return list(OMAN).index(gov) if gov in OMAN else 99


def valid_pin(pin):
    return pin.isdigit() and 4 <= len(pin) <= 8


init_db()

PUBLIC_ENDPOINTS = {"login", "d_login", "s_login", "set_lang", "manifest", "service_worker", "static"}


@app.context_processor
def common_context():
    """اللغة وأعداد القائمة الجانبية."""
    ctx = {"lang": current_lang(), "place_map": PLACES_EN if current_lang() == "en" else {}}
    role = session.get("role")
    if role in ("admin", "supervisor"):
        gov_sql, params = ("AND governorate = ?", (session.get("gov"),)) if role == "supervisor" else ("", ())
        ctx["nav_today"] = int(db_df(f"SELECT COUNT(*) AS n FROM claims WHERE status = ? AND pickup_time LIKE ? {gov_sql}",
                                     (WAITING, today_oman() + "%", *params))["n"][0])
        ctx["nav_late"] = int(db_df(f"SELECT COUNT(*) AS n FROM claims WHERE status = ? AND pickup_time < ? {gov_sql}",
                                    (WAITING, now_oman(), *params))["n"][0])
        ctx["nav_available"] = int(db_df("SELECT COUNT(*) AS n FROM shipments WHERE status = ?",
                                         (AVAILABLE,))["n"][0])
    return ctx


@app.before_request
def require_login():
    endpoint = request.endpoint or ""
    if endpoint in PUBLIC_ENDPOINTS:
        return None
    role = session.get("role")
    if endpoint == "logout" and role:
        return None
    if endpoint.startswith("d_"):
        # صفحات المندوب: يجب أن يكون المندوب ما زال موجوداً في القائمة
        if role == "driver" and session.get("driver") in driver_names():
            return None
        session.clear()
        return redirect(url_for("login"))
    if endpoint.startswith("s_"):
        if role == "supervisor" and session.get("gov") in supervisors_map():
            return None
        session.clear()
        return redirect(url_for("login"))
    if role == "admin":
        return None
    if role == "driver":
        return redirect(url_for("d_home"))
    if role == "supervisor":
        return redirect(url_for("s_home"))
    return redirect(url_for("login"))


# ----------------------------------------------------------------------
# الدخول واللغة والتطبيق على الجوال
# ----------------------------------------------------------------------
def login_page(show_form=None):
    sup_govs = [g for g, s in supervisors_map().items() if s.get("pin_hash")]
    return render_template("login.html", title="دخول", driver_names=driver_names(),
                           sup_govs=sorted(sup_govs, key=gov_order), show_form=show_form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session.clear()
            session["role"] = "admin"
            return redirect(url_for("today"))
        flash(tr("كلمة المرور غير صحيحة"))
        return login_page("admin")
    home = {"admin": "today", "driver": "d_home", "supervisor": "s_home"}.get(session.get("role"))
    return redirect(url_for(home)) if home else login_page()


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
    flash(tr("الاسم أو رمز PIN غير صحيح"))
    return redirect(url_for("login"))


@app.route("/supervisor/login", methods=["POST"])
def s_login():
    gov = request.form.get("governorate", "")
    sup = supervisors_map().get(gov)
    if sup and sup.get("pin_hash") and check_password_hash(sup["pin_hash"], request.form.get("pin", "").strip()):
        session.clear()
        session["role"] = "supervisor"
        session["gov"] = gov
        return redirect(url_for("s_home"))
    flash(tr("المحافظة أو رمز PIN غير صحيح"))
    return login_page("sup")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/lang/<code>")
def set_lang(code):
    resp = make_response(redirect(request.referrer or url_for("login")))
    resp.set_cookie("lang", "en" if code == "en" else "ar", max_age=365 * 24 * 3600, samesite="Lax")
    return resp


@app.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": f"{BRAND_EN} — {BRAND_AR}",
        "short_name": BRAND_EN,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#1e3a8a",
        "lang": "ar",
        "dir": "rtl",
        "icons": [
            {"src": url_for("static", filename="icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": url_for("static", filename="icon-maskable-512.png"), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }
    return Response(json.dumps(data, ensure_ascii=False), mimetype="application/manifest+json")


SERVICE_WORKER = """
// يجعل الموقع قابلاً للتثبيت كتطبيق، ويعرض رسالة بسيطة عند انقطاع الإنترنت
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<html dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<body style="font-family:sans-serif;text-align:center;padding:60px">' +
    '<h2>لا يوجد اتصال بالإنترنت</h2><p>No internet connection</p></body></html>',
    {headers: {'Content-Type': 'text/html; charset=utf-8'}})));
});
"""


@app.route("/sw.js")
def service_worker():
    return Response(SERVICE_WORKER, mimetype="application/javascript", headers={"Cache-Control": "no-cache"})


@app.route("/")
def index():
    return redirect(url_for("today"))


# ----------------------------------------------------------------------
# مساعدات الحجوزات
# ----------------------------------------------------------------------
def release_claim(conn, cid):
    """يرجع شحنات الحجز التي لم توصَّل إلى المتاح."""
    conn.execute("UPDATE shipments SET driver = '', status = ?, claim_id = NULL "
                 "WHERE claim_id = ? AND status = ?", (AVAILABLE, cid, CLAIMED))
    conn.execute("UPDATE claims SET status = ? WHERE id = ?", (CANCELLED, cid))


def decorate(rows):
    """يضيف علامة التأخير لكل حجز ينتظر الاستلام وتجاوز موعده."""
    now = datetime.now(TZ).replace(tzinfo=None)
    for c in rows:
        c["is_late"] = False
        c["late_label"] = ""
        if c["status"] == WAITING:
            try:
                due = datetime.strptime(c["pickup_time"], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if due < now:
                minutes = int((now - due).total_seconds() // 60)
                c["is_late"] = True
                c["late_label"] = (tr("تأخر {m} دقيقة").format(m=minutes) if minutes < 120
                                   else tr("تأخر {h} ساعة").format(h=minutes // 60))
    return rows


def claims_query(gov, condition, params):
    sql = "SELECT * FROM claims WHERE " + condition
    if gov:
        sql += " AND governorate = ?"
        params = (*params, gov)
    return sql, params


def day_board(gov=None):
    """بيانات صفحة اليوم (للمدير أو لمشرف محافظة)."""
    tomorrow = (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    sql, p = claims_query(gov, "status = ? AND pickup_time < ?", (WAITING, now_oman()))
    late = decorate(db_df(sql + " ORDER BY pickup_time", p).to_dict("records"))
    sql, p = claims_query(gov, "status <> ? AND pickup_time LIKE ?", (CANCELLED, today_oman() + "%"))
    today_rows = decorate(db_df(sql + " ORDER BY pickup_time", p).to_dict("records"))
    sql, p = claims_query(gov, "status = ? AND pickup_time >= ?", (WAITING, tomorrow))
    upcoming = decorate(db_df(sql + " ORDER BY pickup_time LIMIT 100", p).to_dict("records"))
    k = {
        "today": len(today_rows),
        "waiting": sum(1 for c in today_rows if c["status"] == WAITING),
        "picked": sum(1 for c in today_rows if c["status"] in (PICKED, CLAIM_DONE)),
        "late": len(late),
    }
    return {"late": late, "today_rows": today_rows, "upcoming": upcoming, "k": k}


def mark_picked(cid, by, gov=None):
    sql = "UPDATE claims SET status = ?, picked_at = ?, picked_by = ? WHERE id = ? AND status = ?"
    params = [PICKED, now_oman(), by, cid, WAITING]
    if gov:
        sql += " AND governorate = ?"
        params.append(gov)
    return db_exec(sql, params)


def cancel_claim(cid, gov=None):
    conn = connect()
    try:
        row = conn.execute("SELECT governorate, status FROM claims WHERE id = ?", (cid,)).fetchone()
        if row and (gov is None or row[0] == gov) and row[1] in (WAITING, PICKED):
            release_claim(conn, cid)
            conn.commit()
            return True
    finally:
        conn.close()
    return False


# ----------------------------------------------------------------------
# 1) اليوم (المدير)
# ----------------------------------------------------------------------
@app.route("/today")
def today():
    return render_template("today.html", title="اليوم", subtitle="مواعيد استلام اليوم والمتأخرون",
                           pick_ep="claim_picked", cancel_ep="claim_cancel", show_gov=True,
                           avail=None, gov=None, **day_board())


# ----------------------------------------------------------------------
# 2) الشحنات (المدير)
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
    return render_template("shipments.html", title="الشحنات",
                           subtitle="أضف الشحنات لكل محافظة وولاية وتابع مواعيد استلام المندوبين",
                           oman=OMAN, totals=totals, summary=summary, max_bulk=MAX_BULK)


def insert_shipments(rows):
    """rows: [(المحافظة, الولاية, العدد)]"""
    now = now_oman()
    conn = connect()
    try:
        for gov, wilaya, count in rows:
            conn.executemany("INSERT INTO shipments (governorate, wilaya, status, created_at) VALUES (?,?,?,?)",
                             [(gov, wilaya, AVAILABLE, now)] * count)
        conn.commit()
    finally:
        conn.close()


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
    insert_shipments([(gov, wilaya, count)])
    flash(f"✅ تمت إضافة {count} شحنة في {place(wilaya)} ({place(gov)})")
    return redirect(url_for("shipments"))


@app.route("/shipments/remove", methods=["POST"])
def remove_shipments():
    try:
        count = int(request.form.get("count", ""))
        if count < 1:
            raise ValueError
    except ValueError:
        flash(tr("اكتب عدداً صحيحاً"))
        return redirect(url_for("shipments"))
    removed = db_exec(
        """DELETE FROM shipments WHERE id IN (
               SELECT id FROM shipments WHERE status = ? AND governorate = ? AND wilaya = ?
               ORDER BY id DESC LIMIT ?)""",
        (AVAILABLE, request.form.get("governorate", ""), request.form.get("wilaya", ""), count))
    flash(f"تم حذف {removed} شحنة متاحة")
    return redirect(url_for("shipments"))


# ----------------------------------------------------------------------
# 3) رفع الشحنات من Excel
# ----------------------------------------------------------------------
UPLOAD_COLUMNS = {
    "gov": {"المحافظة", "governorate", "gov"},
    "wil": {"الولاية", "wilaya", "wilayat", "state"},
    "qty": {"العدد", "qty", "quantity", "count", "عدد الشحنات"},
}


def to_place(value):
    """يقبل اسم المكان بالعربي أو الإنجليزي ويعيده بالعربي."""
    value = str(value).strip()
    if value in WILAYA_TO_GOV or value in OMAN:
        return value
    return PLACES_AR.get(value.lower(), value)


def parse_upload(df):
    """يعيد (الصفوف الصحيحة، الأخطاء)."""
    cols = {}
    for c in df.columns:
        key = str(c).strip().lower()
        for k, names in UPLOAD_COLUMNS.items():
            if key in {n.lower() for n in names}:
                cols[k] = c
    if "wil" not in cols or "qty" not in cols:
        return [], [(1, "الملف يجب أن يحتوي على عمودي الولاية والعدد (والمحافظة اختيارياً)")]
    rows, errors, total = [], [], 0
    for i, r in df.iterrows():
        line = i + 2  # السطر الأول للعناوين
        wil_raw, qty_raw = r[cols["wil"]], r[cols["qty"]]
        gov_raw = r[cols["gov"]] if "gov" in cols else None
        if (pd.isna(wil_raw) or not str(wil_raw).strip()) and pd.isna(qty_raw):
            continue  # سطر فارغ
        wil = to_place(wil_raw)
        has_gov = gov_raw is not None and not pd.isna(gov_raw) and str(gov_raw).strip()
        gov = to_place(gov_raw) if has_gov else WILAYA_TO_GOV.get(wil, "")
        if wil not in WILAYA_TO_GOV:
            errors.append((line, f"ولاية غير معروفة: {wil_raw}"))
            continue
        if gov not in OMAN or wil not in OMAN[gov]:
            errors.append((line, f"الولاية {wil_raw} لا تتبع المحافظة {gov_raw}"))
            continue
        try:
            qty = int(float(qty_raw))
            if qty < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append((line, f"عدد غير صحيح: {qty_raw}"))
            continue
        total += qty
        rows.append((gov, wil, qty))
    if total > MAX_UPLOAD_TOTAL:
        errors.append(("—", f"المجموع {total} أكبر من الحد المسموح {MAX_UPLOAD_TOTAL}"))
    if not rows and not errors:
        errors.append((1, "الملف فارغ"))
    return rows, errors


def upload_view(errors=None):
    return render_template("upload.html", title="رفع من Excel",
                           subtitle="أضف شحنات كثيرة دفعة واحدة من ملف Excel", errors=errors)


@app.route("/upload")
def upload_page():
    return upload_view()


@app.route("/upload/template.xlsx")
def upload_template():
    sample = pd.DataFrame([
        {"المحافظة": "ظفار", "الولاية": "صلالة", "العدد": 250},
        {"المحافظة": "مسقط", "الولاية": "السيب", "العدد": 120},
        {"المحافظة": "شمال الباطنة", "الولاية": "صحار", "العدد": 80},
    ])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        sample.to_excel(writer, sheet_name="الشحنات", index=False)
        pd.DataFrame([(g, w, PLACES_EN.get(g, g), PLACES_EN.get(w, w)) for g, ws in OMAN.items() for w in ws],
                     columns=["المحافظة", "الولاية", "Governorate", "Wilaya"]).to_excel(
            writer, sheet_name="الولايات", index=False)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="shipments_template.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/upload", methods=["POST"])
def upload_shipments():
    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("upload_page"))
    try:
        df = pd.read_csv(f) if f.filename.lower().endswith(".csv") else pd.read_excel(f)
    except Exception:
        return upload_view([(1, "تعذّر قراءة الملف — تأكد أنه ملف Excel أو CSV")])
    rows, errors = parse_upload(df)
    if errors:
        return upload_view(errors)
    insert_shipments(rows)
    flash(f"✅ تمت إضافة {sum(q for _, _, q in rows)} شحنة في {len(rows)} سطر من الملف")
    return redirect(url_for("shipments"))


# ----------------------------------------------------------------------
# 4) حجوزات المندوبين (المدير)
# ----------------------------------------------------------------------
@app.route("/claims")
def claims():
    f = {k: request.args.get(k, "").strip() for k in ("status", "q", "gov", "date")}
    where, params = [], []
    if f["q"]:
        where.append("(driver LIKE ? OR phone LIKE ?)")
        params += [f"%{f['q']}%", f"%{f['q']}%"]
    if f["gov"]:
        where.append("governorate = ?")
        params.append(f["gov"])
    if f["date"]:
        where.append("pickup_time LIKE ?")
        params.append(f["date"] + "%")
    base = (" WHERE " + " AND ".join(where)) if where else ""

    # أعداد التبويبات تحترم البحث والتصفية
    stats = db_df(f"SELECT status, COUNT(*) AS n FROM claims {base} GROUP BY status", params)
    counts = {r.status: int(r.n) for r in stats.itertuples()}

    status_sql, status_params = "", []
    if f["status"]:
        status_sql = (" AND " if base else " WHERE ") + "status = ?"
        status_params = [f["status"]]
    rows = db_df(f"SELECT * FROM claims {base}{status_sql} ORDER BY "
                 f"CASE status WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END, pickup_time LIMIT 500",
                 (*params, *status_params, WAITING, PICKED)).to_dict("records")

    totals = db_df("SELECT status, COUNT(*) AS n, COALESCE(SUM(qty), 0) AS q FROM claims GROUP BY status")
    stat = {r.status: (int(r.n), int(r.q)) for r in totals.itertuples()}
    return render_template("claims.html", title="حجوزات المندوبين",
                           subtitle="من حجز، وكم، ومن أي ولاية، ومتى سيأتي للاستلام",
                           rows=decorate(rows), statuses=CLAIM_STATUSES, f=f, counts=counts,
                           oman=OMAN, min_left=get_min_left(),
                           waiting_count=stat.get(WAITING, (0, 0))[0],
                           waiting_qty=stat.get(WAITING, (0, 0))[1],
                           picked_qty=stat.get(PICKED, (0, 0))[1])


@app.route("/claims/<int:cid>/picked", methods=["POST"])
def claim_picked(cid):
    mark_picked(cid, "الإدارة")
    flash(tr("تم تسجيل تسليم الشحنات للمندوب"))
    return redirect(request.referrer or url_for("claims"))


@app.route("/claims/<int:cid>/cancel", methods=["POST"])
def claim_cancel(cid):
    cancel_claim(cid)
    flash(tr("تم إلغاء الحجز ورجعت الشحنات متاحة"))
    return redirect(request.referrer or url_for("claims"))


@app.route("/settings/min-left", methods=["POST"])
def set_min_left():
    try:
        value = int(request.form.get("min_left", ""))
        if value < 0:
            raise ValueError
    except ValueError:
        flash(tr("اكتب عدداً صحيحاً"))
        return redirect(url_for("claims"))
    db_exec("INSERT OR REPLACE INTO settings (key, value) VALUES ('min_left', ?)", (str(value),))
    flash(f"تم الحفظ: إذا بقي أقل من {value} يُجبَر المندوب على أخذ الباقي")
    return redirect(url_for("claims"))


# ----------------------------------------------------------------------
# 5) مشرفو المحافظات ورسائل الواتساب
# ----------------------------------------------------------------------
def supervisors_map():
    df = db_df("SELECT governorate, name, phone, pin_hash FROM supervisors")
    return {r.governorate: {"name": r.name, "phone": r.phone, "pin_hash": r.pin_hash} for r in df.itertuples()}


def whatsapp_number(phone):
    """يحوّل الرقم إلى صيغة واتساب الدولية (أرقام عُمان من 8 خانات تأخذ 968)."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 8:
        digits = "968" + digits
    return digits


def whatsapp_link(phone, text):
    return f"https://wa.me/{whatsapp_number(phone)}?text={urllib.parse.quote(text)}"


def claim_message(c):
    lines = [
        f"📦 حجز شحنات جديد رقم {c['id']}",
        f"المندوب: {c['driver']}",
        f"الهاتف: {c['phone']}",
        f"المحافظة: {c['governorate']}",
        f"الولاية: {c['wilaya']}",
        f"العدد: {c['qty']} شحنة",
        f"موعد الاستلام: {c['pickup_time']}",
    ]
    return "\n".join(lines)


@app.route("/supervisors")
def supervisors():
    return render_template("supervisors.html", title="مشرفو المحافظات",
                           subtitle="يستلم المشرف رسالة واتساب عند كل حجز في محافظته، ويدخل بحسابه ليؤكد الاستلام",
                           oman=OMAN, sups=supervisors_map())


@app.route("/supervisors/save", methods=["POST"])
def save_supervisor():
    gov = request.form.get("governorate", "")
    if gov not in OMAN:
        return redirect(url_for("supervisors"))
    if request.form.get("clear"):
        db_exec("DELETE FROM supervisors WHERE governorate = ?", (gov,))
        flash(f"تم حذف مشرف {place(gov)}")
        return redirect(url_for("supervisors"))
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    pin = request.form.get("pin", "").strip()
    if not name or len(whatsapp_number(phone)) < 8:
        flash("اكتب اسم المشرف ورقم واتساب صحيح")
        return redirect(url_for("supervisors"))
    if pin and not valid_pin(pin):
        flash("رمز PIN يجب أن يكون من 4 إلى 8 أرقام")
        return redirect(url_for("supervisors"))
    old = supervisors_map().get(gov, {})
    pin_hash = generate_password_hash(pin) if pin else old.get("pin_hash")
    db_exec("INSERT OR REPLACE INTO supervisors (governorate, name, phone, pin_hash) VALUES (?, ?, ?, ?)",
            (gov, name, phone, pin_hash))
    flash(f"✅ تم حفظ مشرف {place(gov)}: {name}")
    return redirect(url_for("supervisors"))


# ----------------------------------------------------------------------
# 6) صفحات المشرف
# ----------------------------------------------------------------------
@app.route("/supervisor")
def s_home():
    gov = session["gov"]
    return render_template("today.html", title="حجوزات محافظتي", subtitle="مواعيد استلام اليوم والمتأخرون",
                           pick_ep="s_picked", cancel_ep="s_cancel", show_gov=False,
                           avail=available_map().get(gov, {}), gov=gov, **day_board(gov))


@app.route("/supervisor/claims/<int:cid>/picked", methods=["POST"])
def s_picked(cid):
    gov = session["gov"]
    if mark_picked(cid, f"مشرف {gov}", gov):
        flash(tr("تم تسجيل تسليم الشحنات للمندوب"))
    return redirect(url_for("s_home"))


@app.route("/supervisor/claims/<int:cid>/cancel", methods=["POST"])
def s_cancel(cid):
    if cancel_claim(cid, session["gov"]):
        flash(tr("تم إلغاء الحجز ورجعت الشحنات متاحة"))
    return redirect(url_for("s_home"))


# ----------------------------------------------------------------------
# 7) المندوبين (المدير)
# ----------------------------------------------------------------------
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
    return render_template("drivers.html", title="المندوبين",
                           subtitle="أضف المندوبين وأعطِ كل واحد رمز PIN للدخول", rows=rows)


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
    conn = connect()
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
# 8) صفحات المندوب
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


def quick_times():
    """أزرار المواعيد السريعة للمندوب."""
    now = datetime.now(TZ)
    options = []
    for label, day, hour in (("اليوم صباحاً", 0, 9), ("اليوم العصر", 0, 16), ("بكرة صباحاً", 1, 9)):
        when = (now + timedelta(days=day)).replace(hour=hour, minute=0, second=0, microsecond=0)
        if when > now:
            options.append((label, when.strftime("%Y-%m-%dT%H:%M")))
    return options


@app.route("/driver")
def d_home():
    phone = db_df("SELECT phone FROM drivers WHERE name = ?", (session["driver"],))["phone"][0] or ""
    js_text = {"pick": tr("— اختر —"), "only": tr("المتاح في {w} فقط {n}"),
               "forced": tr("سيبقى {l} فقط — يجب أن تأخذ الكل: {n} شحنة"),
               "will": tr("ستحجز {q} من {w}، ويبقى {l}"), "avail": tr("المتاح في {w}: {n}")}
    return render_template("d_home.html", title="حجز شحنات", subtitle="اختر الولاية وعدد الشحنات وموعد الاستلام",
                           avail=available_map(), min_left=get_min_left(), phone=phone,
                           now_local=datetime.now(TZ).strftime("%Y-%m-%dT%H:%M"),
                           quick_times=quick_times(), js_text=js_text)


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
        flash(tr("اكتب عدداً صحيحاً"))
        return redirect(url_for("d_home"))
    if not phone or not pickup:
        flash(tr("اكتب رقم هاتفك وموعد الاستلام"))
        return redirect(url_for("d_home"))

    min_left = get_min_left()
    conn = connect(isolation_level=None)
    try:
        # قفل الكتابة حتى لا يحجز مندوبان نفس الشحنات في نفس اللحظة
        conn.execute("BEGIN IMMEDIATE")
        avail = conn.execute("SELECT COUNT(*) FROM shipments WHERE status = ? AND governorate = ? AND wilaya = ?",
                             (AVAILABLE, gov, wilaya)).fetchone()[0]
        if avail == 0:
            conn.execute("ROLLBACK")
            flash(tr("لم تعد هناك شحنات متاحة في هذه الولاية"))
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

    msg = "✅ " + tr("تم حجز {n} شحنة في {w} — موعد الاستلام {t}").format(n=qty, w=place(wilaya), t=pickup)
    if forced:
        msg += tr(" (أُضيف الباقي لأنه أقل من {m})").format(m=min_left)
    flash(msg)
    return redirect(url_for("d_mine", notify=cid))


@app.route("/driver/mine")
def d_mine():
    claims_list = db_df("SELECT * FROM claims WHERE driver = ? AND status <> ? ORDER BY id DESC LIMIT 50",
                        (session["driver"], CANCELLED)).to_dict("records")
    sups = supervisors_map()
    notify = None
    nid = request.args.get("notify", type=int)
    claim = next((c for c in claims_list if c["id"] == nid), None)
    if claim:
        sup = sups.get(claim["governorate"])
        notify = {"id": claim["id"], "governorate": claim["governorate"], "text": claim_message(claim),
                  "wa": bool(sup), "sup_name": sup["name"] if sup else ""}
    return render_template("d_mine.html", title="حجوزاتي", subtitle="حجوزاتك ومواعيد استلامها",
                           claims=claims_list, notify=notify, has_sup={g: True for g in sups})


@app.route("/driver/claims/<int:cid>/notify")
def d_notify(cid):
    """يسجّل الإبلاغ ثم يفتح واتساب برسالة جاهزة إلى مشرف المحافظة."""
    row = db_df("SELECT * FROM claims WHERE id = ? AND driver = ?", (cid, session["driver"]))
    if row.empty:
        return redirect(url_for("d_mine"))
    claim = row.to_dict("records")[0]
    sup = supervisors_map().get(claim["governorate"])
    if not sup:
        flash(tr("لا يوجد مشرف لمحافظة {g}").format(g=place(claim["governorate"])))
        return redirect(url_for("d_mine"))
    db_exec("UPDATE claims SET notified_at = ? WHERE id = ?", (now_oman(), cid))
    return redirect(whatsapp_link(sup["phone"], claim_message(claim)))


@app.route("/driver/claims/<int:cid>/cancel", methods=["POST"])
def d_claim_cancel(cid):
    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM claims WHERE id = ? AND driver = ? AND status = ?",
                        (cid, session["driver"], WAITING)).fetchone():
            release_claim(conn, cid)
            conn.commit()
            flash(tr("تم إلغاء الحجز ورجعت الشحنات متاحة"))
    finally:
        conn.close()
    return redirect(url_for("d_mine"))


@app.route("/driver/claims/<int:cid>/done", methods=["POST"])
def d_claim_done(cid):
    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM claims WHERE id = ? AND driver = ? AND status = ?",
                        (cid, session["driver"], PICKED)).fetchone():
            conn.execute("UPDATE shipments SET status = ?, delivered_at = ? WHERE claim_id = ? AND status = ?",
                         (DELIVERED, now_oman(), cid, CLAIMED))
            conn.execute("UPDATE claims SET status = ? WHERE id = ?", (CLAIM_DONE, cid))
            conn.commit()
            flash(tr("✅ تم تسجيل التوصيل"))
    finally:
        conn.close()
    return redirect(url_for("d_mine"))


# ----------------------------------------------------------------------
# 9) تصدير Excel
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
    sups_df = db_df('SELECT governorate AS "المحافظة", name AS "المشرف", phone AS "الهاتف" FROM supervisors')

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        places.to_excel(writer, sheet_name="الشحنات", index=False)
        claims_df.to_excel(writer, sheet_name="حجوزات المندوبين", index=False)
        drivers_df.to_excel(writer, sheet_name="المندوبين", index=False)
        sups_df.to_excel(writer, sheet_name="المشرفين", index=False)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"shipments_{today_oman()}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ----------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
