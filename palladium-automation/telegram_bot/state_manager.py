import json
import os
import logging

logger = logging.getLogger('palladium_automation.state_manager')

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'users.json')

# States
WAITING_USERNAME = "WAITING_USERNAME"
WAITING_PASSWORD = "WAITING_PASSWORD"
WAITING_CAMPAIGN = "WAITING_CAMPAIGN"
WAITING_LINKS = "WAITING_LINKS"
WAITING_INTERVAL = "WAITING_INTERVAL"
COMPLETED = "COMPLETED"

def load_users():
    """Loads user data from the JSON file."""
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error(f"Error decoding {DATA_FILE}. Returning empty dict.")
        return {}
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return {}

def save_users(data):
    """Saves user data to the JSON file."""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving users: {e}")

def get_user(user_id):
    """Gets data for a specific user. Initializes if not exists."""
    users = load_users()
    str_user_id = str(user_id)
    if str_user_id not in users:
        users[str_user_id] = {
            "state": None,
            "username": "",
            "password": "",
            "campaign": "",
            "links": [],
            "interval": 10,
            "running": False,
            "current_index": 0
        }
        save_users(users)
    return users[str_user_id]

def update_user(user_id, new_data):
    """Updates specific fields for a user."""
    users = load_users()
    str_user_id = str(user_id)
    if str_user_id not in users:
        users[str_user_id] = {}
    
    users[str_user_id].update(new_data)
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

