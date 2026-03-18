import logging
import os
import sys
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

# Adjust path so we can import from the main project
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logger
from telegram_bot.handlers import start_command, help_command, status_command, setup_command, handle_message, run_command, stop_command, logs_command, users_command

# Global variable to store the bot application instance
bot_app = None

def main():
    """Starts the Telegram bot."""
    global bot_app
    # Initialize logger
    logger = setup_logger()
    logger.info("Starting Palladium Telegram Bot...")

    # Load environment variables
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token or token == "your_telegram_bot_token_here":
        logger.error("Invalid or missing TELEGRAM_BOT_TOKEN in .env file.")
        print("❌ ERROR: Please set a valid TELEGRAM_BOT_TOKEN in the .env file.")
        return

    # Auto Recovery on Startup
    from telegram_bot.state_manager import load_users, save_users
    from telegram_bot.automation_runner import active_campaigns, campaign_lock
    logger.info("Running auto-recovery on user states...")
    users = load_users()
    recovery_needed = False
    for uid, user in users.items():
        if user.get("running"):
            logger.warning(f"Resetting stuck session for user {uid}")
            user["running"] = False
            recovery_needed = True
    if recovery_needed:
        save_users(users)
        logger.info("Auto-recovery completed.")

    # Initialize Global Session Manager
    from telegram_bot.session_manager import SessionManager
    SessionManager.get_instance()
    logger.info("Global Session Manager initialized.")

    try:
        # Create the Application and pass it your bot's token.
        application = ApplicationBuilder().token(token).build()
        bot_app = application

        # Register command handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("setup", setup_command))
        application.add_handler(CommandHandler("run", run_command))
        application.add_handler(CommandHandler("stop", stop_command))
        application.add_handler(CommandHandler("logs", logs_command))
        application.add_handler(CommandHandler("users", users_command))

        # Register message handler for setup flow
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Bot is initialized and polling for updates...")
        
        # Run the bot until the user presses Ctrl-C
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"❌ ERROR: Failed to start bot. Check logs for details. {e}")
    finally:
        from telegram_bot.session_manager import SessionManager
        SessionManager.get_instance().stop_session()
        logger.info("Bot shutdown complete.")

if __name__ == "__main__":
    main()
