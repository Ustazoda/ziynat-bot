import os
import asyncio
import sqlite3
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    BotCommand, 
    BotCommandScopeAllGroupChats, 
    BotCommandScopeAllPrivateChats
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# ==========================================
# 1. SOZLAMALAR VA ENVIRONMENT VARIABLE'LAR
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", "-1002234057863"))
ISHGA_KELISH_THREAD_ID = int(os.environ.get("ISHGA_KELISH_THREAD_ID", "1"))
JARIMALAR_THREAD_ID = int(os.environ.get("JARIMALAR_THREAD_ID", "55"))

# Rahbarlar Telegram ID lar ro'yxati (So'rovlar va tasdiqlash uchun)
BOSS_IDS = [
    int(x.strip()) for x in os.environ.get("BOSS_IDS", "108819011,108819012").split(",") if x.strip()
]

# Toshkent vaqt zonasi
TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

# ==========================================
# 2. XODIMLAR VA BAZA MANBALARI
# ==========================================
EMPLOYEES = {
    "sohibjon": {"name": "Sohibjon Ustaboyev", "per_min": 1000, "absent": 50000},
    "ilhomjon": {"name": "Ilhomjon", "per_min": 1000, "absent": 50000},
    "hojiakbar": {"name": "Hojiakbar", "per_min": 1000, "absent": 50000},
    "shohruh": {"name": "Shohruh", "per_min": 1000, "absent": 50000},
    "mirzoolim": {"name": "Mirzoolim", "per_min": 1000, "absent": 50000},
    "muhammadali": {"name": "Muhammadali", "per_min": 1000, "absent": 50000},
    "murodjon": {"name": "Murodjon", "per_min": 1000, "absent": 50000},
}

DB_PATH = "attendance.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            emp_key TEXT PRIMARY KEY,
            status TEXT,
            time_str TEXT,
            late_minutes INTEGER,
            fine INTEGER,
            boss_name TEXT,
            until_time TEXT,
            reason TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            req_id INTEGER PRIMARY KEY AUTOINCREMENT,
            req_type TEXT,
            emp_key TEXT,
            emp_name TEXT,
            username TEXT,
            reason TEXT,
            until_time TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

init_db()

def db_get_records():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT emp_key, status, time_str, late_minutes, fine, boss_name, until_time, reason FROM attendance")
    rows = cur.fetchall()
    conn.close()
    records = {}
    for r in rows:
        records[r[0]] = {
            "status": r[1],
            "time": r[2],
            "late": r[3],
            "fine": r[4],
            "boss": r[5],
            "until_time": r[6],
            "reason": r[7]
        }
    return records

def db_set_record(emp_key, record):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO attendance (emp_key, status, time_str, late_minutes, fine, boss_name, until_time, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        emp_key,
        record.get("status"),
        record.get("time"),
        record.get("late", 0),
        record.get("fine", 0),
        record.get("boss"),
        record.get("until_time"),
        record.get("reason")
    ))
    conn.commit()
    conn.close()

def db_clear_today():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()

# ==========================================
# 3. AIOGRAM INITIALIZATION & FSM
# ==========================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=TASHKENT_TZ)

class Form(StatesGroup):
    waiting_sabab = State()
    waiting_kech_time = State()
    waiting_kech_reason = State()

# ==========================================
# 4. YUZAGA KELADIGAN BUYRUKLAR VA BOT
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Kelolmaslik iltimosnomasi", callback_link="sabab_start")],
        [InlineKeyboardButton(text="⏰ Kechikish so'rovi", callback_data="kech_start")],
        [InlineKeyboardButton(text="🆔 Mening Telegram ID m", callback_data="my_id")]
    ])
    await message.reply(
        "👋 **Ziynat Nazorat Botiga xush kelibsiz!**\n\n"
        "Ushbu bot orqali ishga kelish videolari, kechikish va uzr so'rovlarini yuborishingiz mumkin.",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "my_id")
async def cb_my_id(callback: types.CallbackQuery):
    await callback.answer(f"Sizning Telegram ID ingiz: {callback.from_user.id}", show_alert=True)

# ------------------------------------------
# A) SABABLI KELOLMASLIK SO'ROVI (FSM)
# ------------------------------------------
@dp.message(Command("sabab"))
@dp.callback_query(F.data == "sabab_start")
async def cmd_sabab(event: types.Message | types.CallbackQuery, state: FSMContext):
    msg = event.message if isinstance(event, types.CallbackQuery) else event
    await state.set_state(Form.waiting_sabab)
    await msg.reply("✍️ **Bugun ishga kelolmasligingiz sababini batafsil yozib yuboring:**", parse_mode="Markdown")

@dp.message(Form.waiting_sabab)
async def process_sabab(message: types.Message, state: FSMContext):
    reason = message.text
    await state.clear()
    
    username = (message.from_user.username or "username_yoq").lower()
    emp_name = message.from_user.full_name
    emp_key = username if username in EMPLOYEES else "unknown"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO requests (req_type, emp_key, emp_name, username, reason)
        VALUES (?, ?, ?, ?, ?)
    """, ("sabab", emp_key, emp_name, username, reason))
    req_id = cur.lastrowid
    conn.commit()
    conn.close()

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash (Ruxsat)", callback_data=f"req_sabab_a_{req_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"req_sabab_r_{req_id}")
        ]
    ])

    boss_card = (
        f"📩 **SABABLI ISHGA KELOLMASLIK ILTIMOSNOMASI**\n\n"
        f"👤 **Xodim:** {emp_name} (@{username})\n"
        f"📝 **Sababi:** {reason}\n\n"
        f"👇 *Ushbu so'rov bo'yicha qaroringizni tanlang:*"
    )

    # Barcha rahbarlarga xabar yuborish
    for boss_id in BOSS_IDS:
        try:
            await bot.send_message(boss_id, boss_card, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass

    await message.reply("✅ **Iltimosnomangiz rahbarlarga ko'rib chiqish uchun yuborildi.**", parse_mode="Markdown")

# ------------------------------------------
# B) KECHIKISH SO'ROVI (FSM)
# ------------------------------------------
@dp.message(Command("kech_qolish"))
@dp.callback_query(F.data == "kech_start")
async def cmd_kechikish(event: types.Message | types.CallbackQuery, state: FSMContext):
    msg = event.message if isinstance(event, types.CallbackQuery) else event
    await state.set_state(Form.waiting_kech_time)
    await msg.reply("⏰ **Soat nechagacha kechikishingizni kiriting (Masalan: 09:30 yoki 10:00):**", parse_mode="Markdown")

@dp.message(Form.waiting_kech_time)
async def process_kech_time(message: types.Message, state: FSMContext):
    await state.update_data(until_time=message.text)
    await state.set_state(Form.waiting_kech_reason)
    await msg_reply = message.reply("📝 **Kechikishingiz sababini yozing:**", parse_mode="Markdown")

@dp.message(Form.waiting_kech_reason)
async def process_kech_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    until_time = data.get("until_time", "09:30")
    reason = message.text
    await state.clear()

    username = (message.from_user.username or "username_yoq").lower()
    emp_name = message.from_user.full_name
    emp_key = username if username in EMPLOYEES else "unknown"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO requests (req_type, emp_key, emp_name, username, reason, until_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("late", emp_key, emp_name, username, reason, until_time))
    req_id = cur.lastrowid
    conn.commit()
    conn.close()

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ruxsat berish", callback_data=f"req_late_a_{req_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"req_late_r_{req_id}")
        ]
    ])

    boss_card = (
        f"⏰ **KECHIKISHGA RUXSAT SO'ROVI**\n\n"
        f"👤 **Xodim:** {emp_name} (@{username})\n"
        f"🕒 **Kelish vaqti:** {until_time} gacha\n"
        f"📝 **Sababi:** {reason}\n\n"
        f"👇 *Qaroringizni tanlang:*"
    )

    for boss_id in BOSS_IDS:
        try:
            await bot.send_message(boss_id, boss_card, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass

    await message.reply("✅ **Kechikish so'rovingiz rahbarlarga yuborildi.**", parse_mode="Markdown")

# ------------------------------------------
# C) RAHBAR TUGMALARI ISHLOVCHI (CALLBACK)
# ------------------------------------------
@dp.callback_query(F.data.startswith("req_"))
async def handle_request_callback(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    category = parts[1]   # sabab / late
    action = parts[2]     # a (approve) / r (reject)
    req_id = int(parts[3])

    boss_name = callback.from_user.first_name or "Rahbar"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT req_type, emp_key, emp_name, username, reason, until_time FROM requests WHERE req_id=?", (req_id,))
    row = cur.fetchone()

    if not row:
        await callback.answer("⚠️ So'rov topilmadi yoki ko'rib chiqilgan.", show_alert=True)
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

# ------------------------------------------
# D) ISHGA KELISH VIDEOSINI QABUL QILISH
# ------------------------------------------
@dp.message(F.video | F.video_note)
async def handle_attendance_video(message: types.Message):
    now = datetime.now(TASHKENT_TZ)
    time_str = now.strftime("%H:%M")
    current_minutes = now.hour * 60 + now.minute
    limit_minutes = 9 * 60  # Soat 09:00 ISH BOSHLANISH VAQTI

    username = (message.from_user.username or "").lower()
    full_name = message.from_user.full_name
    emp_key = username if username in EMPLOYEES else "unknown"
    emp_data = EMPLOYEES.get(emp_key, {"name": full_name, "per_min": 1000, "absent": 50000})

    records = db_get_records()
    prev_rec = records.get(emp_key, {})

    # Kechikishga ruxsat borligini tekshirish
    if prev_rec.get("status") == "late_approved":
        until_str = prev_rec.get("until_time", "09:30")
        try:
            h, m = map(int, until_str.split(":"))
            approved_limit = h * 60 + m
            if current_minutes <= approved_limit:
                rec = {"name": emp_data["name"], "status": "on_time_approved", "time": time_str, "late": 0, "fine": 0}
                db_set_record(emp_key, rec)
                await message.reply(
                    f"✅ **Ruxsat berilgan vaqtda kelindi!**\n\n"
                    f"👤 **Xodim:** {emp_data['name']}\n"
                    f"🕒 **Kelgan vaqti:** {time_str}\n"
                    f"👑 **Ruxsat bergan rahbar:** {prev_rec.get('boss', 'Rahbar')}\n"
                    f"📌 **Jarima:** 0 so'm",
                    parse_mode="Markdown"
                )
                return
        except Exception:
            pass

    # Standard vaqt bo'yicha hisoblash (09:00 gacha)
    if current_minutes <= limit_minutes:
        rec = {"name": emp_data["name"], "status": "on_time", "time": time_str, "late": 0, "fine": 0}
        db_set_record(emp_key, rec)
        await message.reply(
            f"✅ **O'z vaqtida kelindi!**\n\n"
            f"👤 **Xodim:** {emp_data['name']}\n"
            f"🕒 **Vaqt:** {time_str}\n"
            f"🎉 **Barakalla!** Bugun jarima qo'llanilmaydi.",
            parse_mode="Markdown"
        )
    else:
        late_mins = current_minutes - limit_minutes
        fine = late_mins * emp_data["per_min"]
        rec = {"name": emp_data["name"], "status": "late", "time": time_str, "late": late_mins, "fine": fine}
        db_set_record(emp_key, rec)

        fine_msg = (
            f"⚠️ **ISHGA KECHIKIB KELINDI!**\n\n"
            f"👤 **Xodim:** {emp_data['name']}\n"
            f"🕒 **Kelgan vaqti:** {time_str}\n"
            f"⏰ **Kechikish:** {late_mins} daqiqa\n"
            f"💸 **Hisoblangan jarima:** {fine:,} so'm"
        )

        await message.reply(fine_msg, parse_mode="Markdown")

        # Jarimalar mavzusiga ham xabar yuborish
        await bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=fine_msg,
            message_thread_id=JARIMALAR_THREAD_ID,
            parse_mode="Markdown"
        )

# ------------------------------------------
# E) SOAT 12:31 DAGI KUNLIK HISOBOT (CRON)
# ------------------------------------------
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

# ------------------------------------------
# F) RENDER PORTI UCHUN DUMMY WEB SERVER
# ------------------------------------------
async def start_dummy_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Ziynat Nazorat Bot is running 24/7 on Render!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ==========================================
# 5. ASOSIY ISHGA TUSHIRISH (MAIN)
# ==========================================
async def main():
    # Render portini ochiq ushlash uchun veb-serverni ishga tushiramiz
    await start_dummy_server()

    commands = [
        BotCommand(command="sabab", description="✍️ Kelolmaslik iltimosnomasi"),
        BotCommand(command="kech_qolish", description="⏰ Kech qolishga ruxsat so'rash"),
        BotCommand(command="start", description="🤖 Botni qayta ishga tushirish")
    ]
    
    await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    
    # Har kuni soat 12:31 da avtomatik hisobot
    scheduler.add_job(check_absentees_1231, 'cron', hour=12, minute=31)
    
    # Har kuni yarim tunda (00:00 da) bazani tozalash
    scheduler.add_job(db_clear_today, 'cron', hour=0, minute=0)
    
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    
    print("🤖 Ziynat Nazorat Boti muvaffaqiyatli ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
