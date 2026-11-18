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


def dismiss_messenger_dialogs(page) -> bool:
    """
    Dismisses Messenger modal dialogs such as 'Enter your PIN to restore your chats'
    and its secondary confirmation 'Continue without restoring?' -> 'Don't restore messages'.
    Returns True if any dialog action was taken.
    """
    acted = False
    try:
        if page.locator('[role="dialog"]').count() == 0:
            return False

        # Step A: If confirmation dialog ("Continue without restoring?") is open, click "Don't restore messages"
        dont_restore = page.locator(
            '[role="dialog"] [role="button"][aria-label*="restore"], '
            '[role="dialog"] [role="button"]:has-text("Don\'t restore"), '
            '[role="dialog"] [role="button"]:has-text("Không khôi phục")'
        )
        if dont_restore.count() > 0:
            dont_restore.last.click(force=True, timeout=2000)
            time.sleep(1.0)
            acted = True

        # Step B: If PIN restore dialog is open, click "Close" / "Đóng"
        if page.locator('[role="dialog"]').count() > 0:
            close_btn = page.locator(
                '[role="dialog"] [role="button"][aria-label="Close"], '
                '[role="dialog"] [role="button"][aria-label="Đóng"]'
            )
            if close_btn.count() > 0:
                close_btn.first.click(force=True, timeout=2000)
                time.sleep(1.0)
                acted = True

        # Step C: Clicking Close on PIN dialog opens "Continue without restoring?"; dismiss it immediately
        if page.locator('[role="dialog"]').count() > 0:
            dont_restore = page.locator(
                '[role="dialog"] [role="button"][aria-label*="restore"], '
                '[role="dialog"] [role="button"]:has-text("Don\'t restore"), '
                '[role="dialog"] [role="button"]:has-text("Không khôi phục")'
            )
            if dont_restore.count() > 0:
                dont_restore.last.click(force=True, timeout=2000)
                time.sleep(1.0)
                acted = True
    except Exception:
        pass
    return acted


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


def insert_messenger_lexical_text(page, textbox, message: str) -> None:
    """
    Clears any stale draft in Messenger's Lexical contenteditable textbox and inserts
    `message` exactly once via `document.execCommand('insertText')`.

    Avoids `page.keyboard.insert_text()` / `locator.fill()`, which in Firefox Juggler
    emit a duplicate `insertCompositionText` input event after `compositionend` that
    causes Meta's Lexical editor to double the inserted text (e.g. 'ok' -> 'okok').
    """
    clean_message = message.replace("\r\n", "\n")

    # Clear any leftover unsent draft in the persistent profile
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    time.sleep(0.15)

    textbox.evaluate(
        "(el, txt) => { el.focus(); document.execCommand('insertText', false, txt); }",
        clean_message,
    )
    time.sleep(0.35)

    if clean_message.strip() and not textbox.inner_text().strip():
        raise RuntimeError("Failed to insert message text into Messenger input box")


def send_thread_message(
    profile_dir: str,
    thread_id: str,
    message: str,
    timeout: int = 25,
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
                humanize=False,
                i_know_what_im_doing=True,
            ) as browser:
                page = browser.pages[0] if browser.pages else browser.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    # Allow Facebook's async E2EE module time to mount any PIN modal before checking readiness
                    time.sleep(3.5)

                    start_wait = time.time()
                    ready = False
                    while time.time() - start_wait < timeout:
                        dismiss_messenger_dialogs(page)
                        has_textbox = page.locator('div[role="textbox"]').count() > 0
                        has_dialog = page.locator('[role="dialog"]').count() > 0
                        if has_textbox and not has_dialog:
                            ready = True
                            break
                        time.sleep(0.8)

                    if not ready and page.locator('div[role="textbox"]').count() == 0:
                        raise RuntimeError("Could not find message input box on page")

                    textbox = page.locator('div[role="textbox"]').first
                    try:
                        textbox.click(timeout=5000)
                    except Exception:
                        # Retry once in case a late dialog appeared right as click() ran
                        dismiss_messenger_dialogs(page)
                        time.sleep(0.5)
                        textbox.click(timeout=5000)

                    time.sleep(0.25)
                    insert_messenger_lexical_text(page, textbox, message)

                    page.keyboard.press("Enter")

                    # Wait for Lexical textbox to clear after Enter (confirming send), then let E2EE flush
                    send_deadline = time.time() + 4.0
                    while time.time() < send_deadline:
                        try:
                            if not textbox.inner_text().strip():
                                break
                        except Exception:
                            break
                        time.sleep(0.25)

                    time.sleep(1.5)
                    return True, None, None
                except Exception as e:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = os.path.join(screenshot_dir, f"error_{thread_id}_{timestamp}.png")
                    try:
                        page.screenshot(path=screenshot_path)
                    except Exception:
                        screenshot_path = None
                    return False, str(e), screenshot_path

    except Exception as e:
        return False, str(e), None
