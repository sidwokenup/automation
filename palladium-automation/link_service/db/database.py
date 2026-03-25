import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "links.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS links ( 
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id TEXT, 
        url TEXT, 
        status TEXT DEFAULT 'ACTIVE', 
        last_checked TIMESTAMP, 
        fail_count INTEGER DEFAULT 0 
    )
    ''')
    
    conn.commit()
    conn.close()

# Initialize db on import
init_db()