import threading
from playwright.sync_api import sync_playwright
import logging
from automation.browser import login

logger = logging.getLogger('palladium_automation.session')

class SessionManager:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.logged_in = False
        self.username = None
        self.password = None

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = SessionManager()
            return cls._instance

    def start_session(self, username, password):
        """Initializes the browser and performs a single global login."""
        with self._lock:
            if self.logged_in and self.browser:
                logger.info("Global session already active.")
                return

            logger.info("Starting global browser session...")
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=True,
                executable_path="/usr/bin/chromium-browser",
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu"
                ]
            )

            # Use a temporary context just for login to establish session state
            context = self.browser.new_context()
            page = context.new_page()

            self.username = username
            self.password = password

            logger.info("Performing global login...")
            login(page, username, password)

            self.logged_in = True
            
            # Close the temporary page but keep browser and context alive
            page.close()
            context.close()
            logger.info("Global login complete. Ready for campaign pages.")

    def create_campaign_page(self):
        """Creates a new isolated page for a specific campaign using the shared browser."""
        if not self.browser:
            raise Exception("Global session is not started.")
        context = self.browser.new_context()
        return context, context.new_page()

    def check_and_recover_session(self, page):
        """Checks if session expired and recovers globally if needed."""
        current_url = page.url
        if "login" in current_url.lower() or "next.palladium.expert" not in current_url:
            with self._lock:
                # Double check in case another thread already recovered it
                if self.logged_in:
                    logger.warning("Session appears invalid. Triggering global re-authentication...")
                    self.logged_in = False
                    # Use the current page to re-login to restore cookies for its context
                    login(page, self.username, self.password)
                    self.logged_in = True
        else:
            try:
                if page.locator('input[type="text"]').is_visible(timeout=2000):
                    with self._lock:
                        logger.warning("Login fields visible. Triggering global re-authentication...")
                        self.logged_in = False
                        login(page, self.username, self.password)
                        self.logged_in = True
            except:
                pass

    def stop_session(self):
        """Stops the global browser session."""
        with self._lock:
            if self.browser:
                try:
                    self.browser.close()
                except:
                    pass
            if self.playwright:
                try:
                    self.playwright.stop()
                except:
                    pass
            self.browser = None
            self.playwright = None
            self.logged_in = False
