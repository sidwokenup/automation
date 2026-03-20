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

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /status command."""
    user = update.effective_user
    user_id = user.id
    
    # 1. Check if user has setup
    user_data = state_manager.get_user(user_id)
    state = user_data.get("state")
    running = state_manager.is_running(user_id)
    
    logger.info(f"[User {user_id}] ({user.username}) issued /status command. State={state}, Running={running}")
    
    if not user_data:
        await update.message.reply_text("❌ Please run /setup first")
        return
        
    if state != state_manager.COMPLETED:
        await update.message.reply_text("⚠️ Setup incomplete. Continue setup.")
        return

    if not running:
        await update.message.reply_text("🛑 Automation Status: STOPPED\n\nUse /run to start automation.")
        return
        
    # 2. Get runtime status
    status = get_status(user_id)
    
    # 3. Check if never started
    if not status:
        status = {}
        
    campaign = user_data.get("campaign", "Unknown")
    total_links = status.get("total_links", 0)
    current_link = status.get("current_link", "None")
    last_updated = status.get("last_updated")
    interval = user_data.get("interval", 10)
    
    # 4. Construct response
    if running:
        # Format last updated time
        time_msg = "Never"
        if last_updated:
            elapsed = int(time.time() - last_updated)
            if elapsed < 60:
                time_msg = "just now"
            elif elapsed < 3600:
                time_msg = f"{elapsed // 60} minutes ago"
            else:
                time_msg = f"{elapsed // 3600} hours ago"
        
        msg = (
            "🚀 Automation Status: RUNNING\n\n"
            f"📌 Campaign: {campaign}\n"
            f"🔗 Current Link: `{current_link}`\n\n"
            f"📊 Total Links: {total_links}\n"
            f"⏱ Last Updated: {time_msg}\n\n"
            f"🔄 Next Update: in ~{interval} minutes\n"
            f"⏳ Current Interval: {interval} minutes"
        )
    else:
        msg = (
            "🛑 Automation Status: STOPPED\n\n"
            f"📌 Campaign: {campaign}\n"
            f"📊 Total Links: {total_links}\n"
            f"⏳ Current Interval: {interval} minutes\n\n"
            "Use /run to start again"
        )
        
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
        
    if state != state_manager.COMPLETED:
        await update.message.reply_text("⚠️ Setup incomplete. Continue setup.")
        return

    if not running:
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
    user_id = str(user.id)
    logger.info(f"User {user.id} ({user.username}) started setup.")
    
    # Initialize user if not exists
    user_data = state_manager.get_user(user.id)
    
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
    
    # Check if setup is completed or ready to run
    if state not in [state_manager.COMPLETED, state_manager.READY_TO_RUN]:
        await update.message.reply_text("❌ Please complete setup first using /setup")
        return

    # Check if already running
    if running:
        await update.message.reply_text("⚠️ Automation already running")
        return

    # Start automation
    try:
        # Pass the global logger or create a specific one
        # Pass the bot instance from context
        start_automation(user_id, user_data, logging.getLogger('palladium_automation.runner'), context.bot)
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
    
    # --- 1. STRICT STATE MACHINE FOR SETUP FLOW ---
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

    # --- 2. INTENT DETECTION (Pre-AI) ---
    lower_text = text.lower()
    if any(keyword in lower_text for keyword in ["start", "run now", "begin automation"]):
        if state in [state_manager.COMPLETED, state_manager.READY_TO_RUN]:
            await update.message.reply_text("Triggering automation...")
            await run_command(update, context)
            return
        else:
            await update.message.reply_text("Please complete /setup first.")
            return
            
    if any(keyword in lower_text for keyword in ["stop", "halt", "pause"]):
        await update.message.reply_text("Stopping automation...")
        await stop_command(update, context)
        return

    # --- 3. AI ASSISTANT (For messy inputs / queries) ---
    # Show typing indicator while LLM processes
    await context.bot.send_chat_action(chat_id=user_id, action='typing')
    
    try:
        from telegram_bot.agent import process_user_message
        
        # Pass the message to the AI Agent
        response = await process_user_message(user_id, text, bot_instance=context.bot)
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in AI handler: {e}")
        await update.message.reply_text("❌ An error occurred while processing your message.")
