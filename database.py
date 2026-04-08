import sqlite3
from datetime import datetime
from typing import List, Optional
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'schedules.db')

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
            remind_before INTEGER DEFAULT 15,
            created_at TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def add_schedule(user_id: int, title: str, description: str, schedule_time: datetime, remind_before: int = 15) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO schedules (user_id, title, description, schedule_time, remind_before, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, title, description, schedule_time.isoformat(), remind_before, datetime.now().isoformat()))
    schedule_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return schedule_id

def get_user_schedules(user_id: int) -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, description, schedule_time, remind_before
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
            'remind_before': row[4]
        })
    return schedules

def get_today_schedules(user_id: int) -> List[dict]:
    today = datetime.now().date()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, description, schedule_time, remind_before
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
            'remind_before': row[4]
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
        SELECT id, user_id, title, description, schedule_time, remind_before
        FROM schedules
        WHERE schedule_time > ?
        ORDER BY schedule_time ASC
    ''', (datetime.now().isoformat(),))
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
            'remind_before': row[5]
        })
    return schedules

def delete_schedule_by_id(schedule_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted