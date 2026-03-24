import asyncio
import os

def run_async(coro): 
    try: 
        loop = asyncio.get_running_loop() 
    except RuntimeError: 
        loop = None 

    if loop and loop.is_running(): 
        asyncio.create_task(coro) 
    else: 
        asyncio.run(coro)

def send_telegram_photo(application, user_id, photo_path, caption):
    """Safely sends a photo via Telegram from a synchronous thread."""
    if not application:
        print("[Notifier Error] Application instance is missing.")
        return

    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as photo:
                run_async(application.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=caption
                ))
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
        run_async(application.bot.send_message(chat_id=user_id, text=text))
    except Exception as e:
        print(f"[Notifier Error] Failed to send message: {e}")