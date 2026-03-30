import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot import state_manager
from telegram_bot.automation_runner import start_automation, stop_automation, get_status, get_logs
import time

# Set up logger for handlers
logger = logging.getLogger('palladium_automation.telegram')

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /users command to view active users."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) issued /users command.")
    
    users_data = state_manager.load_users()
    active_users = []
    
    for uid, u_data in users_data.items():
        if u_data.get("running"):
            campaign = u_data.get("campaign", "Unknown")
            username = u_data.get("username", "Unknown")
            active_users.append(f"👤 `{uid}` ({username}) | 📌 `{campaign}`")
            
    if not active_users:
        await update.message.reply_text("📉 No active automations running right now.")
    else:
        response = "🚀 **Active Users:**\n\n" + "\n".join(active_users)
        await update.message.reply_text(response, parse_mode='Markdown')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) issued /start command.")
    
    welcome_message = (
        "👋 Welcome to Palladium Automation Bot\n\n"
        "Available commands:\n"
        "/setup - Configure your automation\n"
        "/run - Start automation\n"
        "/stop - Stop automation\n"
        "/status - Check status\n"
        "/logs - View recent activity logs\n"
        "/users - View all active automations (Admin)"
    )
    await update.message.reply_text(welcome_message)
    
    from telegram_bot.utils.link_api import check_api_health 

    api_ok = check_api_health() 

    if api_ok: 
        await update.message.reply_text("🔗 Link Service Connected ✅") 
    else: 
        await update.message.reply_text("⚠️ Link Service Not Reachable")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) issued /help command.")
    
    help_message = (
        "👋 Welcome to Palladium Automation Bot\n\n"
        "Available commands:\n"
        "/setup - Configure your automation\n"
        "/run - Start automation\n"
        "/stop - Stop automation\n"
        "/status - Check status\n"
        "/logs - View recent activity logs\n"
        "/users - View all active automations (Admin)"
    )
    await update.message.reply_text(help_message)

def is_user_fully_configured(user_data: dict) -> bool:
    """Check if the user has provided all necessary setup data."""
    if not user_data:
        return False
    required_keys = ["username", "password", "campaign", "links", "interval"]
    return all(bool(user_data.get(key)) for key in required_keys)

def calculate_progress(user_data):
    total = user_data.get("total_links", 0)
    if total == 0:
        links = user_data.get("active_links") or user_data.get("links", [])
        total = len(links) if isinstance(links, list) else 0
    current = user_data.get("current_index", 0)
    if total == 0:
        return 0
    return int(((current + 1) / total) * 100)

def get_current_link(user_data):
    user_id = str(user_data.get("user_id", ""))
    
    # Try to get from running status first for most accurate live data
    try:
        from telegram_bot.automation_runner import user_status
        live_status = user_status.get(user_id, {})
        index = live_status.get("current_index")
        if index is not None:
            active_links = user_data.get("active_links", [])
            if active_links and index < len(active_links):
                return active_links[index]
            if live_status.get("current_link"):
                return live_status["current_link"]
    except ImportError:
        pass
        
    active_links = user_data.get("active_links", [])
    index = user_data.get("current_index", 0)
    if isinstance(active_links, list) and 0 <= index < len(active_links):
        return active_links[index]
    return "N/A"

def calculate_eta(user_data):
    total = user_data.get("total_links", 0)
    if total == 0:
        links = user_data.get("links", [])
        total = len(links) if isinstance(links, list) else 0
    current = user_data.get("current_index", 0)
    try:
        interval = int(user_data.get("interval", 1))
    except ValueError:
        interval = 1
    remaining = total - current
    if remaining < 0:
        remaining = 0
    return remaining * interval * 60

def format_eta(seconds):
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}m {secs}s"

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /status command."""
    user = update.effective_user
    user_id = user.id
    str_user_id = str(user_id)
    
    user_data = state_manager.get_user(user_id)
    # Ensure user_id is in user_data for get_current_link
    user_data["user_id"] = str_user_id
    running = state_manager.is_running(user_id)
    
    logger.info(f"[User {user_id}] ({user.username}) issued /status command. Running={running}")
    
    if not user_data:
        await update.message.reply_text("❌ Please run /setup first")
        return
        
    if not running and not is_user_fully_configured(user_data):
        await update.message.reply_text("⚠️ Setup incomplete. Continue setup.")
        return
        
    # Get accurate live index
    current_index = user_data.get("current_index", 0)
    try:
        from telegram_bot.automation_runner import user_status
        live_status = user_status.get(str_user_id, {})
        if "current_index" in live_status:
            current_index = live_status["current_index"]
    except ImportError:
        pass
        
    # Inject current_index for calculation functions
    user_data["current_index"] = current_index

    progress = calculate_progress(user_data)
    current_link = get_current_link(user_data)
    eta = format_eta(calculate_eta(user_data))
    
    total_links = user_data.get("total_links", 0)
    if total_links == 0:
        links = user_data.get("active_links") or user_data.get("links", [])
        total_links = len(links) if isinstance(links, list) else 0
        
    interval = user_data.get("interval", 10)
    campaign = user_data.get("campaign", "Unknown")
    
    status_emoji = "🟢 Status: RUNNING" if running else "🟡 Status: STOPPED"
    
    status_text = f"""🚀 *Automation Dashboard*

📊 Progress: {progress}%
🔗 Current Link:
`{current_link}`

📦 Total Links: {total_links}
🔁 Current Index: {current_index + 1}

⏱️ Interval: {interval} min
⌛ ETA: {eta}

{status_emoji}
🎯 Campaign: {campaign}"""

    if running:
        await update.message.reply_text(status_text, parse_mode='Markdown')
    else:
        await update.message.reply_text("✅ Setup complete. Ready to run.\n\n" + status_text, parse_mode='Markdown')

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /progress command for a quick lightweight status check."""
    user = update.effective_user
    user_id = user.id
    user_data = state_manager.get_user(user_id)
    running = state_manager.is_running(user_id)
    
    if not user_data or (not running and not is_user_fully_configured(user_data)):
        await update.message.reply_text("⚠️ Setup incomplete or not running.")
        return
        
    progress = calculate_progress(user_data)
    current_index = user_data.get("current_index", 0)
    
    # Try to get live index
    try:
        from telegram_bot.automation_runner import user_status
        live_status = user_status.get(str(user_id), {})
        if "current_index" in live_status:
            current_index = live_status["current_index"]
    except ImportError:
        pass
        
    total_links = user_data.get("total_links", 0)
    if total_links == 0:
         links = user_data.get("active_links") or user_data.get("links", [])
         total_links = len(links) if isinstance(links, list) else 0
         
    status_emoji = "🟢 RUNNING" if running else "🟡 STOPPED"
    
    msg = f"📊 *Progress*: {progress}% ({current_index + 1}/{total_links}) | {status_emoji}"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /logs command to show recent automation activity."""
    user = update.effective_user
    user_id = user.id
    
    # 1. Check if user has setup
    user_data = state_manager.get_user(user_id)
    state = user_data.get("state")
    running = state_manager.is_running(user_id)
    
    logger.info(f"[User {user_id}] ({user.username}) issued /logs command. State={state}, Running={running}")
    
    if not user_data:
        await update.message.reply_text("❌ Please run /setup first")
        return
        
    # 2. Get logs
    from telegram_bot.utils.file_logger import read_logs
    
    logs = read_logs(user_id, limit=20)
    
    if not logs:
        await update.message.reply_text("📭 No logs available yet.")
        return
        
    # 3. Format response
    response = "📜 **Recent Logs:**\n\n"
    for log in logs:
        response += f"`{log.strip()}`\n"
        
    await update.message.reply_text(response, parse_mode='Markdown')

def parse_proxy(proxy_string):
    """Parses a proxy string (or multiple separated by comma or newline) into a list of strings and dicts."""
    try:
        proxies_list = []
        proxies_strings = []
        
        # Split by comma or newline to support multiple proxies
        raw_strings = [p.strip() for p in proxy_string.replace("\n", ",").split(",") if p.strip()]
        
        for p_str in raw_strings:
            if "@" in p_str:
                creds, host = p_str.split("@")
                username, password = creds.split(":")
                ip, port = host.split(":")
                proxy_url = f"http://{username}:{password}@{ip}:{port}"
            else:
                username = password = None
                ip, port = p_str.split(":")
                proxy_url = f"http://{ip}:{port}"
                
            proxies_list.append({
                "server": f"http://{ip}:{port}",
                "username": username,
                "password": password
            })
            proxies_strings.append(proxy_url)
            
        if not proxies_list:
            return None, None
            
        old_format = {
            "enabled": True,
            "list": proxies_list,
            "current_index": 0
        }
        return old_format, proxies_strings
    except Exception:
        return None, None

async def proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /proxy command to start proxy configuration."""
    user = update.effective_user
    user_id = user.id
    
    if state_manager.is_running(user_id):
        await update.message.reply_text("⚠️ Automation is currently running. Please /stop it before configuring proxy.")
        return
        
    state_manager.set_state(user_id, state_manager.WAITING_PROXY_CHOICE)
    await update.message.reply_text("🌐 Do you want to use a proxy? (yes/no)")

async def proxy_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /proxy_status command."""
    user = update.effective_user
    user_id = user.id
    user_data = state_manager.get_user(user_id)
    
    proxy_info = user_data.get("proxy", {})
    if proxy_info.get("enabled") and proxy_info.get("list"):
        count = len(proxy_info["list"])
        current_idx = proxy_info.get("current_index", 0)
        current_server = proxy_info["list"][current_idx]["server"]
        msg = f"🌐 Proxy Status: Enabled\nTotal Proxies: {count}\nCurrent Server: {current_server}"
    else:
        msg = "🌐 Proxy Status: Disabled"
        
    await update.message.reply_text(msg)

async def delete_proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /delete_proxy command."""
    user_id = update.effective_user.id
    state_manager.update_user(user_id, {"proxy": None, "proxies": [], "current_proxy_index": 0})
    await update.message.reply_text("✅ Proxy deleted successfully.")

async def delete_setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /delete_setup command."""
    user_id = update.effective_user.id
    users_data = state_manager.load_users()
    if str(user_id) in users_data:
        del users_data[str(user_id)]
        state_manager.save_users(users_data)
    await update.message.reply_text("🗑 Setup deleted. Use /setup to reconfigure.")

async def test_links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram_bot.utils.link_api import get_next_link
    
    user_id = update.effective_user.id
    
    result = get_next_link(user_id)
    
    if not result or not result.get("url"):
        await update.message.reply_text("🚨 No active links available")
    else:
        await update.message.reply_text(f"✅ Next link: {result['url']}")

async def why_stopped_command(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    from telegram_bot.utils.error_tracker import load_error 
    
    user_id = update.effective_user.id 
    error_data = load_error(user_id) 
    
    if not error_data: 
        await update.message.reply_text("✅ No recent errors found. Automation stopped normally.") 
        return 
    
    error_type = error_data.get("error_type", "UNKNOWN") 
    message = error_data.get("error_message", "No details") 
    count = error_data.get("consecutive_errors", 0) 
    
    if error_type == "BROWSER_CRASH": 
        explanation = "Browser session crashed or page closed unexpectedly." 
        suggestion = "Try changing proxy or restarting automation." 
        
    elif error_type == "TIMEOUT": 
        explanation = "Website took too long to respond." 
        suggestion = "Increase interval or check network stability." 
        
    elif error_type == "PROXY_ERROR": 
        explanation = "Proxy connection failed." 
        suggestion = "Use a different proxy." 
        
    else: 
        explanation = "Unexpected error occurred." 
        suggestion = "Check logs for more details." 

    response = f"""❌ Automation Stopped 

🧠 Reason: 
{explanation} 

📄 Technical Detail: 
{message} 

🔁 Occurred {count} times 

💡 Suggested Fix: 
{suggestion} 
""" 
    
    await update.message.reply_text(response)

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_state = state_manager.get_user(user_id)

    links_data = user_state.get("links_data", [])
    
    if not links_data:
        await update.message.reply_text("📦 No links configured or data missing.")
        return

    active = [] 
    failed = [] 
 
    for link in links_data: 
        if link["status"] == "active": 
            active.append(link) 
        else: 
            failed.append(link) 
 
    message = "🔗 Link Status:\n\n" 
 
    message += "🟢 Active Links:\n" 
    for l in active: 
        message += f"- {l['url']} (✔ {l['success_count']})\n" 
 
    message += "\n🔴 Failed Links:\n" 
    for l in failed: 
        message += f"- {l['url']} (❌ {l['fail_count']})\n" 
 
    message += f"\n📍 Current Index: {user_state.get('current_index', 0) + 1}" 
 
    await update.message.reply_text(message)

async def flagged_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = state_manager.get_user(user_id)

    flagged = user.get("flagged_links", [])

    if not flagged:
        await update.message.reply_text("🚫 No flagged links.")
        return

    msg = "🚫 Flagged Links:\n\n"

    for i, link in enumerate(flagged, 1):
        msg += f"{i}. {link}\n"

    await update.message.reply_text(msg)

async def current_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = state_manager.get_user(user_id)
    
    # Try to get from running status first for most accurate live data
    from telegram_bot.automation_runner import user_status
    live_status = user_status.get(user_id, {})

    index = live_status.get("current_index")
    if index is None:
        index = user.get("current_index", 0)
    
    active_links = user.get("active_links", [])
    link = active_links[index] if active_links and index < len(active_links) else (live_status.get("current_link") or user.get("current_link"))

    if not link:
        await update.message.reply_text("🔗 No active link currently.")
        return

    msg = f"🔗 Current Link:\n{link}\n\n📍 Index: {index + 1}"

    await update.message.reply_text(msg)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = state_manager.get_user(user_id)

    # Use API for active count if available
    from telegram_bot.utils.link_api import get_active_links
    api_active = get_active_links(user_id)
    
    active = len(api_active) if api_active else len(user.get("active_links", []))
    flagged = len(user.get("flagged_links", []))

    stats = user.get("link_stats", {})

    msg = (
        "📊 Link Stats:\n\n"
        f"✅ Active: {active}\n"
        f"❌ Flagged: {flagged}\n"
        f"🔁 Rotations: {stats.get('total_rotations', 0)}\n"
        f"⚠️ Failures: {stats.get('failures', 0)}"
    )

    await update.message.reply_text(msg)

async def setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /setup command to start the configuration flow."""
    user = update.effective_user
    user_id = user.id
    logger.info(f"User {user.id} ({user.username}) started setup.")
    
    # Check if automation is running
    if state_manager.is_running(user_id):
        await update.message.reply_text("⚠️ Automation is currently running. Please /stop it before running setup.")
        return
    
    # Initialize user if not exists
    user_data = state_manager.get_user(user_id)
    
    # Check if they already have config
    has_config = bool(user_data.get("username") and user_data.get("campaign"))
    
    state_manager.set_state(user.id, state_manager.WAITING_USERNAME)
    
    if has_config:
        await update.message.reply_text(
            f"You already have a configuration saved for campaign '{user_data.get('campaign')}'.\n"
            "Entering new details will overwrite it.\n\n"
            "Please enter your Palladium username (email):"
        )
    else:
        await update.message.reply_text("Let's configure your automation.\n\nEnter your Palladium username (email):")

async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /run command to start automation."""
    user = update.effective_user
    user_id = user.id

    user_data = state_manager.get_user(user_id)
    state = user_data.get("state")
    running = state_manager.is_running(user_id)
    
    logger.info(f"[User {user_id}] ({user.username}) issued /run command. State={state}, Running={running}")
    
    if not user_data:
        await update.message.reply_text("❌ Please run /setup first")
        return
    
    # Check if setup is completed based on data
    if not is_user_fully_configured(user_data):
        await update.message.reply_text("❌ Please complete setup first using /setup")
        return

    # Check if already running
    if running:
        await update.message.reply_text("⚠️ Automation already running")
        return
        
    # Prevent Rapid /run Abuse and Global Cooldown Check
    last_run = user_data.get("last_run_cmd_time", 0)
    cooldown_until = user_data.get("global_cooldown_until", 0)
    
    if time.time() < cooldown_until:
        remaining = int((cooldown_until - time.time()) / 60) + 1
        await update.message.reply_text(f"⛔ Too many attempts detected. Please wait ~{remaining} minutes before retrying.")
        return
        
    if time.time() - last_run < 30:
        await update.message.reply_text("⚠️ Please wait before restarting automation")
        return
        
    state_manager.update_user(user_id, {"last_run_cmd_time": time.time()})

    # Start automation
    try:
        # Pass the global logger or create a specific one
        # Pass the application context
        start_automation(user_id, user_data, logging.getLogger('palladium_automation.runner'), bot_instance=context.application)
        # Note: start_automation now handles setting 'running': True in disk, and shouldn't change state.
        await update.message.reply_text("🚀 Automation started successfully!")
    except Exception as e:
        logger.error(f"Failed to start automation for user {user_id}: {e}")
        await update.message.reply_text("❌ Failed to start automation. Check logs.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /stop command to halt automation."""
    user = update.effective_user
    user_id = user.id
    
    user_data = state_manager.get_user(user_id)
    state = user_data.get("state")
    running = state_manager.is_running(user_id)
    
    logger.info(f"[User {user_id}] ({user.username}) issued /stop command. State={state}, Running={running}")

    # Check if running
    if not running:
        from telegram_bot.automation_runner import active_threads
        str_user_id = str(user_id)
        if str_user_id not in active_threads:
            await update.message.reply_text("⚠️ No automation is currently running")
            return

    # Stop automation
    try:
        stop_automation(user_id)
        # Note: stop_automation now handles setting 'running': False in disk, and shouldn't change state.
        await update.message.reply_text("🛑 Automation stopped successfully")
    except Exception as e:
        logger.error(f"Failed to stop automation for user {user_id}: {e}")
        await update.message.reply_text("❌ Failed to stop automation. Check logs.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming text messages with a hybrid State Machine + AI approach."""
    user = update.effective_user
    text = update.message.text.strip()
    user_id = user.id
    
    logger.info(f"Received message from User {user_id} ({user.username}): {text}")
    
    user_data = state_manager.get_user(user_id)
    state = user_data.get("state")
    running = state_manager.is_running(user_id)
    lower_text = text.lower()
    
    # --- 1. GLOBAL COMMAND INTERCEPTOR (During Runtime) ---
    if running:
        if "status" in lower_text or "progress" in lower_text:
            return await status_command(update, context)
        if "log" in lower_text:
            return await logs_command(update, context)
        if "stop" in lower_text or "halt" in lower_text:
            return await stop_command(update, context)
            
        # IMPORTANT: DO NOT BREAK FLOW
        await update.message.reply_text(
            "🤖 Automation is running.\n\n"
            "Use:\n"
            "/status - View live dashboard\n"
            "/logs - View activity logs\n"
            "/stop - Stop automation"
        )
        return

    # --- 2. INTENT DETECTION (Pre-AI) ---
    if not state or state in [state_manager.READY_TO_RUN, state_manager.COMPLETED, state_manager.IDLE]:
        from telegram_bot.intelligence.intent_handler import detect_intent
        intent = detect_intent(text)

        if intent == "DELETE_PROXY":
            state_manager.update_user(user_id, {"proxy": None, "proxies": [], "current_proxy_index": 0})
            await update.message.reply_text("✅ Proxy deleted successfully.")
            return

        if intent == "DELETE_SETUP":
            # Clear user data except maybe basic info, essentially defaulting them
            users_data = state_manager.load_users()
            if str(user_id) in users_data:
                del users_data[str(user_id)]
                state_manager.save_users(users_data)
            await update.message.reply_text("🗑 Setup deleted. Use /setup to reconfigure.")
            return

        if intent == "GREETING":
            await update.message.reply_text("👋 Hey! I'm your automation bot. Use /run to start.")
            return

        if any(keyword in lower_text for keyword in ["start", "run now", "begin automation"]):
            if is_user_fully_configured(user_data):
                await update.message.reply_text("Triggering automation...")
                return await run_command(update, context)
            else:
                await update.message.reply_text("Please complete /setup first.")
                return await setup_command(update, context)
                
        if any(keyword in lower_text for keyword in ["stop", "halt", "pause"]):
            await update.message.reply_text("Stopping automation...")
            return await stop_command(update, context)
            
        if "status" in lower_text or "progress" in lower_text:
            return await status_command(update, context)
            
        if "log" in lower_text:
            return await logs_command(update, context)
            
        if "setup" in lower_text or "configure" in lower_text:
            return await setup_command(update, context)

    # --- 3. STRICT STATE MACHINE FOR SETUP FLOW ---
    if state == state_manager.WAITING_USERNAME:
        state_manager.update_user(user_id, {"username": text, "state": state_manager.WAITING_PASSWORD})
        await update.message.reply_text("Enter your password:")
        return

    elif state == state_manager.WAITING_PASSWORD:
        state_manager.update_user(user_id, {"password": text, "state": state_manager.WAITING_CAMPAIGN})
        try:
            await update.message.delete()
            await update.message.reply_text("*(Password message deleted for security)*", parse_mode='Markdown')
        except:
            pass
        await update.message.reply_text("Enter campaign name (e.g., CAMP-1):")
        return

    elif state == state_manager.WAITING_CAMPAIGN:
        state_manager.update_user(user_id, {"campaign": text, "state": state_manager.WAITING_LINKS})
        await update.message.reply_text("Enter links (comma-separated):")
        return

    elif state == state_manager.WAITING_LINKS:
        links = [l.strip() for l in text.split(",") if l.strip()]
        if not links:
            await update.message.reply_text("❌ At least 1 valid link is required.\nEnter links (comma-separated):")
            return
        state_manager.update_user(user_id, {
            "links": links, 
            "active_links": links.copy(),
            "flagged_links": [],
            "links_data": [],
            "state": state_manager.WAITING_INTERVAL
        })
        
        from telegram_bot.utils.link_api import add_links 
        try: 
            add_links(user_id, links) 
            await update.message.reply_text("🔗 Links synced to Link Service ✅") 
        except Exception as e:
            logger.error(f"Failed to sync links: {e}")
            await update.message.reply_text("⚠️ Failed to sync links to Link Service") 

        await update.message.reply_text("Enter interval in minutes (e.g., 10):")
        return

    elif state == state_manager.WAITING_INTERVAL:
        try:
            interval = int(text)
            if interval < 1: raise ValueError()
        except ValueError:
            await update.message.reply_text("❌ Invalid input. Please enter a valid number (minimum 1):\nEnter interval in minutes:")
            return
            
        state_manager.update_user(user_id, {"interval": interval, "state": state_manager.READY_TO_RUN})
        
        completion_msg = (
            "✅ Setup completed successfully!\n\n"
            "Use /run to start automation\n"
            "Use /stop to stop automation\n"
            "Use /status to check status\n"
            "Use /logs to view activity logs"
        )
        await update.message.reply_text(completion_msg)
        return

    elif state == state_manager.WAITING_PROXY_CHOICE:
        if lower_text in ["yes", "y", "true"]:
            state_manager.set_state(user_id, state_manager.WAITING_PROXY_INPUT)
            await update.message.reply_text("Enter proxy (or multiple separated by comma) in format:\n`ip:port` OR `username:password@ip:port`", parse_mode='Markdown')
        else:
            state_manager.update_user(user_id, {"proxy": {"enabled": False}, "state": state_manager.COMPLETED})
            await update.message.reply_text("🌐 Proxy disabled. Use /run to start automation.")
        return

    elif state == state_manager.WAITING_PROXY_INPUT:
        old_proxy_data, proxies_strings = parse_proxy(text)
        if not old_proxy_data:
            await update.message.reply_text("❌ Invalid proxy format. Please use `ip:port` or `username:password@ip:port`", parse_mode='Markdown')
            return
            
        state_manager.update_user(user_id, {
            "proxy": old_proxy_data, 
            "proxies": proxies_strings,
            "current_proxy_index": 0,
            "state": state_manager.COMPLETED
        })
        await update.message.reply_text("✅ Proxy configured successfully!\nUse /proxy_status to verify.")
        return

    # --- 4. AI ASSISTANT (For messy inputs / queries) ---
    # Show typing indicator while LLM processes
    await context.bot.send_chat_action(chat_id=user_id, action='typing')
    
    if "why" in lower_text and "stop" in lower_text: 
        from telegram_bot.agent import process_user_message 
        response = await process_user_message(user_id, text, application_instance=context.application) 
        await update.message.reply_text(response, parse_mode='Markdown') 
        return 
    
    response = None
    try:
        from telegram_bot.agent import process_user_message
        
        # Pass the message to the AI Agent
        response = await process_user_message(user_id, text, application_instance=context.application)
        
        if response:
            await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in AI handler: {e}")
        
    # Fallback as requested
    if not response:
        await update.message.reply_text("🤖 I didn't understand. Try /help.")
