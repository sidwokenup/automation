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
        "/status - Check status"
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
        "/status - Check status"
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

    # 2. Get runtime status
    status = get_status(user_id)
    
    # 3. Check if never started
    if not status:
        await update.message.reply_text("⚠️ Automation has not been started yet. Use /run.")
        return
        
    campaign = status.get("campaign", "Unknown")
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

    # 2. Get logs
    logs = get_logs(user_id)
    
    if not logs:
        await update.message.reply_text("📭 No logs available yet.\nRun /run to start automation.")
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
    
    from telegram_bot.state_manager import load_users, save_users
    user_data = load_users()
    
    if user_id not in user_data:
        user_data[user_id] = {}
        
    user_data[user_id]["state"] = state_manager.WAITING_USERNAME
    user_data[user_id]["running"] = False
    
    save_users(user_data)
    
    await update.message.reply_text("Let's configure your automation.\n\nEnter your username:")

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
    
    # Check if setup is completed
    if state != state_manager.COMPLETED:
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
    """Handles incoming text messages based on user state."""
    user = update.effective_user
    text = update.message.text.strip()
    user_id = user.id
    str_user_id = str(user_id)
    
    # load_users() is called correctly before reading state
    users_data = state_manager.load_users()
    
    if str_user_id not in users_data:
        return
        
    user_state = users_data[str_user_id]
    state = user_state.get("state")
    
    if not state or state == state_manager.COMPLETED:
        # Ignore messages if not in setup flow
        return

    # WAITING_USERNAME
    if state == state_manager.WAITING_USERNAME:
        if not text:
            await update.message.reply_text("❌ Invalid input. Please try again.\nEnter your username:")
            return
            
        logger.info(f"User {user_id} provided username.")
        
        users_data = state_manager.load_users()
        users_data[str_user_id]["username"] = text
        users_data[str_user_id]["state"] = state_manager.WAITING_PASSWORD
        state_manager.save_users(users_data)
        
        logger.info(f"User {user_id} state: {users_data[str_user_id]['state']}")
        await update.message.reply_text("Enter your password:")
        return

    # WAITING_PASSWORD
    elif state == state_manager.WAITING_PASSWORD:
        if not text:
            await update.message.reply_text("❌ Invalid input. Please try again.\nEnter your password:")
            return
            
        logger.info(f"User {user_id} provided password.")
        
        users_data = state_manager.load_users()
        users_data[str_user_id]["password"] = text
        users_data[str_user_id]["state"] = state_manager.WAITING_CAMPAIGN
        state_manager.save_users(users_data)
        
        logger.info(f"User {user_id} state: {users_data[str_user_id]['state']}")
        
        # Delete the message containing the password for security
        try:
            await update.message.delete()
            await update.message.reply_text("*(Password message deleted for security)*", parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"Could not delete password message: {e}")
            
        await update.message.reply_text("Enter campaign name (e.g., CAMP-1):")
        return

    # WAITING_CAMPAIGN
    elif state == state_manager.WAITING_CAMPAIGN:
        if not text:
            await update.message.reply_text("❌ Invalid input. Please try again.\nEnter campaign name:")
            return
            
        logger.info(f"User {user_id} provided campaign: {text}")
        
        users_data = state_manager.load_users()
        users_data[str_user_id]["campaign"] = text
        users_data[str_user_id]["state"] = state_manager.WAITING_LINKS
        state_manager.save_users(users_data)
        
        logger.info(f"User {user_id} state: {users_data[str_user_id]['state']}")
        await update.message.reply_text("Enter links (comma-separated):")
        return

    # WAITING_LINKS
    elif state == state_manager.WAITING_LINKS:
        if not text:
            await update.message.reply_text("❌ Invalid input. Please try again.\nEnter links (comma-separated):")
            return
            
        links = text.split(",")
        links = [l.strip() for l in links if l.strip()]
        
        if not links:
            await update.message.reply_text("❌ At least 1 valid link is required. Please try again.\nEnter links (comma-separated):")
            return
            
        logger.info(f"User {user_id} provided {len(links)} links.")
        
        users_data = state_manager.load_users()
        users_data[str_user_id]["links"] = links
        users_data[str_user_id]["state"] = state_manager.WAITING_INTERVAL
        state_manager.save_users(users_data)
        
        logger.info(f"User {user_id} state: {users_data[str_user_id]['state']}")
        await update.message.reply_text("Enter interval in minutes (e.g., 10):")
        return

    # WAITING_INTERVAL
    elif state == state_manager.WAITING_INTERVAL:
        if not text:
            await update.message.reply_text("❌ Invalid input. Please try again.\nEnter interval in minutes (e.g., 10):")
            return
            
        try:
            interval = int(text)
            if interval < 1:
                raise ValueError("Interval must be at least 1")
        except ValueError:
            await update.message.reply_text("❌ Invalid input. Please enter a valid number (minimum 1):\nEnter interval in minutes (e.g., 10):")
            return
            
        logger.info(f"User {user_id} provided interval: {interval} minutes.")
        
        users_data = state_manager.load_users()
        users_data[str_user_id]["interval"] = interval
        users_data[str_user_id]["state"] = state_manager.COMPLETED
        state_manager.save_users(users_data)
        
        logger.info(f"User {user_id} state: {users_data[str_user_id]['state']}")
        
        completion_msg = (
            "✅ Setup completed successfully!\n\n"
            "Use /run to start automation\n"
            "Use /stop to stop automation"
        )
        await update.message.reply_text(completion_msg)
        return
