import logging
import threading
import time
from automation.browser import launch_browser, login, navigate_to_campaigns, open_campaign, update_target_link, ensure_logged_in, ensure_campaign_page
from telegram_bot.state_manager import get_current_index, update_current_index

import asyncio

# Global storage for tracking user threads and flags
user_threads = {}
user_flags = {}
user_status = {}
user_logs = {}
user_bots = {} # Store bot instance per user
last_error_time = {}
ERROR_COOLDOWN = 300 # 5 minutes

async def send_error_alert(bot_instance, user_id, message):
    """Sends an error alert to the user via Telegram."""
    try:
        if bot_instance:
            await bot_instance.send_message(
                chat_id=user_id,
                text=message
            )
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

def should_send_error(user_id):
    """Checks if an error alert should be sent based on cooldown."""
    now = time.time()
    last_time = last_error_time.get(str(user_id), 0)
    
    if now - last_time > ERROR_COOLDOWN:
        last_error_time[str(user_id)] = now
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
    
    # Create and start thread
    thread = threading.Thread(target=automation_loop, args=(str_user_id, config, logger), daemon=True)
    user_threads[str_user_id] = thread
    thread.start()
    
    logger.info(f"Started automation thread for user {user_id}")
    add_log(str_user_id, "Automation thread started")
    return True

def stop_automation(user_id):
    """Stops the automation loop for a user."""
    str_user_id = str(user_id)
    
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

def recover_session(user_id, config, browser, playwright, logger):
    """Attempts to recover the session by restarting the browser."""
    logger.warning(f"[User {user_id}] Initiating session recovery...")
    add_log(user_id, "Recovery triggered: Restarting browser session")
    
    if browser:
        try:
            browser.close()
        except:
            pass
            
    if playwright:
        try:
            playwright.stop()
        except:
            pass
            
    try:
        new_playwright, new_browser, new_page = launch_browser()
        login(new_page, config["username"], config["password"])
        add_log(user_id, "Recovery successful: Re-logged in")
        return new_playwright, new_browser, new_page
    except Exception as e:
        logger.error(f"[User {user_id}] Recovery failed: {e}")
        add_log(user_id, f"Recovery failed: {e}")
        raise e

def wait_with_interrupt(user_id, seconds):
    """Waits for the specified seconds but can be interrupted if the flag is cleared."""
    for _ in range(seconds):
        if not user_flags.get(str(user_id), False):
            break
        time.sleep(1)

def automation_loop(user_id, config, logger):
    """The main automation loop that runs in the background with persistent session."""
    logger.info(f"[User {user_id}] Automation loop started.")
    add_log(user_id, "Automation loop started")
    
    links = config.get("links", [])
    if not links:
        logger.error(f"[User {user_id}] No links found in config to process.")
        add_log(user_id, "Error: No links found in configuration")
        user_flags[user_id] = False
        if user_id in user_status:
            user_status[user_id]["running"] = False
        return

    interval_minutes = config.get("interval", 10)
    
    playwright = None
    browser = None
    page = None
    
    # Initial Setup
    try:
        playwright, browser, page = launch_browser()
        login(page, config["username"], config["password"])
        add_log(user_id, "Initial login successful")
    except Exception as e:
        logger.error(f"[User {user_id}] Initial setup failed: {e}")
        add_log(user_id, f"Initial setup failed: {e}")
        user_flags[user_id] = False
        if user_id in user_status:
            user_status[user_id]["running"] = False
        if browser:
            try: browser.close()
            except: pass
        if playwright:
            try: playwright.stop()
            except: pass
        return

    link_index = get_current_index(user_id)
    failure_count = 0

    while user_flags.get(user_id, False):
        # Validate index (e.g. if user updated links and removed some)
        if link_index >= len(links):
            link_index = 0
            
        current_link = links[link_index]
        
        # Update status
        if user_id in user_status:
            user_status[user_id]["current_link"] = current_link
            user_status[user_id]["current_index"] = link_index + 1

        try:
            logger.info(f"[User {user_id}] Starting cycle with link index {link_index}: {current_link}")
            add_log(user_id, f"Using link index: {link_index}")
            
            # Ensure persistent state
            ensure_logged_in(page, config["username"], config["password"])
            add_log(user_id, "Session valid")
            
            ensure_campaign_page(page)
            open_campaign(page, config["campaign"])
            add_log(user_id, f"Opened campaign: {config['campaign']}")
            
            update_target_link(page, current_link)
            
            logger.info(f"[User {user_id}] Updated link successfully: {current_link}")
            add_log(user_id, f"Updated link successfully: {current_link}")
            
            # Update status after success
            if user_id in user_status:
                user_status[user_id]["last_updated"] = time.time()
                
            # Reset failure count on success
            failure_count = 0
            
            # Update persistent index ONLY after successful update
            link_index = (link_index + 1) % len(links)
            update_current_index(user_id, link_index)
            add_log(user_id, f"Next index will be: {link_index}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[User {user_id}] Error during automation cycle: {e}")
            add_log(user_id, f"Error: {error_msg}")
            
            # Send alert if cooldown passed
            bot_instance = user_bots.get(str(user_id))
            if should_send_error(user_id) and bot_instance:
                message = (
                    "🚨 *Automation Error*\n\n"
                    f"📌 Campaign: {config.get('campaign', 'Unknown')}\n"
                    f"❌ Error: `{error_msg}`\n\n"
                    "🔄 The system will retry automatically."
                )
                asyncio.run_coroutine_threadsafe(
                    send_error_alert(bot_instance, user_id, message),
                    bot_instance.loop
                )

            failure_count += 1
            
            if failure_count >= 3:
                logger.error(f"[User {user_id}] Max failures reached. Attempting session recovery...")
                
                # Alert for recovery
                add_log(user_id, "Recovery triggered")
                if should_send_error(user_id) and bot_instance:
                    msg_rec = "⚠️ System encountered repeated issues. Recovering session..."
                    asyncio.run_coroutine_threadsafe(
                        send_error_alert(bot_instance, user_id, msg_rec),
                        bot_instance.loop
                    )
                
                try:
                    playwright, browser, page = recover_session(user_id, config, browser, playwright, logger)
                    failure_count = 0 # Reset after recovery
                except Exception as recovery_error:
                    logger.error(f"[User {user_id}] Recovery failed completely. Stopping automation.")
                    user_flags[user_id] = False
                    break
            else:
                logger.warning(f"[User {user_id}] Minor failure. Retrying next cycle.")

        # Wait before processing the next link
        if user_flags.get(user_id, False):
            logger.info(f"[User {user_id}] Waiting {interval_minutes} minutes before next cycle...")
            wait_with_interrupt(user_id, interval_minutes * 60)

    # Clean Shutdown
    logger.info(f"[User {user_id}] Automation loop terminated. Cleaning up...")
    add_log(user_id, "Automation loop terminated. Cleaning up...")
    if browser:
        try:
            browser.close()
        except:
            pass
    if playwright:
        try:
            playwright.stop()
        except:
            pass
            
    if user_id in user_status:
        user_status[user_id]["running"] = False
