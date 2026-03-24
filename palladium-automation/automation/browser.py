from playwright.sync_api import sync_playwright
import logging
import time
import random
import os

logger = logging.getLogger('palladium_automation')

def launch_browser(user_id=None):
    """
    Launches the browser with session persistence and returns playwright, browser (or context), and page objects.
    """
    logger.info("Starting Playwright...")
    playwright = sync_playwright().start()
    
    if user_id:
        # Session persistence
        user_data_dir = os.path.join(os.getcwd(), "sessions", str(user_id))
        os.makedirs(user_data_dir, exist_ok=True)
        
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=True,
            executable_path="/usr/bin/chromium-browser",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        # Stealth mode script to bypass basic webdriver detection
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        # Persistent context already has a default page
        pages = context.pages
        page = pages[0] if pages else context.new_page()
        return playwright, context, page
    else:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path="/usr/bin/chromium-browser",
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        page = context.new_page()
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
    Checks if login was successful using multi-strategy SPA detection.
    """
    # Signal 1: URL change
    if "dashboard" in page.url.lower() or "campaign" in page.url.lower():
        return True
        
    # Signal 2: Dashboard element exists
    try:
        if page.locator("text=Campaign").count() > 0:
            return True
    except:
        pass
        
    # Signal 3: Logout/Profile button exists
    try:
        if page.locator("text=Logout").count() > 0 or page.locator("text=Profile").count() > 0:
            return True
    except:
        pass
        
    # Signal 4: Cookies/session present
    try:
        cookies = page.context.cookies()
        if len(cookies) > 0:
            # Basic check to see if we got some auth cookies
            return True
    except:
        pass
        
    return False

def login(page, username, password):
    """
    Logs into the website using SPA-aware multi-strategy detection, human delays, and retries.
    """
    # Check if already logged in first to save time with persistent sessions
    if is_login_successful(page):
        logger.info("Session already active, skipping login.")
        return True

    for attempt in range(3):
        try:
            logger.info(f"Navigating to login page (Attempt {attempt+1})...")
            page.goto("https://next.palladium.expert")
            
            # Wait for login fields
            logger.info("Waiting for login fields...")
            try:
                page.wait_for_selector('input[type="text"]', state='visible', timeout=10000)
            except Exception as e:
                logger.error(f"Error waiting for selectors: {e}")
                raise Exception(f"Login page not fully loaded: {e}")
        
            # Add a human-like delay before typing
            time.sleep(random.uniform(1.5, 3.5))
            
            # Fill credentials with delays
            logger.info("Filling credentials...")
            page.fill('input[type="text"]', username)
            
            time.sleep(random.uniform(1.0, 2.5))
            page.fill('input[type="password"]', password)
            
            # Human delay
            time.sleep(random.uniform(1.0, 2.0))
            
            # Click login
            logger.info("Clicking login button...")
            page.click('button[type="submit"]')
            
            # Smart wait
            logger.info("Waiting for login resolution...")
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except:
                logger.warning("Network idle timeout during login. Proceeding to validation.")
                
            time.sleep(3) # Let React process the state change
            
            # Retry-Based Login Validation
            login_success = False
            for val_attempt in range(3):
                logger.info(f"Checking login success (Validation {val_attempt+1})...")
                
                # Check if form is explicitly still there indicating failure
                if page.locator("input[name='email']").is_visible() or page.locator("input[type='password']").is_visible():
                    # If form is still visible AND there's an error message
                    if page.locator("text=Login Error").is_visible(timeout=1000) or page.locator("text=Invalid").is_visible(timeout=1000) or page.locator("text=Error").is_visible(timeout=1000):
                        raise Exception("Login failed due to server/validation error")
                
                if is_login_successful(page):
                    logger.info("Login successful")
                    login_success = True
                    break
                    
                time.sleep(2)
                
            if login_success:
                return True
            else:
                raise Exception("Login validation failed: Could not verify dashboard load or session state.")
                
        except Exception as e:
            logger.warning(f"Login attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise e
            # Backoff before retry
            backoff_time = 5 * (attempt + 1)
            logger.info(f"Waiting {backoff_time}s before retrying login...")
            time.sleep(backoff_time)
            
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
    Updates the target link in the campaign settings page using robust selectors and multi-strategy waiting.
    """
    logger.info(f"Updating target link to: {new_link}")

    try:
        # 1. Ensure we are on the correct page and UI is ready
        logger.info(f"Current URL: {page.url}")
        page.wait_for_url("**/change/**", timeout=15000)
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

        # 3. Clear & Enter New Link (Defensive)
        logger.info(f"Entering new link: {new_link}")
        input_field.click()
        input_field.fill(new_link)
        
        # Double check value
        if input_field.input_value() != new_link:
             logger.warning("Input value mismatch, retrying via JS...")
             page.evaluate("(el, val) => { el.value = val; el.dispatchEvent(new Event('input')); el.dispatchEvent(new Event('change')); }", [input_field, new_link])

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
        
        # 5. Multi-Strategy Save Action (Retry Logic)
        max_retries = 1
        success = False
        
        for attempt in range(max_retries + 1):
            logger.info(f"Executing Save Action (Attempt {attempt+1})...")
            
            # Ensure button is clickable
            if not save_button.is_enabled():
                 logger.info("Waiting for button to become enabled...")
                 try:
                     save_button.wait_for(state="enabled", timeout=5000)
                 except:
                     logger.warning("Button did not become enabled, trying to click anyway...")

            # Step 1: Trigger Action
            try:
                save_button.click(timeout=5000)
            except Exception as e:
                logger.warning(f"Standard click failed: {e}. Attempting force click.")
                save_button.click(force=True)

            # Step 2: Initial Delay for JS
            time.sleep(random.uniform(2.0, 4.0))
            
            # Step 3: Primary Wait (Network)
            logger.info("Waiting for network idle...")
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except:
                logger.warning("Network idle timeout. Proceeding to UI checks.")

            # Step 4: Secondary Success Detection (UI-Based)
            # Check for generic success indicators
            success_selectors = [
                "text=Saved", "text=Updated", "text=Success", "text=Changes saved",
                "div[role='alert']", ".Toastify", ".notification"
            ]
            
            for selector in success_selectors:
                if page.locator(selector).is_visible(timeout=2000):
                    logger.info(f"Success confirmed via UI indicator: {selector}")
                    success = True
                    break
            
            if success:
                break
                
            # Step 5: URL Check (Optional)
            if "campaign-page" in page.url and "change" not in page.url:
                logger.info("Success confirmed via URL redirect.")
                success = True
                break
                
            # Check for error
            if page.locator("text=Error").is_visible(timeout=1000) or page.locator("text=Failed").is_visible(timeout=1000):
                logger.error("Error message detected on page.")
            
            if attempt < max_retries:
                logger.warning("Success verification failed. Retrying save action...")
                # Optional: Refill input just in case
                input_field.fill(new_link)
                time.sleep(1)
        
        if not success:
            # Final check - if we are still on the page, assume failure but log extensively
            logger.warning("All success indicators failed. Logging state.")
            try:
                page.screenshot(path=f"logs/save_failed_state_{int(time.time())}.png")
                logger.info(f"Current URL: {page.url}")
            except: pass
            
            raise Exception("Save action could not be verified after retries.")

        logger.info("Link updated successfully.")
        return True

    except Exception as e:
        logger.error(f"Error updating target link: {e}")
        raise
