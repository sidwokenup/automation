import asyncio
import os

def send_telegram_photo(application, user_id, photo_path, caption):
    """Safely sends a photo via Telegram from a synchronous thread."""
    if not application:
        print("[Notifier Error] Application instance is missing.")
        return

    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as photo:
                photo_data = photo.read()
                
            asyncio.run_coroutine_threadsafe(
                application.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_data,
                    caption=caption
                ),
                application.bot.loop if hasattr(application.bot, 'loop') else asyncio.get_event_loop()
            )
        else:
            print(f"[Notifier Warning] Photo path {photo_path} does not exist. Falling back to message.")
            send_telegram_message(application, user_id, caption)
    except Exception as e:
        print(f"[Notifier Error] Failed to send photo: {e}")

def send_telegram_message(application, user_id, text):
    """Safely sends a text message via Telegram from a synchronous thread."""
    if not application:
        print("[Notifier Error] Application instance is missing.")
        return
        
    try:
        asyncio.run_coroutine_threadsafe(
            application.bot.send_message(
                chat_id=user_id,
                text=text
            ),
            application.bot.loop if hasattr(application.bot, 'loop') else asyncio.get_event_loop()
        )
    except Exception as e:
        print(f"[Notifier Error] Failed to send message: {e}")