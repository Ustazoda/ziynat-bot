import os
import json
import base64
import re
import datetime
import logging
import asyncio
import secrets
import aiohttp
from zoneinfo import ZoneInfo
from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand,
    BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, FSInputFile
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

# ==========================================================
# 🕒 VAQT ZONASI — O'zbekiston vaqti (Asia/Tashkent)
# ==========================================================
TZ = ZoneInfo("Asia/Tashkent")

def now_tz() -> datetime.datetime:
    return datetime.datetime.now(TZ)

# ==========================================================
# 🔑 SOZLAMALAR
# ==========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable topilmadi! Render'ning Environment "
        "bo'limida BOT_TOKEN ni sozlang."
    )

GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1003993511736"))
JARIMALAR_THREAD_ID = int(os.getenv("JARIMALAR_THREAD_ID", "55"))
ISHGA_KELISH_THREAD_ID = int(os.getenv("ISHGA_KELISH_THREAD_ID", "1"))

GITHUB_REPO = "Ustazoda/ziynat-bot"
GITHUB_FILE_PATH = "attendance_data.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "ghp_YOUR_GITHUB_TOKEN_HERE")

bot = Bot(token=BOT_TOKEN)

BASE_WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL", "")
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or secrets.token_urlsafe(32)

BOSS_USERNAMES = {"abduvali94", "abdullayev1200", "abdullayev_12_00"}

EMPLOYEES = {
    "abdullayev1200": {
        "name": "Ma'murxon",
        "aliases": ["abdullayev1200", "abdullayev_12_00", "abdullayev", "mamurxon", "ma'murxon"],
        "work_start": (8, 20),
        "work_end": (12, 30),
        "leave_time": "20:30",
        "rates": [(10, 30000), (30, 50000), (60, 70000), (120, 100000), (270, 150000)],
        "absent": 150000,
        "active": True
    },
    "ganiboyevozodbek": {
        "name": "Ozodbek",
        "aliases": ["ganiboyevozodbek", "ganiboyev_ozodbek", "ozodbek", "𓈆1%"],
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "21:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
        "active": True
    },
    "ustazoda0125": {
        "name": "Asadbek",
        "aliases": ["ustazoda0125", "asadbek", "tizim menenjeri"],
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "18:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
        "active": True
    },
    "muhammad201207": {
        "name": "Muhammadsodiq",
        "aliases": ["muhammad201207", "umarov777777777", "muhammadsodiq"],
        "work_start": (7, 0),
        "work_end": (12, 30),
        "leave_time": "21:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 100000,
        "active": True
    },
    "murodjanovnaa_02": {
        "name": "Mubina",
        "aliases": ["murodjanovnaa_02", "muradjanovnaa_02", "mubina"],
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "18:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
        "active": True
    },
    "wsev7": {
        "name": "Gulzoda",
        "aliases": ["wsev7", "gulzoda"],
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "19:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
        "active": False
    },
    "muradjanvnam": {
        "name": "Moxinur",
        "aliases": ["muradjanvnam"],
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "19:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
        "active": False
    }
}

DEFAULT_FINE = {
    "name": "Xodim",
    "work_start": (8, 0),
    "work_end": (12, 30),
    "leave_time": "18:00",
    "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
    "absent": 120000,
}

# ==========================================================
# 📁 FAYL TIZIMI VA GITHUB SINXRONIZATSIYASI
# ==========================================================
DATA_FILE = "attendance_data.json"

def clean_str(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', str(text)).lower()

def get_employee(username: str | None, first_name: str = "") -> tuple[str, dict]:
    uname = (username or "").lower()
    fname = (first_name or "").lower()
    clean_u = clean_str(uname)
    clean_f = clean_str(fname)

    # 1. Aniq username yoki alias mosligi
    for key, data in EMPLOYEES.items():
        if uname == key or uname in data.get("aliases", []):
            return key, data

    # 2. Tozalangan matn mosligi
    for key, data in EMPLOYEES.items():
        aliases = [clean_str(a) for a in data.get("aliases", [])]
        aliases.append(clean_str(key))
        aliases.append(clean_str(data["name"]))
        
        if clean_u and any(clean_u == a or (len(clean_u) > 3 and clean_u in a) for a in aliases if a):
            return key, data
        if clean_f and any(clean_f == a or (len(clean_f) > 3 and clean_f in a) for a in aliases if a):
            return key, data

    # Anonymous admin fallback to Asadbek
    if uname == "groupanonymousbot" or fname == "group" or clean_f == "tizimmenenjeri":
        return "ustazoda0125", EMPLOYEES["ustazoda0125"]

    clean_name = username or first_name or "Xodim"
    return clean_name.lower(), DEFAULT_FINE

async def pull_from_github():
    """
    Bot ishga tushganda (yoki qayta deploy bo'lganda) Render'ning diski
    tozalanib ketishi mumkin — shu sababli GitHub'dagi eng so'nggi
    attendance_data.json faylini diskka tiklab olamiz. Buni qilmasak,
    har qayta ishga tushishda kunlik davomat ma'lumotlari yo'qolib qoladi.
    """
    if not GITHUB_TOKEN or GITHUB_TOKEN == "ghp_YOUR_GITHUB_TOKEN_HERE":
        logging.warning("GITHUB_TOKEN sozlanmagan — ma'lumotlarni tiklashning iloji yo'q.")
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    res_data = await resp.json()
                    content_b64 = res_data.get("content", "")
                    if content_b64:
                        content_bytes = base64.b64decode(content_b64)
                        with open(DATA_FILE, "wb") as f:
                            f.write(content_bytes)
                        logging.info("✅ attendance_data.json GitHub'dan muvaffaqiyatli tiklandi.")
                elif resp.status == 404:
                    logging.info("ℹ️ GitHub'da hali attendance_data.json topilmadi — yangi fayl bilan boshlanadi.")
                else:
                    logging.warning(f"⚠️ GitHub'dan o'qishda kutilmagan status: {resp.status}")
    except Exception as e:
        logging.error(f"❌ GitHub'dan tiklashda xato: {e}")

async def push_to_github():
    if not GITHUB_TOKEN or GITHUB_TOKEN == "ghp_YOUR_GITHUB_TOKEN_HERE":
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            sha = ""
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    res_data = await resp.json()
                    sha = res_data.get("sha", "")

            if not os.path.exists(DATA_FILE):
                return

            with open(DATA_FILE, "rb") as f:
                content_bytes = f.read()
                content_b64 = base64.b64encode(content_bytes).decode("utf-8")

            payload = {
                "message": "🤖 Auto-update attendance_data.json [skip render]",
                "content": content_b64,
                "branch": "main"
            }
            if sha:
                payload["sha"] = sha

            async with session.put(url, headers=headers, json=payload) as put_resp:
                if put_resp.status in [200, 201]:
                    logging.info("✅ attendance_data.json GitHub'ga muvaffaqiyatli saqlandi!")
                else:
                    logging.error(f"❌ GitHub'ga saqlashda xato: {await put_resp.text()}")
    except Exception as e:
        logging.error(f"❌ GitHub sync xatosi: {e}")

def load_db() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"attendance": {}, "requests": {}, "day_off_dates": []}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "attendance" not in data:
                data["attendance"] = {}
            if "requests" not in data:
                data["requests"] = {}
            if "day_off_dates" not in data:
                data["day_off_dates"] = []
            return data
    except Exception as e:
        logging.error(f"Fayl o'qishda xatolik: {e}")
        return {"attendance": {}, "requests": {}, "day_off_dates": []}

def save_db(data: dict):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(push_to_github())
        except RuntimeError:
            pass
    except Exception as e:
        logging.error(f"Faylga yozishda xatolik: {e}")

def db_set_record(emp_key: str, record: dict, date_str: str | None = None):
    """
    date_str berilmasa — bugungi kunga yoziladi (avvalgidek).
    date_str berilsa — o'sha kunga yoziladi (masalan, kechqurun ertangi kun
    uchun yuborilgan /sabab iltimosnomasi ERTANGI sanaga yozilishi kerak,
    aks holda kunlik hisobotlarda noto'g'ri kunga tushib qoladi).
    """
    canonical_key, emp_data = get_employee(emp_key, record.get("name", ""))

    db = load_db()
    if date_str is None:
        date_str = now_tz().strftime("%Y-%m-%d")

    if date_str not in db["attendance"]:
        db["attendance"][date_str] = {}
        
    existing = db["attendance"][date_str].get(canonical_key, {})
    existing.update(record)
    existing["name"] = emp_data["name"]
    db["attendance"][date_str][canonical_key] = existing
    save_db(db)

def db_clean_today_records():
    db = load_db()
    today_str = now_tz().strftime("%Y-%m-%d")
    if today_str not in db.get("attendance", {}):
        return

    day_data = db["attendance"][today_str]
    cleaned_day = {}

    for raw_key, rec in day_data.items():
        canonical_key, emp_data = get_employee(raw_key, rec.get("name", ""))

        rec["name"] = emp_data["name"]

        if canonical_key not in cleaned_day:
            cleaned_day[canonical_key] = rec
        else:
            existing_st = cleaned_day[canonical_key].get("status", "")
            new_st = rec.get("status", "")
            if existing_st == "absent" and new_st != "absent":
                cleaned_day[canonical_key] = rec
            elif new_st != "absent":
                cleaned_day[canonical_key].update(rec)

    db["attendance"][today_str] = cleaned_day
    save_db(db)

def db_get_today_records() -> dict:
    db_clean_today_records()
    db = load_db()
    today_str = now_tz().strftime("%Y-%m-%d")
    return db["attendance"].get(today_str, {})

# ==========================================================
# 🌴 DAM OLISH KUNLARI (endi haftalik emas — qo'lda belgilanadi)
# ==========================================================
# Avvalgi versiyada har Yakshanba avtomatik dam kuni hisoblanardi. Endi
# do'kon har kuni ishlaydi — dam kuni faqat rahbariyat /dam_olish orqali
# aniq bir sanani belgilab qo'yganda hosil bo'ladi.

def is_day_off(date_obj: datetime.date | None = None) -> bool:
    if date_obj is None:
        date_obj = now_tz().date()
    db = load_db()
    return date_obj.strftime("%Y-%m-%d") in db.get("day_off_dates", [])

def set_day_off(date_obj: datetime.date) -> bool:
    """Sanani dam kuni deb belgilaydi. Agar allaqachon belgilangan bo'lsa
    False, aks holda True qaytaradi."""
    db = load_db()
    if "day_off_dates" not in db:
        db["day_off_dates"] = []
    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str in db["day_off_dates"]:
        return False
    db["day_off_dates"].append(date_str)
    save_db(db)
    return True

def relevant_work_date(now: datetime.datetime | None = None) -> datetime.date:
    """
    /sabab so'rovi qaysi ish kuniga tegishli ekanini aniqlaydi:
    - soat 08:00 dan oldin (00:00–07:59) yuborilsa -> BUGUNGI ish kuni
    - soat 12:30 dan keyin (kechqurun) yuborilsa -> ERTANGI ish kuni
    """
    if now is None:
        now = now_tz()
    if now.time() >= datetime.time(12, 30):
        return (now + datetime.timedelta(days=1)).date()
    return now.date()

class ExcuseState(StatesGroup):
    waiting_for_reason = State()

class LateState(StatesGroup):
    waiting_for_reason = State()

dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=TZ)

def calculate_fine(employee: dict, minutes_late: int) -> int:
    rules = employee.get("rates", DEFAULT_FINE["rates"])
    for limit, price in rules:
        if minutes_late <= limit:
            return price
    return rules[-1][1]

# /id
@dp.message(Command("id"))
async def cmd_id(message: types.Message):
    user = message.from_user
    thread_info = f"🧵 <b>Mavzu ID:</b> <code>{message.message_thread_id}</code>\n" if message.message_thread_id else ""
    await message.answer(
        f"🆔 <b>Sizning ID:</b> <code>{user.id}</code>\n"
        f"👤 <b>Ism:</b> {user.full_name}\n"
        f"🔗 <b>Username:</b> @{user.username or 'yoq'}\n"
        f"💬 <b>Chat ID:</b> <code>{message.chat.id}</code>\n"
        f"{thread_info}",
        parse_mode="HTML"
    )

# /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Assalomu alaykum! 'Ziynat' do'koni nazorat botiga xush kelibsiz.\n\n"
        "Buyruqlarni ko'rish uchun yozish joyida <code>/</code> belgisini bosing.",
        parse_mode="HTML"
    )

# 📎 /fayl
@dp.message(Command("fayl"))
async def cmd_get_file(message: types.Message):
    clicker_username = (message.from_user.username or "").lower()
    if clicker_username not in BOSS_USERNAMES:
        await message.answer("❌ Bu buyruq faqat rahbarlar uchun!")
        return
        
    if os.path.exists(DATA_FILE):
        file = FSInputFile(DATA_FILE)
        await message.answer_document(file, caption="📁 Barcha kunlik va oylik davomatlar yozilgan JSON fayli.")
    else:
        await message.answer("⚠️ Hali fayl yaratilmagan.")

# 🌴 /dam_olish — endi qo'lda belgilanadigan dam kuni tizimi
@dp.message(Command("dam_olish"))
async def cmd_dam_olish(message: types.Message):
    now = now_tz()
    days = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
    today_name = days[now.weekday()]

    if is_day_off(now.date()):
        status_text = f"🌴 <b>Bugun ({today_name}) — DAM OLISH KUNI deb belgilangan!</b>\n\nBugun jarima va kechikishlar hisoblanmaydi."
    else:
        status_text = f"📅 <b>Bugun ({today_name}) — oddiy ISH KUNI.</b>\n\nEndi bizda haftalik dam kuni yo'q, har kuni ish kuni — dam kuni faqat rahbariyat quyidagi tugmalar orqali alohida belgilaganda bo'ladi."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌴 Bugun dam", callback_data="damolish_today"),
            InlineKeyboardButton(text="🌴 Ertaga dam", callback_data="damolish_tomorrow"),
        ]
    ])

    await message.answer(status_text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("damolish_"))
async def handle_dam_olish_decision(callback: types.CallbackQuery):
    clicker_username = (callback.from_user.username or "").lower()
    if clicker_username not in BOSS_USERNAMES:
        await callback.answer("❌ Dam kunini faqat rahbariyat belgilashi mumkin!", show_alert=True)
        return

    which = callback.data.split("_", 1)[1]  # "today" | "tomorrow"
    target_date = now_tz().date() if which == "today" else (now_tz().date() + datetime.timedelta(days=1))
    label = "Bugun" if which == "today" else "Ertaga"
    date_str = target_date.strftime("%d.%m.%Y")

    added = set_day_off(target_date)

    if added:
        await callback.answer(f"✅ {label} ({date_str}) dam kuni deb belgilandi.", show_alert=True)
        try:
            await callback.message.edit_text(
                f"🌴 <b>{label} ({date_str}) — DAM OLISH KUNI deb belgilandi!</b>\n\n"
                f"👑 <b>Belgilagan:</b> {callback.from_user.first_name}\n"
                f"Bu kuni jarima va kechikishlar hisoblanmaydi.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await callback.answer(f"ℹ️ {label} ({date_str}) allaqachon dam kuni deb belgilangan edi.", show_alert=True)

# 📊 /oylik
@dp.message(Command("oylik"))
async def cmd_monthly_stat(message: types.Message):
    now = now_tz()
    month_str = now.strftime("%Y-%m")

    db = load_db()
    attendance_db = db.get("attendance", {})

    stats = {}
    for k, v in EMPLOYEES.items():
        stats[k] = {
            "name": v["name"],
            "present": 0,
            "late_mins": 0,
            "fine": 0,
            "bonus": 0,
            "excused": 0,
            "absent": 0
        }

    for date_key, day_records in attendance_db.items():
        if date_key.startswith(month_str):
            for raw_key, rec in day_records.items():
                canonical_key, emp_data = get_employee(raw_key, rec.get("name", ""))

                if canonical_key not in stats:
                    stats[canonical_key] = {
                        "name": emp_data["name"],
                        "present": 0,
                        "late_mins": 0,
                        "fine": 0,
                        "bonus": 0,
                        "excused": 0,
                        "absent": 0
                    }

                st = rec.get("status", "")
                late = rec.get("late", 0)
                fine = rec.get("fine", 0)
                bonus = rec.get("bonus", 0)

                if st in ["on_time", "on_time_approved", "late"]:
                    stats[canonical_key]["present"] += 1
                    stats[canonical_key]["late_mins"] += late
                    stats[canonical_key]["fine"] += fine
                elif st == "excused_approved":
                    stats[canonical_key]["excused"] += 1
                elif st in ["excused_rejected", "late_rejected", "absent"]:
                    stats[canonical_key]["absent"] += 1
                    stats[canonical_key]["fine"] += fine

                stats[canonical_key]["bonus"] += bonus

    report = f"📊 <b>{month_str} OYLIK DAVOMAT VA MAOSH HISOBI</b>\n\n"
    
    for key, s in stats.items():
        net = s["bonus"] - s["fine"]
        net_str = f"+{net:,}" if net >= 0 else f"{net:,}"
        report += (
            f"👤 <b>{s['name']}</b> (@{key}):\n"
            f"  🟢 Ishga kelgan: <b>{s['present']} kun</b>\n"
            f"  🔵 Uzrli kelmagan: <b>{s['excused']} kun</b>\n"
            f"  🔴 Kelmagan/Rad etilgan: <b>{s['absent']} kun</b>\n"
            f"  ⏱ Jami kechikish: <b>{s['late_mins']} daqiqa</b>\n"
            f"  💸 Jami jarima: <b>{s['fine']:,} so'm</b>\n"
            f"  🎁 Jami bonus: <b>{s['bonus']:,} so'm</b>\n"
            f"  ⚖️ <b>Net balans:</b> <code>{net_str} so'm</code>\n\n"
        )

    try:
        await message.answer(report, parse_mode="HTML")
    except Exception as e:
        logging.error(f"HTML hisobotda xato: {e}")
        await message.answer(report)

# /ketish
@dp.message(Command("ketish"))
async def handle_ketish(message: types.Message):
    emp_key, emp = get_employee(message.from_user.username, message.from_user.first_name or "")
    now = now_tz()
    now_time = now.strftime("%H:%M")

    leave_h, leave_m = map(int, emp["leave_time"].split(":"))
    leave_dt = now.replace(hour=leave_h, minute=leave_m, second=0, microsecond=0)

    base_text = (
        f"🚪 <b>{emp['name']}</b> ishxonadan chiqib ketdi.\n"
        f"⏰ <b>Chiqish vaqti:</b> {now_time}\n"
        f"📌 <i>Belgilangan ketish vaqti: {emp['leave_time']}</i>\n"
    )

    rec = {"name": emp["name"], "left_at": now_time}

    if now > leave_dt:
        extra_minutes = int((now - leave_dt).total_seconds() / 60)
        bonus_sum = calculate_fine(emp, extra_minutes)
        rec["bonus"] = bonus_sum
        base_text += (
            f"\n✅ <b>Qo'shimcha ishlagan vaqt:</b> {extra_minutes} daqiqa\n"
            f"🎁 <b>Bonus miqdori:</b> {bonus_sum:,} so'm."
        )
    else:
        base_text += "\nℹ️ <i>Ish vaqti hali tugamagan, shuning uchun bonus qo'llanilmaydi.</i>"

    db_set_record(emp_key, rec)
    await message.answer(base_text, parse_mode="HTML")

# /qaytib_keldim
@dp.message(Command("qaytib_keldim"))
async def handle_qaytib_keldim(message: types.Message):
    emp_key, emp = get_employee(message.from_user.username, message.from_user.first_name or "")
    name = emp["name"]
    now_time = now_tz().strftime("%H:%M")
    await message.answer(
        f"🔄 <b>{name}</b> ishxonaga qaytib keldi.\n"
        f"⏰ <b>Qaytish vaqti:</b> {now_time}",
        parse_mode="HTML"
    )

# 📹 VIDEO NOTE / VIDEO
@dp.message(F.video | F.video_note)
async def handle_video(message: types.Message):
    username = message.from_user.username
    first_name = message.from_user.first_name or ""
    emp_key, emp = get_employee(username, first_name)
    user_name = emp["name"]

    now = now_tz()

    if is_day_off(now.date()):
        await message.answer(
            f"🌴 <b>{user_name}</b>, bugun DAM OLISH KUNI deb belgilangan!\nVideo qabul qilindi, lekin jarima va kechikishlar hisoblanmaydi.",
            parse_mode="HTML"
        )
        return

    start_h, start_m = emp.get("work_start", (8, 0))
    end_h, end_m = emp.get("work_end", (12, 30))

    work_start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    work_end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    if now > work_end:
        await message.answer(
            f"⛔ <b>{user_name}</b>, soat {end_h:02d}:{end_m:02d} dan o'tdi. Video qabul qilish to'xtatilgan!",
            parse_mode="HTML"
        )
        return

    time_str = now.strftime("%H:%M")
    records = db_get_today_records()

    if emp_key in records and records[emp_key].get("status") == "late_approved":
        allowed_until = records[emp_key].get("until_time", f"{end_h:02d}:{end_m:02d}")
        ah, am = map(int, allowed_until.split(":"))
        # "X gacha kech qolaman" desa, X:00 dan X:59 gacha ham o'z vaqtida
        # hisoblanadi — faqat X+1 daqiqadan boshlab kechikish sanaladi.
        allowed_dt = now.replace(hour=ah, minute=am, second=0, microsecond=0)
        allowed_cutoff = allowed_dt + datetime.timedelta(minutes=1)

        if now < allowed_cutoff:
            rec = {"name": user_name, "time": time_str, "late": 0, "fine": 0, "status": "on_time_approved", "until_time": allowed_until}
            db_set_record(emp_key, rec)
            await message.answer(
                f"✅ Baraka toping, <b>{user_name}</b>!\n"
                f"Ruxsat berilgan vaqtda ({time_str} da) keldingiz. Jarima qo'llanilmaydi.",
                parse_mode="HTML"
            )
            return
        else:
            late_mins = int((now - allowed_dt).total_seconds() / 60)
            fine_sum = calculate_fine(emp, late_mins)
            rec = {"name": user_name, "time": time_str, "late": late_mins, "fine": fine_sum, "status": "late"}
            db_set_record(emp_key, rec)
            await message.answer(
                f"⚠️ <b>{user_name}</b>, siz ruxsat berilgan vaqtdan ({allowed_until}) {late_mins} daqiqa kechikdingiz!\n"
                f"💸 <b>Jarima miqdori:</b> {fine_sum:,} so'm.",
                parse_mode="HTML"
            )
            return

    # Xuddi shu "daqiqa ichi hammasi o'z vaqtida" mantig'i oddiy kelish
    # vaqti uchun ham qo'llanadi (masalan ish 08:00 da boshlansa, 08:00:40
    # da kelgan xodim ham kechikkan hisoblanmasligi kerak).
    work_start_cutoff = work_start + datetime.timedelta(minutes=1)

    if now < work_start_cutoff:
        rec = {"name": user_name, "time": time_str, "late": 0, "fine": 0, "status": "on_time"}
        db_set_record(emp_key, rec)
        await message.answer(
            f"✅ Baraka toping, <b>{user_name}</b>!\nIshga o'z vaqtida keldingiz. (Vaqt: {time_str})",
            parse_mode="HTML"
        )
        return

    late_minutes = int((now - work_start).total_seconds() / 60)
    fine_sum = calculate_fine(emp, late_minutes)
    
    rec = {"name": user_name, "time": time_str, "late": late_minutes, "fine": fine_sum, "status": "late"}
    db_set_record(emp_key, rec)
    
    await message.answer(
        f"⚠️ <b>{user_name}</b>, siz bugun {late_minutes} daqiqa kechikdingiz. (Kelgan vaqtingiz: {time_str})\n"
        f"💸 <b>Jarima miqdori:</b> {fine_sum:,} so'm.",
        parse_mode="HTML"
    )

# ✍️ /sabab — endi soat 12:30 dan 07:59 gacha (kechqurun ertangi kun uchun,
# yoki ertalab bugungi kun uchun) qabul qilinadi
@dp.message(Command("sabab"))
async def start_excuse(message: types.Message, state: FSMContext):
    now = now_tz()
    target_date = relevant_work_date(now)

    in_window = (now.time() >= datetime.time(12, 30)) or (now.time() < datetime.time(8, 0))
    if not in_window:
        await message.answer(
            "⛔ <b>Sababli kelolmaslik iltimosnomasi faqat soat 12:30 dan 07:59 gacha "
            "(kechqurun yoki ertalab) qabul qilinadi.</b>",
            parse_mode="HTML"
        )
        return

    if is_day_off(target_date):
        await message.answer("🌴 Bu kun dam olish kuni deb belgilangan. Iltimosnoma yuborish shart emas!", parse_mode="HTML")
        return

    warning_text = (
        "⚠️ <b>DIQQAT! SABABLI ISHGA KELOLMASLIK BO'YICHA ILTIMOSNOMA</b>\n\n"
        "Iltimos, ishga kelolmasligingiz sababini <b>juda jiddiy yondashib, to'liq va tushunarli</b> holatda yozing.\n\n"
        "✍️ <b>Sababingizni ushbu mavzuga yozib yuboring:</b>"
    )
    warning_msg = await message.answer(warning_text, parse_mode="HTML")
    await state.update_data(
        warning_msg_id=warning_msg.message_id,
        warning_chat_id=warning_msg.chat.id,
        target_date=target_date.strftime("%Y-%m-%d"),
    )
    await state.set_state(ExcuseState.waiting_for_reason)

@dp.message(ExcuseState.waiting_for_reason)
async def send_excuse_to_group(message: types.Message, state: FSMContext):
    user_name = message.from_user.first_name or "Xodim"
    username = message.from_user.username or ""
    emp_key, emp = get_employee(username, user_name)
    reason_text = message.text

    state_data = await state.get_data()
    if state_data.get("warning_msg_id"):
        try:
            await bot.delete_message(chat_id=state_data["warning_chat_id"], message_id=state_data["warning_msg_id"])
        except Exception:
            pass

    target_date_str = state_data.get("target_date") or now_tz().strftime("%Y-%m-%d")
    req_id = f"exc_{int(datetime.datetime.now().timestamp())}"
    
    approve_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Roziman", callback_data=f"sabab_a_{req_id}"),
            InlineKeyboardButton(text="❌ Rozi emasman", callback_data=f"sabab_r_{req_id}")
        ]
    ])
    
    group_msg = (
        f"📩 <b>YANGI ILTIMOSNOMA (Sababli kelolmaslik)</b>\n\n"
        f"👤 <b>Xodim:</b> {emp['name']} (@{username})\n"
        f"📅 <b>Qaysi kun uchun:</b> {target_date_str}\n"
        f"📝 <b>Sababi:</b> {reason_text}\n\n"
        f"⚖️ <i>Qaror berish huquqi faqat rahbariyatda (Abduvali / Ma'murxon)</i>"
    )

    db = load_db()
    db["requests"][req_id] = {
        "req_type": "sabab",
        "emp_key": emp_key,
        "emp_name": emp["name"],
        "username": username,
        "reason": reason_text,
        "until_time": "",
        "work_date": target_date_str,
        "status": "pending"
    }
    save_db(db)

    await message.answer(group_msg, reply_markup=approve_keyboard, parse_mode="HTML")
    await state.clear()

# ⏰ /kech_qolish — endi soat 00:00 dan 07:59 gacha qabul qilinadi
time_picker_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="08:30", callback_data="time_08:30"), InlineKeyboardButton(text="09:00", callback_data="time_09:00"), InlineKeyboardButton(text="09:30", callback_data="time_09:30")],
    [InlineKeyboardButton(text="10:00", callback_data="time_10:00"), InlineKeyboardButton(text="10:30", callback_data="time_10:30"), InlineKeyboardButton(text="11:00", callback_data="time_11:00")],
    [InlineKeyboardButton(text="11:30", callback_data="time_11:30"), InlineKeyboardButton(text="12:00", callback_data="time_12:00")]
])

@dp.message(Command("kech_qolish"))
async def start_late_request(message: types.Message, state: FSMContext):
    now = now_tz()

    if is_day_off(now.date()):
        await message.answer("🌴 Bugun dam olish kuni deb belgilangan. Kechikishga ruxsat so'rash shart emas!", parse_mode="HTML")
        return

    if now.time() >= datetime.time(8, 0):
        await message.answer(
            "⛔ <b>Kechikishga ruxsat so'rash faqat soat 00:00 dan 07:59 gacha qabul qilinadi.</b>",
            parse_mode="HTML"
        )
        return

    msg = await message.answer(
        "⏰ <b>KECHIKISHGA RUXSAT SO'RASH</b>\n\n"
        "Iltimos, bugun soat <b>nechagacha kechikishingizni</b> pastdagi tugmalar orqali tanlang:",
        reply_markup=time_picker_keyboard,
        parse_mode="HTML"
    )
    await state.update_data(warning_msg_id=msg.message_id, warning_chat_id=msg.chat.id)

@dp.callback_query(F.data.startswith("time_"))
async def handle_time_selection(callback: types.CallbackQuery, state: FSMContext):
    selected_time = callback.data.split("_")[1]
    await state.update_data(selected_time=selected_time)
    await callback.message.edit_text(
        f"⏰ Belgilangan vaqt: <b>{selected_time}</b>\n\n"
        f"✍️ Endi kechikishingiz <b>sababini batafsil va jiddiy</b> yozib yuboring:",
        parse_mode="HTML"
    )
    await state.set_state(LateState.waiting_for_reason)
    await callback.answer()

@dp.message(LateState.waiting_for_reason)
async def send_late_request_to_group(message: types.Message, state: FSMContext):
    user_name = message.from_user.first_name or "Xodim"
    username = message.from_user.username or ""
    emp_key, emp = get_employee(username, user_name)
    reason_text = message.text
    
    data = await state.get_data()
    selected_time = data.get("selected_time", "10:00")

    if data.get("warning_msg_id"):
        try:
            await bot.delete_message(chat_id=data["warning_chat_id"], message_id=data["warning_msg_id"])
        except Exception:
            pass

    req_id = f"late_{int(datetime.datetime.now().timestamp())}"

    approve_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Roziman", callback_data=f"late_a_{req_id}"),
            InlineKeyboardButton(text="❌ Rozi emasman", callback_data=f"late_r_{req_id}")
        ]
    ])
    
    group_msg = (
        f"⏰ <b>YANGI ILTIMOSNOMA (Kech qolishga ruxsat)</b>\n\n"
        f"👤 <b>Xodim:</b> {emp['name']} (@{username})\n"
        f"🕒 <b>Kutilayotgan kelish vaqti:</b> {selected_time} gacha\n"
        f"📝 <b>Sababi:</b> {reason_text}\n\n"
        f"⚖️ <i>Qaror berish huquqi faqat rahbariyatda (Abduvali / Ma'murxon)</i>"
    )
    
    db = load_db()
    db["requests"][req_id] = {
        "req_type": "late",
        "emp_key": emp_key,
        "emp_name": emp["name"],
        "username": username,
        "reason": reason_text,
        "until_time": selected_time,
        "status": "pending"
    }
    save_db(db)

    await message.answer(group_msg, reply_markup=approve_keyboard, parse_mode="HTML")
    await state.clear()

# 👑 RAHBARLAR QARORLARI
@dp.callback_query(F.data.startswith("sabab_") | F.data.startswith("late_"))
async def handle_boss_decisions(callback: types.CallbackQuery):
    clicker_username = (callback.from_user.username or "").lower()
    
    if clicker_username not in BOSS_USERNAMES:
        await callback.answer("❌ Sizda bu qarorni qabul qilish huquqi yo'q! Qarorni faqat Abduvali yoki Ma'murxon beradi.", show_alert=True)
        return

    parts = callback.data.split("_")
    category = parts[0]
    action = parts[1]
    req_id = "_".join(parts[2:]) if len(parts) > 2 else ""

    boss_name = callback.from_user.first_name or "Rahbar"

    db = load_db()
    req_data = db.get("requests", {}).get(req_id)

    if not req_data:
        await callback.answer("⚠️ So'rov topilmadi yoki allaqachon ko'rib chiqilgan.", show_alert=True)
        return

    emp_key = req_data["emp_key"]
    emp_name = req_data["emp_name"]
    emp_username = req_data["username"]
    reason = req_data["reason"]
    until_time = req_data["until_time"]
    # "sabab" so'rovlari kechqurun ertangi kun uchun yuborilgan bo'lishi
    # mumkin — shu sababli yozuv REQUEST yaratilganda aniqlangan sanaga
    # yoziladi, qaror qabul qilingan sanaga emas.
    work_date = req_data.get("work_date")

    if category == "sabab":
        if action == "a":
            rec = {"name": emp_name, "status": "excused_approved", "boss": boss_name, "reason": reason}
            db_set_record(emp_key, rec, date_str=work_date)
            public_msg = (
                f"✅ <b>SABABLI ISHGA KELOLMASLIK (RUXSAT BERILDI)</b>\n\n"
                f"👤 <b>Xodim:</b> {emp_name} (@{emp_username})\n"
                f"👑 <b>Qaror beruvchi:</b> {boss_name}\n"
                f"📌 <b>Natija:</b> <i>Uzrli sabab deb topildi. Bugun jarima qo'llanilmaydi.</i>"
            )
            await callback.answer("✅ Iltimosnoma tasdiqlandi.", show_alert=True)
        else:
            rec = {"name": emp_name, "status": "excused_rejected", "boss": boss_name, "reason": reason}
            db_set_record(emp_key, rec, date_str=work_date)
            public_msg = (
                f"❌ <b>SABABLI ISHGA KELOLMASLIK (RAD ETILDI)</b>\n\n"
                f"👤 <b>Xodim:</b> {emp_name} (@{emp_username})\n"
                f"👑 <b>Qaror beruvchi:</b> {boss_name}\n"
                f"📌 <b>Natija:</b> <i>Sabab yetarsiz deb topildi. Belgilangan jarima qo'llaniladi.</i>"
            )
            await callback.answer("❌ Iltimosnoma rad etildi.", show_alert=True)

    elif category == "late":
        if action == "a":
            rec = {"name": emp_name, "status": "late_approved", "until_time": until_time, "boss": boss_name, "reason": reason}
            db_set_record(emp_key, rec)
            public_msg = (
                f"✅ <b>KECHIKISHGA RUXSAT BERILDI</b>\n\n"
                f"👤 <b>Xodim:</b> {emp_name} (@{emp_username})\n"
                f"⏰ <b>Ruxsat berilgan vaqt:</b> Soat {until_time} gacha\n"
                f"👑 <b>Qaror beruvchi:</b> {boss_name}\n"
                f"📌 <b>Natija:</b> <i>{until_time} gacha kelib video tashlasa jarima yozilmaydi.</i>"
            )
            await callback.answer(f"✅ {until_time} gacha ruxsat berildi.", show_alert=True)
        else:
            rec = {"name": emp_name, "status": "late_rejected", "until_time": until_time, "boss": boss_name, "reason": reason}
            db_set_record(emp_key, rec)
            public_msg = (
                f"❌ <b>KECHIKISHGA RUXSAT BERILMADI</b>\n\n"
                f"👤 <b>Xodim:</b> {emp_name} (@{emp_username})\n"
                f"⏰ <b>So'ralgan vaqt:</b> {until_time}\n"
                f"👑 <b>Qaror beruvchi:</b> {boss_name}\n"
                f"📌 <b>Natija:</b> <i>Standard kechikish jarimasi qo'llaniladi.</i>"
            )
            await callback.answer("❌ Kechikish rad etildi.", show_alert=True)

    db["requests"][req_id]["status"] = "approved" if action == "a" else "rejected"
    save_db(db)

    try:
        updated_card = callback.message.text + f"\n\n📌 <b>HUKM:</b> {'✅ TASDIQLANDI' if action == 'a' else '❌ RAD ETILDI'} ({boss_name})"
        await callback.message.edit_text(updated_card, parse_mode="HTML")
    except Exception:
        pass

    await bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=public_msg,
        message_thread_id=ISHGA_KELISH_THREAD_ID,
        parse_mode="HTML"
    )

# 📊 SOAT 12:31 DAGI KUNLIK HISOBOT
async def check_absentees_1231():
    if is_day_off(now_tz().date()):
        await bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text="🌴 <b>BUGUN DAM OLISH KUNI DEB BELGILANGAN</b>\n\nBugun do'konimizda ish kuni emas, shuning uchun davomat va jarimalar hisoblanmadi. Barchaga maroqli dam olish tilaymiz!",
            message_thread_id=JARIMALAR_THREAD_ID,
            parse_mode="HTML"
        )
        return

    records = db_get_today_records()
    present_text = []
    absent_text = []
    total_fine = 0

    for key, data in EMPLOYEES.items():
        if not data.get("active", True):
            continue

        if key in records and records[key].get("status") != "absent":
            rec = records[key]
            st = rec.get("status", "")

            if st == "on_time":
                present_text.append(f"🟢 <b>{data['name']}</b> — {rec.get('time', '')} da keldi (O'z vaqtida)")
            elif st == "on_time_approved":
                present_text.append(f"🟢 <b>{data['name']}</b> — {rec.get('time', '')} da keldi (Ruxsat berilgan vaqtda kelgan)")
            elif st == "late":
                present_text.append(f"🟡 <b>{data['name']}</b> — {rec.get('time', '')} da keldi ({rec.get('late', 0)} daqiqa kechikdi, Jarima: {rec.get('fine', 0):,} so'm)")
                total_fine += rec.get('fine', 0)
            elif st == "excused_approved":
                present_text.append(f"🔵 <b>{data['name']}</b> — Sababli kelmadi ({rec.get('boss', 'Rahbar')} tomonidan RUXSAT BERILGAN)")
        else:
            fine = data["absent"]

            st = records.get(key, {}).get("status", "")
            boss = records.get(key, {}).get("boss", "Rahbar")
            until_t = records.get(key, {}).get("until_time", "12:30")

            if st == "excused_rejected":
                absent_text.append(f"🔴 <b>{data['name']}</b> — Kelmadi (Ruxsat so'ralgan, lekin {boss} tomonidan RAD ETILGAN. Jarima: {fine:,} so'm)")
            elif st == "late_approved":
                absent_text.append(f"🔴 <b>{data['name']}</b> — {until_t} gacha ruxsat olgan edi, lekin kelmadi (Jarima: {fine:,} so'm)")
            elif st == "late_rejected":
                absent_text.append(f"🔴 <b>{data['name']}</b> — Kechikish so'ragan, lekin RAD ETILGAN va kelmadi (Jarima: {fine:,} so'm)")
            else:
                absent_text.append(f"🔴 <b>{data['name']}</b> (@{key}) — Kelmadi (Jarima: {fine:,} so'm)")

            total_fine += fine
            db_set_record(key, {"name": data["name"], "fine": fine, "status": "absent"})

    report = "📊 <b>SOAT 12:31 KUNLIK DAVOMAT VA JARIMALAR HISOBOTI</b>\n\n"

    if present_text:
        present_str = "\n".join(present_text)
        report += f"✅ <b>Ishga kelganlar va ruxsat olganlar:</b>\n{present_str}\n\n"
    else:
        report += "⚠️ <b>Bugun hech kim ishga kelmadi!</b>\n\n"

    if absent_text:
        absent_str = "\n".join(absent_text)
        report += f"❌ <b>Ishga kelmaganlar:</b>\n{absent_str}\n\n"

    report += f"💸 <b>Bugungi jami belgilanayotgan jarima:</b> {total_fine:,} so'm."

    await bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=report,
        message_thread_id=JARIMALAR_THREAD_ID,
        parse_mode="HTML"
    )

# ==========================================================
# 🌐 WEBHOOK REJIMI
# ==========================================================

async def on_startup(bot: Bot) -> None:
    # Diskdagi ma'lumot Render qayta ishga tushganda yo'qolib ketmasligi
    # uchun eng birinchi navbatda GitHub'dan tiklab olamiz.
    await pull_from_github()

    if not BASE_WEBHOOK_URL:
        logging.error("❌ BASE_WEBHOOK_URL aniqlanmadi!")
        return

    # 🤖 Bot o'zining username'ini xotiraga yuklaydi (@ziynat_nazorat_bot bo'lib kelganda ham ishlashi uchun)
    try:
        bot_info = await bot.get_me()
        logging.info(f"🤖 Bot ma'lumotlari yuklandi: @{bot_info.username}")
    except Exception as e:
        logging.error(f"Bot info yuklashda xato: {e}")

    webhook_url = f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET)
    logging.info(f"✅ Webhook o'rnatildi: {webhook_url}")

    commands = [
        BotCommand(command="kech_qolish", description="⏰ Kech qolishga ruxsat so'rash"),
        BotCommand(command="sabab", description="✍️ Kelolmaslik iltimosnomasi"),
        BotCommand(command="ketish", description="🚪 Ishxonadan chiqib ketish"),
        BotCommand(command="qaytib_keldim", description="🔄 Ishxonaga qaytib kelish"),
        BotCommand(command="oylik", description="📊 Oylik davomat va maosh hisobi"),
        BotCommand(command="dam_olish", description="🌴 Dam olish kunini belgilash / ko'rish"),
        BotCommand(command="fayl", description="📎 Barcha davomat faylini yuklab olish"),
        BotCommand(command="id", description="🆔 ID ma'lumotlarini ko'rish"),
        BotCommand(command="start", description="🤖 Botni qayta ishga tushirish")
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())

    if not scheduler.running:
        scheduler.add_job(check_absentees_1231, 'cron', hour=12, minute=31, misfire_grace_time=300)
        scheduler.start()

    print("🤖 Ziynat Nazorat Boti (webhook rejimida) muvaffaqiyatli ishga tushdi...")

async def on_shutdown(bot: Bot) -> None:
    logging.info("🧹 Bot to'xtatilmoqda...")
    try:
        await bot.delete_webhook()
    except Exception:
        pass
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    logging.info("✅ Bot xavfsiz to'xtatildi.")

def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get(
        "/",
        lambda r: web.Response(text="Ziynat Nazorat Bot ishlamoqda (webhook rejimida)!")
    )

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
