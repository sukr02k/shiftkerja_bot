import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional
import os

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'schedules.db'))

WITA_OFFSET = timedelta(hours=8)

def get_local_now():
    utc_now = datetime.utcnow()
    return utc_now + WITA_OFFSET

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            schedule_time TEXT NOT NULL,
            remind_times TEXT DEFAULT '15',
            category TEXT DEFAULT 'general',
            status TEXT DEFAULT 'pending',
            recurring_type TEXT DEFAULT 'none',
            created_at TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            reminder_time TEXT NOT NULL,
            sent_at TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_list_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            view_type TEXT DEFAULT 'list',
            created_at TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS start_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            sent_at TEXT NOT NULL
        )
    ''')
    
    try:
        cursor.execute('ALTER TABLE schedules ADD COLUMN remind_times TEXT DEFAULT "15"')
    except:
        pass
    
    try:
        cursor.execute('ALTER TABLE schedules ADD COLUMN category TEXT DEFAULT "general"')
    except:
        pass
    
    try:
        cursor.execute('ALTER TABLE schedules ADD COLUMN status TEXT DEFAULT "pending"')
    except:
        pass
    
    try:
        cursor.execute('ALTER TABLE schedules ADD COLUMN recurring_type TEXT DEFAULT "none"')
    except:
        pass
    
    conn.commit()
    conn.close()

def add_schedule(user_id: int, title: str, description: str, schedule_time: datetime, 
                 remind_times: str = '5', recurring_type: str = 'none') -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO schedules (user_id, title, description, schedule_time, remind_times, 
                              status, recurring_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, title, description, schedule_time.isoformat(), remind_times, 
          'pending', recurring_type, get_local_now().isoformat()))
    schedule_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return schedule_id

def get_user_schedules(user_id: int, status: str = None) -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if status:
        cursor.execute('''
            SELECT id, title, description, schedule_time, remind_times, status, recurring_type
            FROM schedules
            WHERE user_id = ? AND status = ?
            ORDER BY schedule_time ASC
        ''', (user_id, status))
    else:
        cursor.execute('''
            SELECT id, title, description, schedule_time, remind_times, status, recurring_type
            FROM schedules
            WHERE user_id = ?
            ORDER BY schedule_time ASC
        ''', (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    schedules = []
    for row in rows:
        schedules.append({
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'schedule_time': datetime.fromisoformat(row[3]),
            'remind_times': row[4],
            'status': row[5],
            'recurring_type': row[6]
        })
    return schedules

def get_today_schedules(user_id: int) -> List[dict]:
    today = get_local_now().date()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, description, schedule_time, remind_times, status, recurring_type
        FROM schedules
        WHERE user_id = ? AND DATE(schedule_time) = ?
        ORDER BY schedule_time ASC
    ''', (user_id, today.isoformat()))
    rows = cursor.fetchall()
    conn.close()
    
    schedules = []
    for row in rows:
        schedules.append({
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'schedule_time': datetime.fromisoformat(row[3]),
            'remind_times': row[4],
            'status': row[5],
            'recurring_type': row[6]
        })
    return schedules

def delete_schedule(user_id: int, schedule_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM schedules WHERE id = ? AND user_id = ?', (schedule_id, user_id))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def get_all_pending_schedules() -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, title, description, schedule_time, remind_times, status, recurring_type
        FROM schedules
        WHERE schedule_time > ? AND status = 'pending'
        ORDER BY schedule_time ASC
    ''', (get_local_now().isoformat(),))
    rows = cursor.fetchall()
    conn.close()
    
    schedules = []
    for row in rows:
        schedules.append({
            'id': row[0],
            'user_id': row[1],
            'title': row[2],
            'description': row[3],
            'schedule_time': datetime.fromisoformat(row[4]),
            'remind_times': row[5],
            'status': row[6],
            'recurring_type': row[7]
        })
    return schedules

def search_schedules(user_id: int, keyword: str) -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, description, schedule_time, remind_times, status, recurring_type
        FROM schedules
        WHERE user_id = ? AND (title LIKE ? OR description LIKE ?)
        ORDER BY schedule_time ASC
    ''', (user_id, f'%{keyword}%', f'%{keyword}%'))
    rows = cursor.fetchall()
    conn.close()
    
    schedules = []
    for row in rows:
        schedules.append({
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'schedule_time': datetime.fromisoformat(row[3]),
            'remind_times': row[4],
            'status': row[5],
            'recurring_type': row[6]
        })
    return schedules

def get_schedules_by_date_range(user_id: int, start_date: datetime, end_date: datetime) -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, description, schedule_time, remind_times, status, recurring_type
        FROM schedules
        WHERE user_id = ? AND schedule_time >= ? AND schedule_time <= ?
        ORDER BY schedule_time ASC
    ''', (user_id, start_date.isoformat(), end_date.isoformat()))
    rows = cursor.fetchall()
    conn.close()
    
    schedules = []
    for row in rows:
        schedules.append({
            'id': row[0],
            'title': row[1],
            'description': row[2],
            'schedule_time': datetime.fromisoformat(row[3]),
            'remind_times': row[4],
            'status': row[5],
            'recurring_type': row[6]
        })
    return schedules

def get_schedule_by_id(schedule_id: int) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, title, description, schedule_time, remind_times, status, recurring_type
        FROM schedules
        WHERE id = ?
    ''', (schedule_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row[0],
            'user_id': row[1],
            'title': row[2],
            'description': row[3],
            'schedule_time': datetime.fromisoformat(row[4]),
            'remind_times': row[5],
            'status': row[6],
            'recurring_type': row[7]
        }
    return None

def update_schedule_status(user_id: int, schedule_id: int, status: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE schedules 
        SET status = ? 
        WHERE id = ? AND user_id = ?
    ''', (status, schedule_id, user_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def update_schedule(user_id: int, schedule_id: int, title: str = None, description: str = None, 
                   schedule_time: datetime = None, remind_times: str = None) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    
    if schedule_time is not None:
        updates.append("schedule_time = ?")
        params.append(schedule_time.isoformat())
    
    if remind_times is not None:
        updates.append("remind_times = ?")
        params.append(remind_times)
    
    if not updates:
        conn.close()
        return False
    
    params.extend([schedule_id, user_id])
    
    query = f"UPDATE schedules SET {', '.join(updates)} WHERE id = ? AND user_id = ?"
    cursor.execute(query, params)
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def mark_reminder_sent(schedule_id: int, reminder_time: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reminders_sent (schedule_id, reminder_time, sent_at)
        VALUES (?, ?, ?)
    ''', (schedule_id, reminder_time, get_local_now().isoformat()))
    conn.commit()
    conn.close()

def get_sent_reminders(schedule_id: int) -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT reminder_time FROM reminders_sent
        WHERE schedule_id = ?
    ''', (schedule_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def delete_schedule_by_id(schedule_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def add_active_list_view(user_id: int, message_id: int, chat_id: int, view_type: str = 'list'):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM active_list_views WHERE user_id = ?', (user_id,))
    cursor.execute('''
        INSERT INTO active_list_views (user_id, message_id, chat_id, view_type, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, message_id, chat_id, view_type, get_local_now().isoformat()))
    conn.commit()
    conn.close()

def get_all_active_list_views() -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, message_id, chat_id, view_type FROM active_list_views')
    rows = cursor.fetchall()
    conn.close()
    return [{'user_id': row[0], 'message_id': row[1], 'chat_id': row[2], 'view_type': row[3]} for row in rows]

def remove_active_list_view(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM active_list_views WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def mark_start_notification_sent(schedule_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO start_notifications_sent (schedule_id, sent_at)
        VALUES (?, ?)
    ''', (schedule_id, get_local_now().isoformat()))
    conn.commit()
    conn.close()

def get_start_notifications_sent(schedule_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM start_notifications_sent WHERE schedule_id = ?', (schedule_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_schedules_starting_now() -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = get_local_now()
    time_window_start = now - timedelta(minutes=6)
    time_window_end = now + timedelta(minutes=1)
    
    cursor.execute('''
        SELECT id, user_id, title, schedule_time, remind_times, status
        FROM schedules
        WHERE schedule_time >= ? AND schedule_time <= ? AND status = 'pending'
    ''', (time_window_start.isoformat(), time_window_end.isoformat()))
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'id': row[0],
        'user_id': row[1],
        'title': row[2],
        'schedule_time': datetime.fromisoformat(row[3]),
        'remind_times': row[4],
        'status': row[5]
    } for row in rows]