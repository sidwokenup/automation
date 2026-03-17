import json
import os
import sys
import time
from automation.browser import launch_browser, login, navigate_to_campaigns, open_campaign, update_target_link
from utils.logger import setup_logger

def load_config(config_path='config/config.json'):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found at {config_path}")
    with open(config_path, 'r') as f:
        return json.load(f)

def run_automation_cycle(logger, config, link):
    """
    Runs a single automation cycle: Login -> Navigate -> Open Campaign -> Update Link
    """
    playwright = None
    browser = None
    
    try:
        username = config['credentials']['username']
        password = config['credentials']['password']
        
        # Get first campaign name (extendable logic for multiple campaigns later)
        campaigns = config.get('campaigns', [])
        if not campaigns:
            raise Exception("No campaigns found in config.")
        campaign_name = campaigns[0]['name']

        if username == "YOUR_USERNAME" or password == "YOUR_PASSWORD":
            logger.warning("Using placeholder credentials. Login will likely fail.")

        # Launch browser
        playwright, browser, page = launch_browser()

        # Perform login
        if login(page, username, password):
            logger.info("Login successful")
            
            # Navigate to campaigns
            navigate_to_campaigns(page)
            
            # Open specific campaign
            open_campaign(page, campaign_name)
            logger.info(f"Successfully opened campaign: {campaign_name}")
            
            # Update target link
            update_target_link(page, link)
            
            logger.info("Cycle completed successfully")
            return True
            
    except Exception as e:
        logger.error(f"Error in cycle: {e}")
        raise
    finally:
        if browser:
            logger.info("Closing browser...")
            try:
                browser.close()
            except:
                pass
        if playwright:
            try:
                playwright.stop()
            except:
                pass

def main():
    # Initialize logger
    logger = setup_logger()
    logger.info("Automation bot started")

    while True:
        try:
            # Reload config at the start of each major loop to allow dynamic updates
            config = load_config()
            links = config.get('links', [])
            interval_minutes = config.get('interval_minutes', 10)
            
            if not links:
                logger.error("No links found in config. Waiting 1 minute before retry...")
                time.sleep(60)
                continue

            logger.info(f"Loaded {len(links)} links. Interval set to {interval_minutes} minutes.")

            # Loop through links
            for i, link in enumerate(links):
                logger.info(f"Starting cycle {i+1}/{len(links)} with link: {link}")
                
                try:
                    run_automation_cycle(logger, config, link)
                    
                    logger.info(f"Next update in {interval_minutes} minutes...")
                    time.sleep(interval_minutes * 60)
                    
                except Exception as cycle_error:
                    logger.error(f"Cycle failed: {cycle_error}")
                    logger.info("Retrying in 1 minute...")
                    time.sleep(60)
                    # We continue to the next link/cycle instead of breaking
                    continue

        except Exception as e:
            logger.error(f"Critical error in main loop: {e}")
            logger.info("Restarting main loop in 1 minute...")
            time.sleep(60)

if __name__ == "__main__":
    main()
