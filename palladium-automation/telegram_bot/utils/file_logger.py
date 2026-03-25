import os
import time

LOG_DIR = "logs"

def get_log_file(user_id):
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"user_{user_id}.log")

def write_log(user_id, message):
    file_path = get_log_file(user_id)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    
    log_entry = f"[{timestamp}] {message}\n"
    
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(log_entry)

def read_logs(user_id, limit=20):
    file_path = get_log_file(user_id)
    
    if not os.path.exists(file_path):
        return []
    
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    return lines[-limit:]
