import os
import datetime
import logging
import asyncio
import sqlite3
from zoneinfo import ZoneInfo
from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand,
    BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

# ==========================================================
# 🕒 VAQT ZONASI — O'zbekiston vaqti (Asia/Tashkent)
# ==========================================================
TZ = ZoneInfo("Asia/Tashkent")

def now_tz() -> datetime.datetime:
    return datetime.datetime.now(TZ)

# ==========================================================
# 🔑 SOZLAMALAR (Environment Variables)
# ==========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8707986524:AAF0tby_NWvgLCxBIkofyHL3nE-Tce-EELE")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1003993511736"))
JARIMALAR_THREAD_ID = int(os.getenv("JARIMALAR_THREAD_ID", "55"))
ISHGA_KELISH_THREAD_ID = int(os.getenv("ISHGA_KELISH_THREAD_ID", "1"))

bot = Bot(token=BOT_TOKEN)

BOSS_USERNAMES = {"abduvali94", "abdullayev_12_00"}

EMPLOYEES = {
    "abdullayev_12_00": {
        "name": "Ma'murxon",
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "21:00",
        "rates": [(10, 30000), (30, 50000), (60, 70000), (120, 100000), (270, 150000)],
        "absent": 150000,
    },
    "ganiboyev_ozodbek": {
        "name": "Ozodbek",
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "21:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
    },
    "wsev7": {
        "name": "Gulzoda",
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "19:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
    },
    "muradjanvna_m": {
        "name": "Moxinur",
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "19:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
    },
    "ustazoda0125": {
        "name": "Asadbek",
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "18:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 120000,
    },
    "muhammadsodiq": {
        "name": "Muhammadsodiq",
        "work_start": (8, 0),
        "work_end": (12, 30),
        "leave_time": "21:00",
        "rates": [(10, 15000), (30, 30000), (60, 40000), (120, 60000), (270, 80000)],
        "absent": 100000,
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
# 🗄️ SQLITE DATABASE (Render Serverida Saqlash)
# ==========================================================
DB_PATH = "ziynat_attendance.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            emp_key TEXT PRIMARY KEY,
            date_str TEXT,
            name TEXT,
            time_str TEXT,
            late_minutes INTEGER,
            fine INTEGER,
            status TEXT,
            until_time TEXT,
            boss TEXT,
            reason TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            req_id TEXT PRIMARY KEY,
            req_type TEXT,
            emp_key TEXT,
            emp_name TEXT,
            username TEXT,
            reason TEXT,
            until_time TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def db_set_record(emp_key: str, record: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    today_str = now_tz().strftime("%Y-%m-%d")
    cur.execute("""
        INSERT INTO attendance (emp_key, date_str, name, time_str, late_minutes, fine, status, until_time, boss, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(emp_key) DO UPDATE SET
            date_str=excluded.date_str,
            name=excluded.name,
            time_str=excluded.time_str,
            late_minutes=excluded.late_minutes,
            fine=excluded.fine,
            status=excluded.status,
            until_time=excluded.until_time,
            boss=excluded.boss,
            reason=excluded.reason
    """, (
        emp_key,
        today_str,
        record.get("name", ""),
        record.get("time", ""),
        record.get("late", 0),
        record.get("fine", 0),
        record.get("status", ""),
        record.get("until_time", ""),
        record.get("boss", ""),
        record.get("reason", "")
    ))
    conn.commit()
    conn.close()

def db_get_records() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    today_str = now_tz().strftime("%Y-%m-%d")
    cur.execute("SELECT emp_key, name, time_str, late_minutes, fine, status, until_time, boss, reason FROM attendance WHERE date_str=?", (today_str,))
    rows = cur.fetchall()
    conn.close()
    res = {}
    for r in rows:
        res[r[0]] = {
            "name": r[1],
            "time": r[2],
            "late": r[3],
            "fine": r[4],
            "status": r[5],
            "until_time": r[6],
            "boss": r[7],
            "reason": r[8]
        }
    return res

def db_clear_today():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    today_str = now_tz().strftime("%Y-%m-%d")
    cur.execute("DELETE FROM attendance WHERE date_str=?", (today_str,))
    conn.commit()
    conn.close()

# FSM states
class ExcuseState(StatesGroup):
    waiting_for_reason = State()

class LateState(StatesGroup):
    waiting_for_reason = State()

dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=TZ)

def get_employee(username: str | None, first_name: str = "") -> tuple[str, dict]:
    if username and username.lower() in EMPLOYEES:
        return username.lower(), EMPLOYEES[username.lower()]
    for key, data in EMPLOYEES.items():
        if data["name"].lower() in (first_name or "").lower():
            return key, data
    clean_name = username or first_name or "Xodim"
    return clean_name.lower(), DEFAULT_FINE

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
    thread_info = f"🧵 **Mavzu ID:** `{message.message_thread_id}`\n" if message.message_thread_id else ""
    await message.answer(
        f"🆔 **Sizning ID:** `{user.id}`\n"
        f"👤 **Ism:** {user.full_name}\n"
        f"🔗 **Username:** @{user.username or 'yoq'}\n"
        f"💬 **Chat ID:** `{message.chat.id}`\n"
        f"{thread_info}",
        parse_mode="Markdown"
    )

# /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Assalomu alaykum! 'Ziynat' do'koni nazorat botiga xush kelibsiz.\n\n"
        "Buyruqlarni ko'rish uchun yozish joyida `/` belgisini bosing.",
        parse_mode="Markdown"
    )

# /ketish
@dp.message(Command("ketish"))
async def handle_ketish(message: types.Message):
    emp_key, emp = get_employee(message.from_user.username, message.from_user.first_name or "")
    name = message.from_user.first_name or emp["name"]
    now_time = now_tz().strftime("%H:%M")
    await message.answer(
        f"🚪 **{name}** ishxonadan chiqib ketdi.\n"
        f"⏰ **Chiqish vaqti:** {now_time}\n"
        f"📌 *Belgilangan ketish vaqti: {emp['leave_time']}*",
        parse_mode="Markdown"
    )

# /qaytib_keldim
@dp.message(Command("qaytib_keldim"))
async def handle_qaytib_keldim(message: types.Message):
    emp_key, emp = get_employee(message.from_user.username, message.from_user.first_name or "")
    name = message.from_user.first_name or emp["name"]
    now_time = now_tz().strftime("%H:%M")
    await message.answer(
        f"🔄 **{name}** ishxonaga qaytib keldi.\n"
        f"⏰ **Qaytish vaqti:** {now_time}",
        parse_mode="Markdown"
    )

# 📹 VIDEO NOTE / VIDEO (Tuzatilgan Dinamik Vaqt Algoritmi)
@dp.message(F.video | F.video_note)
async def handle_video(message: types.Message):
    username = message.from_user.username
    first_name = message.from_user.first_name or ""
    emp_key, emp = get_employee(username, first_name)
    user_name = first_name or emp["name"]
    
    now = now_tz()
    start_h, start_m = emp.get("work_start", (8, 0))
    end_h, end_m = emp.get("work_end", (12, 30))

    work_start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    work_end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

    if now > work_end:
        await message.answer(
            f"⛔ **{user_name}**, soat {end_h:02d}:{end_m:02d} dan o'tdi. Video qabul qilish to'xtatilgan!",
            parse_mode="Markdown"
        )
        return

    time_str = now.strftime("%H:%M")
    records = db_get_records()

    if emp_key in records and records[emp_key].get("status") == "late_approved":
        allowed_until = records[emp_key].get("until_time", f"{end_h:02d}:{end_m:02d}")
        ah, am = map(int, allowed_until.split(":"))
        allowed_dt = now.replace(hour=ah, minute=am, second=0, microsecond=0)
        
        if now <= allowed_dt:
            rec = {"name": user_name, "time": time_str, "late": 0, "fine": 0, "status": "on_time_approved", "until_time": allowed_until}
            db_set_record(emp_key, rec)
            await message.answer(
                f"✅ Baraka toping, **{user_name}**!\n"
                f"Ruxsat berilgan vaqtda ({time_str} da) keldingiz. Jarima qo'llanilmaydi.",
                parse_mode="Markdown"
            )
            return
        else:
            late_mins = int((now - allowed_dt).total_seconds() / 60)
            fine_sum = calculate_fine(emp, late_mins)
            rec = {"name": user_name, "time": time_str, "late": late_mins, "fine": fine_sum, "status": "late"}
            db_set_record(emp_key, rec)
            await message.answer(
                f"⚠️ **{user_name}**, siz ruxsat berilgan vaqtdan ({allowed_until}) {late_mins} daqiqa kechikdingiz!\n"
                f"💸 **Jarima miqdori:** {fine_sum:,} so'm.",
                parse_mode="Markdown"
            )
            return

    if now <= work_start:
        rec = {"name": user_name, "time": time_str, "late": 0, "fine": 0, "status": "on_time"}
        db_set_record(emp_key, rec)
        await message.answer(
            f"✅ Baraka toping, **{user_name}**!\nIshga o'z vaqtida keldingiz. (Vaqt: {time_str})",
            parse_mode="Markdown"
        )
        return

    late_minutes = int((now - work_start).total_seconds() / 60)
    fine_sum = calculate_fine(emp, late_minutes)
    
    rec = {"name": user_name, "time": time_str, "late": late_minutes, "fine": fine_sum, "status": "late"}
    db_set_record(emp_key, rec)
    
    await message.answer(
        f"⚠️ **{user_name}**, siz bugun {late_minutes} daqiqa kechikdingiz. (Kelgan vaqtingiz: {time_str})\n"
        f"💸 **Jarima miqdori:** {fine_sum:,} so'm.",
        parse_mode="Markdown"
    )

# ✍️ /sabab — ILTIMOSNOMA
@dp.message(Command("sabab"))
async def start_excuse(message: types.Message, state: FSMContext):
    warning_text = (
        "⚠️ **DIQQAT! SABABLI ISHGA KELOLMASLIK BO'YICHA ILTIMOSNOMA**\n\n"
        "Iltimos, ishga kelolmasligingiz sababini **juda jiddiy yondashib, to'liq va tushunarli** holatda yozing.\n\n"
        "❗️ *Yuzaki yoki sababsiz yozilgan iltimosnomalar rahbariyat tomonidan rad etiladi va belgilangan jarima kuchida qoladi.*\n\n"
        "✍️ **Sababingizni ushbu mavzuga yozib yuboring:**"
    )
    warning_msg = await message.answer(warning_text, parse_mode="Markdown")
    await state.update_data(warning_msg_id=warning_msg.message_id, warning_chat_id=warning_msg.chat.id)
    await state.set_state(ExcuseState.waiting_for_reason)

@dp.message(ExcuseState.waiting_for_reason)
async def send_excuse_to_group(message: types.Message, state: FSMContext):
    user_name = message.from_user.first_name or "Xodim"
    username = message.from_user.username or ""
    emp_key, _ = get_employee(username, user_name)
    reason_text = message.text

    state_data = await state.get_data()
    if state_data.get("warning_msg_id"):
        try:
            await bot.delete_message(chat_id=state_data["warning_chat_id"], message_id=state_data["warning_msg_id"])
        except Exception:
            pass

    req_id = f"exc_{int(datetime.datetime.now().timestamp())}"
    
    approve_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Roziman", callback_data=f"sabab_a_{req_id}"),
            InlineKeyboardButton(text="❌ Rozi emasman", callback_data=f"sabab_r_{req_id}")
        ]
    ])
    
    group_msg = (
        f"📩 **YANGI ILTIMOSNOMA (Sababli kelolmaslik)**\n\n"
        f"👤 **Xodim:** {user_name} (@{username})\n"
        f"📝 **Sababi:** {reason_text}\n\n"
        f"⚖️ *Qaror berish huquqi faqat rahbariyatda (Abduvali / Ma'murxon)*"
    )

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (req_id, "sabab", emp_key, user_name, username, reason_text, "", "pending")
    )
    conn.commit()
    conn.close()

    await message.answer(group_msg, reply_markup=approve_keyboard, parse_mode="Markdown")
    await state.clear()

# ⏰ /kech_qolish
time_picker_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="08:30", callback_data="time_08:30"), InlineKeyboardButton(text="09:00", callback_data="time_09:00"), InlineKeyboardButton(text="09:30", callback_data="time_09:30")],
    [InlineKeyboardButton(text="10:00", callback_data="time_10:00"), InlineKeyboardButton(text="10:30", callback_data="time_10:30"), InlineKeyboardButton(text="11:00", callback_data="time_11:00")],
    [InlineKeyboardButton(text="11:30", callback_data="time_11:30"), InlineKeyboardButton(text="12:00", callback_data="time_12:00")]
])

@dp.message(Command("kech_qolish"))
async def start_late_request(message: types.Message, state: FSMContext):
    msg = await message.answer(
        "⏰ **KECHIKISHGA RUXSAT SO'RASH**\n\n"
        "Iltimos, bugun soat **nechagacha kechikishingizni** pastdagi tugmalar orqali tanlang:",
        reply_markup=time_picker_keyboard,
        parse_mode="Markdown"
    )
    await state.update_data(warning_msg_id=msg.message_id, warning_chat_id=msg.chat.id)

@dp.callback_query(F.data.startswith("time_"))
async def handle_time_selection(callback: types.CallbackQuery, state: FSMContext):
    selected_time = callback.data.split("_")[1]
    await state.update_data(selected_time=selected_time)
    await callback.message.edit_text(
        f"⏰ Belgilangan vaqt: **{selected_time}**\n\n"
        f"✍️ Endi kechikishingiz **sababini batafsil va jiddiy** yozib yuboring:",
        parse_mode="Markdown"
    )
    await state.set_state(LateState.waiting_for_reason)
    await callback.answer()

@dp.message(LateState.waiting_for_reason)
async def send_late_request_to_group(message: types.Message, state: FSMContext):
    user_name = message.from_user.first_name or "Xodim"
    username = message.from_user.username or ""
    emp_key, _ = get_employee(username, user_name)
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
        f"⏰ **YANGI ILTIMOSNOMA (Kech qolishga ruxsat)**\n\n"
        f"👤 **Xodim:** {user_name} (@{username})\n"
        f"🕒 **Kutilayotgan kelish vaqti:** {selected_time} gacha\n"
        f"📝 **Sababi:** {reason_text}\n\n"
        f"⚖️ *Qaror berish huquqi faqat rahbariyatda (Abduvali / Ma'murxon)*"
    )
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (req_id, "late", emp_key, user_name, username, reason_text, selected_time, "pending")
    )
    conn.commit()
    conn.close()

    await message.answer(group_msg, reply_markup=approve_keyboard, parse_mode="Markdown")
    await state.clear()

# 👑 RAHBARLAR QARORLARI
@dp.callback_query(F.data.startswith("sabab_") | F.data.startswith("late_"))
async def handle_boss_decisions(callback: types.CallbackQuery):
    clicker_username = (callback.from_user.username or "").lower()
    
    if clicker_username not in BOSS_USERNAMES:
        await callback.answer("❌ Sizda bu qarorni qabul qilish huquqi yo'q! Qarorni faqat Abduvali yoki Ma'murxon beradi.", show_alert=True)
        return

    parts = callback.data.split("_")
    category = parts[0]   # 'sabab' or 'late'
    action = parts[1]     # 'a' (approve) or 'r' (reject)
    req_id = f"{category}_{parts[2]}" if len(parts) > 2 else ""

    boss_name = callback.from_user.first_name or "Rahbar"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT req_type, emp_key, emp_name, username, reason, until_time FROM requests WHERE req_id=?", (req_id,))
    row = cur.fetchone()

    if not row:
        await callback.answer("⚠️ So'rov topilmadi yoki allaqachon ko'rib chiqilgan.", show_alert=True)
        conn.close()
        return

    req_type, emp_key, emp_name, emp_username, reason, until_time = row

    if category == "sabab":
        if action == "a":
            rec = {"name": emp_name, "status": "excused_approved", "boss": boss_name, "reason": reason}
            db_set_record(emp_key, rec)
            public_msg = (
                f"✅ **SABABLI ISHGA KELOLMASLIK (RUXSAT BERILDI)**\n\n"
                f"👤 **Xodim:** {emp_name} (@{emp_username})\n"
                f"👑 **Qaror beruvchi:** {boss_name}\n"
                f"📌 **Natija:** *Uzrli sabab deb topildi. Bugun jarima qo'llanilmaydi.*"
            )
            await callback.answer("✅ Iltimosnoma tasdiqlandi.", show_alert=True)
        else:
            rec = {"name": emp_name, "status": "excused_rejected", "boss": boss_name, "reason": reason}
            db_set_record(emp_key, rec)
            public_msg = (
                f"❌ **SABABLI ISHGA KELOLMASLIK (RAD ETILDI)**\n\n"
                f"👤 **Xodim:** {emp_name} (@{emp_username})\n"
                f"👑 **Qaror beruvchi:** {boss_name}\n"
                f"📌 **Natija:** *Sabab yetarsiz deb topildi. Belgilangan jarima qo'llaniladi.*"
            )
            await callback.answer("❌ Iltimosnoma rad etildi.", show_alert=True)

    elif category == "late":
        if action == "a":
            rec = {"name": emp_name, "status": "late_approved", "until_time": until_time, "boss": boss_name, "reason": reason}
            db_set_record(emp_key, rec)
            public_msg = (
                f"✅ **KECHIKISHGA RUXSAT BERILDI**\n\n"
                f"👤 **Xodim:** {emp_name} (@{emp_username})\n"
                f"⏰ **Ruxsat berilgan vaqt:** Soat {until_time} gacha\n"
                f"👑 **Qaror beruvchi:** {boss_name}\n"
                f"📌 **Natija:** *{until_time} gacha kelib video tashlasa jarima yozilmaydi.*"
            )
            await callback.answer(f"✅ {until_time} gacha ruxsat berildi.", show_alert=True)
        else:
            rec = {"name": emp_name, "status": "late_rejected", "until_time": until_time, "boss": boss_name, "reason": reason}
            db_set_record(emp_key, rec)
            public_msg = (
                f"❌ **KECHIKISHGA RUXSAT BERILMADI**\n\n"
                f"👤 **Xodim:** {emp_name} (@{emp_username})\n"
                f"⏰ **So'ralgan vaqt:** {until_time}\n"
                f"👑 **Qaror beruvchi:** {boss_name}\n"
                f"📌 **Natija:** *Standard kechikish jarimasi qo'llaniladi.*"
            )
            await callback.answer("❌ Kechikish rad etildi.", show_alert=True)

    cur.execute("UPDATE requests SET status=? WHERE req_id=?", ("approved" if action == "a" else "rejected", req_id))
    conn.commit()
    conn.close()

    try:
        updated_card = callback.message.text + f"\n\n📌 **HUKM:** {'✅ TASDIQLANDI' if action == 'a' else '❌ RAD ETILDI'} ({boss_name})"
        await callback.message.edit_text(updated_card, parse_mode="Markdown")
    except Exception:
        pass

    await bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=public_msg,
        message_thread_id=ISHGA_KELISH_THREAD_ID,
        parse_mode="Markdown"
    )

# 📊 SOAT 12:31 DAGI KUNLIK TO'LIQ HISOBOT
async def check_absentees_1231():
    records = db_get_records()
    present_text = []
    absent_text = []
    total_fine = 0
    
    for key, data in EMPLOYEES.items():
        if key in records:
            rec = records[key]
            st = rec["status"]
            
            if st == "on_time":
                present_text.append(f"🟢 **{data['name']}** — {rec['time']} da keldi (O'z vaqtida)")
            elif st == "on_time_approved":
                present_text.append(f"🟢 **{data['name']}** — {rec['time']} da keldi (Ruxsat berilgan vaqtda kelgan)")
            elif st == "late":
                present_text.append(f"🟡 **{data['name']}** — {rec['time']} da keldi ({rec['late']} daqiqa kechikdi, Jarima: {rec['fine']:,} so'm)")
                total_fine += rec["fine"]
            elif st == "excused_approved":
                present_text.append(f"🔵 **{data['name']}** — Sababli kelmadi ({rec.get('boss', 'Rahbar')} tomonidan RUXSAT BERILGAN)")
            elif st == "excused_rejected":
                fine = data["absent"]
                absent_text.append(f"🔴 **{data['name']}** — Kelmadi (Ruxsat so'ralgan, lekin {rec.get('boss', 'Rahbar')} tomonidan RAD ETILGAN. Jarima: {fine:,} so'm)")
                total_fine += fine
            elif st == "late_approved":
                fine = data["absent"]
                absent_text.append(f"🔴 **{data['name']}** — {rec.get('until_time', '12:30')} gacha ruxsat olgan edi, lekin kelmadi (Jarima: {fine:,} so'm)")
                total_fine += fine
            elif st == "late_rejected":
                fine = data["absent"]
                absent_text.append(f"🔴 **{data['name']}** — Kechikish so'ragan, lekin RAD ETILGAN va kelmadi (Jarima: {fine:,} so'm)")
                total_fine += fine
        else:
            fine = data["absent"]
            absent_text.append(f"🔴 **{data['name']}** (@{key}) — Kelmadi (Jarima: {fine:,} so'm)")
            total_fine += fine

    report = f"📊 **SOAT 12:31 KUNLIK DAVOMAT VA JARIMALAR HISOBOTI**\n\n"
    
    if present_text:
        report += "✅ **Ishga kelganlar va ruxsat olganlar:**\n" + "\n".join(present_text) + "\n\n"
    else:
        report += "⚠️ **Bugun hech kim ishga kelmadi!**\n\n"
        
    if absent_text:
        report += "❌ **Ishga kelmaganlar:**\n" + "\n".join(absent_text) + "\n\n"
        
    report += f"💸 **Bugungi jami belgilanayotgan jarima:** {total_fine:,} so'm."

    await bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=report,
        message_thread_id=JARIMALAR_THREAD_ID,
        parse_mode="Markdown"
    )

# 🌐 RENDER BEPUL TARIFI UCHUN VEB-SERVER
async def start_dummy_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Ziynat Nazorat Bot is running 24/7 on Render!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_dummy_server()

    commands = [
        BotCommand(command="sabab", description="✍️ Kelolmaslik iltimosnomasi"),
        BotCommand(command="kech_qolish", description="⏰ Kech qolishga ruxsat so'rash"),
        BotCommand(command="ketish", description="🚪 Ishxonadan chiqib ketish"),
        BotCommand(command="qaytib_keldim", description="🔄 Ishxonaga qaytib kelish"),
        BotCommand(command="id", description="🆔 ID ma'lumotlarini ko'rish"),
        BotCommand(command="start", description="🤖 Botni qayta ishga tushirish")
    ]
    
    await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    
    scheduler.add_job(check_absentees_1231, 'cron', hour=12, minute=31)
    scheduler.add_job(db_clear_today, 'cron', hour=0, minute=0)
    
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    
    print("🤖 Ziynat Nazorat Boti muvaffaqiyatli ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
