import os
import json
import time

ERROR_DIR = "logs"

def get_error_file(user_id):
    os.makedirs(ERROR_DIR, exist_ok=True)
    return os.path.join(ERROR_DIR, f"user_{user_id}_error.json")

def save_error(user_id, error_data):
    file_path = get_error_file(user_id)
    error_data["timestamp"] = time.time()
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(error_data, f, indent=2)

def load_error(user_id):
    file_path = get_error_file(user_id)
    
    if not os.path.exists(file_path):
        return None
    
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def clear_error(user_id):
    file_path = get_error_file(user_id)
    if os.path.exists(file_path):
        os.remove(file_path)