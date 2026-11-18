import time

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
    Fetches the recipient/thread name using the shared warm multi-tab AccountBrowserPool
    so concurrent tasks reuse an already-running browser and open parallel tabs.
    """
    from apps.messenger.browser_pool import get_browser_pool

    return get_browser_pool().fetch_recipient_name(profile_dir, thread_id, timeout=float(timeout))


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
    Dispatches a message to a Facebook Messenger thread via the shared warm multi-tab
    AccountBrowserPool (one persistent browser per account, concurrent tabs across recipients).
    Returns (success: bool, error_message: str | None, screenshot_path: str | None)
    """
    from apps.messenger.browser_pool import get_browser_pool

    return get_browser_pool().send_message(profile_dir, thread_id, message, timeout=float(timeout))
