import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

scheduler = BackgroundScheduler()
scheduler.start()

def format_datetime(dt: datetime) -> str:
    days = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    day_name = days[dt.weekday()]
    month_name = months[dt.month - 1]
    return f"{day_name}, {dt.day} {month_name} {dt.year} - {dt.hour:02d}:{dt.minute:02d}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = """
🎉 **Bot Jadwal Kerja** 

Commands:
/add [judul] - Tambah jadwal baru
/list - Lihat semua jadwal
/today - Jadwal hari ini
/delete [id] - Hapus jadwal
/help - Panduan lengkap

Contoh:
`/add Meeting Senin 09:00`
`/add Lunch break daily 12:00`

Bot akan mengirim reminder sebelum jadwal dimulai!
"""
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_msg = """
📖 **Panduan Bot Jadwal**

**Tambah Jadwal:**
Format: `/add [judul] [hari] [jam]`

Hari yang didukung:
- Senin, Selasa, Rabu, Kamis, Jumat, Sabtu, Minggu
- today, tomorrow
- daily (setiap hari)
- tanggal: 15/01/2026

Jam format: HH:MM (09:00, 14:30)

**Contoh:**
```
/add Meeting client Senin 09:00
/add Lunch tomorrow 12:30
/add Report daily 17:00
/add Review 15/04/2026 10:00
```

**Reminder:**
Bot akan mengirim notifikasi 15 menit sebelum jadwal dimulai.
"""
    await update.message.reply_text(help_msg, parse_mode='Markdown')

async def add_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received add command from user {update.effective_user.id}: {context.args}")
    
    if not context.args:
        await update.message.reply_text(
            "❌ Format salah!\n\nGunakan: `/add [judul] [hari] [jam]`\nContoh: `/add Meeting Senin 09:00`",
            parse_mode='Markdown'
        )
        return
    
    args = context.args
    logger.info(f"Args: {args}")
    
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Argument kurang!\n\nMinimal: judul, hari, dan jam.\nContoh: `/add Meeting Senin 09:00`",
            parse_mode='Markdown'
        )
        return
    
    time_str = args[-1]
    
    if not ':' in time_str:
        await update.message.reply_text(
            "❌ Format jam salah!\n\nGunakan format HH:MM\nContoh: 09:00, 14:30",
            parse_mode='Markdown'
        )
        return
    
    try:
        hour, minute = map(int, time_str.split(':'))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Invalid time")
    except:
        await update.message.reply_text(
            "❌ Jam tidak valid!\n\nGunakan format HH:MM\nContoh: 09:00, 14:30",
            parse_mode='Markdown'
        )
        return
    
    day_str = args[-2].lower()
    title_parts = args[:-2]
    title = ' '.join(title_parts)
    
    now = datetime.now()
    schedule_time = None
    
    days_mapping = {
        'senin': 0, 'selasa': 1, 'rabu': 2, 'kamis': 3,
        'jumat': 4, 'sabtu': 5, 'minggu': 6,
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }
    
    if day_str == 'today' or day_str == 'hari':
        schedule_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if schedule_time <= now:
            schedule_time += timedelta(days=1)
    elif day_str == 'tomorrow' or day_str == 'besok':
        schedule_time = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    elif day_str == 'daily' or day_str == 'harian':
        schedule_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if schedule_time <= now:
            schedule_time += timedelta(days=1)
    elif day_str in days_mapping:
        target_day = days_mapping[day_str]
        current_day = now.weekday()
        days_ahead = target_day - current_day
        if days_ahead <= 0:
            days_ahead += 7
        schedule_time = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    elif '/' in day_str:
        try:
            date_parts = day_str.split('/')
            day_num = int(date_parts[0])
            month_num = int(date_parts[1])
            year = int(date_parts[2]) if len(date_parts) > 2 else now.year
            schedule_time = datetime(year, month_num, day_num, hour, minute, 0, 0)
        except:
            await update.message.reply_text(
                "❌ Format tanggal salah!\n\nGunakan: DD/MM/YYYY atau DD/MM\nContoh: 15/04/2026",
                parse_mode='Markdown'
            )
            return
    else:
        await update.message.reply_text(
            "❌ Hari tidak dikenali!\n\nGunakan: Senin, Selasa, etc. atau today, tomorrow, daily",
            parse_mode='Markdown'
        )
        return
    
    user_id = update.effective_user.id
    schedule_id = database.add_schedule(user_id, title, "", schedule_time, remind_before=15)
    
    reminder_time = schedule_time - timedelta(minutes=15)
    
    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(run_date=reminder_time),
        args=[user_id, schedule_id, title, schedule_time],
        id=f'reminder_{schedule_id}',
        replace_existing=True
    )
    
    msg = f"""
✅ **Jadwal berhasil ditambahkan!**

📝 {title}
📅 {format_datetime(schedule_time)}

⏰ Reminder akan dikirim 15 menit sebelum jadwal dimulai.
"""
    await update.message.reply_text(msg, parse_mode='Markdown')

async def send_reminder(user_id: int, schedule_id: int, title: str, schedule_time: datetime):
    try:
        app = Application.builder().token(BOT_TOKEN).build()
        msg = f"""
⏰ **Reminder Jadwal!**

📝 {title}
📅 {format_datetime(schedule_time)}

Jadwal akan dimulai dalam 15 menit!
"""
        await app.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
        logger.info(f"Reminder sent for schedule {schedule_id} to user {user_id}")
    except Exception as e:
        logger.error(f"Failed to send reminder: {e}")

async def list_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    schedules = database.get_user_schedules(user_id)
    
    if not schedules:
        await update.message.reply_text("📭 Tidak ada jadwal.\n\nTambah dengan `/add [judul] [hari] [jam]`", parse_mode='Markdown')
        return
    
    msg = "📋 **Daftar Jadwal Anda:**\n\n"
    for i, s in enumerate(schedules, 1):
        msg += f"{i}. **{s['title']}**\n   📅 {format_datetime(s['schedule_time'])}\n   ID: {s['id']}\n\n"
    
    msg += "Hapus dengan `/delete [id]`"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def today_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    schedules = database.get_today_schedules(user_id)
    
    if not schedules:
        await update.message.reply_text("📭 Tidak ada jadwal hari ini.\n\nTambah dengan `/add [judul] today [jam]`", parse_mode='Markdown')
        return
    
    msg = "📅 **Jadwal Hari Ini:**\n\n"
    for i, s in enumerate(schedules, 1):
        time_only = f"{s['schedule_time'].hour:02d}:{s['schedule_time'].minute:02d}"
        msg += f"{i}. **{s['title']}**\n   🕐 {time_only}\n\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def delete_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Format salah!\n\nGunakan: `/delete [id]`\nLihat ID dengan `/list`", parse_mode='Markdown')
        return
    
    try:
        schedule_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ ID tidak valid!\n\nGunakan angka dari `/list`", parse_mode='Markdown')
        return
    
    user_id = update.effective_user.id
    deleted = database.delete_schedule(user_id, schedule_id)
    
    if deleted:
        try:
            scheduler.remove_job(f'reminder_{schedule_id}')
        except:
            pass
        await update.message.reply_text("✅ Jadwal berhasil dihapus!", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Jadwal tidak ditemukan atau bukan milik Anda.", parse_mode='Markdown')

async def clear_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    schedules = database.get_user_schedules(user_id)
    
    if not schedules:
        await update.message.reply_text("📭 Tidak ada jadwal untuk dihapus.", parse_mode='Markdown')
        return
    
    for s in schedules:
        database.delete_schedule(user_id, s['id'])
        try:
            scheduler.remove_job(f'reminder_{s["id"]}')
        except:
            pass
    
    await update.message.reply_text(f"✅ {len(schedules)} jadwal berhasil dihapus!", parse_mode='Markdown')

def main():
    database.init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_schedule))
    app.add_handler(CommandHandler("list", list_schedules))
    app.add_handler(CommandHandler("today", today_schedules))
    app.add_handler(CommandHandler("delete", delete_schedule))
    app.add_handler(CommandHandler("clear", clear_all))
    
    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()