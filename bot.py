import os
import logging
import re
import asyncio
from datetime import datetime, timedelta, timezone
from calendar import monthrange
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
import database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

WITA_OFFSET = timedelta(hours=8)
WITA_TIMEZONE = timezone(WITA_OFFSET)

def get_local_now():
    return datetime.now(WITA_TIMEZONE)

scheduler = BackgroundScheduler(timezone=WITA_TIMEZONE)
scheduler.start()

user_states = {}

def auto_complete_expired_schedules():
    conn = None
    try:
        now = get_local_now()
        grace_period = timedelta(hours=1)
        
        all_schedules = database.get_all_pending_schedules()
        
        for schedule in all_schedules:
            schedule_time = schedule['schedule_time']
            schedule_id = schedule['id']
            user_id = schedule['user_id']
            
            if now > schedule_time + grace_period:
                database.update_schedule_status(user_id, schedule_id, 'completed')
                logger.info(f"Auto-completed schedule {schedule_id} - {schedule['title']}")
    
    except Exception as e:
        logger.error(f"Error in auto_complete: {e}")

scheduler.add_job(
    auto_complete_expired_schedules,
    trigger=IntervalTrigger(minutes=30),
    id='auto_complete_job',
    replace_existing=True
)

logger.info("Auto-complete scheduler started - runs every 30 minutes")

def restore_reminders():
    try:
        pending_schedules = database.get_all_pending_schedules()
        logger.info(f"Found {len(pending_schedules)} pending schedules to restore")
        restored_count = 0
        
        for schedule in pending_schedules:
            schedule_id = schedule['id']
            user_id = schedule['user_id']
            title = schedule['title']
            schedule_time = schedule['schedule_time']
            
            if schedule_time.tzinfo is None:
                schedule_time = schedule_time.replace(tzinfo=WITA_TIMEZONE)
            
            remind_times = schedule.get('remind_times', '5')
            
            logger.info(f"Schedule {schedule_id}: time={schedule_time}, remind_times={remind_times}")
            
            if not remind_times:
                continue
            
            sent_reminders = database.get_sent_reminders(schedule_id)
            
            for rem_time in [int(x) for x in remind_times.split(',')]:
                if str(rem_time) in sent_reminders:
                    logger.info(f"Reminder {rem_time} already sent for schedule {schedule_id}")
                    continue
                    
                reminder_datetime = schedule_time - timedelta(minutes=rem_time)
                
                logger.info(f"Reminder {rem_time} min: reminder_time={reminder_datetime}, now={get_local_now()}")
                
                if reminder_datetime > get_local_now():
                    scheduler.add_job(
                        send_reminder_sync,
                        trigger=DateTrigger(run_date=reminder_datetime),
                        args=[user_id, schedule_id, title, schedule_time, rem_time],
                        id=f'reminder_{schedule_id}_{rem_time}',
                        replace_existing=True
                    )
                    restored_count += 1
                    logger.info(f"Restored reminder for schedule {schedule_id} at {reminder_datetime}")
                else:
                    logger.info(f"Skipped reminder {rem_time} for schedule {schedule_id} - time already passed")
        
        logger.info(f"Restored {restored_count} reminders from database")
    except Exception as e:
        logger.error(f"Error restoring reminders: {e}")

def get_smart_status(schedule: dict) -> str:
    now = get_local_now()
    schedule_time = schedule['schedule_time']
    status = schedule.get('status', 'pending')
    
    if status == 'completed':
        return '✅'
    
    if now >= schedule_time:
        return '⏱️'
    
    return '⏳'

def get_status_text(schedule: dict) -> str:
    now = get_local_now()
    schedule_time = schedule['schedule_time']
    status = schedule.get('status', 'pending')
    
    if status == 'completed':
        return '✅ Selesai'
    
    if now >= schedule_time:
        return '⏱️ Sedang berlangsung'
    
    return '⏳ Menunggu'

def format_datetime(dt: datetime, shift_info: str = '') -> str:
    days = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    day_name = days[dt.weekday()]
    month_name = months[dt.month - 1]
    
    if shift_info:
        return f"{day_name}, {dt.day} {month_name} {dt.year} - {shift_info}"
    
    return f"{day_name}, {dt.day} {month_name} {dt.year} - {dt.hour:02d}:{dt.minute:02d}"

def format_schedule_display(schedule: dict) -> str:
    days = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    dt = schedule['schedule_time']
    day_name = days[dt.weekday()]
    month_name = months[dt.month - 1]
    
    description = schedule.get('description', '')
    if description and 'Shift' in description or 'Operasional' in description:
        return f"{day_name}, {dt.day} {month_name} {dt.year} - {description}"
    
    return f"{day_name}, {dt.day} {month_name} {dt.year} - {dt.hour:02d}:{dt.minute:02d}"

def parse_time_natural(text: str) -> tuple:
    text = text.lower()
    
    time_patterns = [
        (r'shift\s*1|shift\s*satu', lambda m: (0, 0)),
        (r'shift\s*2|shift\s*dua', lambda m: (8, 0)),
        (r'shift\s*3|shift\s*tiga', lambda m: (16, 0)),
        (r'operasional|ops', lambda m: (11, 0)),
        (r'(\d{1,2}):(\d{2})', lambda m: (int(m.group(1)), int(m.group(2)))),
        (r'jam (\d{1,2})', lambda m: (int(m.group(1)), 0)),
        (r'(\d{1,2}) jam', lambda m: (int(m.group(1)), 0)),
        (r'pagi|subuh', lambda m: (6, 0)),
        (r'siang', lambda m: (12, 0)),
        (r'sore|petang', lambda m: (15, 0)),
        (r'malam', lambda m: (20, 0)),
        (r'dini hari', lambda m: (2, 0)),
    ]
    
    for pattern, parser in time_patterns:
        match = re.search(pattern, text)
        if match:
            hour, minute = parser(match)
            if hour > 23:
                hour = hour % 24
            return (hour, minute)
    
    return None

def parse_date_natural(text: str) -> datetime:
    text = text.lower()
    now = get_local_now()
    
    if 'hari ini' in text or 'today' in text:
        return now
    elif 'besok' in text or 'tomorrow' in text:
        return now + timedelta(days=1)
    elif 'lusa' in text:
        return now + timedelta(days=2)
    elif 'minggu depan' in text or 'next week' in text:
        return now + timedelta(days=7)
    elif 'bulan depan' in text or 'next month' in text:
        next_month = now.month + 1
        next_year = now.year if next_month <= 12 else now.year + 1
        next_month = next_month if next_month <= 12 else 1
        return now.replace(year=next_year, month=next_month, day=1)
    
    days_mapping = {
        'senin': 0, 'selasa': 1, 'rabu': 2, 'kamis': 3,
        'jumat': 4, 'sabtu': 5, 'minggu': 6,
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }
    
    for day_name, day_num in days_mapping.items():
        if day_name in text:
            current_day = now.weekday()
            days_ahead = day_num - current_day
            if days_ahead <= 0:
                days_ahead += 7
            return now + timedelta(days=days_ahead)
    
    date_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-]?(\d{4})?', text)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else now.year
        try:
            return datetime(year, month, day)
        except:
            pass
    
    return None

def parse_relative_time(text: str) -> datetime:
    text = text.lower()
    now = get_local_now()
    
    patterns = [
        (r'in (\d+) minutes|(\d+) menit lagi', 'minutes'),
        (r'in (\d+) hours|(\d+) jam lagi', 'hours'),
        (r'in (\d+) days|(\d+) hari lagi', 'days'),
    ]
    
    for pattern, unit in patterns:
        match = re.search(pattern, text)
        if match:
            amount = int(match.group(1) or match.group(2))
            if unit == 'minutes':
                return now + timedelta(minutes=amount)
            elif unit == 'hours':
                return now + timedelta(hours=amount)
            elif unit == 'days':
                return now + timedelta(days=amount)
    
    return None

def create_calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    keyboard = []
    
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    nav_row = [
        InlineKeyboardButton('◀️', callback_data=f'cal_{year}_{month-1}'),
        InlineKeyboardButton(f'{month_names[month-1]} {year}', callback_data='ignore'),
        InlineKeyboardButton('▶️', callback_data=f'cal_{year}_{month+1}'),
    ]
    keyboard.append(nav_row)
    
    days_row = [
        InlineKeyboardButton('S', callback_data='ignore'),
        InlineKeyboardButton('S', callback_data='ignore'),
        InlineKeyboardButton('R', callback_data='ignore'),
        InlineKeyboardButton('K', callback_data='ignore'),
        InlineKeyboardButton('J', callback_data='ignore'),
        InlineKeyboardButton('S', callback_data='ignore'),
        InlineKeyboardButton('M', callback_data='ignore'),
    ]
    keyboard.append(days_row)
    
    first_day = datetime(year, month, 1).weekday()
    num_days = monthrange(year, month)[1]
    
    current_row = []
    for i in range(first_day):
        current_row.append(InlineKeyboardButton(' ', callback_data='ignore'))
    
    for day in range(1, num_days + 1):
        current_row.append(InlineKeyboardButton(str(day), callback_data=f'date_{year}_{month}_{day}'))
        if len(current_row) == 7:
            keyboard.append(current_row)
            current_row = []
    
    if current_row:
        while len(current_row) < 7:
            current_row.append(InlineKeyboardButton(' ', callback_data='ignore'))
        keyboard.append(current_row)
    
    keyboard.append([
        InlineKeyboardButton('❌ Cancel', callback_data='cancel_calendar')
    ])
    
    return InlineKeyboardMarkup(keyboard)

def create_filter_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('⏰ Filter by Shift', callback_data='filter_shift'),
        ],
        [
            InlineKeyboardButton('📅 Filter by Time', callback_data='filter_time'),
        ],
        [
            InlineKeyboardButton('✅ Filter by Status', callback_data='filter_status'),
        ],
        [
            InlineKeyboardButton('⬅️ Back to Menu', callback_data='show_menu'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_filter_shift_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('🟥 Shift 1 (00:00-08:00)', callback_data='filter_shift_1'),
        ],
        [
            InlineKeyboardButton('🟩 Shift 2 (08:00-16:00)', callback_data='filter_shift_2'),
        ],
        [
            InlineKeyboardButton('🟦 Shift 3 (16:00-00:00)', callback_data='filter_shift_3'),
        ],
        [
            InlineKeyboardButton('🟨 Operasional (11:00-19:00)', callback_data='filter_shift_ops'),
        ],
        [
            InlineKeyboardButton('⬅️ Back', callback_data='filter'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_filter_time_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('📅 Hari Ini', callback_data='filter_today'),
        ],
        [
            InlineKeyboardButton('📆 Minggu Ini', callback_data='filter_week'),
        ],
        [
            InlineKeyboardButton('🗓️ Bulan Ini', callback_data='filter_month'),
        ],
        [
            InlineKeyboardButton('📊 Custom Range', callback_data='filter_custom'),
        ],
        [
            InlineKeyboardButton('⬅️ Back', callback_data='filter'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_filter_status_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('⏳ Pending', callback_data='filter_pending'),
        ],
        [
            InlineKeyboardButton('✅ Completed', callback_data='filter_completed'),
        ],
        [
            InlineKeyboardButton('📊 All', callback_data='filter_all'),
        ],
        [
            InlineKeyboardButton('⬅️ Back', callback_data='filter'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('➕ Tambah Jadwal', callback_data='add_schedule'),
            InlineKeyboardButton('📋 Daftar Jadwal', callback_data='list_schedules'),
        ],
        [
            InlineKeyboardButton('📅 Hari Ini', callback_data='today'),
            InlineKeyboardButton('🔍 Search', callback_data='search'),
        ],
        [
            InlineKeyboardButton('📊 Filter', callback_data='filter'),
            InlineKeyboardButton('⚙️ Settings', callback_data='settings'),
        ],
        [
            InlineKeyboardButton('❓ Help', callback_data='help'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_schedule_actions_keyboard(schedule_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('✅ Selesai', callback_data=f'complete_{schedule_id}'),
            InlineKeyboardButton('🗑️ Hapus', callback_data=f'delete_{schedule_id}'),
        ],
        [
            InlineKeyboardButton('📝 Edit', callback_data=f'edit_{schedule_id}'),
            InlineKeyboardButton('🔔 Reminder', callback_data=f'reminder_{schedule_id}'),
        ],
        [
            InlineKeyboardButton('🏠 Menu Utama', callback_data='main_menu'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_shift_selection_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('🟥 Shift 1 (00:00-08:00)', callback_data='shift_template_1'),
        ],
        [
            InlineKeyboardButton('🟩 Shift 2 (08:00-16:00)', callback_data='shift_template_2'),
        ],
        [
            InlineKeyboardButton('🟦 Shift 3 (16:00-00:00)', callback_data='shift_template_3'),
        ],
        [
            InlineKeyboardButton('🟨 Operasional (11:00-19:00)', callback_data='shift_template_ops'),
        ],
        [
            InlineKeyboardButton('⏰ Custom Time', callback_data='shift_custom'),
        ],
        [
            InlineKeyboardButton('❌ Cancel', callback_data='cancel_time'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_minute_selection_keyboard(hour: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(f'{hour:02d}:00', callback_data=f'time_{hour:02d}:00'),
            InlineKeyboardButton(f'{hour:02d}:10', callback_data=f'time_{hour:02d}:10'),
            InlineKeyboardButton(f'{hour:02d}:20', callback_data=f'time_{hour:02d}:20'),
        ],
        [
            InlineKeyboardButton(f'{hour:02d}:30', callback_data=f'time_{hour:02d}:30'),
            InlineKeyboardButton(f'{hour:02d}:40', callback_data=f'time_{hour:02d}:40'),
            InlineKeyboardButton(f'{hour:02d}:50', callback_data=f'time_{hour:02d}:50'),
        ],
        [
            InlineKeyboardButton('⬅️ Back', callback_data=f'back_hour_{hour}'),
            InlineKeyboardButton('❌ Cancel', callback_data='cancel_time'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_all_hours_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('00', callback_data='hour_00'),
            InlineKeyboardButton('01', callback_data='hour_01'),
            InlineKeyboardButton('02', callback_data='hour_02'),
            InlineKeyboardButton('03', callback_data='hour_03'),
        ],
        [
            InlineKeyboardButton('04', callback_data='hour_04'),
            InlineKeyboardButton('05', callback_data='hour_05'),
            InlineKeyboardButton('06', callback_data='hour_06'),
            InlineKeyboardButton('07', callback_data='hour_07'),
        ],
        [
            InlineKeyboardButton('08', callback_data='hour_08'),
            InlineKeyboardButton('09', callback_data='hour_09'),
            InlineKeyboardButton('10', callback_data='hour_10'),
            InlineKeyboardButton('11', callback_data='hour_11'),
        ],
        [
            InlineKeyboardButton('12', callback_data='hour_12'),
            InlineKeyboardButton('13', callback_data='hour_13'),
            InlineKeyboardButton('14', callback_data='hour_14'),
            InlineKeyboardButton('15', callback_data='hour_15'),
        ],
        [
            InlineKeyboardButton('16', callback_data='hour_16'),
            InlineKeyboardButton('17', callback_data='hour_17'),
            InlineKeyboardButton('18', callback_data='hour_18'),
            InlineKeyboardButton('19', callback_data='hour_19'),
        ],
        [
            InlineKeyboardButton('20', callback_data='hour_20'),
            InlineKeyboardButton('21', callback_data='hour_21'),
            InlineKeyboardButton('22', callback_data='hour_22'),
            InlineKeyboardButton('23', callback_data='hour_23'),
        ],
        [
            InlineKeyboardButton('⬅️ Back', callback_data='back_shift'),
            InlineKeyboardButton('❌ Cancel', callback_data='cancel_time'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_reminder_selection_keyboard(selected_reminders: str = '') -> InlineKeyboardMarkup:
    reminder_options = [5, 10, 20, 30, 60]
    selected_list = [int(x) for x in selected_reminders.split(',') if x.strip()]
    
    keyboard = []
    
    for rem in reminder_options:
        is_selected = rem in selected_list
        
        if rem == 60:
            label = '1 hour'
        else:
            label = f'{rem} min'
        
        if is_selected:
            btn_text = f'✅ {label}'
        else:
            btn_text = f'⬜ {label}'
        
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f'toggle_rem_{rem}')])
    
    keyboard.append([InlineKeyboardButton('✏️ Custom (Manual)', callback_data='custom_reminder')])
    
    if selected_list:
        selected_str = ', '.join([f'{x} min' if x != 60 else '1 hour' for x in sorted(selected_list, reverse=True)])
        keyboard.append([
            InlineKeyboardButton(f'✓ Set: {selected_str}', callback_data='set_reminders'),
        ])
    
    keyboard.append([
        InlineKeyboardButton('⬅️ Back', callback_data='back_to_schedule'),
        InlineKeyboardButton('❌ Skip Reminder', callback_data='skip_reminder'),
    ])
    
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = {}
    
    welcome_msg = """
🎉 **Selamat Datang di Shift Bot!**

Bot untuk manajemen jadwal shift kerja dengan fitur lengkap!

**⏰ Shift Template:**
• Shift 1 (00:00-08:00)
• Shift 2 (08:00-16:00)
• Shift 3 (16:00-00:00)
• Operasional (11:00-19:00)

**Fitur:**
• Natural Language Input
• Multiple Reminders
• Calendar Visual
• Search & Filter

Klik tombol di bawah untuk mulai! 👇
"""
    
    keyboard = [
        [InlineKeyboardButton('🚀 Mulai Sekarang', callback_data='show_menu')],
        [InlineKeyboardButton('📖 Panduan', callback_data='help')],
    ]
    
    await update.message.reply_text(welcome_msg, parse_mode='Markdown',
                                     reply_markup=InlineKeyboardMarkup(keyboard))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_msg = """
📖 **Panduan Lengkap Bot Jadwal**

**➕ TAMBAH JADWAL:**

**Cara 1: Natural Language (Rekomendasi)**
Ketik langsung dalam bahasa Indonesia:
```
Meeting besok jam 2 siang
Lunch hari ini 12:30
Report lusa pagi
Standup minggu depan 09:00
Deadline 25/04/2026 sore
```

**Cara 2: Command**
```
/add [judul] [tanggal] [jam]
/add Meeting Senin 09:00
/add Report 15/04/2026 10:00
```

**Tanggal Natural:**
• Hari ini, Besok, Lusa
• Senin-Sabtu, Minggu
• Minggu depan, Bulan depan
• DD/MM/YYYY atau DD/MM

**Waktu Natural:**
• Jam 2, Jam 10
• Pagi (06:00), Siang (12:00)
• Sore (15:00), Malam (20:00)
• HH:MM format

**🔔 REMINDERS:**
Pilih reminder yang diinginkan:
• 5 menit sebelum
• 15 menit sebelum  
• 30 menit sebelum
• 1 jam sebelum
Toggle on/off sesuai kebutuhan!

**⏰ SHIFT TEMPLATE:**
• 🟥 Shift 1: 00:00-08:00 (mulai 00:00)
• 🟩 Shift 2: 08:00-16:00 (mulai 08:00)
• 🟦 Shift 3: 16:00-00:00 (mulai 16:00)
• 🟨 Operasional: 11:00-19:00 (mulai 11:00)
• ⏰ Custom: jam fleksibel

**📅 INLINE CALENDAR:**
Klik tombol ➕ Tambah Jadwal
→ Pilih tanggal di calendar
→ Pilih shift (jam otomatis)
→ Toggle reminder
→ Set!

**📊 STATUS SYSTEM:**
• ⏳ Menunggu - Belum waktunya
• ⏱️ Berlangsung - Sedang berlangsung saat ini
• ✅ Selesai - Ditandai selesai manual atau auto-complete

Auto-complete berjalan setiap 30 menit untuk jadwal yang sudah lewat 1 jam.

**Quick Actions tersedia di menu.**
"""
    await update.message.reply_text(help_msg, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id in user_states:
        state = user_states[user_id]
        
        if state.get('waiting_for') == 'title':
            state['title'] = text
            state['waiting_for'] = 'datetime'
            
            msg = "📅 Pilih tanggal atau ketik natural language:\n\nContoh: `besok`, `lusa`, `Senin`, `15/04/2026`"
            await update.message.reply_text(msg, parse_mode='Markdown',
                                            reply_markup=create_calendar_keyboard(datetime.now().year, datetime.now().month))
            return
        
        elif state.get('waiting_for') == 'datetime':
            parsed_date = parse_date_natural(text)
            
            if parsed_date:
                state['date'] = parsed_date
                state['waiting_for'] = 'time'
                state['remind_times'] = ''
                
                msg = f"✅ Tanggal: {parsed_date.strftime('%d/%m/%Y')}\n\n⏰ Pilih shift waktu:"
                await update.message.reply_text(msg, parse_mode='Markdown',
                                                reply_markup=create_shift_selection_keyboard())
                return
            else:
                await update.message.reply_text(
                    "❌ Format tanggal tidak dikenali.\n\nCoba: `besok`, `Senin`, `15/04/2026`",
                    parse_mode='Markdown'
                )
                return
        
        elif state.get('waiting_for') == 'time':
            parsed_time = parse_time_natural(text)
            
            if parsed_time:
                hour, minute = parsed_time
                date = state.get('date', get_local_now())
                schedule_time = date.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=WITA_TIMEZONE)
                
                title = state.get('title', 'Untitled')
                
                state['schedule_time'] = schedule_time
                state['waiting_for'] = 'reminder'
                
                msg = f"""
✅ **Detail Jadwal:**

📝 {title}
📅 {format_datetime(schedule_time)}

🔔 Pilih reminder yang diinginkan:
"""
                await update.message.reply_text(msg, parse_mode='Markdown',
                                                reply_markup=create_reminder_selection_keyboard())
                return
        
        elif state.get('waiting_for') == 'custom_reminder_minutes':
            try:
                minutes = [int(x.strip()) for x in text.split(',') if x.strip().isdigit()]
                if minutes:
                    minutes.sort(reverse=True)
                    state['remind_times'] = ','.join([str(x) for x in minutes])
                    state['waiting_for'] = 'reminder'
                    
                    remind_str = ', '.join([f'{x} min' for x in minutes])
                    msg = f"✅ Custom reminder set: {remind_str}\n\nKlik Set untuk konfirmasi atau pilih lain:"
                    await update.message.reply_text(msg, parse_mode='Markdown',
                                                    reply_markup=create_reminder_selection_keyboard(state['remind_times']))
                else:
                    await update.message.reply_text(
                        "❌ Format salah. Ketik angka menit (contoh: 5 atau 3,7,45)",
                        parse_mode='Markdown'
                    )
            except Exception as e:
                await update.message.reply_text(
                    "❌ Format salah. Ketik angka menit (contoh: 5 atau 3,7,45)",
                    parse_mode='Markdown'
                )
            return
        
        elif state.get('waiting_for') == 'search':
            keyword = text.strip()
            schedules = database.search_schedules(user_id, keyword)
            
            if not schedules:
                await update.message.reply_text(
                    f"🔍 Tidak ditemukan jadwal dengan keyword: **{keyword}**",
                    parse_mode='Markdown',
                    reply_markup=create_main_menu()
                )
            else:
                msg = f"🔍 **Hasil Search '{keyword}':**\n\n"
                for i, s in enumerate(schedules, 1):
                    status_emoji = '✅' if s['status'] == 'completed' else '⏳'
                    msg += f"{i}. {status_emoji} **{s['title']}**\n"
                    msg += f"   📅 {format_schedule_display(s)}\n"
                    msg += f"   ID: {s['id']}\n\n"
                
                await update.message.reply_text(msg, parse_mode='Markdown',
                                                reply_markup=create_main_menu())
            
            user_states[user_id] = {}
            return
        
        elif state.get('waiting_for') == 'filter_start':
            try:
                if '/' in text:
                    parts = text.split('/')
                    day = int(parts[0])
                    month = int(parts[1])
                    year = int(parts[2]) if len(parts) > 2 else datetime.now().year
                    start_date = datetime(year, month, day)
                    
                    state['filter_start'] = start_date
                    state['waiting_for'] = 'filter_end'
                    
                    msg = f"""
✅ **Tanggal Awal:** {start_date.strftime('%d/%m/%Y')}

Sekarang ketik tanggal akhir (DD/MM atau DD/MM/YYYY):

Contoh:
• 15/04
• 15/04/2026
"""
                    await update.message.reply_text(msg, parse_mode='Markdown')
                else:
                    await update.message.reply_text(
                        "❌ Format salah!\n\nGunakan: DD/MM atau DD/MM/YYYY\nContoh: 10/04 atau 10/04/2026",
                        parse_mode='Markdown'
                    )
            except:
                await update.message.reply_text(
                    "❌ Format tanggal salah!\n\nGunakan: DD/MM atau DD/MM/YYYY\nContoh: 10/04 atau 10/04/2026",
                    parse_mode='Markdown'
                )
            return
        
        elif state.get('waiting_for') == 'filter_end':
            try:
                if '/' in text:
                    parts = text.split('/')
                    day = int(parts[0])
                    month = int(parts[1])
                    year = int(parts[2]) if len(parts) > 2 else datetime.now().year
                    end_date = datetime(year, month, day, 23, 59, 59)
                    
                    start_date = state.get('filter_start')
                    schedules = database.get_schedules_by_date_range(user_id, start_date, end_date)
                    
                    if not schedules:
                        msg = f"""
📭 Tidak ada jadwal dalam range:
{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}
"""
                        await update.message.reply_text(msg, parse_mode='Markdown',
                                                        reply_markup=create_main_menu())
                    else:
                        msg = f"""
📊 **Jadwal {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}:**

"""
                        for i, s in enumerate(schedules, 1):
                            status_emoji = '✅' if s['status'] == 'completed' else '⏳'
                            msg += f"{i}. {status_emoji} **{s['title']}**\n"
                            msg += f"   📅 {format_schedule_display(s)}\n\n"
                        
                        await update.message.reply_text(msg, parse_mode='Markdown',
                                                        reply_markup=create_main_menu())
                    
                    user_states[user_id] = {}
                else:
                    await update.message.reply_text(
                        "❌ Format salah!\n\nGunakan: DD/MM atau DD/MM/YYYY\nContoh: 15/04 atau 15/04/2026",
                        parse_mode='Markdown'
                    )
            except:
                await update.message.reply_text(
                    "❌ Format tanggal salah!\n\nGunakan: DD/MM atau DD/MM/YYYY\nContoh: 15/04 atau 15/04/2026",
                    parse_mode='Markdown'
                )
            return
    
    parsed_datetime = try_parse_full_natural(text)
    if parsed_datetime:
        title, schedule_time = parsed_datetime
        
        user_states[user_id] = {
            'title': title,
            'schedule_time': schedule_time,
            'remind_times': '',
            'waiting_for': 'reminder'
        }
        
        msg = f"""
✅ **Natural Language Detected!**

📝 {title}
📅 {format_datetime(schedule_time)}

🔔 Pilih reminder yang diinginkan:
"""
        await update.message.reply_text(msg, parse_mode='Markdown',
                                        reply_markup=create_reminder_selection_keyboard())
        return
    
    await update.message.reply_text(
        "❓ Ketik jadwal atau gunakan menu di bawah.\n\nContoh: `meeting besok jam 2 siang`",
        parse_mode='Markdown',
        reply_markup=create_main_menu()
    )

def try_parse_full_natural(text: str) -> tuple:
    text_lower = text.lower()
    
    relative_time = parse_relative_time(text_lower)
    if relative_time:
        title = re.sub(r'in \d+ (minutes|hours|days)|\d+ (menit|jam|hari) lagi', '', text_lower).strip()
        if not title:
            title = text
        return (title, relative_time)
    
    parsed_time = parse_time_natural(text_lower)
    parsed_date = parse_date_natural(text_lower)
    
    if parsed_date and parsed_time:
        schedule_time = parsed_date.replace(hour=parsed_time[0], minute=parsed_time[1], second=0, microsecond=0)
        
        time_patterns = [
            r'\d{1,2}:\d{2}',
            r'jam \d{1,2}',
            r'\d{1,2} jam',
            r'pagi|subuh|siang|sore|petang|malam|dini hari',
        ]
        
        date_patterns = [
            r'hari ini|besok|lusa|today|tomorrow',
            r'minggu depan|bulan depan|next week|next month',
            r'senin|selasa|rabu|kamis|jumat|sabtu|minggu|monday|tuesday|wednesday|thursday|friday|saturday|sunday',
            r'\d{1,2}[/-]\d{1,2}[/-]?\d{4}?',
        ]
        
        title = text_lower
        for pattern in time_patterns + date_patterns:
            title = re.sub(pattern, '', title)
        
        title = title.strip()
        if not title:
            title = text
        
        return (title, schedule_time)
    
    return None

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    await query.answer()
    
    if data == 'ignore':
        return
    
    if data == 'cancel_calendar':
        user_states[user_id] = {}
        await query.edit_message_text("❌ Calendar dibatalkan.", reply_markup=None)
        return
    
    if data == 'cancel_time':
        user_states[user_id] = {}
        await query.edit_message_text("❌ Time selection dibatalkan.", reply_markup=None)
        return
    
    if data.startswith('cal_'):
        parts = data.split('_')
        year = int(parts[1])
        month = int(parts[2])
        
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        
        await query.edit_message_reply_markup(reply_markup=create_calendar_keyboard(year, month))
        return
    
    if data.startswith('date_'):
        parts = data.split('_')
        year = int(parts[1])
        month = int(parts[2])
        day = int(parts[3])
        
        selected_date = datetime(year, month, day)
        
        if user_id not in user_states:
            user_states[user_id] = {}
        
        user_states[user_id]['date'] = selected_date
        user_states[user_id]['waiting_for'] = 'time'
        user_states[user_id]['remind_times'] = ''
        
        msg = f"✅ Tanggal dipilih: {selected_date.strftime('%d/%m/%Y')}\n\n⏰ Pilih shift waktu:"
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_shift_selection_keyboard())
        return
    
    if data.startswith('shift_'):
        shift_type = data.replace('shift_', '')
        
        if user_id not in user_states:
            user_states[user_id] = {}
        
        template_shifts = {
            'template_1': {'hour': 0, 'name': '🟥 Shift 1 (00:00-08:00)', 'start': '00:00'},
            'template_2': {'hour': 8, 'name': '🟩 Shift 2 (08:00-16:00)', 'start': '08:00'},
            'template_3': {'hour': 16, 'name': '🟦 Shift 3 (16:00-00:00)', 'start': '16:00'},
            'template_ops': {'hour': 11, 'name': '🟨 Operasional (11:00-19:00)', 'start': '11:00'},
        }
        
        if shift_type in template_shifts:
            shift_info = template_shifts[shift_type]
            hour = shift_info['hour']
            
            date = user_states[user_id].get('date', get_local_now())
            schedule_time = date.replace(hour=hour, minute=0, second=0, microsecond=0, tzinfo=WITA_TIMEZONE)
            
            user_states[user_id]['schedule_time'] = schedule_time
            user_states[user_id]['waiting_for'] = 'reminder'
            user_states[user_id]['remind_times'] = ''
            user_states[user_id]['shift_info'] = shift_info['name']
            
            title = user_states[user_id].get('title', 'Jadwal')
            
            msg = f"""
✅ **{shift_info['name']}**

📝 {title}

🔔 Pilih reminder yang diinginkan:
"""
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_reminder_selection_keyboard())
        elif shift_type == 'custom':
            msg = "⏰ **Custom Time**\n\nPilih jam secara manual:"
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_all_hours_keyboard())
        return
    
    if data.startswith('hour_'):
        hour = int(data.replace('hour_', ''))
        
        if user_id in user_states:
            user_states[user_id]['selected_hour'] = hour
        
        msg = f"🕐 Jam: {hour:02d}\n\nPilih menit:"
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_minute_selection_keyboard(hour))
        return
    
    if data.startswith('back_hour_'):
        hour = int(data.replace('back_hour_', ''))
        await query.edit_message_text("⏰ Pilih shift waktu:",
                                      reply_markup=create_shift_selection_keyboard())
        return
    
    if data == 'back_shift':
        now = get_local_now()
        year = user_states[user_id].get('date', now).year
        month = user_states[user_id].get('date', now).month
        
        msg = "📅 Pilih tanggal:"
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_calendar_keyboard(year, month))
        return
    
    if data.startswith('time_'):
        time_str = data.replace('time_', '')
        hour, minute = map(int, time_str.split(':'))
        
        if user_id in user_states:
            date = user_states[user_id].get('date', get_local_now())
            schedule_time = date.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=WITA_TIMEZONE)
            
            user_states[user_id]['schedule_time'] = schedule_time
            user_states[user_id]['waiting_for'] = 'reminder'
            
            title = user_states[user_id].get('title', 'Jadwal')
            
            msg = f"""
✅ **Detail Jadwal:**

📝 {title}
📅 {format_datetime(schedule_time)}

🔔 Pilih reminder yang diinginkan:
"""
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_reminder_selection_keyboard())
        return
    
    if data.startswith('toggle_rem_'):
        rem_time = int(data.replace('toggle_rem_', ''))
        
        if user_id in user_states:
            current_rem = user_states[user_id].get('remind_times', '')
            
            if current_rem:
                rem_list = [int(x) for x in current_rem.split(',') if x.strip()]
            else:
                rem_list = []
            
            if rem_time in rem_list:
                rem_list.remove(rem_time)
            else:
                rem_list.append(rem_time)
            
            rem_list.sort(reverse=True)
            user_states[user_id]['remind_times'] = ','.join([str(x) for x in rem_list]) if rem_list else ''
            
            await query.edit_message_reply_markup(
                reply_markup=create_reminder_selection_keyboard(user_states[user_id]['remind_times'])
            )
        return
    
    if data == 'custom_reminder':
        if user_id in user_states:
            user_states[user_id]['waiting_for'] = 'custom_reminder_minutes'
            await query.edit_message_text(
                "✏️ Ketik jumlah menit untuk reminder (contoh: 3, 7, 45):\n\n"
                "Bisa multiple dengan koma: 3,7,45"
            )
        return
    
    if data == 'set_reminders':
        if user_id in user_states:
            remind_times = user_states[user_id].get('remind_times', '')
            
            if not remind_times:
                remind_times = '5'
            
            schedule_time = user_states[user_id].get('schedule_time', get_local_now())
            title = user_states[user_id].get('title', 'Jadwal')
            shift_info = user_states[user_id].get('shift_info', '')
            
            schedule_id = database.add_schedule(
                user_id, title, shift_info, schedule_time,
                remind_times=remind_times
            )
            
            for rem_time in [int(x) for x in remind_times.split(',')]:
                reminder_datetime = schedule_time - timedelta(minutes=rem_time)
                logger.info(f"Checking reminder {rem_time} min: reminder_time={reminder_datetime}, now={get_local_now()}, should_schedule={reminder_datetime > get_local_now()}")
                if reminder_datetime > get_local_now():
                    scheduler.add_job(
                        send_reminder_sync,
                        trigger=DateTrigger(run_date=reminder_datetime),
                        args=[user_id, schedule_id, title, schedule_time, rem_time],
                        id=f'reminder_{schedule_id}_{rem_time}',
                        replace_existing=True
                    )
                    logger.info(f"Scheduled reminder for schedule {schedule_id} at {reminder_datetime}")
                else:
                    logger.info(f"Skipped reminder {rem_time} min - time already passed")
            
            remind_str = ', '.join([f'{x} min' for x in remind_times.split(',')])
            msg = f"""
✅ **Jadwal berhasil ditambahkan!**

📝 {title}
📅 {format_datetime(schedule_time, shift_info)}

🔔 Reminder: {remind_str} sebelum
"""
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_schedule_actions_keyboard(schedule_id))
            user_states[user_id] = {}
        return
    
    if data == 'skip_reminder':
        if user_id in user_states:
            schedule_time = user_states[user_id].get('schedule_time', get_local_now())
            title = user_states[user_id].get('title', 'Jadwal')
            shift_info = user_states[user_id].get('shift_info', '')
            
            schedule_id = database.add_schedule(
                user_id, title, shift_info, schedule_time,
                remind_times=''
            )
            
            msg = f"""
✅ **Jadwal berhasil ditambahkan!**

📝 {title}
📅 {format_datetime(schedule_time, shift_info)}

🔔 No reminder set
"""
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_schedule_actions_keyboard(schedule_id))
            user_states[user_id] = {}
        return
    
    if data == 'back_to_schedule':
        if user_id in user_states:
            schedule_time = user_states[user_id].get('schedule_time', get_local_now())
            title = user_states[user_id].get('title', 'Jadwal')
            
            msg = f"""
📝 Judul: {title}
📅 Tanggal: {format_datetime(schedule_time)}

⏰ Pilih waktu lagi:
"""
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_shift_selection_keyboard())
        return
    
    if data == 'main_menu':
        await query.edit_message_text(
            "🏠 Menu Utama",
            reply_markup=create_main_menu()
        )
        return
    
    if data == 'add_schedule':
        user_states[user_id] = {'waiting_for': 'title'}
        
        await query.edit_message_text(
            "📝 Ketik judul jadwal:",
            reply_markup=None
        )
        return
    
    if data == 'list_schedules':
        schedules = database.get_user_schedules(user_id)
        
        if not schedules:
            await query.edit_message_text(
                "📭 Tidak ada jadwal.\n\nTambah dengan ➕ Tambah Jadwal",
                reply_markup=create_main_menu()
            )
            return
        
        msg = "📋 **Daftar Jadwal Anda:**\n\n"
        msg += "Legend: ⏳ Menunggu | ⏱️ Berlangsung | ✅ Selesai\n\n"
        
        for i, s in enumerate(schedules, 1):
            status_emoji = get_smart_status(s)
            status_text = get_status_text(s)
            
            msg += f"{i}. {status_emoji} **{s['title']}**\n"
            msg += f"   📅 {format_schedule_display(s)}\n"
            msg += f"   📊 {status_text}\n"
            msg += f"   ID: {s['id']}\n\n"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'today':
        schedules = database.get_today_schedules(user_id)
        
        if not schedules:
            await query.edit_message_text(
                "📭 Tidak ada jadwal hari ini.",
                reply_markup=create_main_menu()
            )
            return
        
        msg = "📅 **Jadwal Hari Ini:**\n\n"
        msg += "Legend: ⏳ Menunggu | ⏱️ Berlangsung | ✅ Selesai\n\n"
        
        for i, s in enumerate(schedules, 1):
            status_emoji = get_smart_status(s)
            time_only = f"{s['schedule_time'].hour:02d}:{s['schedule_time'].minute:02d}"
            msg += f"{i}. {status_emoji} **{s['title']}** - {time_only}\n"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'search':
        user_states[user_id] = {'waiting_for': 'search'}
        await query.edit_message_text(
            "🔍 Ketik keyword untuk search:",
            reply_markup=None
        )
        return
    
    if data == 'filter':
        msg = "📊 **Filter Jadwal**\n\nPilih kategori filter:"
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_filter_main_keyboard())
        return
    
    if data == 'filter_shift':
        msg = "⏰ **Filter by Shift**\n\nPilih shift:"
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_filter_shift_keyboard())
        return
    
    if data == 'filter_time':
        msg = "📅 **Filter by Time**\n\nPilih periode:"
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_filter_time_keyboard())
        return
    
    if data == 'filter_status':
        msg = "✅ **Filter by Status**\n\nPilih status:"
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_filter_status_keyboard())
        return
    
    if data.startswith('filter_shift_'):
        shift_num = data.replace('filter_shift_', '')
        
        shift_times = {
            '1': (0, 8, '🟥 Shift 1 (00:00-08:00)'),
            '2': (8, 16, '🟩 Shift 2 (08:00-16:00)'),
            '3': (16, 24, '🟦 Shift 3 (16:00-00:00)'),
            'ops': (11, 19, '🟨 Operasional (11:00-19:00)')
        }
        
        if shift_num in shift_times:
            start_hour, end_hour, shift_name = shift_times[shift_num]
            
            all_schedules = database.get_user_schedules(user_id)
            
            filtered = []
            for s in all_schedules:
                hour = s['schedule_time'].hour
                if shift_num == '3':
                    if hour >= start_hour or hour < end_hour:
                        filtered.append(s)
                else:
                    if start_hour <= hour < end_hour:
                        filtered.append(s)
            
            if not filtered:
                msg = f"{shift_name}\n\n📭 Tidak ada jadwal untuk shift ini."
            else:
                msg = f"{shift_name}\n\n"
                for i, s in enumerate(filtered, 1):
                    status_emoji = '✅' if s['status'] == 'completed' else '⏳'
                    msg += f"{i}. {status_emoji} **{s['title']}**\n"
                    msg += f"   📅 {format_schedule_display(s)}\n"
            
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_main_menu())
        return
    
    if data == 'filter_pending':
        schedules = database.get_user_schedules(user_id, status='pending')
        
        if not schedules:
            msg = "⏳ **Pending Jadwal**\n\n📭 Tidak ada jadwal pending."
        else:
            msg = f"⏳ **Pending Jadwal ({len(schedules)} items):**\n\n"
            for i, s in enumerate(schedules, 1):
                msg += f"{i}. **{s['title']}**\n"
                msg += f"   📅 {format_schedule_display(s)}\n"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'filter_completed':
        schedules = database.get_user_schedules(user_id, status='completed')
        
        if not schedules:
            msg = "✅ **Completed Jadwal**\n\n📭 Tidak ada jadwal yang sudah selesai."
        else:
            msg = f"✅ **Completed Jadwal ({len(schedules)} items):**\n\n"
            for i, s in enumerate(schedules, 1):
                msg += f"{i}. **{s['title']}**\n"
                msg += f"   📅 {format_schedule_display(s)}\n"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'filter_all':
        schedules = database.get_user_schedules(user_id)
        
        if not schedules:
            msg = "📊 **Semua Jadwal**\n\n📭 Tidak ada jadwal."
        else:
            msg = f"📊 **Semua Jadwal ({len(schedules)} items):**\n\n"
            for i, s in enumerate(schedules, 1):
                status_emoji = '✅' if s['status'] == 'completed' else '⏳'
                msg += f"{i}. {status_emoji} **{s['title']}**\n"
                msg += f"   📅 {format_schedule_display(s)}\n"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'filter_today':
        today = get_local_now().date()
        start_date = datetime.combine(today, datetime.min.time())
        end_date = datetime.combine(today, datetime.max.time())
        
        schedules = database.get_schedules_by_date_range(user_id, start_date, end_date)
        
        if not schedules:
            msg = "📭 Tidak ada jadwal hari ini."
        else:
            msg = f"📅 **Jadwal Hari Ini ({today.strftime('%d/%m/%Y')}):**\n\n"
            msg += "Legend: ⏳ Menunggu | ⏱️ Berlangsung | ✅ Selesai\n\n"
            for i, s in enumerate(schedules, 1):
                status_emoji = get_smart_status(s)
                time_only = s['schedule_time'].strftime('%H:%M')
                msg += f"{i}. {status_emoji} **{s['title']}** - {time_only}\n"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'filter_week':
        today = get_local_now()
        start_week = today - timedelta(days=today.weekday())
        start_date = datetime.combine(start_week.date(), datetime.min.time())
        end_date = start_date + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        schedules = database.get_schedules_by_date_range(user_id, start_date, end_date)
        
        if not schedules:
            msg = "📭 Tidak ada jadwal minggu ini."
        else:
            msg = f"📆 **Jadwal Minggu Ini:**\n\n"
            for i, s in enumerate(schedules, 1):
                status_emoji = '✅' if s['status'] == 'completed' else '⏳'
                msg += f"{i}. {status_emoji} **{s['title']}**\n"
                msg += f"   📅 {format_schedule_display(s)}\n"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'filter_month':
        today = get_local_now()
        start_date = datetime(today.year, today.month, 1)
        if today.month == 12:
            end_date = datetime(today.year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end_date = datetime(today.year, today.month + 1, 1) - timedelta(seconds=1)
        
        schedules = database.get_schedules_by_date_range(user_id, start_date, end_date)
        
        if not schedules:
            msg = "📭 Tidak ada jadwal bulan ini."
        else:
            msg = f"🗓️ **Jadwal Bulan Ini ({today.strftime('%B %Y')}):**\n\n"
            for i, s in enumerate(schedules, 1):
                status_emoji = get_smart_status(s)
                msg += f"{i}. {status_emoji} **{s['title']}**\n"
                msg += f"   📅 {format_schedule_display(s)}\n"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'filter_custom':
        user_states[user_id] = {'waiting_for': 'filter_start'}
        msg = """
📊 **Custom Range Filter**

Ketik tanggal awal (DD/MM atau DD/MM/YYYY):

Contoh:
• 10/04
• 10/04/2026
"""
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=None)
        return
    
    if data == 'help':
        await help_command(update, context)
        return
    
    if data == 'settings':
        msg = """
⚙️ **Settings**

**🔔 Reminder Options:**
• 5 min
• 15 min
• 30 min
• 1 hour

**⏰ Shift Templates:**
• Shift 1: 00:00-08:00
• Shift 2: 08:00-16:00
• Shift 3: 16:00-00:00
• Operasional: 11:00-19:00

**📊 Statistics:**
Total jadwal: {total}
Pending: {pending}
Completed: {completed}

Pilih reminder sesuai kebutuhan saat membuat jadwal.
"""
        
        schedules = database.get_user_schedules(user_id)
        total = len(schedules)
        pending = len([s for s in schedules if s['status'] == 'pending'])
        completed = len([s for s in schedules if s['status'] == 'completed'])
        
        msg = msg.format(total=total, pending=pending, completed=completed)
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
        return
    
    if data == 'show_menu':
        await query.edit_message_text(
            "🏠 **Menu Utama**\n\nPilih aksi:",
            parse_mode='Markdown',
            reply_markup=create_main_menu()
        )
        return
    
    if data.startswith('complete_'):
        schedule_id = int(data.replace('complete_', ''))
        
        if database.update_schedule_status(user_id, schedule_id, 'completed'):
            await query.edit_message_text(
                "✅ Jadwal ditandai selesai!",
                reply_markup=create_main_menu()
            )
        else:
            await query.edit_message_text(
                "❌ Gagal update status.",
                reply_markup=create_main_menu()
            )
        return
    
    if data.startswith('delete_'):
        schedule_id = int(data.replace('delete_', ''))
        
        if database.delete_schedule(user_id, schedule_id):
            try:
                for rem_time in [60, 30, 15, 5]:
                    scheduler.remove_job(f'reminder_{schedule_id}_{rem_time}')
            except:
                pass
            
            await query.edit_message_text(
                "✅ Jadwal berhasil dihapus!",
                reply_markup=create_main_menu()
            )
        else:
            await query.edit_message_text(
                "❌ Jadwal tidak ditemukan.",
                reply_markup=create_main_menu()
            )
        return
    
    if data.startswith('rem_'):
        rem_time = int(data.replace('rem_', '').replace('min', '').replace('hour', '60'))
        
        if user_id in user_states:
            current_rem = user_states[user_id].get('remind_times', '5')
            rem_list = [int(x) for x in current_rem.split(',') if x.strip()]
            
            if rem_time not in rem_list:
                rem_list.append(rem_time)
                rem_list.sort(reverse=True)
                user_states[user_id]['remind_times'] = ','.join([str(x) for x in rem_list])
        
        await query.edit_message_text(
            f"✅ Reminder {rem_time} min ditambahkan.\n\nCurrent reminders: {user_states[user_id].get('remind_times', '5')}",
            reply_markup=create_reminder_selection_keyboard(user_states[user_id].get('remind_times', '5'))
        )
        return

def send_reminder_sync(user_id: int, schedule_id: int, title: str, schedule_time: datetime, rem_minutes: int):
    logger.info(f"send_reminder_sync called for schedule {schedule_id}, reminder {rem_minutes} min")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_reminder(user_id, schedule_id, title, schedule_time, rem_minutes))
        loop.close()
    except Exception as e:
        logger.error(f"Error in send_reminder_sync: {e}")

async def send_reminder(user_id: int, schedule_id: int, title: str, schedule_time: datetime, rem_minutes: int):
    app = None
    try:
        if schedule_time.tzinfo is None:
            schedule_time = schedule_time.replace(tzinfo=WITA_TIMEZONE)
        
        app = Application.builder().token(BOT_TOKEN).build()
        await app.initialize()
        await app.start()
        
        schedule = database.get_schedule_by_id(schedule_id)
        if schedule and schedule['status'] == 'completed':
            logger.info(f"Schedule {schedule_id} already completed, skipping reminder")
            return
        
        sent_reminders = database.get_sent_reminders(schedule_id)
        if str(rem_minutes) in sent_reminders:
            logger.info(f"Reminder {rem_minutes} already sent for schedule {schedule_id}")
            return
        
        msg = f"""
⏰ **Reminder Jadwal!**

📝 {title}
📅 {format_datetime(schedule_time)}

Jadwal akan dimulai dalam **{rem_minutes} menit**!
"""
        
        await app.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown',
                                   reply_markup=create_schedule_actions_keyboard(schedule_id))
        
        database.mark_reminder_sent(schedule_id, str(rem_minutes))
        logger.info(f"Reminder {rem_minutes} min sent for schedule {schedule_id} to user {user_id}")
    except Exception as e:
        logger.error(f"Failed to send reminder: {e}")
    finally:
        if app:
            try:
                await app.stop()
                await app.shutdown()
            except:
                pass

async def add_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received add command from user {update.effective_user.id}: {context.args}")
    
    if not context.args:
        await update.message.reply_text(
            "❌ Format salah!\n\nGunakan: `/add [judul] [tanggal] [jam]`\nContoh: `/add Meeting Senin 09:00`",
            parse_mode='Markdown',
            reply_markup=create_main_menu()
        )
        return
    
    args = context.args
    logger.info(f"Args: {args}")
    
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Argument kurang!\n\nMinimal: judul, hari, dan jam.\nContoh: `/add Meeting Senin 09:00`",
            parse_mode='Markdown',
            reply_markup=create_main_menu()
        )
        return
    
    time_str = args[-1]
    
    if ':' not in time_str:
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
    
    now = get_local_now()
    schedule_time = None
    
    days_mapping = {
        'senin': 0, 'selasa': 1, 'rabu': 2, 'kamis': 3,
        'jumat': 4, 'sabtu': 5, 'minggu': 6,
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }
    
    if day_str == 'today' or day_str == 'hari' or day_str == 'ini':
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
    schedule_id = database.add_schedule(user_id, title, "", schedule_time, remind_times='60,30,15,5')
    
    for rem_time in [60, 30, 15, 5]:
        reminder_time = schedule_time - timedelta(minutes=rem_time)
        if reminder_time > now:
            scheduler.add_job(
                send_reminder_sync,
                trigger=DateTrigger(run_date=reminder_time),
                args=[user_id, schedule_id, title, schedule_time, rem_time],
                id=f'reminder_{schedule_id}_{rem_time}',
                replace_existing=True
            )
    
    msg = f"""
✅ **Jadwal berhasil ditambahkan!**

📝 {title}
📅 {format_datetime(schedule_time)}

⏰ Reminder akan dikirim:
• 1 jam sebelum
• 30 menit sebelum
• 15 menit sebelum  
• 5 menit sebelum
"""
    await update.message.reply_text(msg, parse_mode='Markdown',
                                    reply_markup=create_schedule_actions_keyboard(schedule_id))

async def list_schedules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    schedules = database.get_user_schedules(user_id)
    
    if not schedules:
        await update.message.reply_text(
            "📭 Tidak ada jadwal.\n\nTambah dengan ➕ Tambah Jadwal",
            parse_mode='Markdown',
            reply_markup=create_main_menu()
        )
        return
    
    msg = "📋 **Daftar Jadwal Anda:**\n\n"
    for i, s in enumerate(schedules, 1):
        status_emoji = '✅' if s['status'] == 'completed' else '⏳'
        
        msg += f"{i}. {status_emoji} **{s['title']}**\n"
        msg += f"   📅 {format_schedule_display(s)}\n"
        msg += f"   ID: {s['id']}\n\n"
    
    msg += "Hapus dengan `/delete [id]`"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def today_schedules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    schedules = database.get_today_schedules(user_id)
    
    if not schedules:
        await update.message.reply_text(
            "📭 Tidak ada jadwal hari ini.\n\nTambah dengan `/add [judul] today [jam]`",
            parse_mode='Markdown',
            reply_markup=create_main_menu()
        )
        return
    
    msg = "📅 **Jadwal Hari Ini:**\n\n"
    for i, s in enumerate(schedules, 1):
        status_emoji = '✅' if s['status'] == 'completed' else '⏳'
        time_only = f"{s['schedule_time'].hour:02d}:{s['schedule_time'].minute:02d}"
        msg += f"{i}. {status_emoji} **{s['title']}**\n"
        msg += f"   🕐 {time_only}\n\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Ketik keyword!\n\nGunakan: `/search [keyword]`\nContoh: `/search meeting`",
            parse_mode='Markdown'
        )
        return
    
    keyword = ' '.join(context.args)
    user_id = update.effective_user.id
    schedules = database.search_schedules(user_id, keyword)
    
    if not schedules:
        await update.message.reply_text(
            f"🔍 Tidak ditemukan jadwal dengan keyword: **{keyword}**",
            parse_mode='Markdown'
        )
        return
    
    msg = f"🔍 **Hasil Search '{keyword}':**\n\n"
    for i, s in enumerate(schedules, 1):
        msg += f"{i}. **{s['title']}**\n"
        msg += f"   📅 {format_schedule_display(s)}\n"
        msg += f"   ID: {s['id']}\n\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format salah!\n\nGunakan: `/filter [start] [end]`\nContoh: `/filter 01/04 30/04`",
            parse_mode='Markdown'
        )
        return
    
    try:
        start_str = context.args[0]
        end_str = context.args[1]
        
        now = get_local_now()
        
        if '/' in start_str:
            parts = start_str.split('/')
            start_day = int(parts[0])
            start_month = int(parts[1])
            start_year = int(parts[2]) if len(parts) > 2 else now.year
            start_date = datetime(start_year, start_month, start_day)
        
        if '/' in end_str:
            parts = end_str.split('/')
            end_day = int(parts[0])
            end_month = int(parts[1])
            end_year = int(parts[2]) if len(parts) > 2 else now.year
            end_date = datetime(end_year, end_month, end_day, 23, 59, 59)
        
        user_id = update.effective_user.id
        schedules = database.get_schedules_by_date_range(user_id, start_date, end_date)
        
        if not schedules:
            await update.message.reply_text(
                f"📊 Tidak ada jadwal dalam range tersebut.",
                parse_mode='Markdown'
            )
            return
        
        msg = f"📊 **Jadwal {start_str} - {end_str}:**\n\n"
        for i, s in enumerate(schedules, 1):
            msg += f"{i}. **{s['title']}**\n"
            msg += f"   📅 {format_schedule_display(s)}\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(
            "❌ Format tanggal salah!\n\nGunakan: DD/MM atau DD/MM/YYYY",
            parse_mode='Markdown'
        )

async def delete_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Format salah!\n\nGunakan: `/delete [id]`\nLihat ID dengan `/list`",
            parse_mode='Markdown'
        )
        return
    
    try:
        schedule_id = int(context.args[0])
    except:
        await update.message.reply_text(
            "❌ ID tidak valid!\n\nGunakan angka dari `/list`",
            parse_mode='Markdown'
        )
        return
    
    user_id = update.effective_user.id
    deleted = database.delete_schedule(user_id, schedule_id)
    
    if deleted:
        try:
            for rem_time in [60, 30, 15, 5]:
                scheduler.remove_job(f'reminder_{schedule_id}_{rem_time}')
        except:
            pass
        await update.message.reply_text("✅ Jadwal berhasil dihapus!", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Jadwal tidak ditemukan atau bukan milik Anda.", parse_mode='Markdown')

async def complete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Format salah!\n\nGunakan: `/complete [id]`",
            parse_mode='Markdown'
        )
        return
    
    try:
        schedule_id = int(context.args[0])
    except:
        await update.message.reply_text(
            "❌ ID tidak valid!",
            parse_mode='Markdown'
        )
        return
    
    user_id = update.effective_user.id
    
    if database.update_schedule_status(user_id, schedule_id, 'completed'):
        await update.message.reply_text("✅ Jadwal ditandai selesai!", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Jadwal tidak ditemukan.", parse_mode='Markdown')

async def clear_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    schedules = database.get_user_schedules(user_id)
    
    if not schedules:
        await update.message.reply_text("📭 Tidak ada jadwal untuk dihapus.", parse_mode='Markdown')
        return
    
    for s in schedules:
        database.delete_schedule(user_id, s['id'])
        try:
            for rem_time in [60, 30, 15, 5]:
                scheduler.remove_job(f'reminder_{s["id"]}_{rem_time}')
        except:
            pass
    
    await update.message.reply_text(f"✅ {len(schedules)} jadwal berhasil dihapus!", parse_mode='Markdown')

def main():
    database.init_db()
    restore_reminders()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_schedule_command))
    app.add_handler(CommandHandler("list", list_schedules_command))
    app.add_handler(CommandHandler("today", today_schedules_command))
    app.add_handler(CommandHandler("delete", delete_schedule_command))
    app.add_handler(CommandHandler("clear", clear_all_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("filter", filter_command))
    app.add_handler(CommandHandler("complete", complete_command))
    
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot started with all features!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()