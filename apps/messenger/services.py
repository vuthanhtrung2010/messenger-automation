import os
import time
from datetime import datetime
from camoufox.sync_api import Camoufox

def extract_name_from_dom(aria_label: str | None) -> str | None:
    """
    Extracts human-readable recipient or conversation name from Facebook DOM aria-label.
    """
    if not aria_label:
        return None
    
    label = aria_label.strip()
    if label.startswith("Write to "):
        name = label[len("Write to "):].strip()
        return name if name else None
    
    if label.startswith("Conversation titled "):
        name = label[len("Conversation titled "):].strip()
        return name if name else None
        
    return None


def fetch_thread_recipient_name(profile_dir: str, thread_id: str, timeout: int = 15) -> str | None:
    """
    Opens Facebook Messenger thread in headless Camoufox and extracts the recipient/thread name.
    """
    url = f"https://www.facebook.com/messages/t/{thread_id}"
    
    with Camoufox(
        headless=True,
        persistent_context=True,
        user_data_dir=profile_dir,
        humanize=True,
        i_know_what_im_doing=True,
    ) as browser:
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check textbox aria-label first
            elements = page.query_selector_all('div[role="textbox"], div[aria-label^="Conversation titled "]')
            for el in elements:
                label = el.get_attribute("aria-label")
                name = extract_name_from_dom(label)
                if name:
                    return name
            time.sleep(1)
            
    return None


def send_thread_message(
    profile_dir: str,
    thread_id: str,
    message: str,
    timeout: int = 20,
) -> tuple[bool, str | None, str | None]:
    """
    Dispatches a message to a Facebook Messenger thread using persistent Camoufox context.
    Returns (success: bool, error_message: str | None, screenshot_path: str | None)
    """
    url = f"https://www.facebook.com/messages/t/{thread_id}"
    screenshot_dir = os.path.abspath("data/error_screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)
    
    try:
        with Camoufox(
            headless=True,
            persistent_context=True,
            user_data_dir=profile_dir,
            humanize=True,
            i_know_what_im_doing=True,
        ) as browser:
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(url, wait_until="domcontentloaded")
            
            # Wait for message input textbox
            textbox = page.wait_for_selector('div[role="textbox"]', timeout=timeout * 1000)
            if not textbox:
                raise RuntimeError("Could not find message input box on page")
            
            textbox.focus()
            time.sleep(0.5)
            
            # Type message
            page.keyboard.insert_text(message)
            time.sleep(0.5)
            
            # Send message
            page.keyboard.press("Enter")
            
            # Wait 3 seconds for message to dispatch over network
            time.sleep(3.0)
            return True, None, None
            
    except Exception as e:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.join(screenshot_dir, f"error_{thread_id}_{timestamp}.png")
        try:
            if 'page' in locals() and page:
                page.screenshot(path=screenshot_path)
        except Exception:
            screenshot_path = None
        return False, str(e), screenshot_path
