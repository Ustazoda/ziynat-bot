import os
import re
import json
import html
import base64
import asyncio
import logging
import secrets
import datetime
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand,
    BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, MenuButtonCommands
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ==========================================================
# 🕒 VAQT ZONASI — O'zbekiston vaqti (Asia/Tashkent)
# ==========================================================
TZ = ZoneInfo("Asia/Tashkent")


def now_tz() -> datetime.datetime:
    return datetime.datetime.now(TZ)


def msg_time(message: types.Message) -> datetime.datetime:
    """
    Xabarning Telegram serveriga kelgan ANIQ vaqti (Toshkent bo'yicha).

    MUHIM: avval hamma joyda now_tz() ishlatilgan edi. Render qayta ishga
    tushganda Telegram to'planib qolgan eski xabarlarni qaytadan yuboradi va
    bot ularni "hozir keldi" deb hisoblab, noto'g'ri kechikish yozib qo'yardi.
    Endi xabarning o'z vaqti olinadi.
    """
    if message.date:
        return message.date.astimezone(TZ)
    return now_tz()


def esc(text) -> str:
    """
    HTML xavfsiz matn. Xodim yozgan sabab ichida < > & belgilari bo'lsa,
    Telegram "can't parse entities" xatosi bilan xabarni umuman yubormaydi
    (ya'ni iltimosnoma rahbarga yetib bormaydi). Shuning uchun majburiy.
    """
    return html.escape(str(text if text is not None else ""), quote=False)


# ==========================================================
# 🔑 SOZLAMALAR
# ==========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable topilmadi! Render'ning Environment "
        "bo'limida BOT_TOKEN ni sozlang."
    )


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logging.warning(f"⚠️ {name} noto'g'ri formatda — standart qiymat ishlatildi: {default}")
        return default


GROUP_CHAT_ID = env_int("GROUP_CHAT_ID", -1003993511736)
JARIMALAR_THREAD_ID = env_int("JARIMALAR_THREAD_ID", 55)
ISHGA_KELISH_THREAD_ID = env_int("ISHGA_KELISH_THREAD_ID", 1)

GITHUB_REPO = os.getenv("GITHUB_REPO", "Ustazoda/ziynat-bot")
GITHUB_FILE_PATH = os.getenv("GITHUB_FILE_PATH", "attendance_data.json")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

# Kunlik hisobot vaqti (soat, daqiqa)
REPORT_HOUR = env_int("REPORT_HOUR", 12)
REPORT_MINUTE = env_int("REPORT_MINUTE", 31)

# Davomat videosi shu vaqtdan oldin qabul qilinmaydi.
# (Bazangizda soat 01:31 da yuborilgan video "o'z vaqtida" deb yozilgan —
#  shu teshikni yopadi. Kerak bo'lsa qiymatni o'zgartiring.)
EARLIEST_CHECKIN = (5, 0)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

BASE_WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL", "")
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or secrets.token_urlsafe(32)

BOSS_USERNAMES = {"abduvali94", "abdullayev1200", "abdullayev_12_00"}
# Username o'zgarib ketsa ham ishlashi uchun rahbarlarning Telegram ID sini
# ham kiritish mumkin: BOSS_IDS=123456789,987654321
BOSS_IDS = {
    int(x) for x in re.findall(r"-?\d+", os.getenv("BOSS_IDS", ""))
}

EMPLOYEES = {
    "abdullayev1200": {
        "name": "Ma'murxon",
        "aliases": ["abdullayev1200", "abdullayev_12_00", "abdullayev", "mamurxon", "ma'murxon"],
        "ids": [],
        "work_start": (8, 20),
        "work_end": (12, 30),
        "leave_time": "20:30",
        "rates": [(10, 30000), (30, 50000), (60, 70000), (120, 100000), (270, 150000)],
        "absent": 150000,
        "active": True
    },
    "ganiboyevozodbek": {
        "name": "Ozodbek",
        "aliases": ["ganiboyevozodbek", "ganiboyev_ozodbek", "ozodbek"],
        "ids": [],
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
        "ids": [],
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
        "ids": [],
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
        "ids": [],
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
        "ids": [],
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "19:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
        "active": False
    },
    "muradjanvnam": {
        "name": "Moxinur",
        "aliases": ["muradjanvnam", "moxinur"],
        "ids": [],
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
    "aliases": [],
    "ids": [],
    "work_start": (8, 0),
    "work_end": (12, 30),
    "leave_time": "18:00",
    "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
    "absent": 120000,
    "active": True
}

# Kelgan/uzrli deb hisoblanadigan statuslar
PRESENT_STATUSES = ("on_time", "on_time_approved", "late", "excused_approved")


def is_boss(user: types.User | None) -> bool:
    if user is None:
        return False
    if user.id in BOSS_IDS:
        return True
    return (user.username or "").lower() in BOSS_USERNAMES


# ==========================================================
# ⌨️ MENYU TUGMALARI (yozish joyidagi klaviatura)
# ==========================================================
BTN_KECH = "⏰ Kech qolish"
BTN_SABAB = "✍️ Sabab"
BTN_KETISH = "🚪 Ketish"
BTN_QAYTDIM = "🔄 Qaytib keldim"
BTN_OYLIK = "📊 Oylik hisob"
BTN_HISOBOT = "👁 Bugungi holat"
BTN_DAM = "🌴 Dam olish"
BTN_FAYL = "📎 Fayl"
BTN_YOPISH = "❌ Menyuni yopish"

MENU_BUTTONS = {
    BTN_KECH, BTN_SABAB, BTN_KETISH, BTN_QAYTDIM,
    BTN_OYLIK, BTN_HISOBOT, BTN_DAM, BTN_FAYL, BTN_YOPISH
}


def main_menu(boss: bool, selective: bool = True) -> ReplyKeyboardMarkup:
    """
    Yozish joyining yonidagi ⌨️ tugmasi bosilganda chiqadigan menyu.
    selective=True — klaviatura faqat so'ragan odamga ko'rinadi
    (guruhdagi qolgan xodimlarga xalaqit bermaydi).
    """
    rows = [
        [KeyboardButton(text=BTN_KECH), KeyboardButton(text=BTN_SABAB)],
        [KeyboardButton(text=BTN_KETISH), KeyboardButton(text=BTN_QAYTDIM)],
        [KeyboardButton(text=BTN_OYLIK)],
    ]
    if boss:
        rows.append([KeyboardButton(text=BTN_HISOBOT), KeyboardButton(text=BTN_DAM)])
        rows.append([KeyboardButton(text=BTN_FAYL)])
    rows.append([KeyboardButton(text=BTN_YOPISH)])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        selective=selective,
        input_field_placeholder="Kerakli bo'limni tanlang..."
    )


def cancel_button(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚫 Bekor qilish", callback_data=f"cancelfsm:{user_id}")
    ]])


# ==========================================================
# 📁 FAYL TIZIMI VA GITHUB SINXRONIZATSIYASI
# ==========================================================
DATA_FILE = "attendance_data.json"
GITHUB_ENABLED = bool(GITHUB_TOKEN) and not GITHUB_TOKEN.startswith("ghp_YOUR")

_github_lock = asyncio.Lock()
_push_event = asyncio.Event()
GITHUB_PUSH_DELAY = 4  # sekund — bir necha o'zgarishni bitta push'ga birlashtiradi


def clean_str(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', str(text)).lower()


def get_employee(username: str | None, first_name: str = "", user_id: int | None = None) -> tuple[str, dict]:
    """
    Xodimni aniqlaydi. Tartib: Telegram ID -> aniq username/alias ->
    tozalangan aniq moslik. Avvalgi versiyadagi "qismiy moslik" (clean_u in a)
    olib tashlandi — u boshqa odamni noto'g'ri xodim deb tanib, jarimani
    boshqasiga yozib yuborishi mumkin edi.
    """
    uname = (username or "").lower().lstrip("@")
    fname = (first_name or "").strip().lower()
    clean_u = clean_str(uname)
    clean_f = clean_str(fname)

    # 1. Telegram ID bo'yicha (eng ishonchli)
    if user_id:
        for key, data in EMPLOYEES.items():
            if user_id in data.get("ids", []):
                return key, data

    # 2. Aniq username yoki alias
    if uname:
        for key, data in EMPLOYEES.items():
            aliases = [str(a).lower() for a in data.get("aliases", [])]
            if uname == key or uname in aliases:
                return key, data

    # 3. Tozalangan (belgilarsiz) aniq moslik
    for key, data in EMPLOYEES.items():
        variants = {clean_str(key), clean_str(data["name"])}
        variants.update(clean_str(a) for a in data.get("aliases", []))
        variants.discard("")
        if clean_u and clean_u in variants:
            return key, data
        if clean_f and clean_f in variants:
            return key, data

    # 4. Anonim admin (guruhda "anonim" rejimda yozganda)
    if uname == "groupanonymousbot" or clean_f == "tizimmenenjeri":
        return "ustazoda0125", EMPLOYEES["ustazoda0125"]

    # 5. Ro'yxatda yo'q odam
    fallback_key = clean_u or clean_f or "xodim"
    data = dict(DEFAULT_FINE)
    data["name"] = first_name or username or "Xodim"
    return fallback_key, data


async def pull_from_github():
    """
    Render qayta deploy bo'lganda diskdagi fayl yo'qoladi — shuning uchun
    ishga tushishda GitHub'dagi eng so'nggi nusxani tiklab olamiz.
    """
    if not GITHUB_ENABLED:
        logging.warning("GITHUB_TOKEN sozlanmagan — ma'lumotlarni tiklashning iloji yo'q.")
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, params={"ref": GITHUB_BRANCH}) as resp:
                if resp.status == 200:
                    res_data = await resp.json()
                    content_b64 = res_data.get("content", "")
                    if not content_b64:
                        return
                    content_bytes = base64.b64decode(content_b64)
                    # Buzilgan faylni diskka yozib, mavjud ma'lumotni
                    # yo'q qilib yubormaslik uchun avval tekshiramiz.
                    try:
                        json.loads(content_bytes.decode("utf-8"))
                    except Exception:
                        logging.error("❌ GitHub'dagi fayl buzuq — tiklash bekor qilindi.")
                        return
                    with open(DATA_FILE, "wb") as f:
                        f.write(content_bytes)
                    logging.info("✅ attendance_data.json GitHub'dan muvaffaqiyatli tiklandi.")
                elif resp.status == 404:
                    logging.info("ℹ️ GitHub'da fayl topilmadi — yangi fayl bilan boshlanadi.")
                else:
                    logging.warning(f"⚠️ GitHub'dan o'qishda status: {resp.status}")
    except Exception as e:
        logging.error(f"❌ GitHub'dan tiklashda xato: {e}")


async def push_to_github():
    """
    Faylni GitHub'ga saqlaydi. Lock bor — avval har bir yozuvda alohida
    push ishga tushib, ular bir-biriga xalaqit berardi (409 conflict) va
    ba'zi yozuvlar yo'qolardi.
    """
    if not GITHUB_ENABLED or not os.path.exists(DATA_FILE):
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    timeout = aiohttp.ClientTimeout(total=45)

    async with _github_lock:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                with open(DATA_FILE, "rb") as f:
                    content_b64 = base64.b64encode(f.read()).decode("utf-8")

                for attempt in range(2):
                    sha = ""
                    async with session.get(url, headers=headers, params={"ref": GITHUB_BRANCH}) as resp:
                        if resp.status == 200:
                            sha = (await resp.json()).get("sha", "")

                    payload = {
                        "message": "🤖 Auto-update attendance_data.json [skip render]",
                        "content": content_b64,
                        "branch": GITHUB_BRANCH
                    }
                    if sha:
                        payload["sha"] = sha

                    async with session.put(url, headers=headers, json=payload) as put_resp:
                        if put_resp.status in (200, 201):
                            logging.info("✅ attendance_data.json GitHub'ga saqlandi.")
                            return
                        if put_resp.status == 409 and attempt == 0:
                            await asyncio.sleep(2)
                            continue
                        logging.error(f"❌ GitHub'ga saqlashda xato: {await put_resp.text()}")
                        return
        except Exception as e:
            logging.error(f"❌ GitHub sync xatosi: {e}")


async def github_push_worker():
    """O'zgarishlarni to'plab, bir necha soniyada bir marta yuboradi."""
    while True:
        try:
            await _push_event.wait()
            await asyncio.sleep(GITHUB_PUSH_DELAY)
            _push_event.clear()
            await push_to_github()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"push worker xatosi: {e}")
            await asyncio.sleep(5)


def load_db() -> dict:
    base = {"attendance": {}, "requests": {}, "day_off_dates": []}
    if not os.path.exists(DATA_FILE):
        return base
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return base
        for k, v in base.items():
            if not isinstance(data.get(k), type(v)):
                data[k] = v
        return data
    except Exception as e:
        logging.error(f"Fayl o'qishda xatolik: {e}")
        return base


def save_db(data: dict):
    """Atomik saqlash: yozish paytida bot to'xtab qolsa ham fayl buzilmaydi."""
    try:
        tmp_path = DATA_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, DATA_FILE)
    except Exception as e:
        logging.error(f"Faylga yozishda xatolik: {e}")
        return

    try:
        asyncio.get_running_loop()
        _push_event.set()
    except RuntimeError:
        pass


def db_set_record(emp_key: str, record: dict, date_str: str | None = None):
    """
    date_str berilmasa — bugungi kunga yoziladi.
    date_str berilsa — o'sha kunga (masalan kechqurun yuborilgan /sabab
    ERTANGI kunga tegishli bo'ladi).
    """
    canonical_key, emp_data = get_employee(emp_key, record.get("name", ""))

    db = load_db()
    if date_str is None:
        date_str = now_tz().strftime("%Y-%m-%d")

    day = db["attendance"].setdefault(date_str, {})
    existing = day.get(canonical_key, {})
    existing.update(record)
    existing["name"] = record.get("name") or emp_data["name"]
    day[canonical_key] = existing
    save_db(db)


def db_set_many(records: dict, date_str: str | None = None):
    """Bir nechta yozuvni BITTA saqlash bilan yozadi (kunlik hisobot uchun)."""
    if not records:
        return
    db = load_db()
    if date_str is None:
        date_str = now_tz().strftime("%Y-%m-%d")
    day = db["attendance"].setdefault(date_str, {})
    for raw_key, record in records.items():
        canonical_key, emp_data = get_employee(raw_key, record.get("name", ""))
        existing = day.get(canonical_key, {})
        existing.update(record)
        existing["name"] = record.get("name") or emp_data["name"]
        day[canonical_key] = existing
    save_db(db)


def db_clean_day_records(date_str: str):
    """
    Bir xil odamning turli kalitlar bilan yozilgan yozuvlarini birlashtiradi.
    Avval har chaqirilganda faylni qayta saqlab, keraksiz GitHub push
    qilardi — endi faqat haqiqatan o'zgarish bo'lsa saqlaydi.
    """
    db = load_db()
    day_data = db.get("attendance", {}).get(date_str)
    if not day_data:
        return

    cleaned = {}
    for raw_key, rec in day_data.items():
        canonical_key, emp_data = get_employee(raw_key, rec.get("name", ""))
        rec["name"] = rec.get("name") or emp_data["name"]

        if canonical_key not in cleaned:
            cleaned[canonical_key] = rec
        else:
            existing_st = cleaned[canonical_key].get("status", "")
            new_st = rec.get("status", "")
            if existing_st == "absent" and new_st != "absent":
                cleaned[canonical_key] = rec
            elif new_st != "absent":
                cleaned[canonical_key].update(rec)

    if cleaned != day_data:
        db["attendance"][date_str] = cleaned
        save_db(db)


def db_get_records(date_obj: datetime.date | None = None) -> dict:
    if date_obj is None:
        date_obj = now_tz().date()
    date_str = date_obj.strftime("%Y-%m-%d")
    db_clean_day_records(date_str)
    return load_db().get("attendance", {}).get(date_str, {})


def cleanup_old_requests(days: int = 60):
    """Eski iltimosnomalarni tozalab, fayl shishib ketishining oldini oladi."""
    db = load_db()
    requests = db.get("requests", {})
    if not requests:
        return
    limit_ts = datetime.datetime.now().timestamp() - days * 86400
    keep = {}
    for req_id, data in requests.items():
        m = re.search(r"(\d{9,})", req_id)
        if m and int(m.group(1)) < limit_ts:
            continue
        keep[req_id] = data
    if len(keep) != len(requests):
        db["requests"] = keep
        save_db(db)
        logging.info(f"🧹 {len(requests) - len(keep)} ta eski iltimosnoma o'chirildi.")


# ==========================================================
# 🌴 DAM OLISH KUNLARI (qo'lda belgilanadi)
# ==========================================================
def is_day_off(date_obj: datetime.date | None = None) -> bool:
    if date_obj is None:
        date_obj = now_tz().date()
    return date_obj.strftime("%Y-%m-%d") in load_db().get("day_off_dates", [])


def set_day_off(date_obj: datetime.date) -> bool:
    db = load_db()
    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str in db["day_off_dates"]:
        return False
    db["day_off_dates"].append(date_str)
    save_db(db)
    return True


def unset_day_off(date_obj: datetime.date) -> bool:
    db = load_db()
    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str not in db["day_off_dates"]:
        return False
    db["day_off_dates"] = [d for d in db["day_off_dates"] if d != date_str]
    save_db(db)
    return True


def relevant_work_date(now: datetime.datetime | None = None) -> datetime.date:
    """
    /sabab qaysi ish kuniga tegishli:
    - 00:00–07:59 yuborilsa -> BUGUNGI kun
    - 12:30 dan keyin yuborilsa -> ERTANGI kun
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
    rules = employee.get("rates") or DEFAULT_FINE["rates"]
    for limit, price in rules:
        if minutes_late <= limit:
            return price
    return rules[-1][1]


def chunk_text(text: str, limit: int = 3800) -> list[str]:
    """Telegram 4096 belgidan uzun xabarni qabul qilmaydi."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current)
    return parts


async def send_group(text: str, thread_id: int | None = None, reply_markup=None):
    """
    Guruhga yuborish. Agar mavzu (thread) topilmasa — mavzusiz qayta uriniladi,
    aks holda hisobot umuman yuborilmay qolardi.
    """
    kwargs = {}
    if thread_id and thread_id > 1:
        kwargs["message_thread_id"] = thread_id
    for chunk in chunk_text(text):
        try:
            await bot.send_message(GROUP_CHAT_ID, chunk, reply_markup=reply_markup, **kwargs)
        except TelegramBadRequest as e:
            logging.warning(f"Guruhga yuborishda xato ({e}) — mavzusiz qayta urinilmoqda.")
            try:
                await bot.send_message(GROUP_CHAT_ID, chunk, reply_markup=reply_markup)
            except Exception as e2:
                logging.error(f"Guruhga yuborib bo'lmadi: {e2}")
        except Exception as e:
            logging.error(f"Guruhga yuborib bo'lmadi: {e}")


async def answer_long(message: types.Message, text: str):
    for chunk in chunk_text(text):
        await message.answer(chunk)


# ==========================================================
# 🤖 BUYRUQLAR
# ==========================================================
@dp.message(Command("id"))
async def cmd_id(message: types.Message):
    user = message.from_user
    thread_info = (
        f"🧵 <b>Mavzu ID:</b> <code>{message.message_thread_id}</code>\n"
        if message.message_thread_id else ""
    )
    await message.answer(
        f"🆔 <b>Sizning ID:</b> <code>{user.id}</code>\n"
        f"👤 <b>Ism:</b> {esc(user.full_name)}\n"
        f"🔗 <b>Username:</b> @{esc(user.username or 'yoq')}\n"
        f"💬 <b>Chat ID:</b> <code>{message.chat.id}</code>\n"
        f"{thread_info}"
    )


async def show_menu(message: types.Message, greeting: str):
    selective = message.chat.type != "private"
    kb = main_menu(is_boss(message.from_user), selective=selective)
    # selective klaviatura ishlashi uchun xabar REPLY bo'lishi shart
    try:
        await message.reply(greeting, reply_markup=kb)
    except TelegramBadRequest:
        await message.answer(greeting, reply_markup=kb)


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await show_menu(
        message,
        "Assalomu alaykum! 'Ziynat' do'koni nazorat botiga xush kelibsiz.\n\n"
        "⌨️ Pastdagi <b>menyu tugmalari</b> orqali ishlatishingiz mumkin.\n"
        "<i>Agar tugmalar ko'rinmasa — yozish joyining o'ng tomonidagi "
        "⌨️ belgisini bosing.</i>"
    )


@dp.message(Command("menyu"))
async def cmd_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await show_menu(message, "⌨️ <b>Menyu ochildi.</b> Kerakli bo'limni tanlang:")


@dp.message(Command("bekor"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Yarim qolgan /sabab yoki /kech_qolish jarayonidan chiqish."""
    if await state.get_state() is None:
        await message.answer("ℹ️ Hozir bekor qiladigan jarayon yo'q.")
        return
    await state.clear()
    await message.answer("✅ Jarayon bekor qilindi.")


async def do_fayl(message: types.Message):
    if not is_boss(message.from_user):
        await message.answer("❌ Bu bo'lim faqat rahbarlar uchun!")
        return

    if os.path.exists(DATA_FILE):
        await message.answer_document(
            FSInputFile(DATA_FILE),
            caption="📁 Barcha kunlik va oylik davomatlar yozilgan JSON fayli."
        )
    else:
        await message.answer("⚠️ Hali fayl yaratilmagan.")


@dp.message(Command("fayl"))
async def cmd_get_file(message: types.Message):
    await do_fayl(message)


# 🌴 /dam_olish
async def do_dam_olish(message: types.Message):
    now = now_tz()
    days = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
    today_name = days[now.weekday()]
    tomorrow = now.date() + datetime.timedelta(days=1)

    today_off = is_day_off(now.date())
    tomorrow_off = is_day_off(tomorrow)

    if today_off:
        status_text = (
            f"🌴 <b>Bugun ({today_name}) — DAM OLISH KUNI deb belgilangan!</b>\n\n"
            f"Bugun jarima va kechikishlar hisoblanmaydi."
        )
    else:
        status_text = (
            f"📅 <b>Bugun ({today_name}) — oddiy ISH KUNI.</b>\n\n"
            f"Dam kuni faqat rahbariyat quyidagi tugmalar orqali belgilaganda bo'ladi."
        )
    if tomorrow_off:
        status_text += f"\n\n🌴 Ertaga ({tomorrow.strftime('%d.%m.%Y')}) ham dam kuni deb belgilangan."

    rows = [[
        InlineKeyboardButton(
            text="✅ Bugun dam" if not today_off else "🚫 Bugun dam — bekor",
            callback_data="dayoff:cancel:today" if today_off else "dayoff:set:today"
        ),
        InlineKeyboardButton(
            text="✅ Ertaga dam" if not tomorrow_off else "🚫 Ertaga dam — bekor",
            callback_data="dayoff:cancel:tomorrow" if tomorrow_off else "dayoff:set:tomorrow"
        ),
    ]]

    await message.answer(status_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.message(Command("dam_olish"))
async def cmd_dam_olish(message: types.Message):
    await do_dam_olish(message)


@dp.callback_query(F.data.startswith("dayoff:"))
async def handle_dam_olish_decision(callback: types.CallbackQuery):
    if not is_boss(callback.from_user):
        await callback.answer("❌ Dam kunini faqat rahbariyat belgilashi mumkin!", show_alert=True)
        return

    try:
        _, action, which = callback.data.split(":")
    except ValueError:
        await callback.answer("⚠️ Noto'g'ri tugma.", show_alert=True)
        return

    target_date = now_tz().date() if which == "today" else (now_tz().date() + datetime.timedelta(days=1))
    label = "Bugun" if which == "today" else "Ertaga"
    date_str = target_date.strftime("%d.%m.%Y")
    boss_name = esc(callback.from_user.first_name or "Rahbar")

    if action == "set":
        changed = set_day_off(target_date)
        text = (
            f"🌴 <b>{label} ({date_str}) — DAM OLISH KUNI deb belgilandi!</b>\n\n"
            f"👑 <b>Belgilagan:</b> {boss_name}\n"
            f"Bu kuni jarima va kechikishlar hisoblanmaydi."
        )
        alert = f"✅ {label} ({date_str}) dam kuni deb belgilandi."
    else:
        changed = unset_day_off(target_date)
        text = (
            f"📅 <b>{label} ({date_str}) — yana ODDIY ISH KUNI.</b>\n\n"
            f"👑 <b>Bekor qilgan:</b> {boss_name}"
        )
        alert = f"✅ {label} ({date_str}) dam kuni bekor qilindi."

    if not changed:
        await callback.answer("ℹ️ Bu holat allaqachon o'rnatilgan edi.", show_alert=True)
        return

    await callback.answer(alert, show_alert=True)
    try:
        await callback.message.edit_text(text)
    except Exception:
        pass


# 📊 /oylik  (ixtiyoriy: /oylik 2026-07)
async def do_monthly(message: types.Message, month_str: str = ""):
    month_str = (month_str or "").strip()
    if month_str and not re.fullmatch(r"\d{4}-\d{2}", month_str):
        await message.answer("⚠️ Format: <code>/oylik 2026-07</code>")
        return
    if not month_str:
        month_str = now_tz().strftime("%Y-%m")

    attendance_db = load_db().get("attendance", {})

    stats: dict[str, dict] = {}

    def blank(name: str) -> dict:
        return {"name": name, "present": 0, "late_mins": 0, "fine": 0,
                "bonus": 0, "excused": 0, "absent": 0}

    for date_key, day_records in attendance_db.items():
        if not date_key.startswith(month_str):
            continue
        for raw_key, rec in day_records.items():
            canonical_key, emp_data = get_employee(raw_key, rec.get("name", ""))
            s = stats.setdefault(canonical_key, blank(rec.get("name") or emp_data["name"]))

            st = rec.get("status", "")
            if st in ("on_time", "on_time_approved", "late"):
                s["present"] += 1
                s["late_mins"] += rec.get("late", 0)
                s["fine"] += rec.get("fine", 0)
            elif st == "excused_approved":
                s["excused"] += 1
            elif st in ("excused_rejected", "late_rejected", "late_approved", "absent"):
                s["absent"] += 1
                s["fine"] += rec.get("fine", 0)
            s["bonus"] += rec.get("bonus", 0)

    if not stats:
        await message.answer(f"ℹ️ <b>{month_str}</b> oyi uchun hali ma'lumot yo'q.")
        return

    order = list(EMPLOYEES.keys())
    sorted_keys = sorted(stats.keys(), key=lambda k: order.index(k) if k in order else 999)

    report = f"📊 <b>{month_str} OYLIK DAVOMAT VA MAOSH HISOBI</b>\n\n"
    total_fine = total_bonus = 0

    for key in sorted_keys:
        s = stats[key]
        net = s["bonus"] - s["fine"]
        total_fine += s["fine"]
        total_bonus += s["bonus"]
        net_str = f"+{net:,}" if net >= 0 else f"{net:,}"
        report += (
            f"👤 <b>{esc(s['name'])}</b> (@{esc(key)}):\n"
            f"  🟢 Ishga kelgan: <b>{s['present']} kun</b>\n"
            f"  🔵 Uzrli kelmagan: <b>{s['excused']} kun</b>\n"
            f"  🔴 Kelmagan/Rad etilgan: <b>{s['absent']} kun</b>\n"
            f"  ⏱ Jami kechikish: <b>{s['late_mins']} daqiqa</b>\n"
            f"  💸 Jami jarima: <b>{s['fine']:,} so'm</b>\n"
            f"  🎁 Jami bonus: <b>{s['bonus']:,} so'm</b>\n"
            f"  ⚖️ <b>Net balans:</b> <code>{net_str} so'm</code>\n\n"
        )

    report += (
        f"━━━━━━━━━━━━━━━\n"
        f"💸 <b>Oylik umumiy jarima:</b> {total_fine:,} so'm\n"
        f"🎁 <b>Oylik umumiy bonus:</b> {total_bonus:,} so'm"
    )

    await answer_long(message, report)


@dp.message(Command("oylik"))
async def cmd_monthly_stat(message: types.Message, command: CommandObject):
    await do_monthly(message, command.args or "")


# 🚪 /ketish
async def do_ketish(message: types.Message):
    emp_key, emp = get_employee(
        message.from_user.username, message.from_user.first_name or "", message.from_user.id
    )
    now = msg_time(message)
    now_time = now.strftime("%H:%M")

    leave_h, leave_m = map(int, emp["leave_time"].split(":"))
    leave_dt = now.replace(hour=leave_h, minute=leave_m, second=0, microsecond=0)

    base_text = (
        f"🚪 <b>{esc(emp['name'])}</b> ishxonadan chiqib ketdi.\n"
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

    db_set_record(emp_key, rec, date_str=now.strftime("%Y-%m-%d"))
    await message.answer(base_text)


@dp.message(Command("ketish"))
async def cmd_ketish(message: types.Message):
    await do_ketish(message)


# 🔄 /qaytib_keldim
async def do_qaytib_keldim(message: types.Message):
    emp_key, emp = get_employee(
        message.from_user.username, message.from_user.first_name or "", message.from_user.id
    )
    now = msg_time(message)
    now_time = now.strftime("%H:%M")
    db_set_record(emp_key, {"name": emp["name"], "returned_at": now_time},
                  date_str=now.strftime("%Y-%m-%d"))
    await message.answer(
        f"🔄 <b>{esc(emp['name'])}</b> ishxonaga qaytib keldi.\n"
        f"⏰ <b>Qaytish vaqti:</b> {now_time}"
    )


@dp.message(Command("qaytib_keldim"))
async def cmd_qaytib_keldim(message: types.Message):
    await do_qaytib_keldim(message)


# ==========================================================
# 📹 DAVOMAT VIDEOSI
# ==========================================================
@dp.message(F.video | F.video_note)
async def handle_video(message: types.Message):
    # Shaxsiy chatda yuborilgan video davomat sifatida qabul qilinmaydi —
    # aks holda hech kim ko'rmagan holda "keldim" deb belgilab qo'yish mumkin.
    if message.chat.type == "private":
        await message.answer(
            "ℹ️ Davomat videosi <b>ishchi guruhga</b> yuborilishi kerak, shaxsiy chatga emas."
        )
        return

    emp_key, emp = get_employee(
        message.from_user.username, message.from_user.first_name or "", message.from_user.id
    )
    user_name = emp["name"]
    now = msg_time(message)
    today = now.date()
    date_str = today.strftime("%Y-%m-%d")

    if is_day_off(today):
        await message.answer(
            f"🌴 <b>{esc(user_name)}</b>, bugun DAM OLISH KUNI deb belgilangan!\n"
            f"Video qabul qilindi, lekin jarima va kechikishlar hisoblanmaydi."
        )
        return

    records = db_get_records(today)
    existing = records.get(emp_key, {})

    # Takroriy video: birinchi kelgan vaqt saqlanib qoladi.
    # (Avval ikkinchi video birinchisini o'chirib, xodimni noto'g'ri
    #  kechikkan deb jarimaga tortishi mumkin edi.)
    if existing.get("time"):
        await message.answer(
            f"ℹ️ <b>{esc(user_name)}</b>, siz bugun allaqachon "
            f"<b>{existing.get('time')}</b> da belgilangansiz. Takroriy video hisobga olinmaydi."
        )
        return

    start_h, start_m = emp.get("work_start", (8, 0))
    end_h, end_m = emp.get("work_end", (12, 30))

    work_start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    work_end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    earliest = now.replace(hour=EARLIEST_CHECKIN[0], minute=EARLIEST_CHECKIN[1],
                           second=0, microsecond=0)

    if now < earliest:
        await message.answer(
            f"⏳ <b>{esc(user_name)}</b>, davomat videosi soat "
            f"{EARLIEST_CHECKIN[0]:02d}:{EARLIEST_CHECKIN[1]:02d} dan boshlab qabul qilinadi."
        )
        return

    if now > work_end:
        await message.answer(
            f"⛔ <b>{esc(user_name)}</b>, soat {end_h:02d}:{end_m:02d} dan o'tdi. "
            f"Video qabul qilish to'xtatilgan!"
        )
        return

    time_str = now.strftime("%H:%M")

    # 1) Rahbariyat kechikishga ruxsat bergan bo'lsa
    if existing.get("status") == "late_approved":
        allowed_until = existing.get("until_time") or f"{end_h:02d}:{end_m:02d}"
        try:
            ah, am = map(int, allowed_until.split(":"))
        except ValueError:
            ah, am = end_h, end_m
            allowed_until = f"{end_h:02d}:{end_m:02d}"

        allowed_dt = now.replace(hour=ah, minute=am, second=0, microsecond=0)
        # "X gacha" degani X:00–X:59 emas, X daqiqasining oxirigacha.
        allowed_cutoff = allowed_dt + datetime.timedelta(minutes=1)

        if now < allowed_cutoff:
            db_set_record(emp_key, {
                "name": user_name, "time": time_str, "late": 0, "fine": 0,
                "status": "on_time_approved", "until_time": allowed_until
            }, date_str=date_str)
            await message.answer(
                f"✅ Baraka toping, <b>{esc(user_name)}</b>!\n"
                f"Ruxsat berilgan vaqtda ({time_str} da) keldingiz. Jarima qo'llanilmaydi."
            )
        else:
            late_mins = int((now - allowed_dt).total_seconds() / 60)
            fine_sum = calculate_fine(emp, late_mins)
            db_set_record(emp_key, {
                "name": user_name, "time": time_str, "late": late_mins,
                "fine": fine_sum, "status": "late"
            }, date_str=date_str)
            await message.answer(
                f"⚠️ <b>{esc(user_name)}</b>, siz ruxsat berilgan vaqtdan "
                f"({allowed_until}) {late_mins} daqiqa kechikdingiz!\n"
                f"💸 <b>Jarima miqdori:</b> {fine_sum:,} so'm."
            )
        return

    # 2) Oddiy kelish
    work_start_cutoff = work_start + datetime.timedelta(minutes=1)
    if now < work_start_cutoff:
        db_set_record(emp_key, {
            "name": user_name, "time": time_str, "late": 0, "fine": 0, "status": "on_time"
        }, date_str=date_str)
        await message.answer(
            f"✅ Baraka toping, <b>{esc(user_name)}</b>!\n"
            f"Ishga o'z vaqtida keldingiz. (Vaqt: {time_str})"
        )
        return

    late_minutes = int((now - work_start).total_seconds() / 60)
    fine_sum = calculate_fine(emp, late_minutes)
    db_set_record(emp_key, {
        "name": user_name, "time": time_str, "late": late_minutes,
        "fine": fine_sum, "status": "late"
    }, date_str=date_str)
    await message.answer(
        f"⚠️ <b>{esc(user_name)}</b>, siz bugun {late_minutes} daqiqa kechikdingiz. "
        f"(Kelgan vaqtingiz: {time_str})\n"
        f"💸 <b>Jarima miqdori:</b> {fine_sum:,} so'm."
    )


# ==========================================================
# ✍️ /sabab — 12:30 dan 07:59 gacha
# ==========================================================
async def deliver_request_card(message: types.Message, text: str, keyboard: InlineKeyboardMarkup):
    """Iltimosnoma kartasi har doim rahbarlar ko'radigan joyga tushishi kerak."""
    if message.chat.id == GROUP_CHAT_ID:
        await message.answer(text, reply_markup=keyboard)
    else:
        await send_group(text, thread_id=ISHGA_KELISH_THREAD_ID, reply_markup=keyboard)
        await message.answer("✅ Iltimosnomangiz rahbariyatga yuborildi. Javobini kuting.")


async def do_sabab(message: types.Message, state: FSMContext):
    now = msg_time(message)
    target_date = relevant_work_date(now)

    in_window = (now.time() >= datetime.time(12, 30)) or (now.time() < datetime.time(8, 0))
    if not in_window:
        await message.answer(
            "⛔ <b>Sababli kelolmaslik iltimosnomasi faqat soat 12:30 dan 07:59 gacha "
            "(kechqurun yoki ertalab) qabul qilinadi.</b>"
        )
        return

    if is_day_off(target_date):
        await message.answer("🌴 Bu kun dam olish kuni deb belgilangan. Iltimosnoma yuborish shart emas!")
        return

    warning_msg = await message.answer(
        "⚠️ <b>DIQQAT! SABABLI ISHGA KELOLMASLIK BO'YICHA ILTIMOSNOMA</b>\n\n"
        f"📅 <b>Qaysi kun uchun:</b> {target_date.strftime('%d.%m.%Y')}\n\n"
        "Iltimos, ishga kelolmasligingiz sababini <b>to'liq va tushunarli</b> yozing.\n\n"
        "✍️ <b>Sababingizni shu yerga yozib yuboring:</b>",
        reply_markup=cancel_button(message.from_user.id)
    )
    await state.update_data(
        warning_msg_id=warning_msg.message_id,
        warning_chat_id=warning_msg.chat.id,
        target_date=target_date.strftime("%Y-%m-%d"),
    )
    await state.set_state(ExcuseState.waiting_for_reason)


@dp.message(Command("sabab"))
async def cmd_sabab(message: types.Message, state: FSMContext):
    await do_sabab(message, state)


# ==========================================================
# ⌨️ MENYU TUGMALARINI QAYTA ISHLASH
# Bu handler FSM holatlaridan OLDIN turishi shart — aks holda xodim
# "sabab yozish" holatida turganda bosgan tugmasi sabab matni deb
# yuborilib ketardi.
# ==========================================================
@dp.message(F.text.in_(MENU_BUTTONS))
async def handle_menu_buttons(message: types.Message, state: FSMContext):
    text = message.text
    await state.clear()

    if text == BTN_KECH:
        await do_kech_qolish(message, state)
    elif text == BTN_SABAB:
        await do_sabab(message, state)
    elif text == BTN_KETISH:
        await do_ketish(message)
    elif text == BTN_QAYTDIM:
        await do_qaytib_keldim(message)
    elif text == BTN_OYLIK:
        await do_monthly(message)
    elif text == BTN_HISOBOT:
        await do_hisobot(message)
    elif text == BTN_DAM:
        if not is_boss(message.from_user):
            await message.answer("❌ Bu bo'lim faqat rahbarlar uchun!")
        else:
            await do_dam_olish(message)
    elif text == BTN_FAYL:
        await do_fayl(message)
    elif text == BTN_YOPISH:
        selective = message.chat.type != "private"
        try:
            await message.reply(
                "✅ Menyu yopildi. Qayta ochish uchun /menyu buyrug'ini yuboring.",
                reply_markup=ReplyKeyboardRemove(selective=selective)
            )
        except TelegramBadRequest:
            await message.answer(
                "✅ Menyu yopildi. Qayta ochish uchun /menyu buyrug'ini yuboring.",
                reply_markup=ReplyKeyboardRemove()
            )


@dp.callback_query(F.data.startswith("cancelfsm:"))
async def handle_cancel_fsm(callback: types.CallbackQuery, state: FSMContext):
    try:
        owner_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("⚠️ Noto'g'ri tugma.", show_alert=True)
        return

    if callback.from_user.id != owner_id:
        await callback.answer("❌ Bu so'rov sizniki emas!", show_alert=True)
        return

    await state.clear()
    await callback.answer("✅ Bekor qilindi.")
    try:
        await callback.message.edit_text("🚫 <b>Jarayon bekor qilindi.</b>")
    except Exception:
        pass


@dp.message(ExcuseState.waiting_for_reason)
async def send_excuse_to_group(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/"):
        await message.answer("✍️ Iltimos, sababni <b>oddiy matn</b> ko'rinishida yozing yoki /bekor bosing.")
        return

    emp_key, emp = get_employee(
        message.from_user.username, message.from_user.first_name or "", message.from_user.id
    )
    username = message.from_user.username or ""
    reason_text = message.text.strip()

    data = await state.get_data()
    await state.clear()

    if data.get("warning_msg_id"):
        try:
            await bot.delete_message(chat_id=data["warning_chat_id"], message_id=data["warning_msg_id"])
        except Exception:
            pass

    target_date_str = data.get("target_date") or now_tz().strftime("%Y-%m-%d")
    req_id = f"exc_{int(datetime.datetime.now().timestamp())}_{secrets.token_hex(2)}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Roziman", callback_data=f"dec:sabab:a:{req_id}"),
        InlineKeyboardButton(text="❌ Rozi emasman", callback_data=f"dec:sabab:r:{req_id}")
    ]])

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

    group_msg = (
        f"📩 <b>YANGI ILTIMOSNOMA (Sababli kelolmaslik)</b>\n\n"
        f"👤 <b>Xodim:</b> {esc(emp['name'])} (@{esc(username or 'yoq')})\n"
        f"📅 <b>Qaysi kun uchun:</b> {target_date_str}\n"
        f"📝 <b>Sababi:</b> {esc(reason_text)}\n\n"
        f"⚖️ <i>Qaror berish huquqi faqat rahbariyatda (Abduvali / Ma'murxon)</i>"
    )
    await deliver_request_card(message, group_msg, keyboard)


# ==========================================================
# ⏰ /kech_qolish — 00:00 dan 07:59 gacha
# ==========================================================
def build_time_picker(user_id: int) -> InlineKeyboardMarkup:
    """
    Tugmaga so'rov egasining ID si yoziladi — avval guruhdagi istalgan odam
    tugmani bosib, boshqa odamning so'rovini "o'g'irlab" ketishi mumkin edi.
    """
    times = ["08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00"]
    rows, row = [], []
    for t in times:
        row.append(InlineKeyboardButton(
            text=t, callback_data=f"latetime:{user_id}:{t.replace(':', '')}"
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        text="🚫 Bekor qilish", callback_data=f"cancelfsm:{user_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def do_kech_qolish(message: types.Message, state: FSMContext):
    now = msg_time(message)

    if is_day_off(now.date()):
        await message.answer("🌴 Bugun dam olish kuni deb belgilangan. Kechikishga ruxsat so'rash shart emas!")
        return

    if now.time() >= datetime.time(8, 0):
        await message.answer(
            "⛔ <b>Kechikishga ruxsat so'rash faqat soat 00:00 dan 07:59 gacha qabul qilinadi.</b>"
        )
        return

    msg = await message.answer(
        "⏰ <b>KECHIKISHGA RUXSAT SO'RASH</b>\n\n"
        "Iltimos, bugun soat <b>nechagacha kechikishingizni</b> pastdagi tugmalar orqali tanlang:",
        reply_markup=build_time_picker(message.from_user.id)
    )
    await state.update_data(warning_msg_id=msg.message_id, warning_chat_id=msg.chat.id)


@dp.message(Command("kech_qolish"))
async def cmd_kech_qolish(message: types.Message, state: FSMContext):
    await do_kech_qolish(message, state)


@dp.callback_query(F.data.startswith("latetime:"))
async def handle_time_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, owner_id, raw_time = callback.data.split(":")
        owner_id = int(owner_id)
    except ValueError:
        await callback.answer("⚠️ Noto'g'ri tugma.", show_alert=True)
        return

    if callback.from_user.id != owner_id:
        await callback.answer("❌ Bu so'rov sizniki emas!", show_alert=True)
        return

    selected_time = f"{raw_time[:2]}:{raw_time[2:]}"
    await state.update_data(selected_time=selected_time)
    await callback.message.edit_text(
        f"⏰ Belgilangan vaqt: <b>{selected_time}</b>\n\n"
        f"✍️ Endi kechikishingiz <b>sababini batafsil</b> yozib yuboring:",
        reply_markup=cancel_button(owner_id)
    )
    await state.set_state(LateState.waiting_for_reason)
    await callback.answer()


@dp.message(LateState.waiting_for_reason)
async def send_late_request_to_group(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/"):
        await message.answer("✍️ Iltimos, sababni <b>oddiy matn</b> ko'rinishida yozing yoki /bekor bosing.")
        return

    emp_key, emp = get_employee(
        message.from_user.username, message.from_user.first_name or "", message.from_user.id
    )
    username = message.from_user.username or ""
    reason_text = message.text.strip()

    data = await state.get_data()
    await state.clear()
    selected_time = data.get("selected_time", "10:00")

    if data.get("warning_msg_id"):
        try:
            await bot.delete_message(chat_id=data["warning_chat_id"], message_id=data["warning_msg_id"])
        except Exception:
            pass

    req_id = f"late_{int(datetime.datetime.now().timestamp())}_{secrets.token_hex(2)}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Roziman", callback_data=f"dec:late:a:{req_id}"),
        InlineKeyboardButton(text="❌ Rozi emasman", callback_data=f"dec:late:r:{req_id}")
    ]])

    db = load_db()
    db["requests"][req_id] = {
        "req_type": "late",
        "emp_key": emp_key,
        "emp_name": emp["name"],
        "username": username,
        "reason": reason_text,
        "until_time": selected_time,
        "work_date": msg_time(message).strftime("%Y-%m-%d"),
        "status": "pending"
    }
    save_db(db)

    group_msg = (
        f"⏰ <b>YANGI ILTIMOSNOMA (Kech qolishga ruxsat)</b>\n\n"
        f"👤 <b>Xodim:</b> {esc(emp['name'])} (@{esc(username or 'yoq')})\n"
        f"🕒 <b>Kutilayotgan kelish vaqti:</b> {selected_time} gacha\n"
        f"📝 <b>Sababi:</b> {esc(reason_text)}\n\n"
        f"⚖️ <i>Qaror berish huquqi faqat rahbariyatda (Abduvali / Ma'murxon)</i>"
    )
    await deliver_request_card(message, group_msg, keyboard)


# ==========================================================
# 👑 RAHBARLAR QARORLARI
# ==========================================================
@dp.callback_query(F.data.startswith("dec:"))
async def handle_boss_decisions(callback: types.CallbackQuery):
    if not is_boss(callback.from_user):
        await callback.answer(
            "❌ Sizda bu qarorni qabul qilish huquqi yo'q! Qarorni faqat Abduvali yoki Ma'murxon beradi.",
            show_alert=True
        )
        return

    try:
        _, category, action, req_id = callback.data.split(":", 3)
    except ValueError:
        await callback.answer("⚠️ Noto'g'ri tugma.", show_alert=True)
        return

    boss_name = callback.from_user.first_name or "Rahbar"

    db = load_db()
    req_data = db.get("requests", {}).get(req_id)

    if not req_data:
        await callback.answer("⚠️ So'rov topilmadi.", show_alert=True)
        return

    # Ikki marta bosilishidan himoya
    if req_data.get("status") != "pending":
        await callback.answer("ℹ️ Bu so'rov bo'yicha qaror allaqachon qabul qilingan.", show_alert=True)
        return

    emp_key = req_data["emp_key"]
    emp_name = req_data["emp_name"]
    emp_username = req_data.get("username") or "yoq"
    reason = req_data.get("reason", "")
    until_time = req_data.get("until_time", "")
    work_date = req_data.get("work_date")

    if category == "sabab":
        status = "excused_approved" if action == "a" else "excused_rejected"
        db_set_record(
            emp_key,
            {"name": emp_name, "status": status, "boss": boss_name, "reason": reason},
            date_str=work_date
        )
        if action == "a":
            public_msg = (
                f"✅ <b>SABABLI ISHGA KELOLMASLIK (RUXSAT BERILDI)</b>\n\n"
                f"👤 <b>Xodim:</b> {esc(emp_name)} (@{esc(emp_username)})\n"
                f"📅 <b>Kun:</b> {work_date}\n"
                f"👑 <b>Qaror beruvchi:</b> {esc(boss_name)}\n"
                f"📌 <b>Natija:</b> <i>Uzrli sabab deb topildi. Jarima qo'llanilmaydi.</i>"
            )
            await callback.answer("✅ Iltimosnoma tasdiqlandi.", show_alert=True)
        else:
            public_msg = (
                f"❌ <b>SABABLI ISHGA KELOLMASLIK (RAD ETILDI)</b>\n\n"
                f"👤 <b>Xodim:</b> {esc(emp_name)} (@{esc(emp_username)})\n"
                f"📅 <b>Kun:</b> {work_date}\n"
                f"👑 <b>Qaror beruvchi:</b> {esc(boss_name)}\n"
                f"📌 <b>Natija:</b> <i>Sabab yetarsiz deb topildi. Belgilangan jarima qo'llaniladi.</i>"
            )
            await callback.answer("❌ Iltimosnoma rad etildi.", show_alert=True)

    else:  # late
        status = "late_approved" if action == "a" else "late_rejected"
        db_set_record(
            emp_key,
            {"name": emp_name, "status": status, "until_time": until_time,
             "boss": boss_name, "reason": reason},
            date_str=work_date
        )
        if action == "a":
            public_msg = (
                f"✅ <b>KECHIKISHGA RUXSAT BERILDI</b>\n\n"
                f"👤 <b>Xodim:</b> {esc(emp_name)} (@{esc(emp_username)})\n"
                f"⏰ <b>Ruxsat berilgan vaqt:</b> Soat {until_time} gacha\n"
                f"👑 <b>Qaror beruvchi:</b> {esc(boss_name)}\n"
                f"📌 <b>Natija:</b> <i>{until_time} gacha kelib video tashlasa jarima yozilmaydi.</i>"
            )
            await callback.answer(f"✅ {until_time} gacha ruxsat berildi.", show_alert=True)
        else:
            public_msg = (
                f"❌ <b>KECHIKISHGA RUXSAT BERILMADI</b>\n\n"
                f"👤 <b>Xodim:</b> {esc(emp_name)} (@{esc(emp_username)})\n"
                f"⏰ <b>So'ralgan vaqt:</b> {until_time}\n"
                f"👑 <b>Qaror beruvchi:</b> {esc(boss_name)}\n"
                f"📌 <b>Natija:</b> <i>Standart kechikish jarimasi qo'llaniladi.</i>"
            )
            await callback.answer("❌ Kechikish rad etildi.", show_alert=True)

    db = load_db()
    if req_id in db.get("requests", {}):
        db["requests"][req_id]["status"] = "approved" if action == "a" else "rejected"
        db["requests"][req_id]["boss"] = boss_name
        save_db(db)

    try:
        # html_text — matn ichidagi <b> formatlashni saqlab qoladi.
        original = callback.message.html_text or callback.message.text or ""
        verdict = "✅ TASDIQLANDI" if action == "a" else "❌ RAD ETILDI"
        await callback.message.edit_text(
            f"{original}\n\n📌 <b>HUKM:</b> {verdict} ({esc(boss_name)})"
        )
    except Exception:
        pass

    await send_group(public_msg, thread_id=ISHGA_KELISH_THREAD_ID)


# ==========================================================
# 📊 KUNLIK HISOBOT
# ==========================================================
def build_daily_report(records: dict, date_obj: datetime.date) -> tuple[str, dict]:
    """
    Hisobot matnini va jarima yoziladigan yozuvlarni qaytaradi.

    ESKI XATO: kelmagan xodimlar "else" bo'limida tekshirilardi, lekin
    late_approved / excused_rejected / late_rejected statuslari "absent"
    emasligi uchun birinchi shartga tushib ketardi va hech qaysi elif ga
    mos kelmasdi — natijada bunday xodimlar hisobotda umuman ko'rinmasdi
    va jarima ham yozilmasdi. Endi tekshiruv status bo'yicha aniq.
    """
    present_text, absent_text = [], []
    total_fine = 0
    to_write: dict[str, dict] = {}

    for key, data in EMPLOYEES.items():
        if not data.get("active", True):
            continue

        rec = records.get(key, {})
        st = rec.get("status", "")
        name = esc(data["name"])

        if st == "on_time":
            present_text.append(f"🟢 <b>{name}</b> — {rec.get('time', '')} da keldi (O'z vaqtida)")
        elif st == "on_time_approved":
            present_text.append(f"🟢 <b>{name}</b> — {rec.get('time', '')} da keldi (Ruxsat berilgan vaqtda)")
        elif st == "late":
            fine = rec.get("fine", 0)
            total_fine += fine
            present_text.append(
                f"🟡 <b>{name}</b> — {rec.get('time', '')} da keldi "
                f"({rec.get('late', 0)} daqiqa kechikdi, Jarima: {fine:,} so'm)"
            )
        elif st == "excused_approved":
            present_text.append(
                f"🔵 <b>{name}</b> — Sababli kelmadi "
                f"({esc(rec.get('boss', 'Rahbar'))} tomonidan RUXSAT BERILGAN)"
            )
        else:
            fine = data["absent"]
            boss = esc(rec.get("boss", "Rahbar"))
            until_t = rec.get("until_time", "")

            if st == "excused_rejected":
                absent_text.append(
                    f"🔴 <b>{name}</b> — Kelmadi (Ruxsat so'ralgan, lekin {boss} tomonidan "
                    f"RAD ETILGAN. Jarima: {fine:,} so'm)"
                )
            elif st == "late_approved":
                absent_text.append(
                    f"🔴 <b>{name}</b> — {until_t or '—'} gacha ruxsat olgan edi, lekin kelmadi "
                    f"(Jarima: {fine:,} so'm)"
                )
            elif st == "late_rejected":
                absent_text.append(
                    f"🔴 <b>{name}</b> — Kechikish so'ragan, RAD ETILGAN va kelmadi "
                    f"(Jarima: {fine:,} so'm)"
                )
            else:
                absent_text.append(f"🔴 <b>{name}</b> (@{esc(key)}) — Kelmadi (Jarima: {fine:,} so'm)")

            total_fine += fine
            new_rec = dict(rec)
            new_rec.update({"name": data["name"], "fine": fine, "status": st or "absent"})
            to_write[key] = new_rec

    # Ro'yxatda yo'q, lekin video tashlagan odamlar ham ko'rinsin
    for key, rec in records.items():
        if key in EMPLOYEES:
            continue
        if rec.get("status") in PRESENT_STATUSES:
            present_text.append(
                f"⚪️ <b>{esc(rec.get('name', key))}</b> — {rec.get('time', '')} da keldi "
                f"(ro'yxatda yo'q)"
            )

    report = (
        f"📊 <b>KUNLIK DAVOMAT VA JARIMALAR HISOBOTI</b>\n"
        f"📅 <b>Sana:</b> {date_obj.strftime('%d.%m.%Y')}\n\n"
    )
    if present_text:
        report += "✅ <b>Ishga kelganlar va ruxsat olganlar:</b>\n" + "\n".join(present_text) + "\n\n"
    else:
        report += "⚠️ <b>Bugun hech kim ishga kelmadi!</b>\n\n"

    if absent_text:
        report += "❌ <b>Ishga kelmaganlar:</b>\n" + "\n".join(absent_text) + "\n\n"

    report += f"💸 <b>Bugungi jami belgilanayotgan jarima:</b> {total_fine:,} so'm."
    return report, to_write


async def check_absentees_daily():
    try:
        today = now_tz().date()

        if is_day_off(today):
            await send_group(
                "🌴 <b>BUGUN DAM OLISH KUNI DEB BELGILANGAN</b>\n\n"
                "Bugun davomat va jarimalar hisoblanmadi. Barchaga maroqli dam olish tilaymiz!",
                thread_id=JARIMALAR_THREAD_ID
            )
            return

        records = db_get_records(today)
        report, to_write = build_daily_report(records, today)
        db_set_many(to_write, date_str=today.strftime("%Y-%m-%d"))
        await send_group(report, thread_id=JARIMALAR_THREAD_ID)
        logging.info("✅ Kunlik hisobot yuborildi.")
    except Exception as e:
        logging.exception(f"❌ Kunlik hisobotda xato: {e}")


async def do_hisobot(message: types.Message):
    """Rahbarlar uchun: hozirgi holatni ko'rish (jarima YOZILMAYDI)."""
    if not is_boss(message.from_user):
        await message.answer("❌ Bu bo'lim faqat rahbarlar uchun!")
        return

    today = now_tz().date()
    if is_day_off(today):
        await message.answer("🌴 Bugun dam olish kuni deb belgilangan.")
        return

    report, _ = build_daily_report(db_get_records(today), today)
    await answer_long(
        message,
        "👁 <b>ORALIQ KO'RINISH (jarimalar hali yozilmadi)</b>\n\n" + report
    )


@dp.message(Command("hisobot"))
async def cmd_report_preview(message: types.Message):
    await do_hisobot(message)


# ==========================================================
# 🌐 WEBHOOK REJIMI
# ==========================================================
_push_task: asyncio.Task | None = None


async def on_startup(bot: Bot) -> None:
    global _push_task

    # Render qayta ishga tushganda disk tozalanadi — avval GitHub'dan tiklaymiz.
    await pull_from_github()
    cleanup_old_requests()

    _push_task = asyncio.create_task(github_push_worker())

    try:
        bot_info = await bot.get_me()
        logging.info(f"🤖 Bot ma'lumotlari yuklandi: @{bot_info.username}")
    except Exception as e:
        logging.error(f"Bot info yuklashda xato: {e}")

    if not BASE_WEBHOOK_URL:
        logging.error("❌ BASE_WEBHOOK_URL aniqlanmadi! Webhook o'rnatilmadi.")
    else:
        webhook_url = f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}"
        try:
            await bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET)
            logging.info(f"✅ Webhook o'rnatildi: {webhook_url}")
        except Exception as e:
            logging.error(f"❌ Webhook o'rnatishda xato: {e}")

    commands = [
        BotCommand(command="menyu", description="⌨️ Menyu tugmalarini ochish"),
        BotCommand(command="kech_qolish", description="⏰ Kech qolishga ruxsat so'rash"),
        BotCommand(command="sabab", description="✍️ Kelolmaslik iltimosnomasi"),
        BotCommand(command="ketish", description="🚪 Ishxonadan chiqib ketish"),
        BotCommand(command="qaytib_keldim", description="🔄 Ishxonaga qaytib kelish"),
        BotCommand(command="hisobot", description="👁 Bugungi holat (rahbarlar uchun)"),
        BotCommand(command="oylik", description="📊 Oylik davomat va maosh hisobi"),
        BotCommand(command="dam_olish", description="🌴 Dam olish kunini belgilash / ko'rish"),
        BotCommand(command="fayl", description="📎 Barcha davomat faylini yuklab olish"),
        BotCommand(command="bekor", description="🚫 Boshlangan jarayonni bekor qilish"),
        BotCommand(command="id", description="🆔 ID ma'lumotlarini ko'rish"),
        BotCommand(command="start", description="🤖 Botni qayta ishga tushirish"),
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    except Exception as e:
        logging.error(f"Buyruqlarni o'rnatishda xato: {e}")

    # ⌨️ Yozish joyining chap tomonidagi ko'k "Menu" tugmasi.
    # Bosilganda yuqoridagi buyruqlar ro'yxati tugmalar bo'lib chiqadi.
    # (Telegram cheklovi: bu tugma FAQAT bot bilan shaxsiy chatda ko'rinadi.)
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logging.info("✅ 'Menu' tugmasi o'rnatildi.")
    except Exception as e:
        logging.error(f"'Menu' tugmasini o'rnatishda xato: {e}")

    if not scheduler.running:
        scheduler.add_job(
            check_absentees_daily, 'cron',
            hour=REPORT_HOUR, minute=REPORT_MINUTE,
            id="daily_report", replace_existing=True,
            misfire_grace_time=600
        )
        scheduler.start()
        logging.info(f"🗓 Kunlik hisobot vaqti: {REPORT_HOUR:02d}:{REPORT_MINUTE:02d}")

    logging.info("🤖 Ziynat Nazorat Boti (webhook rejimida) ishga tushdi.")


async def on_shutdown(bot: Bot) -> None:
    logging.info("🧹 Bot to'xtatilmoqda...")

    # To'xtashdan oldin oxirgi o'zgarishlarni GitHub'ga saqlab qolamiz.
    if _push_task:
        _push_task.cancel()
    try:
        await push_to_github()
    except Exception:
        pass
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    try:
        await bot.session.close()
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

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
