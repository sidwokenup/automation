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
        links = user_data.get("links", [])
        total = len(links) if isinstance(links, list) else 0
    current = user_data.get("current_index", 0)
    if total == 0:
        return 0
    return int((current / total) * 100)

def get_current_link(user_data):
    links = user_data.get("links", [])
    index = user_data.get("current_index", 0)
    if isinstance(links, list) and 0 <= index < len(links):
        return links[index]
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
    
    user_data = state_manager.get_user(user_id)
    running = state_manager.is_running(user_id)
    
    logger.info(f"[User {user_id}] ({user.username}) issued /status command. Running={running}")
    
    if not user_data:
        await update.message.reply_text("❌ Please run /setup first")
        return
        
    if not running and not is_user_fully_configured(user_data):
        await update.message.reply_text("⚠️ Setup incomplete. Continue setup.")
        return
        
    progress = calculate_progress(user_data)
    current_link = get_current_link(user_data)
    eta = format_eta(calculate_eta(user_data))
    
    total_links = user_data.get("total_links", 0)
    if total_links == 0:
        links = user_data.get("links", [])
        total_links = len(links) if isinstance(links, list) else 0
        
    current_index = user_data.get("current_index", 0)
    interval = user_data.get("interval", 10)
    campaign = user_data.get("campaign", "Unknown")
    
    status_emoji = "🟢 Status: RUNNING" if running else "🟡 Status: STOPPED"
    
    status_text = f"""🚀 *Automation Dashboard*

📊 Progress: {progress}%
🔗 Current Link:
`{current_link}`

📦 Total Links: {total_links}
🔁 Current Index: {current_index}

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
    total_links = user_data.get("total_links", 0)
    if total_links == 0:
         links = user_data.get("links", [])
         total_links = len(links) if isinstance(links, list) else 0
         
    status_emoji = "🟢 RUNNING" if running else "🟡 STOPPED"
    
    msg = f"📊 *Progress*: {progress}% ({current_index}/{total_links}) | {status_emoji}"
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
        
    if not running:
        if not is_user_fully_configured(user_data):
            await update.message.reply_text("⚠️ Setup incomplete. Continue setup.")
            return
            
        await update.message.reply_text("📭 Automation is not running.\nRun /run to start automation.")
        return

    # 2. Get logs
    logs = get_logs(user_id)
    
    if not logs:
        await update.message.reply_text("📭 No logs available yet. They will appear here once the automation performs actions.")
        return
        
    # 3. Format response (Last 15 logs)
    response = "📜 **Recent Logs:**\n\n"
    for log in logs[-15:]:
        response += f"`{log}`\n"
        
    await update.message.reply_text(response, parse_mode='Markdown')

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
        
    # Prevent Rapid /run Abuse
    if time.time() - user_data.get("last_run_cmd_time", 0) < 30:
        await update.message.reply_text("⚠️ Please wait before restarting automation")
        return
        
    state_manager.update_user(user_id, {"last_run_cmd_time": time.time()})

    # Start automation
    try:
        # Pass the global logger or create a specific one
        # Pass the application context
        start_automation(user_id, user_data, logging.getLogger('palladium_automation.runner'), context.application)
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
        state_manager.update_user(user_id, {"links": links, "state": state_manager.WAITING_INTERVAL})
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

    # --- 4. AI ASSISTANT (For messy inputs / queries) ---
    # Show typing indicator while LLM processes
    await context.bot.send_chat_action(chat_id=user_id, action='typing')
    
    try:
        from telegram_bot.agent import process_user_message
        
        # Pass the message to the AI Agent
        response = await process_user_message(user_id, text, application_instance=context.application)
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in AI handler: {e}")
        await update.message.reply_text("❌ An error occurred while processing your message.")
