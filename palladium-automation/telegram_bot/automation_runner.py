import logging
import threading
import time
import os
from automation.browser import launch_browser, login, navigate_to_campaigns, open_campaign, update_target_link, ensure_logged_in, ensure_campaign_page
from telegram_bot.state_manager import get_current_index, update_current_index

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
active_campaigns = set()
campaign_lock = threading.Lock()

def acquire_campaign(campaign):
    with campaign_lock:
        if campaign in active_campaigns:
            return False
        active_campaigns.add(campaign)
        return True

def release_campaign(campaign):
    with campaign_lock:
        active_campaigns.discard(campaign)

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

def send_telegram_message(user_id, text, photo_path=None):
    """Safely sends a message or photo via Telegram without crashing the thread (Synchronous)."""
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")

        if not token:
            print("[ERROR] TELEGRAM_BOT_TOKEN not found in environment")
            return

        bot = Bot(token=token)
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as photo:
                # Sync call
                bot.send_photo(chat_id=user_id, photo=photo, caption=text)
        else:
            # Sync call
            bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")

# Removed send_error_alert as it is no longer needed (async wrapper)

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

def add_log(user_id, message):
    """Adds a log entry for a specific user."""
    str_user_id = str(user_id)
    
    if str_user_id not in user_logs:
        user_logs[str_user_id] = []
        
    timestamp = time.strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    
    user_logs[str_user_id].append(log_entry)
    
    # Keep only last 25 logs
    if len(user_logs[str_user_id]) > 25:
        user_logs[str_user_id] = user_logs[str_user_id][-25:]

def get_logs(user_id):
    """Retrieves logs for a specific user."""
    return user_logs.get(str(user_id), [])

def start_automation(user_id, config, logger, bot_instance=None):
    """Starts the automation loop for a user in a separate thread."""
    str_user_id = str(user_id)
    
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
    if not acquire_campaign(campaign_name):
        logger.error(f"Campaign {campaign_name} is already in use.")
        raise Exception(f"Campaign '{campaign_name}' is already running. Please stop it first.")

    if bot_instance:
        user_bots[str_user_id] = bot_instance
    
    if user_flags.get(str_user_id, False):
        logger.warning(f"Automation already running for user {user_id}")
        return False

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
        user_data[str_user_id]["state"] = "RUNNING"
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
        users_data[str_user_id]["state"] = "STOPPED"
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
    logger.info(f"[User {user_id}] Automation loop started.")
    add_log(user_id, "Automation loop started")
    
    links = config.get("links", [])
    campaign_name = config.get("campaign", "Unknown")
    
    if not links:
        logger.error(f"[User {user_id}] No links found in config to process.")
        add_log(user_id, "Error: No links found in configuration")
        user_flags[user_id] = False
        if user_id in user_status:
            user_status[user_id]["running"] = False
        release_campaign(campaign_name)
        return

    interval_minutes = config.get("interval", 10)
    
    context = None
    page = None
    
    # Initialize Session
    from telegram_bot.session_manager import SessionManager
    session = SessionManager.get_instance()
    
    try:
        # Start global session if not already started
        session.start_session(config["username"], config["password"])
        # Get an isolated page for this specific campaign
        context, page = session.create_campaign_page()
        add_log(user_id, "Attached to global browser session")
    except Exception as e:
        logger.error(f"[User {user_id}] Initial setup failed: {e}")
        add_log(user_id, f"Initial setup failed: {e}")
        user_flags[user_id] = False
        if user_id in user_status:
            user_status[user_id]["running"] = False
        release_campaign(campaign_name)
        return

    link_index = get_current_index(user_id)
    failure_count = 0
    error_count = 0

    if not os.path.exists("logs"):
        os.makedirs("logs")

    try:
        while user_flags.get(user_id, False):
            # Keep state alive explicitly in disk to prevent /users drift
            from telegram_bot.state_manager import load_users, save_users
            users_data = load_users()
            str_uid = str(user_id)
            if str_uid not in users_data or not users_data[str_uid].get("running"):
                break

                
            # Validate index (e.g. if user updated links and removed some)
            if link_index >= len(links):
                link_index = 0
                
            current_link = links[link_index]
            
            # Update status
            if user_id in user_status:
                user_status[user_id]["current_link"] = current_link
                user_status[user_id]["current_index"] = link_index + 1

            try:
                start_time = time.time()
                logger.info(f"[User {user_id}] Starting cycle with link index {link_index}: {current_link}")
                add_log(user_id, f"Using link index: {link_index}")
                
                # Check for session expiry at the start of the loop
                if "login" in page.url:
                    logger.warning(f"[User {user_id}] Session expired detected. Re-logging...")
                    add_log(user_id, "Session expired. Re-authenticating...")
                    try:
                        session.logged_in = False
                        session.start_session(config["username"], config["password"])
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(3000)
                        logger.info(f"[User {user_id}] Re-login successful.")
                    except Exception as relogin_error:
                        logger.error(f"[User {user_id}] Relogin failed: {relogin_error}")
                        # Don't break, let the outer exception handler catch it or retry next loop
                        raise relogin_error

                # Ensure persistent state using global session manager
                session.check_and_recover_session(page)
                add_log(user_id, "Session verified")
                logger.info(f"[User {user_id}] Session active")
                
                ensure_campaign_page(page)
                
                from automation.browser import retry_action, check_campaign_exists
                
                # Pre-check if campaign exists before attempting to open it
                campaign_found = False
                for attempt in range(3):
                    if check_campaign_exists(page, campaign_name):
                        campaign_found = True
                        break
                    else:
                        logger.warning(f"[User {user_id}] Campaign check attempt {attempt+1} failed. Retrying...")
                        page.reload()
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(7000)

                if not campaign_found:
                    logger.warning(f"[User {user_id}] Campaign not found after retries: {campaign_name}")
                    add_log(user_id, f"Error: Campaign '{campaign_name}' not found.")
                    
                    # Capture Screenshot on Pre-Check Error
                    screenshot_path = None
                    try:
                        screenshot_filename = f"precheck_error_{user_id}_{int(time.time())}.png"
                        screenshot_path = os.path.join("logs", screenshot_filename)
                        page.screenshot(path=screenshot_path, full_page=True)
                        logger.info(f"[User {user_id}] Pre-check screenshot saved: {screenshot_path}")
                        add_log(user_id, f"Screenshot saved: {screenshot_filename}")
                    except Exception as screenshot_error:
                        logger.error(f"[User {user_id}] Pre-check screenshot failed: {screenshot_error}")
                        screenshot_path = None
                    
                    # Send critical error alert (Sync)
                    msg = f"❌ *Automation Stopped*\n\nCampaign '{campaign_name}' could not be found after multiple retries.\nPlease check the name and try again."
                    send_telegram_message(user_id, msg, photo_path=screenshot_path)
                    
                    from telegram_bot.state_manager import load_users, save_users
                    users_data = load_users()
                    if str(user_id) in users_data:
                        users_data[str(user_id)]["running"] = False
                        users_data[str(user_id)]["state"] = "ERROR"
                        save_users(users_data)
                        
                    stop_automation(user_id)
                    continue

                retry_action(lambda: open_campaign(page, campaign_name))
                add_log(user_id, f"Opened campaign: {campaign_name}")
                
                retry_action(lambda: update_target_link(page, current_link))
                
                logger.info(f"[User {user_id}] Updated link successfully: {current_link}")
                add_log(user_id, f"Updated link successfully: {current_link}")
                
                # Update status after success
                if user_id in user_status:
                    user_status[user_id]["last_updated"] = time.time()
                    
                # Reset failure counts on success
                failure_count = 0
                error_count = 0
                
                # Update persistent index ONLY after successful update
                link_index = (link_index + 1) % len(links)
                update_current_index(user_id, link_index)
                add_log(user_id, f"Next index will be: {link_index}")
                
                # Mark error as resolved if it was active
                if mark_error_resolved(user_id):
                     send_telegram_message(user_id, "✅ *Automation Resumed*\n\nSystem has recovered and automation is running normally.")
    
                # Save user data to disk explicitly after status/index change
                from telegram_bot.state_manager import get_user, save_users, load_users
                users = load_users()
                users[str(user_id)] = get_user(user_id)
                save_users(users)
    
            except Exception as e:
                error_msg = str(e)
                error_count += 1
                logger.error(f"[User {user_id}] Recoverable error during automation cycle: {e}. Error count: {error_count}/{MAX_ERRORS}")
                add_log(user_id, f"Recoverable error: {error_msg} (Count: {error_count})")
                
                # Capture Screenshot on Error
                screenshot_path = None
                try:
                    screenshot_filename = f"error_user_{user_id}_{int(time.time())}.png"
                    screenshot_path = os.path.join("logs", screenshot_filename)
                    page.screenshot(path=screenshot_path, full_page=True)
                    logger.info(f"[User {user_id}] Screenshot saved: {screenshot_path}")
                    add_log(user_id, f"Screenshot saved: {screenshot_filename}")
                except Exception as screenshot_error:
                    logger.error(f"[User {user_id}] Screenshot failed: {screenshot_error}")
                    screenshot_path = None
                
                # Check for Max Error Limit
                if error_count >= MAX_ERRORS:
                    logger.error(f"[User {user_id}] Max error limit reached ({MAX_ERRORS}). Stopping automation to prevent infinite loop.")
                    add_log(user_id, "❌ Max error limit reached. Stopping automation.")
                    
                    stop_msg = (
                        "❌ *Automation Stopped*\n\n"
                        f"Reason: Reached maximum limit of {MAX_ERRORS} consecutive errors.\n"
                        "Please check your campaign settings and try again."
                    )
                    send_telegram_message(user_id, stop_msg, photo_path=screenshot_path)
                    
                    from telegram_bot.state_manager import load_users, save_users
                    users_data = load_users()
                    if str(user_id) in users_data:
                        users_data[str(user_id)]["running"] = False
                        users_data[str(user_id)]["state"] = "ERROR"
                        save_users(users_data)
                        
                    stop_automation(user_id)
                    continue
                
                # Send alert if cooldown passed
                
                # Determine user-friendly error reason
                reason = "Unknown Error"
                err_lower = error_msg.lower()
                if "timeout" in err_lower:
                    reason = "Page load timeout (slow server)"
                elif "selector" in err_lower or "found" in err_lower:
                    reason = "Element not found (UI changed or not loaded)"
                elif "login" in err_lower or "session" in err_lower:
                    reason = "Session expired or invalid"
                elif "network" in err_lower:
                    reason = "Network connectivity issue"

                if should_send_error(user_id):
                    message = (
                        "🚨 *Automation Error*\n\n"
                        f"📌 Campaign: {campaign_name}\n"
                        f"❌ Reason: `{reason}`\n"
                        f"🔍 Details: `{error_msg}`\n\n"
                        "🔄 The system will automatically recover and continue."
                    )
                    send_telegram_message(user_id, message, photo_path=screenshot_path)
                    mark_error_sent(user_id)

                failure_count += 1
                
                # We do not stop the loop here. Just wait and try the same link again.
                logger.warning(f"[User {user_id}] Minor failure ({failure_count}). Retrying next cycle.")
                try:
                    page.reload()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(7000)
                except:
                    pass
                continue

            # Wait before processing the next link
            if user_flags.get(user_id, False):
                # Calculate sleep time
                elapsed = time.time() - start_time
                sleep_time = max(0, (interval_minutes * 60) - elapsed)
                logger.info(f"[User {user_id}] Waiting {int(sleep_time)} seconds before next cycle...")
                wait_with_interrupt(user_id, int(sleep_time))

    finally:
        # Clean Shutdown for this specific campaign handler
        logger.info(f"[User {user_id}] Automation loop terminated. Cleaning up...")
        add_log(user_id, "Automation loop terminated. Cleaning up...")
        
        # Cleanup on Crash / Exit
        str_uid = str(user_id)
        if str_uid in active_threads:
            del active_threads[str_uid]
        
        release_campaign(campaign_name)
        
        # Ensure disk state matches memory state on crash/stop
        from telegram_bot.state_manager import load_users, save_users
        users_data = load_users()
        str_user_id = str(user_id)
        if str_user_id in users_data:
            users_data[str_user_id]["running"] = False
            # Only update state if it wasn't already marked as ERROR by the max_errors handler
            if users_data[str_user_id].get("state") != "ERROR":
                users_data[str_user_id]["state"] = "STOPPED"
            save_users(users_data)
        
        if context:
            try:
                context.close()
            except:
                pass
                
        if user_id in user_status:
            user_status[user_id]["running"] = False
