import os
import json
import logging
from PIL import Image
import google.generativeai as genai

logger = logging.getLogger('palladium_automation.ai_selector')

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'selector_cache.json')

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading selector cache: {e}")
    return {}

def save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving selector cache: {e}")

def get_cached_selector(action_key):
    cache = load_cache()
    return cache.get(action_key)

def set_cached_selector(action_key, selector):
    cache = load_cache()
    cache[action_key] = selector
    save_cache(cache)

def parse_selector(response_text):
    """Extracts the selector from the Gemini response."""
    try:
        if "selector:" in response_text.lower():
            # Find the line containing the selector
            lines = response_text.split('\n')
            for line in lines:
                if line.lower().strip().startswith('selector:'):
                    return line.split(':', 1)[1].strip().strip('`').strip('"').strip("'")
        
        # Fallback if the format isn't strictly adhered to but it returns just code
        if "```" in response_text:
            parts = response_text.split("```")
            if len(parts) >= 3:
                return parts[1].replace("playwright", "").replace("css", "").strip()
                
        # Last resort, return the whole text stripped
        return response_text.strip().strip('`').strip('"').strip("'")
    except Exception as e:
        logger.error(f"Failed to parse selector from response: {e}")
        return None

def generate_selector_with_gemini(html_content, screenshot_path, action_description):
    """
    Uses Gemini Vision to generate a new Playwright selector based on the page state.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY is not set. Cannot use AI self-healing.")
        return None

    try:
        genai.configure(api_key=api_key)
        # Using gemini-1.5-flash as it supports vision and is fast/cost-effective
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Compress HTML to avoid massive token usage (simple strip)
        # We take a chunk of the body if it's too large
        if len(html_content) > 50000:
            # Try to extract just the body or main content area
            import re
            body_match = re.search(r'<body.*?>(.*?)</body>', html_content, re.IGNORECASE | re.DOTALL)
            if body_match:
                html_content = body_match.group(1)[:50000]
            else:
                html_content = html_content[:50000]
                
        prompt = f"""You are an expert Playwright automation assistant.

The previous selector failed while trying to perform an action on a webpage.

TASK:
Find a new, reliable Playwright selector for the required action.

ACTION:
{action_description}

CONTEXT:
* The old selector failed.
* The UI may have changed.

INPUTS:
1. Screenshot of the current page (attached)
2. HTML content of the page (partial):
```html
{html_content}
```

INSTRUCTIONS:
* Analyze both screenshot and HTML
* Identify the correct element
* Return ONLY a valid Playwright selector (e.g. css, text, xpath, or role)
* Prefer robust selectors:
  * role-based (e.g. button[name="Save"])
  * text-based (has-text)
  * data-testid if available
* Avoid fragile selectors (like nth-child or generated class names)

OUTPUT FORMAT:
Return exactly and only:
selector: <playwright_selector_here>
"""
        
        # Load image
        img = Image.open(screenshot_path)
        
        logger.info(f"Sending vision request to Gemini for action: {action_description}")
        response = model.generate_content([prompt, img])
        
        new_selector = parse_selector(response.text)
        
        if new_selector:
            logger.info(f"Gemini successfully generated new selector: {new_selector}")
            return new_selector
        else:
            logger.error("Gemini failed to return a recognizable selector format.")
            logger.debug(f"Raw Gemini response: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error during Gemini Vision request: {e}")
        return None