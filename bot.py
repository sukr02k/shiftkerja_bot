import os
import logging
import re
from datetime import datetime, timedelta
from calendar import monthrange
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

user_states = {}

def format_datetime(dt: datetime) -> str:
    days = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    day_name = days[dt.weekday()]
    month_name = months[dt.month - 1]
    return f"{day_name}, {dt.day} {month_name} {dt.year} - {dt.hour:02d}:{dt.minute:02d}"

def parse_time_natural(text: str) -> tuple:
    text = text.lower()
    
    time_patterns = [
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
    now = datetime.now()
    
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
    now = datetime.now()
    
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
    ]
    return InlineKeyboardMarkup(keyboard)

def create_shift_selection_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton('🌙 Night (00:00-08:00)', callback_data='shift_night'),
        ],
        [
            InlineKeyboardButton('☀️ Morning (08:00-16:00)', callback_data='shift_morning'),
        ],
        [
            InlineKeyboardButton('🌆 Evening (16:00-00:00)', callback_data='shift_evening'),
        ],
        [
            InlineKeyboardButton('🔄 Special (11:00-19:00)', callback_data='shift_special'),
        ],
        [
            InlineKeyboardButton('🕐 Custom Time', callback_data='shift_custom'),
        ],
        [
            InlineKeyboardButton('❌ Cancel', callback_data='cancel_time'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_hour_selection_keyboard(shift_type: str) -> InlineKeyboardMarkup:
    shift_hours = {
        'night': [(0,1,2,3,4,5,6,7)],
        'morning': [(8,9,10,11), (12,13,14,15)],
        'evening': [(16,17,18,19), (20,21,22,23)],
        'special': [(11,12,13,14), (15,16,17,18,19)],
    }
    
    hours = shift_hours.get(shift_type, [(0,1,2,3,4,5,6,7), (8,9,10,11), (12,13,14,15), (16,17,18,19), (20,21,22,23)])
    
    keyboard = []
    for hour_row in hours:
        row = [InlineKeyboardButton(f'{h:02d}:XX', callback_data=f'hour_{h}') for h in hour_row]
        keyboard.append(row)
    
    keyboard.append([
        InlineKeyboardButton('⬅️ Back', callback_data='back_shift'),
        InlineKeyboardButton('❌ Cancel', callback_data='cancel_time'),
    ])
    
    return InlineKeyboardMarkup(keyboard)

def create_minute_selection_keyboard(hour: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(f'{hour:02d}:00', callback_data=f'time_{hour:02d}:00'),
            InlineKeyboardButton(f'{hour:02d}:15', callback_data=f'time_{hour:02d}:15'),
            InlineKeyboardButton(f'{hour:02d}:30', callback_data=f'time_{hour:02d}:30'),
            InlineKeyboardButton(f'{hour:02d}:45', callback_data=f'time_{hour:02d}:45'),
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
    reminder_options = [5, 15, 30, 60]
    selected_list = [int(x) for x in selected_reminders.split(',') if x.strip()]
    
    keyboard = []
    row1 = []
    row2 = []
    
    for i, rem in enumerate(reminder_options):
        is_selected = rem in selected_list
        
        if rem == 60:
            label = '1 hour'
        else:
            label = f'{rem} min'
        
        if is_selected:
            btn_text = f'✅ {label}'
        else:
            btn_text = f'⬜ {label}'
        
        callback_data = f'toggle_rem_{rem}'
        
        if i < 2:
            row1.append(InlineKeyboardButton(btn_text, callback_data=callback_data))
        else:
            row2.append(InlineKeyboardButton(btn_text, callback_data=callback_data))
    
    keyboard.append(row1)
    keyboard.append(row2)
    
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
🎉 **Bot Jadwal Kerja - Shift Bot** 

Bot untuk manajemen jadwal kerja dengan fitur lengkap!

**Quick Actions:**
• ➕ Tambah Jadwal
• 📋 Lihat semua jadwal  
• 📅 Jadwal hari ini
• 🔍 Search jadwal
• 📊 Filter by date/category

**Natural Language:**
Ketik: "meeting besok jam 2 siang"
Bot akan otomatis parse dan create jadwal!

**Commands:**
/add - Tambah jadwal manual
/search [keyword] - Cari jadwal
/filter [start] [end] - Filter by date
/complete [id] - Tandai selesai
/settings - Pengaturan

Klik tombol di bawah untuk mulai! 👇
"""
    
    await update.message.reply_text(welcome_msg, parse_mode='Markdown', 
                                     reply_markup=create_main_menu())

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

**🔔 MULTIPLE REMINDERS:**
Bot akan remind di:
• 1 jam sebelum
• 30 menit sebelum  
• 15 menit sebelum
• 5 menit sebelum

**📋 MANAGE JADWAL:**
• /list - Semua jadwal
• /today - Hari ini
• /search [keyword] - Cari
• /filter [start] [end] - Filter tanggal
• /complete [id] - Tandai selesai
• /delete [id] - Hapus

**📅 INLINE CALENDAR:**
Klik tombol ➕ Tambah Jadwal
Pilih tanggal dari calendar visual!

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
                date = state.get('date', datetime.now())
                schedule_time = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
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
        
        if shift_type == 'custom':
            msg = "🕐 Pilih jam secara manual:"
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_all_hours_keyboard())
        else:
            shift_names = {
                'night': '🌙 Night Shift (00:00-08:00)',
                'morning': '☀️ Morning Shift (08:00-16:00)',
                'evening': '🌆 Evening Shift (16:00-00:00)',
                'special': '🔄 Special Shift (11:00-19:00)'
            }
            
            msg = f"{shift_names.get(shift_type, 'Pilih Jam')}\n\nKlik jam:"
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_hour_selection_keyboard(shift_type))
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
        year = user_states[user_id].get('date', datetime.now()).year
        month = user_states[user_id].get('date', datetime.now()).month
        
        msg = "📅 Pilih tanggal:"
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_calendar_keyboard(year, month))
        return
    
    if data.startswith('time_'):
        time_str = data.replace('time_', '')
        hour, minute = map(int, time_str.split(':'))
        
        if user_id in user_states:
            date = user_states[user_id].get('date', datetime.now())
            schedule_time = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
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
    
    if data == 'set_reminders':
        if user_id in user_states:
            remind_times = user_states[user_id].get('remind_times', '')
            
            if not remind_times:
                remind_times = '5'
            
            schedule_time = user_states[user_id].get('schedule_time', datetime.now())
            title = user_states[user_id].get('title', 'Jadwal')
            
            schedule_id = database.add_schedule(
                user_id, title, "", schedule_time,
                remind_times=remind_times
            )
            
            for rem_time in [int(x) for x in remind_times.split(',')]:
                reminder_datetime = schedule_time - timedelta(minutes=rem_time)
                if reminder_datetime > datetime.now():
                    scheduler.add_job(
                        send_reminder,
                        trigger=DateTrigger(run_date=reminder_datetime),
                        args=[user_id, schedule_id, title, schedule_time, rem_time],
                        id=f'reminder_{schedule_id}_{rem_time}',
                        replace_existing=True
                    )
            
            remind_str = ', '.join([f'{x} min' for x in remind_times.split(',')])
            msg = f"""
✅ **Jadwal berhasil ditambahkan!**

📝 {title}
📅 {format_datetime(schedule_time)}

🔔 Reminder: {remind_str} sebelum
"""
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_schedule_actions_keyboard(schedule_id))
            user_states[user_id] = {}
        return
    
    if data == 'skip_reminder':
        if user_id in user_states:
            schedule_time = user_states[user_id].get('schedule_time', datetime.now())
            title = user_states[user_id].get('title', 'Jadwal')
            
            schedule_id = database.add_schedule(
                user_id, title, "", schedule_time,
                remind_times=''
            )
            
            msg = f"""
✅ **Jadwal berhasil ditambahkan!**

📝 {title}
📅 {format_datetime(schedule_time)}

🔔 No reminder set
"""
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_schedule_actions_keyboard(schedule_id))
            user_states[user_id] = {}
        return
    
    if data == 'back_to_schedule':
        if user_id in user_states:
            schedule_time = user_states[user_id].get('schedule_time', datetime.now())
            title = user_states[user_id].get('title', 'Jadwal')
            
            msg = f"""
📝 Judul: {title}
📅 Tanggal: {format_datetime(schedule_time)}

⏰ Pilih waktu lagi:
"""
            await query.edit_message_text(msg, parse_mode='Markdown',
                                          reply_markup=create_shift_selection_keyboard())
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
        for i, s in enumerate(schedules, 1):
            status_emoji = '✅' if s['status'] == 'completed' else '⏳'
            priority_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(s['priority'], '⚪')
            
            msg += f"{i}. {status_emoji} {priority_emoji} **{s['title']}**\n"
            msg += f"   📅 {format_datetime(s['schedule_time'])}\n"
            msg += f"   📁 {s['category']} | ID: {s['id']}\n\n"
        
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
        for i, s in enumerate(schedules, 1):
            status_emoji = '✅' if s['status'] == 'completed' else '⏳'
            time_only = f"{s['schedule_time'].hour:02d}:{s['schedule_time'].minute:02d}"
            msg += f"{i}. {status_emoji} **{s['title']}**\n"
            msg += f"   🕐 {time_only}\n\n"
        
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
        user_states[user_id] = {'waiting_for': 'filter_start'}
        await query.edit_message_text(
            "📊 Ketik tanggal awal (DD/MM/YYYY):",
            reply_markup=None
        )
        return
    
    if data == 'help':
        await help_command(update, context)
        return
    
    if data == 'settings':
        msg = """
⚙️ **Settings**

**🔔 Reminder Default:**
60 min, 30 min, 15 min, 5 min

**📁 Categories Available:**
• general
• work
• meeting
• deadline
• personal

**🔴 Priority Levels:**
• high
• medium
• low

Settings dapat di-custom saat create jadwal.
"""
        await query.edit_message_text(msg, parse_mode='Markdown',
                                      reply_markup=create_main_menu())
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
            current_rem = user_states[user_id].get('remind_times', '15')
            rem_list = [int(x) for x in current_rem.split(',')]
            
            if rem_time not in rem_list:
                rem_list.append(rem_time)
                rem_list.sort(reverse=True)
                user_states[user_id]['remind_times'] = ','.join([str(x) for x in rem_list])
        
        await query.edit_message_text(
            f"✅ Reminder {rem_time} min ditambahkan.\n\nCurrent reminders: {user_states[user_id].get('remind_times', '15')}",
            reply_markup=create_reminder_options_keyboard()
        )
        return

async def send_reminder(user_id: int, schedule_id: int, title: str, schedule_time: datetime, rem_minutes: int):
    try:
        app = Application.builder().token(BOT_TOKEN).build()
        
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
    
    now = datetime.now()
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
                send_reminder,
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
        priority_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(s['priority'], '⚪')
        
        msg += f"{i}. {status_emoji} {priority_emoji} **{s['title']}**\n"
        msg += f"   📅 {format_datetime(s['schedule_time'])}\n"
        msg += f"   📁 {s['category']} | ID: {s['id']}\n\n"
    
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
        msg += f"   📅 {format_datetime(s['schedule_time'])}\n"
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
        
        now = datetime.now()
        
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
            msg += f"   📅 {format_datetime(s['schedule_time'])}\n\n"
        
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