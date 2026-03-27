import logging
import os
import sys
import time
import asyncio
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from telegram.error import NetworkError, TelegramError

# Adjust path so we can import from the main project
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logger
from telegram_bot.handlers import start_command, help_command, status_command, setup_command, handle_message, run_command, stop_command, logs_command, users_command, progress_command, proxy_command, proxy_status_command, delete_proxy_command, delete_setup_command, test_links_command, why_stopped_command, links_command, flagged_command, current_command, stats_command

# Global variable to store the bot application instance
bot_app = None

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger = logging.getLogger('palladium_automation.telegram')
    logger.error("Exception while handling an update:", exc_info=context.error)

async def set_bot_commands(application):
    """Sets the bot menu commands visible in the Telegram UI."""
    from telegram import BotCommand
    commands = [
        BotCommand("start", "Welcome message"),
        BotCommand("help", "Show available commands"),
        BotCommand("setup", "Configure your automation"),
        BotCommand("run", "Start automation"),
        BotCommand("stop", "Stop automation"),
        BotCommand("status", "Check your automation status"),
        BotCommand("progress", "Check automation progress"),
        BotCommand("logs", "View recent activity logs"),
        BotCommand("users", "View all active automations (Admin)"),
        BotCommand("proxy", "Setup proxy configuration"),
        BotCommand("proxy_status", "Check proxy status"),
        BotCommand("delete_proxy", "Remove current proxy"),
        BotCommand("delete_setup", "Clear your automation setup"),
        BotCommand("test_links", "Test next active link in pool"),
        BotCommand("why_stopped", "Find out why automation stopped"),
        BotCommand("links", "Show active links"),
        BotCommand("flagged", "Show removed links"),
        BotCommand("current", "Show current link"),
        BotCommand("stats", "Show link statistics")
    ]
    await application.bot.set_my_commands(commands)

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
    from telegram_bot.automation_runner import recover_running_automations
    logger.info("Running auto-recovery on user states...")
    recover_running_automations()
    logger.info("Auto-recovery completed.")

    # HTTPX Request with timeouts
    request = HTTPXRequest(connect_timeout=30, read_timeout=60)

    try:
        # Create the Application and pass it your bot's token.
        application = ApplicationBuilder().token(token).request(request).build()
        
        # Store main event loop for thread-safe operations
        application.bot_loop = asyncio.get_event_loop()
        
        bot_app = application

        # Add error handler
        application.add_error_handler(global_error_handler)

        # Register command handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("progress", progress_command))
        application.add_handler(CommandHandler("setup", setup_command))
        application.add_handler(CommandHandler("run", run_command))
        application.add_handler(CommandHandler("stop", stop_command))
        application.add_handler(CommandHandler("logs", logs_command))
        application.add_handler(CommandHandler("users", users_command))
        application.add_handler(CommandHandler("proxy", proxy_command))
        application.add_handler(CommandHandler("proxy_status", proxy_status_command))
        application.add_handler(CommandHandler("delete_proxy", delete_proxy_command))
        application.add_handler(CommandHandler("delete_setup", delete_setup_command))
        application.add_handler(CommandHandler("test_links", test_links_command))
        application.add_handler(CommandHandler("why_stopped", why_stopped_command))
        application.add_handler(CommandHandler("links", links_command))
        application.add_handler(CommandHandler("flagged", flagged_command))
        application.add_handler(CommandHandler("current", current_command))
        application.add_handler(CommandHandler("stats", stats_command))

        # Register message handler for setup flow
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Setting bot commands menu...")
        # Since we are not in an async context here, we can set up a task to run once the app starts
        application.job_queue.run_once(lambda ctx: set_bot_commands(application), 1)

        logger.info("Bot is initialized and polling for updates...")
        
        # Robust Polling Loop
        while True:
            try:
                # Run the bot until the user presses Ctrl-C
                application.run_polling(allowed_updates=None, drop_pending_updates=True, close_loop=False)
                # If run_polling returns normally (e.g. signal received), break loop
                break
            except (NetworkError, TelegramError, Exception) as e:
                logger.error(f"Polling crashed due to error: {e}")
                logger.info("Restarting polling in 5 seconds...")
                time.sleep(5)
                continue
        
    except Exception as e:
        logger.error(f"Failed to start bot application: {e}")
        print(f"❌ ERROR: Failed to start bot. Check logs for details. {e}")
    finally:
        logger.info("Bot shutdown complete.")

if __name__ == "__main__":
    main()
