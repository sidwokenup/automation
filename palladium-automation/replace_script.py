import re

with open("automation/browser.py", "r", encoding="utf-8") as f:
    content = f.read()

start_marker = "def update_target_link(page, new_link, user_id=None):"
start_idx = content.find(start_marker)

if start_idx == -1:
    print("Function not found!")
    exit(1)

# The function ends at:
end_marker = '        logger.error(f"Error updating target link: {e}")\n        raise'
end_idx = content.find(end_marker, start_idx) + len(end_marker)

if end_idx < len(end_marker):
    print("End marker not found!")
    exit(1)

new_func = """def update_target_link(page, new_link, user_id=None):
    \"\"\"
    Updates the target link in the campaign settings page using robust selectors and strict value verification.
    \"\"\"
    logger.info(f"Updating target link to: {new_link}")

    try:
        # 1. Ensure we are on the correct page and UI is ready
        logger.info(f"Current URL: {page.url}")
        page.wait_for_load_state("networkidle")
        time.sleep(random.uniform(1.5, 3.0)) # Human-like delay
        
        def get_strict_input_field():
            # 1. Prefer placeholder containing "http"
            inputs = page.locator("input[placeholder*='http']")
            if inputs.count() == 0:
                inputs = page.locator("input")
                
            if inputs.count() == 0:
                raise Exception("No input fields found on page")
                
            # 2. Filter visible and enabled inputs
            valid_inputs = []
            for i in range(inputs.count()):
                loc = inputs.nth(i)
                if loc.is_visible() and loc.is_enabled():
                    valid_inputs.append(loc)
                    
            if len(valid_inputs) == 0:
                raise Exception("No visible and enabled input fields found")
                
            if len(valid_inputs) == 1:
                return valid_inputs[0], 1
                
            # Prioritize input near text like: "target", "link", "url"
            prioritized = []
            for loc in valid_inputs:
                try:
                    is_near = loc.evaluate('''el => {
                        let parent = el.parentElement;
                        for(let i=0; i<4; i++) {
                            if (parent && /(target|link|url)/i.test(parent.innerText)) return true;
                            if (parent) parent = parent.parentElement;
                        }
                        return false;
                    }''')
                    if is_near:
                        prioritized.append(loc)
                except:
                    pass
                    
            if len(prioritized) == 1:
                return prioritized[0], len(valid_inputs)
                
            current_pool = prioritized if len(prioritized) > 1 else valid_inputs
            
            # 3. Choose input whose current value already contains "http"
            http_inputs = []
            for loc in current_pool:
                val = loc.input_value()
                if val and "http" in val:
                    http_inputs.append(loc)
                    
            if len(http_inputs) == 1:
                return http_inputs[0], len(valid_inputs)
                
            # 8. Fail safe for multiple inputs
            if len(valid_inputs) > 3 and len(http_inputs) != 1:
                raise Exception("INPUT_FIELD_NOT_RELIABLE")
                
            # 4. If still ambiguous
            if len(current_pool) > 1:
                raise Exception("AMBIGUOUS_INPUT_FIELD")
                
            return current_pool[0], len(valid_inputs)

        # 2. Locate Correct Input Field (Hierarchy of strategies)
        logger.info("Locating target link input field...")
        
        input_field, inputs_found_count = get_strict_input_field()
        logger.info(f"Input field successfully located. Total visible/enabled inputs found: {inputs_found_count}")
        
        try:
            logger.info(f"Selected input current value: {input_field.input_value()}")
        except:
            pass

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
        
        if value.strip() != new_link.strip(): 
            raise Exception("INPUT_VALUE_MISMATCH") 

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
            if temp_btn.count() > 0 and temp_btn.first.is_visible() and temp_btn.first.is_enabled():
                save_button = temp_btn.first
                logger.info("Cached selector successful.")
        
        if not save_button:
            # 1. Try: button:has-text("Save")
            save_buttons = page.locator("button:has-text('Save')")
            if save_buttons.count() > 0:
                for i in range(save_buttons.count()):
                    btn = save_buttons.nth(i)
                    if btn.is_visible() and btn.is_enabled():
                        save_button = btn
                        logger.info("Found Save button using text 'Save'.")
                        break
                        
            # 3. If none: fallback to button[type="submit"]
            if not save_button:
                submit_buttons = page.locator('button[type="submit"]')
                if submit_buttons.count() > 0:
                    for i in range(submit_buttons.count()):
                        btn = submit_buttons.nth(i)
                        if btn.is_visible() and btn.is_enabled():
                            save_button = btn
                            logger.info("Found Save button using type='submit'.")
                            break
                            
            # 4. If still none: trigger AI recovery
            if not save_button:
                logger.warning("Save button not found. Triggering AI recovery...")
                
                # Take screenshot and get HTML for AI
                os.makedirs("logs", exist_ok=True)
                screenshot_path = f"logs/ai_recovery_save_{int(time.time())}.png"
                page.screenshot(path=screenshot_path)
                html_content = page.content()
                
                new_selector = generate_selector_with_gemini(html_content, screenshot_path, action_desc)
                
                if new_selector:
                    temp_btn = page.locator(new_selector)
                    if temp_btn.count() > 0 and temp_btn.first.is_visible() and temp_btn.first.is_enabled():
                        save_button = temp_btn.first
                        logger.info(f"AI Recovery successful. New selector: {new_selector}")
                        set_cached_selector(action_desc, new_selector)
                        
                        # Send Telegram Alert
                        if user_id:
                            try:
                                from telegram_bot.automation_runner import user_bots
                                from telegram_bot.utils.notifier import send_telegram_photo
                                
                                app_instance = user_bots.get(str(user_id))
                                if app_instance:
                                    msg = f"🤖 *AI Self-Healing Triggered*\\n\\nThe 'Save' button changed on the website.\\nMy AI Vision successfully found the new button and fixed it automatically!\\n\\nNo action required."
                                    # Ensure screenshot is passed here
                                    send_telegram_photo(app_instance, user_id, screenshot_path, msg)
                            except:
                                pass
                    else:
                        raise Exception(f"AI generated selector '{new_selector}' found 0 elements or element not visible/enabled.")
                else:
                    raise Exception("SAVE_BUTTON_NOT_FOUND")
                    
        # 5. If still none: raise Exception
        if not save_button:
            raise Exception("SAVE_BUTTON_NOT_FOUND")
             
        logger.info("Scrolling to Save button...")
        save_button.scroll_into_view_if_needed()
        time.sleep(random.uniform(1.0, 2.0))
        
        save_button.click()
        page.wait_for_timeout(2000)
        
        # AFTER SAVE:
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        
        # Verify if link is visible after reload using strict detection
        logger.info("Re-detecting input field for post-save validation...")
        reloaded_input_field, _ = get_strict_input_field()
        reloaded_value = reloaded_input_field.input_value()
        
        logger.info(f"Final saved value read from platform: {reloaded_value}")
        
        if reloaded_value.strip() != new_link.strip():
            raise Exception("LINK_NOT_SAVED_ON_PLATFORM")
            
        # 5. Advanced Link Validation
        result = validate_link_update(page)
        logger.info(f"Validation result: {result}")
        
        if result == "FAIL":
            raise Exception("link validation failed: rejected by the platform")
            
        if result == "UNKNOWN":
            raise Exception("VALIDATION_UNKNOWN")

        logger.info("Link updated successfully.")
        return True

    except Exception as e:
        logger.error(f"Error updating target link: {e}")
        raise"""

new_content = content[:start_idx] + new_func + content[end_idx:]

with open("automation/browser.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print("Replacement successful")
