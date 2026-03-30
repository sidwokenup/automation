import logging
import threading
import time
import os
import random
import requests
from automation.browser import launch_browser, login, navigate_to_campaigns, open_campaign, update_target_link, ensure_logged_in, ensure_campaign_page

logger = logging.getLogger('palladium_automation.runner')

# Create a lock for critical user state updates (like active_links/flagged_links)
user_state_lock = threading.Lock()

def validate_proxy(proxy_url): 
    try: 
        proxies = { 
            "http": proxy_url, 
            "https": proxy_url 
        } 
        res = requests.get("https://api.ipify.org", proxies=proxies, timeout=10) 
        if res.status_code == 200: 
            return True, res.text 
        return False, f"HTTP {res.status_code}"
    except Exception as e: 
        return False, str(e) 

def get_next_proxy(user_id, user_data): 
    proxies = user_data.get("proxies", []) 
    if not proxies: 
        # Fallback to legacy single proxy if exists
        legacy_proxy = user_data.get("proxy")
        if legacy_proxy and isinstance(legacy_proxy, dict) and legacy_proxy.get("list"):
            # It's the old dict format
            idx = legacy_proxy.get("current_index", 0)
            if idx < len(legacy_proxy["list"]):
                p = legacy_proxy["list"][idx]
                if p.get("username"):
                    return f"{p['server'].replace('http://', 'http://' + p['username'] + ':' + p['password'] + '@')}"
                return p["server"]
        return None 

    index = user_data.get("current_proxy_index", 0) 
    if index >= len(proxies):
        index = 0
    proxy = proxies[index] 

    user_data["current_proxy_index"] = (index + 1) % len(proxies) 
    
    from telegram_bot.state_manager import update_user
    
    # Sync with legacy proxy dict so browser.py uses the same proxy
    update_data = {"current_proxy_index": user_data["current_proxy_index"]}
    if "proxy" in user_data and isinstance(user_data["proxy"], dict):
        user_data["proxy"]["current_index"] = index # set to current index so browser.py uses it! (browser.py will rotate it afterwards)
        update_data["proxy"] = user_data["proxy"]
        
    update_user(user_id, update_data)

    return proxy

# asyncio removed

def recover_running_automations():
    """Recovers automations that were running before a shutdown."""
    from telegram_bot.state_manager import load_users
    
    logger = logging.getLogger('palladium_automation.runner')
    users = load_users()
    
    logger.info(f"Checking {len(users)} users for auto-recovery...")
    
    for user_id, data in users.items():
        if data.get("running"):
            str_uid = str(user_id)
            
            # Safety: do NOT start duplicate thread if already active in this process
            if str_uid in active_threads:
                thread = active_threads[str_uid]
                if thread.is_alive():
                    logger.info(f"User {user_id} automation already active. Skipping recovery.")
                    continue
                else:
                    # Clean dead thread reference
                    del active_threads[str_uid]
            
            logger.info(f"Recovering automation for user {user_id}...")
            
            try:
                # Re-launch automation thread
                # Note: We don't have the bot instance here during startup easily, 
                # but send_telegram_message handles None gracefully.
                # Alerts won't work until the thread gets a bot instance, 
                # but the loop will run.
                start_automation(user_id, data, logger, bot_instance=None)
                logger.info(f"Recovered automation started successfully for {user_id}")
            except Exception as e:
                logger.error(f"Recovery failed for {user_id}: {e}")

# Campaign locks
active_campaigns = {} # Map campaign name to user_id
campaign_lock = threading.Lock()

def acquire_campaign(campaign, user_id):
    with campaign_lock:
        if campaign in active_campaigns and active_campaigns[campaign] != str(user_id):
            return False
        active_campaigns[campaign] = str(user_id)
        return True

def release_campaign(campaign, user_id):
    with campaign_lock:
        if campaign in active_campaigns and active_campaigns[campaign] == str(user_id):
            del active_campaigns[campaign]

# Global storage for tracking user threads and flags
user_threads = {}
active_threads = {}  # Track threads to prevent duplicates
user_flags = {}
user_status = {}
user_logs = {}
user_bots = {} # Store bot instance per user
user_error_state = {} # Track error state per user: {user_id: {"active": bool, "last_time": float}}
ERROR_COOLDOWN = 300 # 5 minutes
MAX_ERRORS = 5 # Maximum consecutive errors before stopping automation

from telegram import Bot
from telegram_bot.utils.notifier import send_telegram_photo, send_telegram_message

def notify_user(user_id, message): 
    try: 
        bot = user_bots.get(str(user_id)) 
        if bot: 
            send_telegram_message(bot, user_id, message) 
    except Exception as e: 
        logger.error(f"Notification failed: {e}") 

# We no longer need the direct send_telegram_message function here as we use the notifier

# Removed send_error_alert as it is no longer needed (async wrapper)

def is_system_error(error_msg): 
    SYSTEM_ERRORS = [ 
        "timeout", 
        "waiting for selector", 
        "network", 
        "browser closed", 
        "context closed",
        "no module named",
        "importerror"
    ] 
    return any(e in error_msg.lower() for e in SYSTEM_ERRORS) 

def is_link_error(error_msg): 
    LINK_ERRORS = [ 
        "link validation failed", 
        "page not found", 
        "blocked", 
        "invalid url",
        "input_field_not_found",
        "input_not_set_properly",
        "link_not_saved_on_platform"
    ] 
    return any(e in error_msg.lower() for e in LINK_ERRORS) 

def move_to_next_link(user_id): 
    str_user_id = str(user_id) 

    user = get_user(str_user_id) 

    active_links = user.get("active_links", []) 
    current_index = user.get("current_index", 0) 

    if not active_links: 
        return 

    # Move to next index 
    new_index = (current_index + 1) % len(active_links) 

    update_user(str_user_id, { 
        "current_index": new_index 
    }) 

    # Debug log 
    logger.info(f"[User {str_user_id}] ➡️ Moved to next link index: {new_index}")
    add_log(str_user_id, f"➡️ Moved to next link index: {new_index}")

def get_next_index(current_index, total_links): 
    return (current_index + 1) % total_links if total_links > 0 else 0

def should_send_error(user_id):
    """Checks if an error alert should be sent based on cooldown."""
    now = time.time()
    str_user_id = str(user_id)
    
    if str_user_id not in user_error_state:
        user_error_state[str_user_id] = {"active": False, "last_time": 0}
        
    last_time = user_error_state[str_user_id]["last_time"]
    
    if now - last_time > ERROR_COOLDOWN:
        return True
    return False

def mark_error_sent(user_id):
    """Marks that an error has been sent and updates the timestamp."""
    str_user_id = str(user_id)
    if str_user_id not in user_error_state:
        user_error_state[str_user_id] = {"active": False, "last_time": 0}
    
    user_error_state[str_user_id]["active"] = True
    user_error_state[str_user_id]["last_time"] = time.time()

def mark_error_resolved(user_id):
    """Marks the error state as resolved."""
    str_user_id = str(user_id)
    if str_user_id in user_error_state and user_error_state[str_user_id]["active"]:
        user_error_state[str_user_id]["active"] = False
        return True
    return False

from telegram_bot.utils.file_logger import write_log
from telegram_bot.state_manager import get_user, update_user
from telegram_bot.utils.error_tracker import save_error, clear_error
from telegram_bot.utils.error_classifier_simple import classify_error as classify_error_simple

def add_log(user_id, message):
    """Adds a log entry for a specific user."""
    str_user_id = str(user_id)
    
    if str_user_id not in user_logs:
        user_logs[str_user_id] = []
        
    # Ensure consistent format
    if not any(message.startswith(tag) for tag in ["[INFO]", "[ERROR]", "[SUCCESS]", "✅", "❌", "⚠️", "➡️", "🔄", "🔁", "🚨"]):
        message = f"[INFO] {message}"
        
    timestamp = time.strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    
    user_logs[str_user_id].append(log_entry)
    
    # Keep only last 25 logs
    if len(user_logs[str_user_id]) > 25:
        user_logs[str_user_id] = user_logs[str_user_id][-25:]

    # NEW: persist to file 
    try: 
        write_log(user_id, message) 
    except: 
        pass 

from telegram_bot.utils.error_tracker import save_error
from telegram_bot.utils.error_classifier_simple import classify_error as classify_error_simple

def log_and_track_error(user_id, error_message, context="automation_loop", consecutive_errors=1, stop_reason=None):
    """Centralized helper for logging and tracking errors."""
    logger = logging.getLogger('palladium_automation.runner')
    logger.error(f"[User {user_id}] {error_message}")
    add_log(user_id, f"[ERROR] {error_message}")
    
    error_type_simple = classify_error_simple(error_message)
    error_data = {
        "error_message": error_message,
        "error_type": error_type_simple,
        "context": context,
        "consecutive_errors": consecutive_errors
    }
    if stop_reason:
        error_data["stop_reason"] = stop_reason
        
    save_error(user_id, error_data)

def get_logs(user_id):
    """Retrieves logs for a specific user."""
    return user_logs.get(str(user_id), [])

def send_error_with_screenshot(page, user_id, message):
    """Helper to consistently capture and send screenshots on errors."""
    screenshot_path = None
    try:
        if page:
            os.makedirs("logs", exist_ok=True)
            screenshot_filename = f"error_{user_id}_{int(time.time())}.png"
            screenshot_path = os.path.join("logs", screenshot_filename)
            page.screenshot(path=screenshot_path, full_page=True)
            add_log(user_id, f"Screenshot saved: {screenshot_filename}")
    except Exception as e:
        logger = logging.getLogger('palladium_automation.runner')
        logger.error(f"[User {user_id}] Screenshot failed: {e}")

    app_instance = user_bots.get(str(user_id))
    if app_instance:
        if screenshot_path:
            send_telegram_photo(app_instance, user_id, screenshot_path, message)
        else:
            send_telegram_message(app_instance, user_id, message)
    return screenshot_path

def mark_link_as_flagged(user_id, link, page=None):
    """
    Directly flags a link as invalid, removes it from rotation, and updates state.
    If page is provided, it will send a screenshot notification instead of just text.
    """
    str_user_id = str(user_id)
    user_data = get_user(str_user_id)
    handle_link_failure(str_user_id, link, user_data, add_log, notify_user, page=page)

def handle_link_failure(user_id, current_link, user_data, add_log, notify_user, page=None):
    str_user_id = str(user_id)
    links_data = user_data.get("links_data", [])
    for link_obj in links_data:
        if link_obj.get("url") == current_link:
            link_obj["fail_count"] = link_obj.get("fail_count", 0) + 1
            link_obj["status"] = "failed"
            link_obj["last_checked"] = time.time()
            break
            
    active_links = user_data.get("active_links", [])
    flagged_links = user_data.get("flagged_links", [])
    
    if current_link in flagged_links:
        add_log(str_user_id, "DUPLICATE FLAG PREVENTED")
    else:
        if current_link in active_links:
            active_links.remove(current_link)
            add_log(str_user_id, "LINK FAILED → removed")
        flagged_links.append(current_link)
        
    retry_map = user_data.get("retry_map", {})
    retry_map.pop(current_link, None)
    
    link_stats = user_data.get("link_stats", {"total_rotations": 0, "failures": 0})
    link_stats["failures"] = link_stats.get("failures", 0) + 1
    
    with user_state_lock:
        update_user(str_user_id, {
            "active_links": active_links,
            "flagged_links": flagged_links,
            "retry_map": retry_map,
            "link_stats": link_stats,
            "links_data": links_data
        })
    
    msg = f"❌ Link flagged and removed:\n{current_link}"
    
    # Try to open the bad link in a temporary tab just to capture its error screen
    screenshot_page = None
    if page:
        try:
            screenshot_page = page.context.new_page()
            screenshot_page.goto(current_link, timeout=10000)
            screenshot_page.wait_for_timeout(2000) # Let error render
        except Exception:
            pass # If it times out or fails entirely, we still use the blank/error page for screenshot

    if screenshot_page:
        send_error_with_screenshot(screenshot_page, str_user_id, msg)
        try:
            screenshot_page.close()
        except:
            pass
    elif page:
        send_error_with_screenshot(page, str_user_id, msg)
    else:
        notify_user(str_user_id, msg)

def process_link_failure(page, user_id, current_link, reason):
    """Centralized handler for all link failures."""
    str_user_id = str(user_id)
    add_log(str_user_id, f"❌ Link failed: {reason}")
    send_error_with_screenshot(page, str_user_id, f"❌ Automation Error: {reason}")

    user = get_user(str_user_id)
    handle_link_failure(str_user_id, current_link, user, add_log, notify_user, page=page)
    # Do NOT call move_to_next_link here! 
    # Removing the item from the list automatically shifts the next item to the current_index.


def start_automation(user_id, config, logger, bot_instance=None):
    """Starts the automation loop for a user in a separate thread."""
    str_user_id = str(user_id)
    
    if bot_instance:
        user_bots[str(user_id)] = bot_instance
    
    # Prevent Duplicate Start (CRITICAL)
    from telegram_bot.state_manager import load_users, save_users
    user_data = load_users()
    
    # Check JSON state
    if user_data.get(str_user_id, {}).get("running"):
        logger.warning(f"Automation already running for user {user_id} (state check)")
        return False

    # Check in-memory thread
    if str_user_id in active_threads:
        thread = active_threads[str_user_id]
        if thread.is_alive():
            logger.warning(f"Automation already running for user {user_id} (thread active)")
            return False
        else:
            # Clean dead thread
            del active_threads[str_user_id]

    # Prevent Duplicate Campaign Usage globally using centralized lock
    campaign_name = config.get("campaign")
    if not acquire_campaign(campaign_name, str_user_id):
        logger.error(f"Campaign {campaign_name} is already in use by another user.")
        raise Exception(f"Campaign '{campaign_name}' is already running. Please stop it first.")
    
    if user_flags.get(str_user_id, False):
        logger.warning(f"Automation already running for user {user_id}")
        return False

    # Reset State on /run (IMPORTANT)
    links = config.get("links", [])
    user_data[str_user_id]["current_index"] = 0
    user_data[str_user_id]["retry_map"] = {}
    user_data[str_user_id]["link_stats"] = {
        "total_rotations": 0,
        "failures": 0
    }
    user_data[str_user_id]["active_links"] = links.copy()
    user_data[str_user_id]["flagged_links"] = []
    user_data[str_user_id]["links_data"] = []

    # Set flag to True
    user_flags[str_user_id] = True
    
    # Initialize status
    user_status[str_user_id] = {
        "running": True,
        "current_link": None,
        "last_updated": None,
        "total_links": len(config.get("links", [])),
        "campaign": config.get("campaign", "Unknown"),
        "start_time": time.time()
    }
    
    # Update running status in disk
    # user_data was loaded above
    if str_user_id in user_data:
        user_data[str_user_id]["running"] = True
        # Do NOT modify state here, state is only for setup flow
        save_users(user_data)
    elif str_user_id not in user_data: # Should exist, but safety check
         # This case should ideally be handled by setup flow, but just in case
         pass
    
    # Create and start thread
    thread = threading.Thread(target=automation_loop, args=(str_user_id, config, logger), daemon=True)
    user_threads[str_user_id] = thread
    thread.start()
    
    # Register Thread
    active_threads[str_user_id] = thread
    
    logger.info(f"Started automation thread for user {user_id}")
    add_log(str_user_id, "Automation thread started")
    return True

def stop_automation(user_id):
    """Stops the automation loop for a user."""
    str_user_id = str(user_id)
    
    # Cleanup on Stop
    if str_user_id in active_threads:
        del active_threads[str_user_id]
    
    # Release campaign from lock
    from telegram_bot.state_manager import get_user
    user_data = get_user(str_user_id)
    campaign_name = user_data.get("campaign")
    if campaign_name:
        release_campaign(campaign_name)
    
    # Update disk state regardless of current memory flags to ensure persistence
    from telegram_bot.state_manager import load_users, save_users
    users_data = load_users()
    if str_user_id in users_data:
        users_data[str_user_id]["running"] = False
        # Do NOT modify state here
        save_users(users_data)
    
    if str_user_id in user_flags:
        user_flags[str_user_id] = False
        if str_user_id in user_status:
            user_status[str_user_id]["running"] = False
        add_log(str_user_id, "Automation stopped by user")
        return True
    return False

def get_status(user_id):
    """Retrieves the current automation status for a user."""
    return user_status.get(str(user_id), None)

def wait_with_interrupt(user_id, seconds):
    """Waits for the specified seconds but can be interrupted if the flag is cleared."""
    for _ in range(seconds):
        if not user_flags.get(str(user_id), False):
            break
        time.sleep(1)

def automation_loop(user_id, config, logger):
    """The main automation loop that runs in the background using the centralized session."""
    str_user_id = str(user_id)
    logger.info(f"[User {str_user_id}] Automation loop started.")
    add_log(str_user_id, "Automation loop started")
    
    links = config.get("links", [])
    campaign_name = config.get("campaign", "Unknown")
    
    if not links:
        logger.error(f"[User {str_user_id}] No links found in config to process.")
        add_log(str_user_id, "Error: No links found in configuration")
        user_flags[str_user_id] = False
        if str_user_id in user_status:
            user_status[str_user_id]["running"] = False
        release_campaign(campaign_name, str_user_id)
        return

    interval_minutes = config.get("interval", 10)
    
    playwright = None
    browser = None
    context = None
    page = None
    
    try:
        # Initialize Playwright objects locally for thread safety (One browser per thread)
        from automation.browser import launch_browser, login, navigate_to_campaigns, open_campaign, update_target_link, ensure_campaign_page, check_campaign_exists, retry_action
        
        # PROXY VALIDATION & ROTATION SYSTEM
        from telegram_bot.state_manager import get_user
        user = get_user(str_user_id)
        
        proxies_count = len(user.get("proxies", []))
        max_attempts = proxies_count if proxies_count > 0 else 1
        
        for attempt in range(max_attempts):
            proxy = get_next_proxy(str_user_id, user)
            
            app_instance = user_bots.get(str_user_id)
            if proxy:
                print(f"[DEBUG] Using proxy: {proxy}")
                is_valid, info = validate_proxy(proxy)
                
                if is_valid:
                    if app_instance:
                        send_telegram_message(app_instance, str_user_id, f"✅ Proxy connected successfully\n🌐 IP: {info}\n\n🚀 Starting automation...")
                else:
                    if app_instance:
                        send_telegram_message(app_instance, str_user_id, f"❌ Proxy failed\nReason: {info}\n\n🔄 Trying next proxy...")
                    continue # Try next proxy
            
            try:
                playwright, browser, page = launch_browser(user_id=str_user_id)
                context = page.context
                
                # Initial Login
                add_log(str_user_id, "Logging in...")
                
                # Add Login Cooldown Check
                now = time.time()
                last_attempt = config.get("last_login_attempt", 0)
                
                if now - last_attempt < 60:
                    raise Exception("Too many login attempts. Please wait 60 seconds.")
                    
                from telegram_bot.state_manager import update_user
                update_user(str_user_id, {"last_login_attempt": now})
                
                login(page, config["username"], config["password"])
                add_log(str_user_id, "Login successful")
                
                break # Browser launched and logged in successfully
            except Exception as e:
                logger.error(f"Browser launch/login failed on attempt {attempt}: {e}")
                
                if "login failed" in str(e).lower() or "invalid credentials" in str(e).lower():
                    if app_instance:
                        send_telegram_message(app_instance, str_user_id, "⚠️ Login failed. Rotating proxy...")
                        if proxy:
                            # Actually get_next_proxy already rotated index, but let's notify
                            send_telegram_message(app_instance, str_user_id, f"🔄 Switched to new proxy: {proxy}")
                
                if attempt == max_attempts - 1:
                    raise e # Re-raise if all attempts failed so outer block can screenshot
                
                # Cleanup before retry
                if page:
                    try: page.close()
                    except: pass
                if context:
                    try: context.close()
                    except: pass
                if browser:
                    try: browser.close()
                    except: pass
                    
                continue
                
        if not page:
            app_instance = user_bots.get(str_user_id)
            if app_instance:
                send_telegram_message(app_instance, str_user_id, "❌ All proxies failed. Try adding new proxies or retry later.")
            return
    except Exception as e:
        error_message = str(e)
        logger.error(f"[User {str_user_id}] Initial setup failed: {e}")
        add_log(str_user_id, f"Initial setup failed: {e}")
        
        # Intelligence Layer: Classify and Decide
        from telegram_bot.intelligence.error_classifier import classify_error, ErrorType
        from telegram_bot.intelligence.decision_engine import decide_action, ActionType, get_user_friendly_message
        
        error_type = classify_error(error_message)
        action = decide_action(error_type)
        
        # Try to grab current URL for debugging context
        if page:
            try:
                current_url = page.url
                error_message = f"{error_message}\n\n*Current URL at failure:* `{current_url}`\n*Time:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`"
            except: pass

        # Handle based on Intelligence
        if action == ActionType.STOP or error_type in [ErrorType.AUTH, ErrorType.CAPTCHA]:
            error_message = get_user_friendly_message(error_type, error_message)
            
            # Apply global cooldown for RATE_LIMIT safely
            if error_type == ErrorType.RATE_LIMIT:
                try:
                    cooldown = time.time() + random.uniform(300, 900) # 5-15 mins
                except Exception as rand_e:
                    logger.error(f"Error calculating cooldown: {rand_e}")
                    cooldown = time.time() + 300
                    
                logger.info(f"Applying cooldown for user {str_user_id}: {cooldown}")
                try:
                    from telegram_bot.state_manager import update_user
                    update_user(str_user_id, {"global_cooldown_until": cooldown})
                except Exception as e_update:
                    logger.error(f"Failed to update global cooldown state for {str_user_id}: {e_update}")
        else:
            error_message = f"""❌ *Automation Error*\n\n*Reason:*\n{error_message}\n\n_Screenshot attached for debugging._"""
        
        send_error_with_screenshot(page, str_user_id, error_message)

        user_flags[str_user_id] = False
        if str_user_id in user_status:
            user_status[str_user_id]["running"] = False
        release_campaign(campaign_name, str_user_id)
        
        # Ensure disk state matches memory state on crash/stop
        from telegram_bot.state_manager import load_users, save_users
        users_data = load_users()
        str_user_id = str(user_id)
        if str_user_id in users_data:
            users_data[str_user_id]["running"] = False
            save_users(users_data)
            
        # Cleanup if failed immediately
        if page: page.close()
        if context: context.close()
        if browser: browser.close()
        if playwright: playwright.stop()
        
        # Remove from active threads
        if str_user_id in active_threads:
            del active_threads[str_user_id]
            
        return

    # Ensure index is local variable only
    current_index = 0
    error_count = 0
    cycle_count = 0  # Track cycles for periodic reset

    if not os.path.exists("logs"):
        os.makedirs("logs")

    try:
        while user_flags.get(str_user_id, False):

            # Periodic Browser Restart (Memory Cleanup)
            MAX_CYCLES_BEFORE_RESTART = 20
            cycle_count += 1
            if cycle_count >= MAX_CYCLES_BEFORE_RESTART:
                add_log(str_user_id, "🔄 Restarting browser (memory cleanup)")
                try:
                    if page: page.close()
                    if context: context.close()
                    if browser: browser.close()
                except:
                    pass
                
                playwright, browser, page = launch_browser(user_id=str_user_id)
                context = page.context
                cycle_count = 0
                
            from telegram_bot.state_manager import get_user, update_user
            user = get_user(str_user_id)
            
            # Ensure initialization
            active_links = user.get("active_links", links) # Fallback to config links if active_links empty/missing
            flagged_links = user.get("flagged_links", [])
            user_current_index = user.get("current_index", 0)
            retry_map = user.get("retry_map", {})
            link_stats = user.get("link_stats", {"total_rotations": 0, "failures": 0})
            
            # F2 Initialize links_data
            links_data = user.get("links_data", [])
            if not links_data and active_links:
                for link in active_links:
                    links_data.append({
                        "url": link,
                        "status": "active",
                        "success_count": 0,
                        "fail_count": 0,
                        "last_checked": None
                    })
            
            # Save initialized structure back just in case
            update_user(str_user_id, {
                "active_links": active_links,
                "flagged_links": flagged_links,
                "retry_map": retry_map,
                "link_stats": link_stats,
                "links_data": links_data
            })

            if not active_links:
                add_log(str_user_id, "No active links available")
                stop_automation(str_user_id)
                return
                
            current_index = user.get("current_index", 0) 
            active_links = user.get("active_links", []) 
            
            # Ensure current_index is within bounds in case active_links length changed
            current_index = current_index % len(active_links)
            current_link = active_links[current_index]
            
            # Update user state with selected link
            update_user(str_user_id, {
                "current_link": current_link,
                "current_index": current_index
            })

            # Prevent Same Link Loop
            last_link = user.get("last_link")
            if current_link == last_link and len(active_links) > 1:
                # add_log(str_user_id, "⚠️ Duplicate link detected, skipping cycle")
                # move_to_next_link(str_user_id)
                # continue
                pass
                
            update_user(str_user_id, {"last_link": current_link})
            
            # Retry Control Per Link initialization
            if current_link not in retry_map:
                retry_map[current_link] = 0
                update_user(str_user_id, {"retry_map": retry_map})
            
            if str_user_id in user_status and user_status[str_user_id].get("current_link") and user_status[str_user_id]["current_link"] != current_link:
                notify_user(str_user_id, f"🔄 Link Switched\n\n➡️ Now using:\n{current_link}")
            
            # Update status
            if str_user_id in user_status:
                user_status[str_user_id]["current_link"] = current_link
                user_status[str_user_id]["current_index"] = current_index

            cycle_start_time = time.time()
            try:
                logger.info(f"[User {str_user_id}] Starting cycle with link index {current_index}: {current_link}")
                add_log(str_user_id, f"Cycle started [Index {current_index}]: {current_link}")
                
                # Check for session expiry at the start of the loop
                if "login" in page.url.lower():
                    logger.warning(f"[User {str_user_id}] Session expired detected. Re-logging...")
                    add_log(str_user_id, "Session expired. Re-authenticating...")
                    try:
                        login(page, config["username"], config["password"])
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(3000)
                        logger.info(f"[User {str_user_id}] Re-login successful.")
                    except Exception as relogin_error:
                        logger.error(f"[User {str_user_id}] Relogin failed: {relogin_error}")
                        raise relogin_error

                # Ensure we are on the campaign page
                ensure_campaign_page(page)
                
                # Pre-check if campaign exists before attempting to open it
                campaign_found = False
                for attempt in range(3):
                    if check_campaign_exists(page, campaign_name):
                        campaign_found = True
                        break
                    else:
                        logger.warning(f"[User {str_user_id}] Campaign check attempt {attempt+1} failed. Retrying...")
                        page.reload()
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(7000)

                if not campaign_found:
                    logger.warning(f"[User {str_user_id}] Campaign not found after retries: {campaign_name}")
                    add_log(str_user_id, f"Error: Campaign '{campaign_name}' not found.")
                    
                    # Send structured error alert via notifier
                    error_message = f"""❌ *Automation Error*

Campaign: `{campaign_name}`

*Reason:*
Campaign not found on dashboard.

*Possible causes:*
• Incorrect campaign name
• No campaigns in account
• Login/session issue

_Screenshot attached for debugging._"""
                    
                    send_error_with_screenshot(page, str_user_id, error_message)
                    
                    from telegram_bot.state_manager import load_users, save_users
                    users_data = load_users()
                    if str_user_id in users_data:
                        users_data[str_user_id]["running"] = False
                        # Do NOT modify state here
                        save_users(users_data)
                        
                    stop_automation(str_user_id)
                    break

                # Introduce AI self-healing during open_campaign
                from telegram_bot.ai_selector import get_cached_selector, set_cached_selector, generate_selector_with_gemini
                
                try:
                    open_campaign(page, campaign_name, user_id=str_user_id)
                    add_log(str_user_id, f"Opened campaign: {campaign_name}")
                except Exception as open_err:
                    from telegram_bot.intelligence.error_classifier import classify_error, ErrorType
                    
                    if classify_error(str(open_err)) == ErrorType.SELECTOR:
                        logger.warning(f"Original open_campaign failed: {open_err}. Triggering AI recovery...")
                        
                        # Take screenshot and get HTML for AI
                        os.makedirs("logs", exist_ok=True)
                        screenshot_filename = f"ai_recovery_open_{int(time.time())}.png"
                        screenshot_path = os.path.join("logs", screenshot_filename)
                        page.screenshot(path=screenshot_path)
                        html_content = page.content()
                        
                        action_desc = f"Click the 'Edit' or 'Settings' button for the campaign named '{campaign_name}'."
                        new_selector = generate_selector_with_gemini(html_content, screenshot_path, action_desc)
                        
                        if new_selector:
                            btn = page.locator(new_selector)
                            if btn.count() > 0:
                                logger.info(f"AI Recovery successful. Clicking new selector: {new_selector}")
                                btn.first.click()
                                page.wait_for_url("**/change/**", timeout=15000)
                                add_log(str_user_id, f"Opened campaign (AI recovered): {campaign_name}")
                                
                                # Send Telegram Alert
                                msg = f"🤖 *AI Self-Healing Triggered*\n\nThe edit button for campaign '{campaign_name}' changed.\nMy AI Vision successfully found the new button and fixed it automatically!\n\nNo action required."
                                send_error_with_screenshot(page, str_user_id, msg)
                            else:
                                raise Exception(f"AI generated selector '{new_selector}' found 0 elements.")
                        else:
                            raise Exception("Failed to open campaign and AI recovery failed.")
                    else:
                        # Re-raise if not a selector error to be handled by the main exception handler
                        raise open_err
                
                # The update_target_link already has internal AI recovery now
                add_log(str_user_id, f"Trying link: {current_link}") 
                
                from automation.browser import validate_external_link
                status = validate_external_link(page, current_link)
                add_log(str_user_id, f"[LINK CHECK] URL: {current_link}")
                add_log(str_user_id, f"[LINK STATUS] {status}")
                
                if status == "INVALID":
                    add_log(str_user_id, "⚠️ Validation failed → retrying once")

                    retry_status = validate_external_link(page, current_link)

                    if retry_status == "VALID":
                        add_log(str_user_id, "Recovered on retry → skipping flag")
                        continue
                        
                    retry_map = user.get("retry_map", {})
                    retry_map[current_link] = retry_map.get(current_link, 0) + 1
                    update_user(str_user_id, {"retry_map": retry_map})
                    
                    if retry_map[current_link] >= 2:
                        logger.warning(f"[User {str_user_id}] LINK_INVALID → flag immediately: {current_link}")
                        add_log(str_user_id, f"[FLAGGED] Link removed: {current_link}")
                        mark_link_as_flagged(str_user_id, current_link, page=page)
                        # Do NOT call move_to_next_link here. Removing the item shifts the array.
                    else:
                        add_log(str_user_id, "Retrying before flagging link...")
                    
                    # Respect interval before skipping to avoid rapid looping
                    elapsed = time.time() - cycle_start_time
                    remaining = (config.get("interval", 1) * 60) - elapsed
                    if remaining > 0:
                        wait_with_interrupt(str_user_id, int(remaining))
                    
                    continue  # skip to next link
                
                # Update link and validate the result directly
                from automation.browser import validate_link_update
                
                update_target_link(page, current_link, user_id=str_user_id)
                
                page.wait_for_timeout(2000) 
                page.reload() 
                
                page.wait_for_load_state("domcontentloaded") 
                
                page_content = page.content() 
                if current_link not in page_content: 
                    logger.warning("Link not visible in page content (SPA delay), continuing...") 
                    
                logger.info(f"[User {str_user_id}] Updated link successfully: {current_link}")
                add_log(str_user_id, "✅ Link success")
                
                error_count = 0 
                
                user = get_user(str_user_id)
                link_stats = user.get("link_stats", {"total_rotations": 0, "failures": 0})
                link_stats["total_rotations"] = link_stats.get("total_rotations", 0) + 1
                
                # Move to next link 
                move_to_next_link(str_user_id)
                user = get_user(str_user_id)
                
                new_index = user.get("current_index", 0) 
                new_link = user.get("active_links", [])[new_index] if user.get("active_links") else "N/A"
                
                logger.info(f"[User {str_user_id}] 🔁 Link switched → {new_link}")
                add_log(str_user_id, f"🔁 Link switched → {new_link}")
                
                # F2 Update On Success
                links_data = user.get("links_data", [])
                for link_obj in links_data:
                    if link_obj.get("url") == current_link:
                        link_obj["success_count"] = link_obj.get("success_count", 0) + 1
                        link_obj["last_checked"] = time.time()
                        break
                
                update_user(str_user_id, {
                    "links_data": links_data, 
                    "link_stats": link_stats
                })
                
                add_log(str_user_id, f"Retry count reset")
                
                # Update status after cycle
                if str_user_id in user_status:
                    user_status[str_user_id]["last_updated"] = time.time()
                    
                # Reset temp notification flag
                user = user_status.get(str_user_id, {})
                if "temp_notified" in user:
                    user["temp_notified"] = False
                    
                # Reset Retry After Success
                user = get_user(str_user_id)
                retry_map = user.get("retry_map", {})
                retry_map.pop(current_link, None)
                
                from telegram_bot.utils.error_tracker import clear_error 
                clear_error(str_user_id) 
                
                update_user(str_user_id, {
                    "retry_map": retry_map,
                    "last_run_time": time.time(),
                    "cycle_start_time": time.time()
                })
                
                # Mark error as resolved if it was active
                if mark_error_resolved(str_user_id):
                     app_instance = user_bots.get(str_user_id)
                     if app_instance:
                         send_telegram_message(app_instance, str_user_id, "✅ *Automation Resumed*\n\nSystem has recovered and automation is running normally.")
    
                # Note: user data is already saved to disk by update_user above
                
                # Periodic Page Reset for Stability (CRITICAL)
                # Note: Now replaced by the global memory restart, but we keep a lighter page reload here if needed.
                if cycle_count > 0 and cycle_count % 3 == 0:
                    logger.info(f"[User {str_user_id}] Refreshing page for stability after 3 loops.")
                    add_log(str_user_id, f"Refreshing page for stability.")
                    try:
                        page.goto("https://next.palladium.expert/pages/campaign-page", timeout=30000)
                        page.wait_for_load_state("domcontentloaded")
                        page.wait_for_timeout(3000)
                        logger.info(f"[User {str_user_id}] Page reset completed successfully.")
                    except Exception as reset_err:
                        logger.warning(f"[User {str_user_id}] Navigation reset failed: {reset_err}. Attempting reload...")
                        try:
                            page.reload(wait_until="domcontentloaded")
                            page.wait_for_timeout(3000)
                            logger.info(f"[User {str_user_id}] Page reload completed successfully.")
                        except Exception as reload_err:
                            logger.error(f"[User {str_user_id}] Page reset entirely failed: {reload_err}")
                            
            except Exception as e:
                error_message = str(e).lower() 
                
                if is_system_error(error_message):
                    logger.error(f"System error (dependency issue): {error_message}")
                    add_log(str_user_id, "⚠️ System error, skipping this cycle")
                    # DO NOT modify active_links
                    # DO NOT modify flagged_links
                    # DO NOT change index
                    # Let interval handle next cycle
                elif is_link_error(error_message):
                    logger.error(f"Link validation error: {error_message}")
                    error_count += 1
                    process_link_failure(page, str_user_id, current_link, "Validation error / page exception")
                else:
                    logger.error(f"Cycle error: {e}")
    
                    if "browser crashed" in error_message: # Re-use browser crash logic safely
                        logger.warning(f"[User {str_user_id}] Browser crashed, restarting...") 
                    
                        add_log(str_user_id, "⚠️ Browser crashed → restarting...") 
                    
                        try: 
                            if page: 
                                page.close() 
                            if context: 
                                context.close() 
                            if browser: 
                                browser.close() 
                        except: 
                            pass 
                    
                        playwright, browser, page = launch_browser(user_id=str_user_id)
                        context = page.context
                    
                        user = get_user(str_user_id)
                        retry_map = user.get("retry_map", {})
                        retry_map.clear()
                        update_user(str_user_id, {"retry_map": retry_map})
                        # error_count only resets on success now, or we keep it to prevent infinite crashes
                        cycle_count = 0
                        # Let the loop finish to respect interval, index doesn't change 
    
                    else:
                        logger.warning(f"[User {str_user_id}] Temporary issue, retrying...") 
                    
                        add_log(str_user_id, "⚠️ Temporary issue → retrying same link") 
                        
                        user = user_status.get(str_user_id, {})
                        if not user.get("temp_notified"): 
                            notify_user(
                                str_user_id, 
                                "⚠️ Temporary issue detected\nRetrying automatically..." 
                            ) 
                            user["temp_notified"] = True 
                    
                        user = get_user(str_user_id)
                        retry_map = user.get("retry_map", {}) 
                        retry_map[current_link] = retry_map.get(current_link, 0) + 1 
                    
                        if retry_map[current_link] < 2: 
                            add_log(str_user_id, f"Retry attempt {retry_map[current_link]}/2")
                            # Do not continue here! Let the loop finish and apply the interval wait.
                        else:
                            # Max retries reached, treat as failure
                            logger.warning(f"[User {str_user_id}] Max retries reached (temp issue): {current_link}")
                            process_link_failure(page, str_user_id, current_link, "Max retries reached (temporary issue)")

                log_and_track_error(user_id, error_message, context="automation_loop", consecutive_errors=error_count)
                
                # Global Error Check
                MAX_GLOBAL_ERRORS = 10 
 
                if error_count > MAX_GLOBAL_ERRORS: 
                    add_log(user_id, "[WARNING] Too many errors → cooling down...") 
                    time.sleep(10) 
                    error_count = 0 
                
                # Intelligence Layer: Classify and Decide
                from telegram_bot.intelligence.error_classifier import classify_error, ErrorType
                from telegram_bot.intelligence.decision_engine import decide_action, ActionType, get_user_friendly_message
                
                error_type = classify_error(error_message)
                action = decide_action(error_type)
                
                # Handle STOP action (Auth, Captcha, or Max Errors)
                if action == ActionType.STOP or error_count >= MAX_ERRORS:
                    if error_count >= MAX_ERRORS:
                        logger.error(f"[User {str_user_id}] Max error limit reached ({MAX_ERRORS}). Stopping automation.")
                        stop_reason = f"Reached maximum limit of {MAX_ERRORS} consecutive true link failures."
                        
                        log_and_track_error(str_user_id, error_message, context="max_error_stop", consecutive_errors=error_count, stop_reason="MAX_CONSECUTIVE_ERRORS")
                    else:
                        logger.error(f"[User {str_user_id}] Critical error detected ({error_type.name}). Stopping automation.")
                        stop_reason = get_user_friendly_message(error_type, error_message)
                        
                    add_log(str_user_id, "❌ Critical error or max limit reached. Stopping automation.")
                    
                    stop_msg = (
                        f"❌ *Automation Stopped*\n\n"
                        f"{stop_reason}\n\n"
                        "Please check your campaign settings and try again."
                    )
                    
                    send_error_with_screenshot(page, str_user_id, stop_msg)
                    
                    from telegram_bot.state_manager import load_users, save_users
                    users_data = load_users()
                    if str_user_id in users_data:
                        users_data[str_user_id]["running"] = False
                        save_users(users_data)
                        
                    stop_automation(str_user_id)
                    break
                
                # Handle WAIT action (Rate Limit)
                elif action == ActionType.WAIT:
                    cooldown_minutes = random.uniform(5, 15)
                    wait_seconds = int(cooldown_minutes * 60)
                    logger.warning(f"[User {str_user_id}] Rate limited. Waiting for {wait_seconds} seconds.")
                    
                    # Store in user state
                    try:
                        from telegram_bot.state_manager import update_user
                        update_user(str_user_id, {"global_cooldown_until": time.time() + wait_seconds})
                    except Exception as e_update:
                        logger.error(f"Failed to update cooldown state: {e_update}")
                    
                    app_instance = user_bots.get(str_user_id)
                    if app_instance and should_send_error(str_user_id):
                        msg = get_user_friendly_message(error_type, error_message)
                        send_telegram_message(app_instance, str_user_id, f"{msg}\n\nCooldown: {int(cooldown_minutes)} minutes.")
                        mark_error_sent(str_user_id)
                        
                    wait_with_interrupt(str_user_id, wait_seconds)
                    
                    # Force browser restart after rate limit to get a fresh session/proxy potentially
                    try: 
                        if page: page.close() 
                        if context: context.close() 
                        if browser: browser.close() 
                    except: 
                        pass
                    playwright, browser, page = launch_browser(user_id=str_user_id)
                    context = page.context
                    
                # Handle RETRY and SELF_HEAL (Self-heal logic is in open_campaign, so we just retry here)
                else:
                    # Send alert if cooldown passed
                    if should_send_error(str_user_id):
                        # Determine user-friendly error reason
                        reason = get_user_friendly_message(error_type, error_message)

                        message = (
                            "🚨 *Automation Error*\n\n"
                            f"📌 Campaign: {campaign_name}\n"
                            f"❌ {reason}\n"
                            f"🔍 Details: `{error_message}`\n\n"
                            "🔄 The system will automatically recover and continue."
                        )
                        
                        send_error_with_screenshot(page, str_user_id, message)
                        mark_error_sent(str_user_id)

                    # We do not stop the loop here. Just wait and try the same link again.
                    logger.warning(f"[User {str_user_id}] Minor failure ({error_count}). Retrying next cycle.")
                    try:
                        page.reload()
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(7000)
                    except:
                        pass
                    
                    # Do NOT use continue here! Let it reach the finally-style interval sleep block

            # ==========================================
            # ALWAYS WAIT FULL INTERVAL BEFORE NEXT LINK
            # ==========================================
            if user_flags.get(str_user_id, False):
                # Calculate sleep time
                interval_minutes = config.get("interval", 1)
                interval_seconds = interval_minutes * 60
                
                elapsed = time.time() - cycle_start_time
                remaining = interval_seconds - elapsed
                
                add_log(str_user_id, f"[INFO] Cycle completed in: {elapsed:.2f} seconds")
                
                if remaining > 0:
                    logger.info(f"[User {str_user_id}] Waiting {int(remaining)} seconds before next cycle...")
                    add_log(str_user_id, f"[INFO] Sleeping for: {int(remaining)} seconds")
                    wait_with_interrupt(str_user_id, int(remaining))
                else:
                    add_log(str_user_id, "⚠️ Cycle took longer than interval, skipping wait")
                    time.sleep(2) # Small safety cooldown if we ran over time

    except Exception as fatal_e:
        logger.error(f"[User {str_user_id}] Fatal automation loop error: {fatal_e}")
        add_log(str_user_id, f"Fatal error: {str(fatal_e)}")
    finally:
        logger.info(f"[User {str_user_id}] Automation loop exiting. Cleaning up.")
        # Ensure cleanup is absolute
        try:
            if page: page.close()
            if context: context.close()
            if browser: browser.close()
            if playwright: playwright.stop()
        except:
            pass
            
        str_user_id = str(user_id)
        user_flags[str_user_id] = False
        if str_user_id in user_status:
            user_status[str_user_id]["running"] = False
            
        if str_user_id in active_threads:
            del active_threads[str_user_id]
            
        release_campaign(campaign_name, str_user_id)
