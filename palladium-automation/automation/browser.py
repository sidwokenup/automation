from playwright.sync_api import sync_playwright
import logging
import time

logger = logging.getLogger('palladium_automation')

def launch_browser():
    """
    Launches the browser and returns playwright, browser, and page objects.
    """
    logger.info("Starting Playwright...")
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(
        headless=True,
        executable_path="/usr/bin/chromium-browser",
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu"
        ]
    )
    context = browser.new_context()
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
def login(page, username, password):
    """
    Logs into the website.
    """
    logger.info("Navigating to login page...")
    page.goto("https://next.palladium.expert")
    
    # Wait for login fields
    logger.info("Waiting for login fields...")
    try:
        page.wait_for_selector('input[type="text"]', state='visible', timeout=10000)
    except Exception as e:
        logger.error(f"Error waiting for selectors: {e}")
        raise

    # Fill credentials
    logger.info("Filling credentials...")
    page.fill('input[type="text"]', username)
    page.fill('input[type="password"]', password)
    
    # Click login
    logger.info("Clicking login button...")
    page.click('button[type="submit"]')
    
    # Wait for successful navigation (dashboard)
    logger.info("Waiting for navigation to dashboard...")
    page.wait_for_load_state('networkidle')
    
    return True

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
        page.wait_for_selector("table", timeout=15000)
        page.wait_for_timeout(2000)
        
        # Check if row exists
        row = page.locator("tr", has_text=campaign_name)
        count = row.count()
        
        if count > 0:
            logger.info(f"Campaign '{campaign_name}' found.")
            return True
        else:
            # Fallback search
            rows = page.locator("tr").all()
            for r in rows:
                if campaign_name.lower() in r.inner_text().lower():
                    logger.info(f"Campaign '{campaign_name}' found via fallback search.")
                    return True
            
            logger.warning(f"Campaign '{campaign_name}' NOT found.")
            return False
            
    except Exception as e:
        logger.error(f"Error checking campaign existence: {e}")
        return False

def open_campaign(page, campaign_name):
    """
    Finds a campaign by name and opens its edit page.
    """
    logger.info(f"Searching for campaign: {campaign_name}")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info(f"Retry attempt: {attempt + 1}")
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("table", timeout=20000)
            page.wait_for_timeout(3000)
            
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
                raise Exception("Campaign not found after retries")
            
            page.reload()
            page.wait_for_timeout(5000)

    # Wait for navigation
    try:
        logger.info("Waiting for campaign settings page to load...")
        page.wait_for_url("**/change/**", timeout=15000)
        logger.info("Campaign settings page loaded.")
    except Exception as e:
        logger.error(f"Error waiting for campaign settings page: {e}")
        raise

def update_target_link(page, new_link):
    """
    Updates the target link in the campaign settings page using robust selectors.
    """
    logger.info(f"Updating target link to: {new_link}")

    try:
        # 1. Ensure we are on the correct page and UI is ready
        logger.info(f"Current URL: {page.url}")
        page.wait_for_url("**/change/**", timeout=15000)
        page.wait_for_timeout(2000) # Allow dynamic UI to settle
        
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

        # 3. Clear Existing Value (Strong Method)
        logger.info("Clearing existing value...")
        input_field.click()
        input_field.press("Control+A")
        input_field.press("Backspace")
            
        # 4. Enter New Link
        logger.info(f"Entering new link: {new_link}")
        input_field.fill(new_link)
        
        # 5. Scroll to Save Button
        logger.info("Locating Save button...")
        save_button = page.locator("button:has-text('Save')")
        
        if save_button.count() == 0:
             raise Exception("Save button not found using :has-text('Save').")
             
        logger.info("Scrolling to Save button...")
        save_button.scroll_into_view_if_needed()
        
        # Wait a bit for UI to settle
        page.wait_for_timeout(2000)
        
        # 6. Click Save
        logger.info("Clicking Save button...")
        save_button.click()
        page.wait_for_timeout(3000)
        
        # 7. Wait for Successful Save (Redirect to campaign dashboard)
        logger.info("Waiting for save confirmation and redirect...")
        page.wait_for_url("**/campaign-page", timeout=15000)
        page.wait_for_timeout(2000)
        
        # 8. Confirm Success
        logger.info("Link updated and saved successfully. Returned to dashboard.")
        return True

    except Exception as e:
        logger.error(f"Error updating target link: {e}")
        raise
