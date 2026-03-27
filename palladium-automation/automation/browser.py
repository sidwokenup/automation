from playwright.sync_api import sync_playwright
try: 
    from playwright_stealth import stealth_sync 
except ImportError: 
    stealth_sync = None 
import logging
import time
import random
import os

logger = logging.getLogger('palladium_automation')

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def launch_browser(user_id=None):
    """
    Launches the browser with session persistence and returns playwright, browser (or context), and page objects.
    """
    logger.info("Starting Playwright...")
    playwright = sync_playwright().start()
    
    proxy_config = None
    if user_id:
        from telegram_bot.state_manager import get_user, update_user
        user_data = get_user(user_id)
        proxy_info = user_data.get("proxy", {})
        
        if proxy_info.get("enabled") and proxy_info.get("list"):
            # Get current proxy from rotation list
            proxies = proxy_info.get("list", [])
            current_idx = proxy_info.get("current_index", 0)
            
            # Ensure index is valid
            if current_idx >= len(proxies):
                current_idx = 0
                
            selected_proxy = proxies[current_idx]
            
            proxy_config = {
                "server": selected_proxy["server"]
            }
            if selected_proxy.get("username"):
                proxy_config["username"] = selected_proxy["username"]
                proxy_config["password"] = selected_proxy["password"]
                
            # Rotate for next time
            next_idx = (current_idx + 1) % len(proxies)
            proxy_info["current_index"] = next_idx
            update_user(user_id, {"proxy": proxy_info})
            logger.info(f"Using proxy {current_idx+1}/{len(proxies)}: {selected_proxy['server']}")

    viewport = {"width": random.randint(1280, 1920), "height": random.randint(720, 1080)}
    user_agent = get_random_user_agent()
    timezone_id = random.choice(["America/New_York", "Europe/London", "Asia/Tokyo", "Europe/Paris", "America/Los_Angeles", "Australia/Sydney"])
    locale = random.choice(["en-US", "en-GB", "en-CA", "en-AU"])
    hardware_concurrency = random.choice([4, 8, 16])
    device_memory = random.choice([8, 16, 32])

    if user_id:
        # Session persistence
        user_data_dir = os.path.join(os.getcwd(), "sessions", str(user_id))
        os.makedirs(user_data_dir, exist_ok=True)
        
        launch_kwargs = {
            "user_data_dir": user_data_dir,
            "headless": True,
            "user_agent": user_agent,
            "viewport": viewport,
            "timezone_id": timezone_id,
            "locale": locale,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-extensions",
                f"--window-size={viewport['width']},{viewport['height']}"
            ]
        }
        if proxy_config:
            launch_kwargs["proxy"] = proxy_config
            
        logger.info("Launching persistent browser context...")
        context = playwright.chromium.launch_persistent_context(**launch_kwargs)
        browser = context # For consistent return type
        
        # Stealth mode script to bypass basic webdriver detection and spoof hardware
        context.add_init_script(f"""
            Object.defineProperty(navigator, 'webdriver', {{
                get: () => undefined
            }});
            window.navigator.chrome = {{
                runtime: {{}}
            }};
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {hardware_concurrency}
            }});
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => {device_memory}
            }});
        """)
        
        # Persistent context already has a default page
        logger.info("Creating new page...")
        pages = context.pages
        page = pages[0] if pages else context.new_page()
        
        if not stealth_sync: 
            print("[WARNING] playwright_stealth not available, running without stealth") 
            
        if stealth_sync: 
            try: 
                stealth_sync(page) 
            except Exception: 
                pass 
        # Check if proxy is working before proceeding
        if proxy_config:
            try:
                logger.info("Validating proxy connection...")
                page.goto("https://api.ipify.org", timeout=15000)
                proxy_ip = page.inner_text("body").strip()
                logger.info(f"Proxy validated successfully. IP: {proxy_ip}")
            except Exception as e:
                logger.error(f"Proxy validation failed: {e}. Falling back to direct connection.")
                # We can't change the context proxy after launch in Playwright sync api easily,
                # but we can raise an error so the runner knows it failed or just continue and risk it.
                # Since the prompt says "fallback to direct connection", we would need to relaunch without proxy.
                context.close()
                if not user_id: browser.close()
                playwright.stop()
                
                # Relaunch without proxy
                logger.info("Relaunching browser without proxy...")
                playwright = sync_playwright().start()
                launch_kwargs.pop("proxy", None)
                if user_id:
                    context = playwright.chromium.launch_persistent_context(**launch_kwargs)
                    context.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                        window.navigator.chrome = { runtime: {} };
                    """)
                    pages = context.pages
                    page = pages[0] if pages else context.new_page()
                    if not stealth_sync: 
                        print("[WARNING] playwright_stealth not available, running without stealth") 
                        
                    if stealth_sync: 
                        try: 
                            stealth_sync(page) 
                        except Exception: 
                            pass 
                    return playwright, context, page
                else:
                    browser = playwright.chromium.launch(
                        headless=True,
                        args=[
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-gpu",
                            "--disable-blink-features=AutomationControlled",
                            "--disable-infobars",
                            "--disable-extensions",
                            f"--window-size={viewport['width']},{viewport['height']}"
                        ]
                    )
                    context = browser.new_context(
                        user_agent=user_agent, 
                        viewport=viewport, 
                        timezone_id=timezone_id,
                        locale=locale
                    )
                    context.add_init_script(f"""
                        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
                        window.navigator.chrome = {{ runtime: {{}} }};
                        Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {hardware_concurrency} }});
                        Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {device_memory} }});
                    """)
                    page = context.new_page()
                    if not stealth_sync: 
                        print("[WARNING] playwright_stealth not available, running without stealth") 
                        
                    if stealth_sync: 
                        try: 
                            stealth_sync(page) 
                        except Exception: 
                            pass 
                    return playwright, browser, page

        return playwright, context, page
    else:
        logger.info("Launching standard browser...")
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-extensions",
                f"--window-size={viewport['width']},{viewport['height']}"
            ]
        )
        context = browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            timezone_id=timezone_id,
            locale=locale
        )
        context.add_init_script(f"""
            Object.defineProperty(navigator, 'webdriver', {{
                get: () => undefined
            }});
            window.navigator.chrome = {{
                runtime: {{}}
            }};
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {hardware_concurrency}
            }});
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => {device_memory}
            }});
        """)
        logger.info("Creating new page...")
        
        try:
            if browser:
                browser.close()
        except:
            pass
            
        page = context.new_page()
        if not stealth_sync: 
            print("[WARNING] playwright_stealth not available, running without stealth") 
            
        if stealth_sync: 
            try: 
                stealth_sync(page) 
            except Exception: 
                pass 
        return playwright, browser, page

def retry_action(action, retries=3):
    """Retries a given action function multiple times."""
    for attempt in range(retries):
        try:
            return action()
        except Exception as e:
            if attempt == retries - 1:
                raise e
            time.sleep(3)
def is_login_successful(page):
    """
    Checks if login was successful using multi-layer SPA detection.
    Requires at least 2 positive signals to confirm success.
    """
    signals = 0
    
    print(f"[DEBUG] Current URL: {page.url}")
    
    # Signal 1: URL change (not on login page)
    current_url = page.url.lower()
    if "dashboard" in current_url or "campaign" in current_url:
        logger.info("Login Signal: URL changed to dashboard/campaign.")
        signals += 1
        
    # Signal 2: Dashboard element exists (any common element)
    try:
        if page.locator("text=Campaign").is_visible():
            logger.info("Login Signal: Dashboard UI elements detected.")
            signals += 1
    except:
        pass
        
    # Signal 3: Logout/Profile button exists
    try:
        if page.locator("button:has-text('Logout')").is_visible():
            logger.info("Login Signal: User profile/logout button detected.")
            signals += 1
    except:
        pass
        
    # Signal 4: Absence of login form
    try:
        login_fields = page.locator("input[type='text']")
        if login_fields.count() == 0:
            logger.info("Login Signal: Login form absent.")
            signals += 1
    except:
        pass

    logger.info(f"[Login Detection] Signals: {signals}")
    
    return signals >= 2

def simulate_mouse_movement(page):
    """Simulates smooth human-like mouse movement across the screen."""
    start_x = random.randint(100, 300)
    start_y = random.randint(100, 300)
    end_x = random.randint(400, 800)
    end_y = random.randint(400, 800)
    
    # Move in steps for smoothness
    steps = random.randint(5, 15)
    for i in range(steps):
        x = start_x + (end_x - start_x) * (i / steps) + random.randint(-10, 10)
        y = start_y + (end_y - start_y) * (i / steps) + random.randint(-10, 10)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.01, 0.05))

def detect_login_fields(page):
    selectors = [
        "input[name='username']",
        "input[name='email']",
        "input[placeholder*='user']",
        "input[placeholder*='email']",
        "input[type='text']"
    ]

    for sel in selectors:
        if page.locator(sel).count() > 0:
            return sel

    return None

def detect_dashboard(page):
    try:
        return (
            "dashboard" in page.url.lower()
            or "campaign" in page.url.lower()
            or page.locator("text=Campaign").count() > 0
        )
    except:
        return False

def login(page, username, password):
    """
    Logs into the website using SPA-aware multi-strategy detection, human delays, and retries.
    """
    # Check if already logged in first to save time with persistent sessions
    if is_login_successful(page) or detect_dashboard(page):
        logger.info("Session already active, skipping login.")
        return True

    MAX_RETRIES = 5
    RETRY_DELAYS = [5, 10, 20, 20, 20]  # seconds

    # Limit to MAX_RETRIES attempts
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Navigating to login page (Attempt {attempt+1})...")
            page.goto("https://next.palladium.expert", wait_until="domcontentloaded")
            
            # Robust page load wait
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except:
                pass
            page.wait_for_timeout(3000)
            
            # Bonus: Wait for body
            try:
                page.wait_for_selector("body", timeout=15000)
            except:
                pass
                
            print(f"[DEBUG] URL: {page.url}")
            try:
                print(f"[DEBUG] Title: {page.title()}")
            except:
                pass
            
            # Decision Logic
            if detect_dashboard(page):
                print("✅ Already logged in")
                return True
                
            login_selector = detect_login_fields(page)
            if login_selector:
                print("🔐 Login form detected")
            else:
                print("⚠️ Unknown page state")
                os.makedirs("logs", exist_ok=True)
                page.screenshot(path=f"logs/debug_unknown_state_{int(time.time())}.png")
                
                # Handle render failures
                logger.warning("No elements found. Reloading page...")
                page.reload(wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except:
                    pass
                page.wait_for_timeout(3000)
                
                login_selector = detect_login_fields(page)
                if not login_selector:
                    raise Exception(f"Login page not fully loaded or blocked. Could not find login fields.")

            # Pre-login human behavior
            time.sleep(random.uniform(2.0, 4.0))
            simulate_mouse_movement(page)
            page.mouse.wheel(0, random.randint(100, 300))
            time.sleep(random.uniform(1.0, 2.0))
            page.mouse.wheel(0, random.randint(-200, -50))
            
            # Simulate human mouse movement to username field
            simulate_mouse_movement(page)
            
            # Fill credentials with human typing delays (character by character)
            logger.info("Filling credentials...")
            page.click(login_selector)
            for char in username:
                page.keyboard.press(char)
                time.sleep(random.uniform(0.05, 0.2))
                if random.random() < 0.1: # 10% chance to pause slightly
                    time.sleep(random.uniform(0.2, 0.6))
            
            time.sleep(random.uniform(1.0, 2.5))
            
            # Simulate human mouse movement to password field
            simulate_mouse_movement(page)
            page.click('input[type="password"]')
            for char in password:
                page.keyboard.press(char)
                time.sleep(random.uniform(0.05, 0.2))
                if random.random() < 0.1: # 10% chance to pause slightly
                    time.sleep(random.uniform(0.2, 0.6))
            
            # Human delay before clicking
            time.sleep(random.uniform(1.5, 3.5))
            
            # Simulate smooth mouse move to button
            box = page.locator('button[type="submit"]').bounding_box()
            if box:
                target_x = box["x"] + box["width"] / 2 + random.randint(-5, 5)
                target_y = box["y"] + box["height"] / 2 + random.randint(-2, 2)
                # Move to button in steps
                current_pos = {"x": random.randint(100, 500), "y": random.randint(100, 500)}
                steps = random.randint(5, 10)
                for i in range(steps):
                    x = current_pos["x"] + (target_x - current_pos["x"]) * (i / steps)
                    y = current_pos["y"] + (target_y - current_pos["y"]) * (i / steps)
                    page.mouse.move(x, y)
                    time.sleep(random.uniform(0.02, 0.08))
                
                page.mouse.move(target_x, target_y)
                time.sleep(random.uniform(0.5, 1.0))
            
            # Click login
            logger.info("Clicking login button...")
            page.click('button[type="submit"]')
            
            # Human delay after login
            time.sleep(random.uniform(2.0, 4.0))
            
            # Smart wait
            logger.info("Waiting for login resolution...")
            try:
                # Wait for navigation OR network idle
                page.wait_for_load_state('networkidle', timeout=15000)
                page.wait_for_timeout(3000)
            except:
                logger.warning("Network idle timeout during login. Proceeding to validation.")
                
            # Validation logic
            login_success = False
            for val_attempt in range(4): # Poll up to 4 times
                logger.info(f"Checking login success (Validation {val_attempt+1})...")
                
                # Check for captcha
                if page.locator("iframe[src*='captcha']").is_visible() or page.locator("text=Verify you are human").is_visible():
                    logger.error("Captcha detected during login.")
                    raise Exception("Captcha challenge presented. Manual intervention required.")

                # Explicit failure check
                if page.locator("input[name='email']").is_visible() or page.locator("input[type='password']").is_visible():
                    if page.locator("text=Login Error").is_visible(timeout=1000) or page.locator("text=Invalid").is_visible(timeout=1000) or page.locator("text=Error").is_visible(timeout=1000):
                        logger.error("Explicit login error detected on page.")
                        raise Exception("Login failed due to invalid credentials or server error")
                    if page.locator("text=rate limit").is_visible(timeout=1000) or page.locator("text=Too many").is_visible(timeout=1000):
                        logger.error("Rate limit detected on page.")
                        raise Exception("Login failed due to rate limiting (too many attempts)")
                
                if is_login_successful(page):
                    logger.info("✅ Login successful")
                    login_success = True
                    break
                    
                time.sleep(3) # Wait between polls
                
            if login_success:
                return True
            else:
                raise Exception("Login validation failed")
                
        except Exception as e:
            logger.warning(f"Login attempt {attempt+1} failed explicitly: {e}")
            os.makedirs("logs", exist_ok=True)
            page.screenshot(path=f"logs/debug_login_fail_{int(time.time())}.png")
            
            e_str = str(e).lower()
            
            # Immediately fail on critical errors that retries won't fix
            if "invalid credentials" in e_str or "captcha" in e_str:
                 raise e
                 
            if attempt >= MAX_RETRIES - 1:
                raise Exception(f"Login failed after {MAX_RETRIES} attempts.")
            
            # Smart retry backoff based on error type
            if "timeout" in e_str:
                wait_time = 5
            elif "proxy" in e_str or "net::" in e_str:
                wait_time = 2
            elif "rate limit" in e_str or "too many" in e_str or "blocked" in e_str:
                wait_time = 10
            else:
                wait_time = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                
            # Cap the max wait time to 15 seconds to ensure speed
            wait_time = min(wait_time, 15)
                
            logger.info(f"[Retry] Attempt {attempt+2} in {wait_time}s")
            time.sleep(wait_time)
            
    raise Exception("Login failed after all retries.")

def ensure_logged_in(page, username, password):
    """
    Checks if session is valid. If not, performs login.
    """
    current_url = page.url
    if "login" in current_url.lower() or "next.palladium.expert" not in current_url:
        logger.warning("Session appears invalid or at login screen. Re-authenticating...")
        login(page, username, password)
    else:
        # Check if login fields are visible just in case URL didn't change
        try:
            if page.locator('input[type="text"]').is_visible(timeout=2000):
                logger.warning("Login fields visible. Re-authenticating...")
                login(page, username, password)
            else:
                logger.info("Session is valid.")
        except:
             logger.info("Session is valid.")

def ensure_campaign_page(page):
    """
    Ensures the browser is on the campaign dashboard.
    """
    current_url = page.url
    if "campaign-page" not in current_url or "change" in current_url:
        logger.info("Not on campaign dashboard. Navigating...")
        retry_action(lambda: navigate_to_campaigns(page))
    else:
        logger.info("Already on campaign dashboard.")

def navigate_to_campaigns(page):
    """
    Navigates to the campaign dashboard.
    """
    logger.info("Navigating to campaign dashboard...")
    page.goto("https://next.palladium.expert/pages/campaign-page")
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)
    logger.info("Campaign dashboard loaded.")

def check_campaign_exists(page, campaign_name):
    """
    Checks if a campaign exists on the page without throwing an error.
    """
    logger.info(f"Checking existence of campaign: {campaign_name}")
    try:
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)
        
        campaign_found = False
        rows = page.locator("tr")
        
        if rows.count() == 0:
             # Just a warning, maybe table didn't load, but don't raise exception yet if we want to return False
             logger.warning("No rows found on campaign page during check.")
             
        logger.info(f"Total rows found: {rows.count()}")
        logger.info(f"Searching for campaign: {campaign_name}")
        
        for i in range(rows.count()):
            row_text = rows.nth(i).inner_text().lower()
            if campaign_name.lower() in row_text:
                campaign_found = True
                break
                
        # Fallback: text-based detection (handles dynamic UI / React tables)
        if not campaign_found:
            logger.warning("Row-based detection failed. Trying text-based detection...")
            
            text_locator = page.locator(f"text={campaign_name}")
            
            if text_locator.count() > 0:
                logger.info(f"Campaign '{campaign_name}' found via text fallback.")
                campaign_found = True
                
        if not campaign_found:
            raise Exception(f"Campaign '{campaign_name}' not found after all detection methods")
            
        logger.info(f"Campaign '{campaign_name}' found.")
        return True
            
    except Exception as e:
        logger.error(f"Error checking campaign existence: {e}")
        return False

def open_campaign(page, campaign_name, user_id=None):
    """
    Finds a campaign by name and opens its edit page.
    """
    logger.info(f"Searching for campaign: {campaign_name}")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info(f"Retry attempt: {attempt + 1}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(5000)
            
            row = page.locator("tr", has_text=campaign_name).first
            
            if row.count() > 0:
                row.wait_for(timeout=10000)
                logger.info("Found campaign row.")
                
                # 2. Find all buttons in the row
                buttons = row.locator("button")
                button_count = buttons.count()
                logger.info(f"Found {button_count} buttons in the campaign row.")
                
                # 3. Click the correct button (Edit button is expected to be at index 4)
                target_index = 4
                if button_count > target_index:
                    logger.info(f"Clicking button at index {target_index} (Edit button)...")
                    buttons.nth(target_index).click()
                else:
                    logger.error(f"Not enough buttons in row. Expected > {target_index}, found {button_count}.")
                    
                    # Attempt fallback: Look for a button with an SVG (icon) if index fails
                    logger.info("Attempting fallback: searching for button with SVG icon...")
                    svg_buttons = row.locator("button:has(svg)")
                    if svg_buttons.count() > 0:
                        logger.info("Found button with SVG, clicking the last one (often actions are at the end)...")
                        svg_buttons.last.click()
                    else:
                        raise Exception("Could not find Edit button by index or icon.")
                break # Exit retry loop on success
            else:
                # OPTIONAL (FALLBACK SEARCH)
                logger.info("Direct row selector failed. Attempting fallback search...")
                rows = page.locator("tr").all()
                found = False
                for r in rows:
                    if campaign_name.lower() in r.inner_text().lower():
                        row = r
                        found = True
                        break
                
                if found:
                    logger.info("Found campaign row via fallback search.")
                    buttons = row.locator("button")
                    button_count = buttons.count()
                    target_index = 4
                    if button_count > target_index:
                        buttons.nth(target_index).click()
                    else:
                        svg_buttons = row.locator("button:has(svg)")
                        if svg_buttons.count() > 0:
                            svg_buttons.last.click()
                        else:
                            raise Exception("Could not find Edit button in fallback row.")
                    break
                else:
                    raise Exception(f"Could not find any row with text '{campaign_name}'")
                    
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                # Instead of crashing, let's bubble up to the AI Recovery
                raise Exception(f"Campaign row not found or unclickable after retries: {e}")
            
            page.reload()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(7000)

    # Wait for navigation
    try:
        logger.info("Waiting for campaign settings page to load...")
        page.wait_for_url("**/change/**", timeout=15000)
        logger.info("Campaign settings page loaded.")
    except Exception as e:
        logger.error(f"Error waiting for campaign settings page: {e}")
        raise

def update_target_link(page, new_link, user_id=None):
    """
    Updates the target link in the campaign settings page using robust selectors and strict value verification.
    """
    logger.info(f"Updating target link to: {new_link}")

    try:
        # 1. Ensure we are on the correct page and UI is ready
        logger.info(f"Current URL: {page.url}")
        page.wait_for_load_state("networkidle")
        time.sleep(random.uniform(1.5, 3.0)) # Human-like delay
        
        # 2. Locate Correct Input Field (Hierarchy of strategies)
        logger.info("Locating target link input field...")
        
        input_field = None
        
        # Strategy A: Placeholder-based (Primary)
        placeholder_input = page.locator("input[placeholder*='http']")
        if placeholder_input.count() > 0:
            logger.info("Strategy A Success: Found input by placeholder containing 'http'.")
            input_field = placeholder_input.first
        else:
            logger.warning("Strategy A Failed: No input with 'http' placeholder found.")
            
            # Strategy B: XPath based on visible text (Strong Method)
            xpath_selector = "xpath=//*[contains(text(), 'Link to the target page')]/following::input[1]"
            xpath_input = page.locator(xpath_selector)
            if xpath_input.count() > 0:
                logger.info("Strategy B Success: Found input using XPath relative to visible text.")
                input_field = xpath_input.first
            else:
                logger.warning("Strategy B Failed: XPath relative to visible text found nothing.")
                
                # Strategy C: Final Fallback (Safe Index)
                inputs = page.locator("input")
                count = inputs.count()
                if count > 0:
                    logger.warning(f"Strategy C Fallback: Found {count} inputs, using the first one.")
                    input_field = inputs.first
                else:
                    raise Exception("No input fields found on page")

        logger.info("Input field successfully located.")

        # 3. Clear & Enter New Link
        logger.info(f"Entering new link: {new_link}")
        
        # Simulate human mouse movement to input field
        simulate_mouse_movement(page)
        
        input_field.click()
        input_field.fill(new_link)
        
        # Small delay for UI update 
        page.wait_for_timeout(1500) 
        
        # Verify input actually updated 
        value = input_field.input_value() 
        
        if new_link not in value: 
            raise Exception("Link not updated in input field") 

        # 4. Locate Save Button
        logger.info("Locating Save button...")
        
        # Integrate self-healing AI selector
        from telegram_bot.ai_selector import generate_selector_with_gemini, get_cached_selector, set_cached_selector
        
        action_desc = "Click the 'Save' button to update the campaign link."
        cached_sel = get_cached_selector(action_desc)
        save_button = None
        
        if cached_sel:
            logger.info(f"Trying cached selector: {cached_sel}")
            temp_btn = page.locator(cached_sel)
            if temp_btn.count() > 0 and temp_btn.first.is_visible():
                save_button = temp_btn.first
                logger.info("Cached selector successful.")
        
        if not save_button:
            # Try original hardcoded strategy
            save_button = page.locator("button:has-text('Save')")
            
            if save_button.count() == 0:
                logger.warning("Original Save button selector failed. Triggering AI recovery...")
                
                # Take screenshot and get HTML for AI
                os.makedirs("logs", exist_ok=True)
                screenshot_path = f"logs/ai_recovery_save_{int(time.time())}.png"
                page.screenshot(path=screenshot_path)
                html_content = page.content()
                
                new_selector = generate_selector_with_gemini(html_content, screenshot_path, action_desc)
                
                if new_selector:
                    save_button = page.locator(new_selector)
                    if save_button.count() > 0:
                        logger.info(f"AI Recovery successful. New selector: {new_selector}")
                        set_cached_selector(action_desc, new_selector)
                        
                        # Send Telegram Alert
                        if user_id:
                            try:
                                from telegram_bot.automation_runner import user_bots
                                from telegram_bot.utils.notifier import send_telegram_photo
                                
                                app_instance = user_bots.get(str(user_id))
                                if app_instance:
                                    msg = f"🤖 *AI Self-Healing Triggered*\n\nThe 'Save' button changed on the website.\nMy AI Vision successfully found the new button and fixed it automatically!\n\nNo action required."
                                    # Ensure screenshot is passed here
                                    send_telegram_photo(app_instance, user_id, screenshot_path, msg)
                            except:
                                pass
                    else:
                        raise Exception(f"AI generated selector '{new_selector}' found 0 elements.")
                else:
                    raise Exception("Save button not found and AI recovery failed to generate a selector.")
             
        logger.info("Scrolling to Save button...")
        save_button.scroll_into_view_if_needed()
        time.sleep(random.uniform(1.0, 2.0))
        
        if save_button:
            save_button.click()
            page.wait_for_timeout(2000)
            
        # 5. Safe Success Confirmation
        error_visible = page.locator("text=error").is_visible() 
        
        if error_visible: 
            raise Exception("Error message detected after updating link") 

        logger.info("Link updated successfully.")
        return True

    except Exception as e:
        logger.error(f"Error updating target link: {e}")
        raise
