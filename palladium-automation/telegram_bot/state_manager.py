import json
import os
import logging
import threading
import tempfile
import shutil
import time
from filelock import FileLock

logger = logging.getLogger('palladium_automation.state_manager')

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'user_data.json')
LOCK_FILE = DATA_FILE + ".lock"

file_lock = threading.Lock() # Internal thread lock
# External file lock is handled by FileLock

user_locks = {}

def get_user_lock(user_id):
    str_user_id = str(user_id)
    if str_user_id not in user_locks:
        user_locks[str_user_id] = threading.Lock()
    return user_locks[str_user_id]

# States
IDLE = "IDLE"
WAITING_USERNAME = "WAITING_USERNAME"
WAITING_PASSWORD = "WAITING_PASSWORD"
WAITING_CAMPAIGN = "WAITING_CAMPAIGN"
WAITING_LINKS = "WAITING_LINKS"
WAITING_INTERVAL = "WAITING_INTERVAL"
READY_TO_RUN = "READY_TO_RUN"
COMPLETED = "COMPLETED"

def load_users():
    """Loads user data from the JSON file. Includes data migration to fix old states."""
    # Use both thread lock and file lock for maximum safety
    with file_lock:
        lock = FileLock(LOCK_FILE)
        try:
            with lock.acquire(timeout=10):
                if not os.path.exists(DATA_FILE):
                    return {}
                try:
                    with open(DATA_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    # DATA MIGRATION: Fix invalid runtime states
                    migrated = False
                    for uid, user_data in data.items():
                        state = user_data.get("state")
                        if state in ["RUNNING", "STOPPED", "ERROR"]:
                            user_data["state"] = COMPLETED
                            migrated = True
                            
                    if migrated:
                        # Re-save immediately if we migrated data
                        logger.info("Migrated invalid states in user_data.json to COMPLETED")
                        # Use same logic as save_users but inline to avoid nested locks
                        with tempfile.NamedTemporaryFile("w", delete=False, encoding='utf-8') as tmp:
                            json.dump(data, tmp, indent=4)
                            temp_name = tmp.name
                        os.replace(temp_name, DATA_FILE)
                        
                    return data
                except Exception as e:
                    logger.error(f"Error decoding {DATA_FILE}: {e}. Attempting recovery.")
                    
                    # Backup corrupted file
                    try:
                        if os.path.exists(DATA_FILE):
                            corrupt_file = DATA_FILE + ".corrupt"
                            shutil.copy(DATA_FILE, corrupt_file)
                    except Exception as backup_error:
                        logger.error(f"Failed to backup corrupted file: {backup_error}")
        
                    # Return empty dict to prevent crash, caller should handle re-init if needed
                    with open(DATA_FILE, "w", encoding="utf-8") as f:
                        json.dump({}, f)
                        
                    return {}
        except Exception as e:
            logger.error(f"Error loading users (Lock/File issue): {e}")
            return {}

def save_users(data):
    """Saves user data safely to the JSON file using atomic writes."""
    with file_lock:
        lock = FileLock(LOCK_FILE)
        try:
            with lock.acquire(timeout=10):
                # Ensure directory exists
                os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
                
                # Use 'w' mode with utf-8 encoding for safety
                # Atomic write: write to temp, then rename
                with tempfile.NamedTemporaryFile("w", delete=False, encoding='utf-8') as tmp:
                    json.dump(data, tmp, indent=4)
                    temp_name = tmp.name
                    
                # Replace is atomic on POSIX, usually safe on Windows too
                os.replace(temp_name, DATA_FILE)
                logger.info("Successfully saved user data.")
        except Exception as e:
            logger.error(f"Error saving users (Lock/File issue): {e}")

def get_user(user_id):
    """Gets data for a specific user. Initializes if not exists."""
    with get_user_lock(user_id):
        users = load_users()
        str_user_id = str(user_id)
        if str_user_id not in users:
            users[str_user_id] = {
                "state": IDLE,
                "username": "",
                "password": "",
                "campaign": "",
                "links": [],
                "interval": 10,
                "running": False,
                "current_index": 0,
                "last_updated": time.time()
            }
            save_users(users)
        return users[str_user_id]

def update_user(user_id, new_data):
    """Updates specific fields for a user."""
    with get_user_lock(user_id):
        users = load_users()
        str_user_id = str(user_id)
        if str_user_id not in users:
            users[str_user_id] = {}
        
        users[str_user_id].update(new_data)
        users[str_user_id]["last_updated"] = time.time()
        save_users(users)

def set_state(user_id, state):
    """Sets the current state for a user."""
    update_user(user_id, {"state": state})

def set_running(user_id, is_running):
    """Sets the running status for a user's automation."""
    update_user(user_id, {"running": is_running})

def is_running(user_id):
    """Checks if a user's automation is currently running."""
    user = get_user(user_id)
    return user.get("running", False)

def get_current_index(user_id):
    """Gets the current persistent link index for a user."""
    user = get_user(user_id)
    return user.get("current_index", 0)

def update_current_index(user_id, index):
    """Updates the persistent link index for a user."""
    update_user(user_id, {"current_index": index})

