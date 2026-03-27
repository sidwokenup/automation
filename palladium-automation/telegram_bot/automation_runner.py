import logging
import threading
import time
import os
import random
import requests
from automation.browser import launch_browser, login, navigate_to_campaigns, open_campaign, update_target_link, ensure_logged_in, ensure_campaign_page
from telegram_bot.state_manager import get_current_index, update_current_index

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

    # NEW: persist to file 
    try: 
        write_log(user_id, message) 
    except: 
        pass 

def get_logs(user_id):
    """Retrieves logs for a specific user."""
    return user_logs.get(str(user_id), [])

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
    if not acquire_campaign(campaign_name):
        logger.error(f"Campaign {campaign_name} is already in use.")
        raise Exception(f"Campaign '{campaign_name}' is already running. Please stop it first.")
    
    if user_flags.get(str_user_id, False):
        logger.warning(f"Automation already running for user {user_id}")
        return False

    # Reset State on /run (IMPORTANT)
    user_data[str_user_id]["current_index"] = 0
    user_data[str_user_id]["retry_map"] = {}
    user_data[str_user_id]["link_stats"] = {
        "total_rotations": 0,
        "failures": 0
    }

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
    
    playwright = None
    browser = None
    context = None
    page = None
    
    try:
        # Initialize Playwright objects locally for thread safety (One browser per thread)
        from automation.browser import launch_browser, login, navigate_to_campaigns, open_campaign, update_target_link, ensure_campaign_page, check_campaign_exists, retry_action
        
        # PROXY VALIDATION & ROTATION SYSTEM
        from telegram_bot.state_manager import get_user
        user_data = get_user(user_id)
        
        proxies_count = len(user_data.get("proxies", []))
        max_attempts = proxies_count if proxies_count > 0 else 1
        
        for attempt in range(max_attempts):
            proxy = get_next_proxy(user_id, user_data)
            
            app_instance = user_bots.get(str(user_id))
            if proxy:
                print(f"[DEBUG] Using proxy: {proxy}")
                is_valid, info = validate_proxy(proxy)
                
                if is_valid:
                    if app_instance:
                        send_telegram_message(app_instance, user_id, f"✅ Proxy connected successfully\n🌐 IP: {info}\n\n🚀 Starting automation...")
                else:
                    if app_instance:
                        send_telegram_message(app_instance, user_id, f"❌ Proxy failed\nReason: {info}\n\n🔄 Trying next proxy...")
                    continue # Try next proxy
            
            try:
                playwright, browser, page = launch_browser(user_id=user_id)
                context = page.context
                
                # Initial Login
                add_log(user_id, "Logging in...")
                
                # Add Login Cooldown Check
                now = time.time()
                last_attempt = config.get("last_login_attempt", 0)
                
                if now - last_attempt < 60:
                    raise Exception("Too many login attempts. Please wait 60 seconds.")
                    
                from telegram_bot.state_manager import update_user
                update_user(user_id, {"last_login_attempt": now})
                
                login(page, config["username"], config["password"])
                add_log(user_id, "Login successful")
                
                break # Browser launched and logged in successfully
            except Exception as e:
                logger.error(f"Browser launch/login failed on attempt {attempt}: {e}")
                
                if "login failed" in str(e).lower() or "invalid credentials" in str(e).lower():
                    if app_instance:
                        send_telegram_message(app_instance, user_id, "⚠️ Login failed. Rotating proxy...")
                        if proxy:
                            # Actually get_next_proxy already rotated index, but let's notify
                            send_telegram_message(app_instance, user_id, f"🔄 Switched to new proxy: {proxy}")
                
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
            app_instance = user_bots.get(str(user_id))
            if app_instance:
                send_telegram_message(app_instance, user_id, "❌ All proxies failed. Try adding new proxies or retry later.")
            return
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[User {user_id}] Initial setup failed: {e}")
        add_log(user_id, f"Initial setup failed: {e}")
        
        # Intelligence Layer: Classify and Decide
        from telegram_bot.intelligence.error_classifier import classify_error, ErrorType
        from telegram_bot.intelligence.decision_engine import decide_action, ActionType, get_user_friendly_message
        
        error_type = classify_error(error_msg)
        action = decide_action(error_type)
        
        # Capture Screenshot on Login Error
        screenshot_path = None
        if page:
            try:
                # Screenshot Labeling Fix
                is_success = "success" in e_str or "validation failed" not in e_str and "dashboard" in page.url.lower()
                prefix = "login_success" if is_success else "login_failed"
                screenshot_filename = f"{prefix}_{user_id}_{int(time.time())}.png"
                screenshot_path = os.path.join("logs", screenshot_filename)
                os.makedirs("logs", exist_ok=True)
                page.screenshot(path=screenshot_path, full_page=True)
                logger.info(f"[User {user_id}] Login screenshot saved: {screenshot_path}")
                
                # Try to grab current URL for debugging context
                try:
                    current_url = page.url
                    e_str = str(e)
                    e = Exception(f"{e_str}\n\n*Current URL at failure:* `{current_url}`\n*Time:* `{time.strftime('%Y-%m-%d %H:%M:%S')}`")
                except: pass
                
            except Exception as screenshot_error:
                logger.error(f"[User {user_id}] Login screenshot failed: {screenshot_error}")
                
        # Handle based on Intelligence
        if action == ActionType.STOP or error_type in [ErrorType.AUTH, ErrorType.CAPTCHA]:
            error_message = get_user_friendly_message(error_type, error_msg)
            
            # Apply global cooldown for RATE_LIMIT safely
            if error_type == ErrorType.RATE_LIMIT:
                try:
                    cooldown = time.time() + random.uniform(300, 900) # 5-15 mins
                except Exception as rand_e:
                    logger.error(f"Error calculating cooldown: {rand_e}")
                    cooldown = time.time() + 300
                    
                logger.info(f"Applying cooldown for user {user_id}: {cooldown}")
                try:
                    from telegram_bot.state_manager import update_user
                    update_user(user_id, {"global_cooldown_until": cooldown})
                except Exception as e_update:
                    logger.error(f"Failed to update global cooldown state for {user_id}: {e_update}")
        else:
            error_message = f"""❌ *Automation Error*\n\n*Reason:*\n{error_msg}\n\n_Screenshot attached for debugging._"""
        
        app_instance = user_bots.get(str(user_id))
        if app_instance:
            if screenshot_path:
                send_telegram_photo(app_instance, user_id, screenshot_path, error_message)
            else:
                send_telegram_message(app_instance, user_id, error_message)

        user_flags[user_id] = False
        if user_id in user_status:
            user_status[user_id]["running"] = False
        release_campaign(campaign_name)
        
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

    link_index = get_current_index(user_id)
    failure_count = 0
    error_count = 0
    cycle_count = 0  # Track cycles for periodic reset

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

            # Periodic Browser Restart (Memory Cleanup)
            MAX_CYCLES_BEFORE_RESTART = 20
            cycle_count += 1
            if cycle_count >= MAX_CYCLES_BEFORE_RESTART:
                add_log(user_id, "🔄 Restarting browser (memory cleanup)")
                try:
                    if page: page.close()
                    if context: context.close()
                    if browser: browser.close()
                except:
                    pass
                
                playwright, browser, page = launch_browser(user_id=user_id)
                context = page.context
                cycle_count = 0
                
            # Validate index (e.g. if user updated links and removed some)
            if link_index >= len(links):
                link_index = 0
                
            from telegram_bot.state_manager import get_user, update_user
            user = get_user(user_id)
            
            # Ensure initialization
            active_links = user.get("active_links", links) # Fallback to config links if active_links empty/missing
            flagged_links = user.get("flagged_links", [])
            user_current_index = user.get("current_index", link_index)
            retry_map = user.get("retry_map", {})
            link_stats = user.get("link_stats", {"total_rotations": 0, "failures": 0})
            
            # Save initialized structure back just in case
            update_user(user_id, {
                "active_links": active_links,
                "flagged_links": flagged_links,
                "retry_map": retry_map,
                "link_stats": link_stats
            })

            # Get Next Link (FIX CORE BUG)
            if not active_links:
                app_instance = user_bots.get(str(user_id)) 

                message = """🚨 All Links Flagged! 
 
All your links are no longer working. 
 
Please add new links using /setup to continue automation. 
""" 
 
                if app_instance: 
                    send_telegram_message(app_instance, user_id, message) 

                stop_automation(user_id) 
                break
                
            user_current_index = user_current_index % len(active_links)
            current_link = active_links[user_current_index]
            
            # Update user state with selected link
            update_user(user_id, {
                "current_link": current_link,
                "current_index": user_current_index
            })

            # Prevent Same Link Loop
            last_link = user.get("last_link")
            if current_link == last_link:
                add_log(user_id, "Skipping duplicate link cycle")
                update_user(user_id, {"current_index": user_current_index + 1})
                continue
                
            update_user(user_id, {"last_link": current_link})
            
            # Retry Control Per Link initialization
            if current_link not in retry_map:
                retry_map[current_link] = 0
                update_user(user_id, {"retry_map": retry_map})
            
            if user_id in user_status and user_status[user_id].get("current_link") and user_status[user_id]["current_link"] != current_link:
                notify_user(user_id, f"🔄 Link Switched\n\n➡️ Now using:\n{current_link}")
            
            # Update status
            if user_id in user_status:
                user_status[user_id]["current_link"] = current_link
                user_status[user_id]["current_index"] = user_current_index + 1

            try:
                start_time = time.time()
                logger.info(f"[User {user_id}] Starting cycle with link index {user_current_index}: {current_link}")
                add_log(user_id, f"[Cycle {cycle_count}] Using link: {current_link}")
                
                # Check for session expiry at the start of the loop
                if "login" in page.url.lower():
                    logger.warning(f"[User {user_id}] Session expired detected. Re-logging...")
                    add_log(user_id, "Session expired. Re-authenticating...")
                    try:
                        login(page, config["username"], config["password"])
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(3000)
                        logger.info(f"[User {user_id}] Re-login successful.")
                    except Exception as relogin_error:
                        logger.error(f"[User {user_id}] Relogin failed: {relogin_error}")
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
                    
                    app_instance = user_bots.get(str(user_id))
                    if app_instance:
                        if screenshot_path:
                            send_telegram_photo(app_instance, user_id, screenshot_path, error_message)
                        else:
                            send_telegram_message(app_instance, user_id, error_message)
                    
                    from telegram_bot.state_manager import load_users, save_users
                    users_data = load_users()
                    if str(user_id) in users_data:
                        users_data[str(user_id)]["running"] = False
                        # Do NOT modify state here
                        save_users(users_data)
                        
                    stop_automation(user_id)
                    continue

                # Introduce AI self-healing during open_campaign
                from telegram_bot.ai_selector import get_cached_selector, set_cached_selector, generate_selector_with_gemini
                
                try:
                    open_campaign(page, campaign_name, user_id=user_id)
                    add_log(user_id, f"Opened campaign: {campaign_name}")
                except Exception as open_err:
                    from telegram_bot.intelligence.error_classifier import classify_error, ErrorType
                    
                    if classify_error(str(open_err)) == ErrorType.SELECTOR:
                        logger.warning(f"Original open_campaign failed: {open_err}. Triggering AI recovery...")
                        
                        # Take screenshot and get HTML for AI
                        os.makedirs("logs", exist_ok=True)
                        screenshot_path = f"logs/ai_recovery_open_{int(time.time())}.png"
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
                                add_log(user_id, f"Opened campaign (AI recovered): {campaign_name}")
                                
                                # Send Telegram Alert
                                app_instance = user_bots.get(str(user_id))
                                if app_instance:
                                    msg = f"🤖 *AI Self-Healing Triggered*\n\nThe edit button for campaign '{campaign_name}' changed.\nMy AI Vision successfully found the new button and fixed it automatically!\n\nNo action required."
                                    send_telegram_photo(app_instance, user_id, screenshot_path, msg)
                            else:
                                raise Exception(f"AI generated selector '{new_selector}' found 0 elements.")
                        else:
                            raise Exception("Failed to open campaign and AI recovery failed.")
                    else:
                        # Re-raise if not a selector error to be handled by the main exception handler
                        raise open_err
                
                # The update_target_link already has internal AI recovery now
                # 🧠 Real Link Validation Before Update
                response = page.goto(current_link, timeout=30000) 
 
                link_failed = False 
                
                if response: 
                    status = response.status 
                
                    if status >= 400: 
                        link_failed = True 
                
                # OPTIONAL content check 
                page_content = page.content() 
                
                if "not found" in page_content.lower() or "blocked" in page_content.lower(): 
                    link_failed = True 

                if link_failed: 
                    logger.warning(f"[User {user_id}] Link truly failed: {current_link}") 
                
                    add_log(user_id, f"Link failed (validated): {current_link}") 
                
                    from telegram_bot.state_manager import get_user, update_user
                    user_data = get_user(user_id)
                    
                    active_links = user_data.get("active_links", [])
                    if current_link in active_links:
                        active_links.remove(current_link)
                    
                    flagged_links = user_data.get("flagged_links", [])
                    if current_link not in flagged_links:
                        flagged_links.append(current_link)
                        
                    retry_map.pop(current_link, None)
                    
                    link_stats["failures"] = link_stats.get("failures", 0) + 1
                    
                    update_user(user_id, {
                        "active_links": active_links,
                        "flagged_links": flagged_links,
                        "retry_map": retry_map,
                        "link_stats": link_stats
                    })
                    
                    notify_user( 
                        user_id, 
                        f"🚫 Link Removed\n\n❌ {current_link}\n\nReason: Validation failed\n\n📦 Remaining Links: {len(active_links)}" 
                    ) 
                    
                    raise Exception(f"Link Validation Failed for {current_link}")
                    
                add_log(user_id, f"Trying link: {current_link}") 
                success = update_target_link(page, current_link, user_id=user_id)
                
                # Fetch value explicitly for logging since the original input_value check was moved to browser.py
                # This ensures we don't break the log requirements in the prompt
                try:
                    value = page.input_value("input[placeholder*='http']")
                except:
                    value = "unknown"
                add_log(user_id, f"Input field value after paste: {value}") 
                
                if success: 
                    logger.info(f"[User {user_id}] Updated link successfully: {current_link}")
                    add_log(user_id, f"Link updated successfully")
                    
                    error_count = 0 
                    
                    # Update Stats
                    link_stats["total_rotations"] = link_stats.get("total_rotations", 0) + 1
                    
                    # Move to next link 
                    user_current_index = (user_current_index + 1) % len(active_links) if active_links else 0
                else: 
                    raise Exception("Update failed") 
                
                # Update status after success
                if user_id in user_status:
                    user_status[user_id]["last_updated"] = time.time()
                    
                # Reset failure counts on success
                failure_count = 0
                error_count = 0
                
                # Reset temp notification flag
                user = user_status.get(str(user_id), {})
                if "temp_notified" in user:
                    user["temp_notified"] = False
                    
                # Reset Retry After Success
                user.get("retry_map", {}).pop(current_link, None)
                
                from telegram_bot.utils.error_tracker import clear_error 
                clear_error(user_id) 
                
                from telegram_bot.state_manager import update_user
                update_user(user_id, {
                    "current_index": user_current_index,
                    "total_links": len(active_links),
                    "last_run_time": time.time(),
                    "cycle_start_time": start_time,
                    "link_stats": link_stats
                })
                
                add_log(user_id, f"Next index will be: {user_current_index}")
                
                # Mark error as resolved if it was active
                if mark_error_resolved(user_id):
                     app_instance = user_bots.get(str(user_id))
                     if app_instance:
                         send_telegram_message(app_instance, user_id, "✅ *Automation Resumed*\n\nSystem has recovered and automation is running normally.")
    
                # Note: user data is already saved to disk by update_user above
                
                # Periodic Page Reset for Stability (CRITICAL)
                # Note: Now replaced by the global memory restart, but we keep a lighter page reload here if needed.
                if cycle_count > 0 and cycle_count % 3 == 0:
                    logger.info(f"[User {user_id}] Refreshing page for stability after 3 loops.")
                    add_log(user_id, f"Refreshing page for stability.")
                    try:
                        page.goto("https://next.palladium.expert/pages/campaign-page", timeout=30000)
                        page.wait_for_load_state("domcontentloaded")
                        page.wait_for_timeout(3000)
                        logger.info(f"[User {user_id}] Page reset completed successfully.")
                    except Exception as reset_err:
                        logger.warning(f"[User {user_id}] Navigation reset failed: {reset_err}. Attempting reload...")
                        try:
                            page.reload(wait_until="domcontentloaded")
                            page.wait_for_timeout(3000)
                            logger.info(f"[User {user_id}] Page reload completed successfully.")
                        except Exception as reload_err:
                            logger.error(f"[User {user_id}] Page reset entirely failed: {reload_err}")
                
                # Cooldown Between Cycles
                time.sleep(2)
    
            except Exception as e:
                error_message = str(e).lower() 
 
                is_browser_crash = ( 
                    "target page" in error_message or 
                    "browser has been closed" in error_message or 
                    "context has been closed" in error_message 
                ) 
                
                is_timeout = ( 
                    "timeout" in error_message 
                ) 
                
                is_network_issue = ( 
                    "net::" in error_message or 
                    "err_connection" in error_message 
                ) 
                
                is_selector_issue = ( 
                    "waiting for selector" in error_message 
                ) 

                if is_browser_crash: 
                    logger.warning(f"[User {user_id}] Browser crashed, restarting...") 
                
                    add_log(user_id, "⚠️ Browser crashed → restarting...") 
                
                    try: 
                        if page: 
                            page.close() 
                        if context: 
                            context.close() 
                        if browser: 
                            browser.close() 
                    except: 
                        pass 
                
                    playwright, browser, page = launch_browser(user_id=user_id)
                    context = page.context
                
                    user["retry_map"].clear() 
                    error_count = 0 
                    cycle_count = 0
                    continue 

                elif is_timeout or is_network_issue or is_selector_issue: 
                    logger.warning(f"[User {user_id}] Temporary issue, retrying...") 
                
                    add_log(user_id, "⚠️ Temporary issue → retrying same link") 
                    
                    user = user_status.get(str(user_id), {})
                    if not user.get("temp_notified"): 
                        notify_user(
                            user_id, 
                            "⚠️ Temporary issue detected\nRetrying automatically..." 
                        ) 
                        user["temp_notified"] = True 
                
                    retry_map = user.get("retry_map", {}) 
                    retry_map[current_link] = retry_map.get(current_link, 0) + 1 
                
                    if retry_map[current_link] < 2: 
                        time.sleep(3) 
                        continue 

                # If it gets here, it's a real failure or exceeded temporary retries
                add_log(user_id, f"❌ Confirmed failure → {current_link}") 
                
                # Double-check link validity before removing
                try: 
                    response = page.goto(current_link, timeout=10000) 
                
                    if response and response.status < 400: 
                        add_log(user_id, "Link still valid → skipping removal") 
                        continue 
                except: 
                    pass 
                
                if current_link in user["active_links"]: 
                    user["active_links"].remove(current_link) 
                
                if current_link not in user["flagged_links"]: 
                    user["flagged_links"].append(current_link) 
                
                user.get("retry_map", {}).pop(current_link, None) 
                
                # Move to next link
                user_current_index = (user_current_index + 1) % len(active_links) if active_links else 0
                update_user(user_id, {"current_index": user_current_index})

                from telegram_bot.utils.error_tracker import save_error 
                from telegram_bot.utils.error_classifier_simple import classify_error as classify_error_simple
                
                error_type_simple = classify_error_simple(error_message) 

                save_error(user_id, { 
                    "error_message": error_message, 
                    "error_type": error_type_simple, 
                    "context": "automation_loop", 
                    "consecutive_errors": error_count + 1
                }) 

                try: 
                    retry_map = user_status.get(str(user_id), {}).get("retry_map", {})
                    if current_link not in retry_map: 
                        retry_map[current_link] = 0 
                    
                    retry_map[current_link] += 1 
                    
                    # Store back in user_status for persistence across loops
                    if str(user_id) in user_status:
                        user_status[str(user_id)]["retry_map"] = retry_map
                    
                    if retry_map[current_link] < 2: 
                        logger.info("Retrying before marking failed...") 
                        continue 

                    api_result = get_next_link(user_id) 
                    
                    if api_result and api_result.get("url"): 
                        new_link = api_result["url"] 
                        if new_link == current_link: 
                            logger.warning("Same link returned, skipping...") 
                            continue 

                        current_link = new_link 
                        
                        app_instance = user_bots.get(str(user_id)) 
                        
                        message = f"""🔄 Link Replaced Automatically 
 
❌ Old link failed 
✅ New link in use: 
{new_link} 
""" 
 
                        if app_instance: 
                            send_telegram_message(app_instance, user_id, message) 
 
                        logger.info(f"[User {user_id}] Switched to new link: {new_link}") 
                        add_log(user_id, f"Switched to new link: {new_link}") 
                except: 
                    pass 

                error_msg = error_message
                error_count += 1
                
                MAX_GLOBAL_ERRORS = 10 
 
                if error_count > MAX_GLOBAL_ERRORS: 
                    add_log(user_id, "Too many errors → cooling down...") 
                    time.sleep(10) 
                    error_count = 0 
                
                logger.error(f"[User {user_id}] Recoverable error during automation cycle: {e}. Error count: {error_count}/{MAX_ERRORS}")
                add_log(user_id, f"Recoverable error: {error_msg} (Count: {error_count})")
                
                # Intelligence Layer: Classify and Decide
                from telegram_bot.intelligence.error_classifier import classify_error, ErrorType
                from telegram_bot.intelligence.decision_engine import decide_action, ActionType, get_user_friendly_message
                
                error_type = classify_error(error_msg)
                action = decide_action(error_type)
                
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
                
                # Handle STOP action (Auth, Captcha, or Max Errors)
                if action == ActionType.STOP or error_count >= MAX_ERRORS:
                    if error_count >= MAX_ERRORS:
                        logger.error(f"[User {user_id}] Max error limit reached ({MAX_ERRORS}). Stopping automation.")
                        stop_reason = f"Reached maximum limit of {MAX_ERRORS} consecutive errors."
                        
                        save_error(user_id, { 
                            "error_message": error_msg, 
                            "error_type": error_type_simple, 
                            "context": "max_error_stop", 
                            "consecutive_errors": error_count, 
                            "stop_reason": "MAX_CONSECUTIVE_ERRORS" 
                        }) 
                    else:
                        logger.error(f"[User {user_id}] Critical error detected ({error_type.name}). Stopping automation.")
                        stop_reason = get_user_friendly_message(error_type, error_msg)
                        
                    add_log(user_id, "❌ Critical error or max limit reached. Stopping automation.")
                    
                    stop_msg = (
                        f"❌ *Automation Stopped*\n\n"
                        f"{stop_reason}\n\n"
                        "Please check your campaign settings and try again."
                    )
                    
                    app_instance = user_bots.get(str(user_id))
                    if app_instance:
                        if screenshot_path:
                            send_telegram_photo(app_instance, user_id, screenshot_path, stop_msg)
                        else:
                            send_telegram_message(app_instance, user_id, stop_msg)
                    
                    from telegram_bot.state_manager import load_users, save_users
                    users_data = load_users()
                    if str(user_id) in users_data:
                        users_data[str(user_id)]["running"] = False
                        save_users(users_data)
                        
                    stop_automation(user_id)
                    continue
                
                # Handle WAIT action (Rate Limit)
                if action == ActionType.WAIT:
                    cooldown_minutes = random.uniform(5, 15)
                    wait_seconds = int(cooldown_minutes * 60)
                    logger.warning(f"[User {user_id}] Rate limited. Waiting for {wait_seconds} seconds.")
                    
                    # Store in user state
                    try:
                        from telegram_bot.state_manager import update_user
                        update_user(user_id, {"global_cooldown_until": time.time() + wait_seconds})
                    except Exception as e_update:
                        logger.error(f"Failed to update cooldown state: {e_update}")
                    
                    app_instance = user_bots.get(str(user_id))
                    if app_instance and should_send_error(user_id):
                        msg = get_user_friendly_message(error_type)
                        send_telegram_message(app_instance, user_id, f"{msg}\n\nCooldown: {int(cooldown_minutes)} minutes.")
                        mark_error_sent(user_id)
                        
                    wait_with_interrupt(user_id, wait_seconds)
                    continue
                    
                # Handle RETRY and SELF_HEAL (Self-heal logic is in open_campaign, so we just retry here)
                # Send alert if cooldown passed
                if should_send_error(user_id):
                    # Determine user-friendly error reason
                    reason = get_user_friendly_message(error_type, error_msg)

                    message = (
                        "🚨 *Automation Error*\n\n"
                        f"📌 Campaign: {campaign_name}\n"
                        f"❌ {reason}\n"
                        f"🔍 Details: `{error_msg}`\n\n"
                        "🔄 The system will automatically recover and continue."
                    )
                    
                    app_instance = user_bots.get(str(user_id))
                    if app_instance:
                        if screenshot_path:
                            send_telegram_photo(app_instance, user_id, screenshot_path, message)
                        else:
                            send_telegram_message(app_instance, user_id, message)
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

    except Exception as fatal_e:
        logger.error(f"[User {user_id}] Fatal automation loop error: {fatal_e}")
        add_log(user_id, f"Fatal error: {str(fatal_e)}")
    finally:
        logger.info(f"[User {user_id}] Automation loop exiting. Cleaning up.")
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
            
        release_campaign(campaign_name)
