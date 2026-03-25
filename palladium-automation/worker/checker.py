import time
import requests
import sys
import os

# Ensure the root project directory is in the sys path to allow importing link_service
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from link_service.db.models import (
    get_all_active_links_global,
    mark_link_flagged,
    update_last_checked,
    increment_fail_count,
    reset_fail_count
)

CHECK_INTERVAL = 30
FAIL_THRESHOLD = 2

BLOCKED_KEYWORDS = [ 
    "blocked", 
    "not available", 
    "access denied", 
    "forbidden", 
    "suspended", 
    "phishing", 
    "malware", 
    "dangerous", 
    "site can't be reached" 
]

def check_link(url):
    try:
        response = requests.get(url, timeout=5, allow_redirects=True)
        
        final_url = response.url.lower() 
        content = response.text.lower() 

        # 1. Status code check 
        if response.status_code != 200: 
            return "FAIL" 

        # 2. Redirect detection 
        if "blocked" in final_url or "warning" in final_url: 
            return "FAIL" 

        # 3. Content keyword detection 
        for word in BLOCKED_KEYWORDS: 
            if word in content: 
                return "FAIL" 

        return "ACTIVE" 
    except:
        return "FAIL"

def run_worker():
    print("🚀 Starting Background Link Checker Worker v2 (Smart Detection)...")
    while True:
        links = get_all_active_links_global()
        
        for link in links:
            url = link["url"]
            print(f"[CHECK] {url}")
            result = check_link(url)

            if result == "FAIL":
                print(f"[FAIL] {url}")
                increment_fail_count(link["id"])
                
                # Fetch current fail count or just assume we incremented the one from memory
                current_fails = link.get("fail_count", 0) + 1
                
                if current_fails >= FAIL_THRESHOLD:
                    if link["status"] != "FLAGGED":
                        print(f"[FLAGGED] {url}")
                        mark_link_flagged(link["id"])
                        
                        # Notify user only once when marking as FLAGGED
                        try: 
                            from telegram_bot.automation_runner import user_bots 
                            from telegram_bot.utils.notifier import send_telegram_message 
                         
                            user_id = link["user_id"] 
                            app_instance = user_bots.get(str(user_id)) 
                         
                            if app_instance: 
                                send_telegram_message( 
                                    app_instance, 
                                    user_id, 
                                    f"⚠️ Link flagged and removed:\n{url}" 
                                ) 
                        except: 
                            pass 
            else:
                # Recovery Check
                if link.get("fail_count", 0) > 0:
                    print(f"[RECOVERED] {url}")
                
                reset_fail_count(link["id"])
                update_last_checked(link["id"])

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run_worker()