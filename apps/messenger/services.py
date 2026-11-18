import os
import time
from datetime import datetime
from camoufox.sync_api import Camoufox
from apps.accounts.profile_lock import acquire_profile_lock

_NAME_PREFIXES = (
    "Write to ",
    "Messages in conversation with ",
    "Messages in conversation titled ",
    "Conversation with ",
    "Conversation titled ",
)


def extract_name_from_dom(aria_label: str | None) -> str | None:
    """
    Extracts human-readable recipient or conversation name from Facebook DOM aria-label.
    """
    if not aria_label:
        return None

    label = aria_label.strip()
    for prefix in _NAME_PREFIXES:
        if label.startswith(prefix):
            remainder = label[len(prefix):].strip()
            if remainder:
                first_line = remainder.splitlines()[0].strip()
                if first_line:
                    return first_line

    return None


def dismiss_messenger_dialogs(page) -> None:
    """
    Dismisses Messenger modal dialogs such as 'Enter your PIN to restore your chats'.
    """
    try:
        close_btns = page.query_selector_all(
            'div[role="dialog"] [aria-label="Close"], div[role="dialog"] [aria-label="Đóng"]'
        )
        for btn in close_btns:
            try:
                btn.click(timeout=1500)
                time.sleep(0.3)
            except Exception:
                pass
    except Exception:
        pass


def fetch_thread_recipient_name(profile_dir: str, thread_id: str, timeout: int = 18) -> str | None:
    """
    Opens Facebook Messenger thread in headless Camoufox and extracts the recipient/thread name.
    Uses cross-process profile locking and cleans up any lingering browser locks first.
    """
    url = f"https://www.facebook.com/messages/t/{thread_id}"

    with acquire_profile_lock(profile_dir):
        with Camoufox(
            headless=True,
            persistent_context=True,
            user_data_dir=profile_dir,
            humanize=False,
            i_know_what_im_doing=True,
        ) as browser:
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)

            start_time = time.time()
            while time.time() - start_time < timeout:
                dismiss_messenger_dialogs(page)
                elements = page.query_selector_all(
                    'div[role="textbox"], [aria-label^="Conversation "], [aria-label^="Messages in conversation "]'
                )
                for el in elements:
                    label = el.get_attribute("aria-label")
                    name = extract_name_from_dom(label)
                    if name:
                        return name
                time.sleep(0.8)

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
        with acquire_profile_lock(profile_dir):
            with Camoufox(
                headless=True,
                persistent_context=True,
                user_data_dir=profile_dir,
                humanize=True,
                i_know_what_im_doing=True,
            ) as browser:
                page = browser.pages[0] if browser.pages else browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=25000)

                start_wait = time.time()
                textbox = None
                while time.time() - start_wait < timeout:
                    dismiss_messenger_dialogs(page)
                    textbox = page.query_selector('div[role="textbox"]')
                    if textbox:
                        break
                    time.sleep(0.8)

                if not textbox:
                    raise RuntimeError("Could not find message input box on page")

                textbox.click()
                time.sleep(0.3)

                page.keyboard.insert_text(message)
                time.sleep(0.4)

                page.keyboard.press("Enter")

                time.sleep(3.0)
                return True, None, None

    except Exception as e:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.join(screenshot_dir, f"error_{thread_id}_{timestamp}.png")
        try:
            if 'page' in locals() and page:
                page.screenshot(path=screenshot_path)
            else:
                screenshot_path = None
        except Exception:
            screenshot_path = None
        return False, str(e), screenshot_path
