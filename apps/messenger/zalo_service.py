import asyncio
import json
import os
import time
from apps.accounts.profile_lock import terminate_lingering_profile_browsers
from apps.messenger.browser_pool import is_profile_streaming

ZALO_CHAT_URL = "https://chat.zalo.me"
ZALO_FIREFOX_PREFS = {
    "dom.storageManager.prompt.testing": True,
    "dom.storageManager.prompt.testing.allow": True,
}


def _save_zalo_error_screenshot(page_sync_or_async_bytes: bytes | None, prefix: str = "zalo_error") -> str:
    if not page_sync_or_async_bytes:
        return ""
    os.makedirs("data/error_screenshots", exist_ok=True)
    path = os.path.abspath(f"data/error_screenshots/{prefix}_{int(time.time())}.png")
    with open(path, "wb") as f:
        f.write(page_sync_or_async_bytes)
    return path


async def _open_zalo_browser(profile_dir: str):
    from camoufox.async_api import AsyncCamoufox

    if is_profile_streaming(profile_dir):
        raise RuntimeError("Account is currently busy in interactive login stream")

    os.makedirs(profile_dir, exist_ok=True)
    await asyncio.to_thread(terminate_lingering_profile_browsers, profile_dir)

    cm = AsyncCamoufox(
        headless=True,
        persistent_context=True,
        user_data_dir=profile_dir,
        humanize=False,
        i_know_what_im_doing=True,
        viewport={"width": 1280, "height": 800},
        firefox_user_prefs=ZALO_FIREFOX_PREFS,
    )
    browser = await cm.__aenter__()
    page = browser.pages[0] if browser.pages else await browser.new_page()
    return cm, browser, page


async def _close_zalo_browser(cm, browser, profile_dir: str) -> None:
    try:
        if browser is not None:
            await browser.close()
    except Exception:
        pass
    try:
        if cm is not None:
            await cm.__aexit__(None, None, None)
    except Exception:
        pass
    await asyncio.to_thread(terminate_lingering_profile_browsers, profile_dir)


async def is_zalo_logged_in_async(browser, page, timeout: float = 15.0) -> tuple[bool, str | None]:
    """
    Verifies whether the Zalo Web session is currently authenticated.
    Checks for `zpw_sek` cookie, chat.zalo.me URL (not id.zalo.me), and `#contact-search-input`.
    Returns `(True, zalo_uid)` when authenticated, `(False, None)` otherwise.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current_url = getattr(page, "url", "") or ""
        if "id.zalo.me" in current_url:
            return False, None

        try:
            has_qr = await page.locator('img[alt*="QR"], .qrcode, [class*="qrcode"]').count() > 0
            if has_qr:
                return False, None
        except Exception:
            pass

        try:
            if await page.locator("#contact-search-input").count() > 0:
                cookies = await browser.cookies()
                has_sek = any(
                    c.get("name") == "zpw_sek" and "zalo.me" in c.get("domain", "")
                    for c in cookies
                )
                if not has_sek:
                    return False, None
                uid = await page.evaluate(
                    "() => localStorage.getItem('sh_z_recentuid') || localStorage.getItem('sh_zlast_uid')"
                )
                return True, (str(uid).strip() if uid else None)
        except Exception:
            pass

        await asyncio.sleep(0.5)

    return False, None


async def _check_zalo_session_async(profile_dir: str, timeout: float = 20.0) -> tuple[bool, str | None]:
    cm, browser, page = await _open_zalo_browser(profile_dir)
    try:
        await page.goto(ZALO_CHAT_URL, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        return await is_zalo_logged_in_async(browser, page, timeout=timeout)
    finally:
        await _close_zalo_browser(cm, browser, profile_dir)


def check_zalo_session(profile_dir: str, timeout: float = 20.0) -> tuple[bool, str | None]:
    """Checks if a Zalo Camoufox profile is still logged in."""
    return asyncio.run(_check_zalo_session_async(profile_dir, timeout=timeout))


async def _list_zalo_contacts_async(profile_dir: str, timeout: float = 20.0) -> list[dict[str, str]]:
    cm, browser, page = await _open_zalo_browser(profile_dir)
    try:
        await page.goto(ZALO_CHAT_URL, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        logged_in, _ = await is_zalo_logged_in_async(browser, page, timeout=timeout)
        if not logged_in:
            raise RuntimeError("Zalo session expired or logged out")

        contacts = await page.evaluate("""() => {
            const out = [];
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                if (!k || !k.startsWith('0_')) continue;
                const uid = k.slice(2);
                if (!uid) continue;
                try {
                    const data = JSON.parse(localStorage.getItem(k) || '{}');
                    const name = (data.aliasName || data.zName || '').trim();
                    if (name) {
                        out.push({ thread_id: uid, name });
                    }
                } catch (e) {}
            }
            return out;
        }""")
        return contacts or []
    finally:
        await _close_zalo_browser(cm, browser, profile_dir)


def list_zalo_contacts(profile_dir: str, timeout: float = 20.0) -> list[dict[str, str]]:
    """Extracts plaintext contact `{thread_id, name}` mappings from Zalo localStorage."""
    return asyncio.run(_list_zalo_contacts_async(profile_dir, timeout=timeout))


async def _open_zalo_conversation_async(
    page,
    thread_id: str,
    recipient_name: str | None = None,
    timeout: float = 20.0,
) -> str | None:
    """
    Searches for `thread_id` (or fallback `recipient_name` / localStorage `0_<thread_id>`)
    in Zalo's `#contact-search-input`, clicks the matching result, and returns the header name.
    """
    ls_name = await page.evaluate(
        """(tid) => {
            try {
                const raw = localStorage.getItem('0_' + tid);
                if (!raw) return null;
                const data = JSON.parse(raw);
                return (data.aliasName || data.zName || '').trim() || null;
            } catch (e) {
                return null;
            }
        }""",
        thread_id,
    )

    search_queries = []
    for candidate in (thread_id, recipient_name, ls_name):
        if candidate and candidate not in search_queries:
            search_queries.append(candidate)

    search_input = page.locator("#contact-search-input")
    await search_input.wait_for(state="visible", timeout=int(timeout * 1000))

    target_selectors = [
        f"#friend-item-{thread_id}",
        f'[id$="-{thread_id}"]',
    ]

    clicked = False
    for query in search_queries:
        await search_input.click()
        await search_input.fill("")
        await search_input.fill(query)
        await asyncio.sleep(1.2)

        for sel in target_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click()
                clicked = True
                break
        if clicked:
            break

        # If searching by name/id returned a single unambiguous conv-item, click it when query == ls_name or recipient_name
        if query != thread_id:
            conv_items = page.locator('.conv-item[id^="friend-item-"]')
            if await conv_items.count() > 0:
                await conv_items.first.click()
                clicked = True
                break

    if not clicked:
        raise RuntimeError(f"Could not find Zalo conversation for {thread_id}")

    await asyncio.sleep(0.8)
    header_text = await page.evaluate("""() => {
        const header = document.querySelector('#header, header, .header-title');
        if (!header) return null;
        const firstLine = (header.innerText || '').split('\\n')[0].trim();
        return firstLine || null;
    }""")
    return ls_name or header_text


async def _fetch_zalo_recipient_name_async(profile_dir: str, thread_id: str, timeout: float = 20.0) -> str | None:
    cm, browser, page = await _open_zalo_browser(profile_dir)
    try:
        await page.goto(ZALO_CHAT_URL, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        logged_in, _ = await is_zalo_logged_in_async(browser, page, timeout=timeout)
        if not logged_in:
            return None

        ls_name = await page.evaluate(
            """(tid) => {
                try {
                    const raw = localStorage.getItem('0_' + tid);
                    if (!raw) return null;
                    const data = JSON.parse(raw);
                    return (data.aliasName || data.zName || '').trim() || null;
                } catch (e) {
                    return null;
                }
            }""",
            thread_id,
        )
        if ls_name:
            return ls_name

        return await _open_zalo_conversation_async(page, thread_id, timeout=timeout)
    except Exception:
        return None
    finally:
        await _close_zalo_browser(cm, browser, profile_dir)


def fetch_zalo_recipient_name(profile_dir: str, thread_id: str, timeout: float = 20.0) -> str | None:
    """Resolves a Zalo user/group ID to its human-readable display name."""
    return asyncio.run(_fetch_zalo_recipient_name_async(profile_dir, thread_id, timeout=timeout))


async def _send_zalo_message_async(
    profile_dir: str,
    thread_id: str,
    message: str,
    timeout: float = 25.0,
    recipient_name: str | None = None,
) -> tuple[bool, str, str]:
    cm, browser, page = await _open_zalo_browser(profile_dir)
    try:
        await page.goto(ZALO_CHAT_URL, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        logged_in, _ = await is_zalo_logged_in_async(browser, page, timeout=timeout)
        if not logged_in:
            shot = _save_zalo_error_screenshot(await page.screenshot(), "zalo_expired")
            return False, "Zalo session expired or logged out. Please re-login.", shot

        await _open_zalo_conversation_async(
            page,
            thread_id,
            recipient_name=recipient_name,
            timeout=timeout,
        )

        rich_input = page.locator("#richInput")
        await rich_input.wait_for(state="visible", timeout=10000)
        await rich_input.click()

        clean_message = message.replace("\r\n", "\n")
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.1)

        await rich_input.evaluate(
            "(el, txt) => { el.focus(); document.execCommand('insertText', false, txt); }",
            clean_message,
        )
        await asyncio.sleep(0.25)

        if clean_message.strip():
            current = await rich_input.inner_text()
            if not current.strip():
                raise RuntimeError("Failed to insert message text into Zalo #richInput box")

        await page.keyboard.press("Enter")
        await asyncio.sleep(1.5)
        return True, "", ""
    except Exception as e:
        shot = ""
        try:
            shot = _save_zalo_error_screenshot(await page.screenshot(), "zalo_send_error")
        except Exception:
            pass
        return False, str(e), shot
    finally:
        await _close_zalo_browser(cm, browser, profile_dir)


def send_zalo_message(
    profile_dir: str,
    thread_id: str,
    message: str,
    timeout: int = 25,
    recipient_name: str | None = None,
) -> tuple[bool, str, str]:
    """Sends a message to a Zalo conversation via Camoufox."""
    return asyncio.run(
        _send_zalo_message_async(
            profile_dir=profile_dir,
            thread_id=thread_id,
            message=message,
            timeout=float(timeout),
            recipient_name=recipient_name,
        )
    )
