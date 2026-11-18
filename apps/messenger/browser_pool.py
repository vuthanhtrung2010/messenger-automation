import os
import time
import atexit
import asyncio
import logging
import threading
from collections import OrderedDict
from concurrent.futures import Future
from datetime import datetime
from apps.accounts.profile_lock import terminate_lingering_profile_browsers

logger = logging.getLogger(__name__)


def _streaming_marker_path(profile_dir: str) -> str:
    return f"{os.path.abspath(profile_dir)}.streaming"


def mark_profile_streaming(profile_dir: str, active: bool) -> None:
    """Marks whether an interactive WebSocket browser stream currently owns `profile_dir`."""
    marker = _streaming_marker_path(profile_dir)
    if active:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    else:
        try:
            if os.path.lexists(marker):
                os.unlink(marker)
        except OSError:
            pass


def is_profile_streaming(profile_dir: str) -> bool:
    """Returns True when an interactive WebSocket browser stream is active for `profile_dir`."""
    marker = _streaming_marker_path(profile_dir)
    if not os.path.exists(marker):
        return False
    if os.path.exists("/proc"):
        try:
            with open(marker, encoding="utf-8") as f:
                pid_str = f.read().strip()
            if pid_str.isdigit() and not os.path.exists(f"/proc/{pid_str}"):
                os.unlink(marker)
                return False
        except OSError:
            pass
    return True


async def dismiss_messenger_dialogs_async(page) -> bool:
    """
    Dismisses Messenger modal dialogs such as 'Enter your PIN to restore your chats'
    and its secondary confirmation 'Continue without restoring?' -> 'Don't restore messages'.
    """
    acted = False
    try:
        if await page.locator('[role="dialog"]').count() == 0:
            return False

        dont_restore = page.locator(
            '[role="dialog"] [role="button"][aria-label*="restore"], '
            '[role="dialog"] [role="button"]:has-text("Don\'t restore"), '
            '[role="dialog"] [role="button"]:has-text("Không khôi phục")'
        )
        if await dont_restore.count() > 0:
            await dont_restore.last.click(force=True, timeout=1500)
            await asyncio.sleep(0.25)
            acted = True

        if await page.locator('[role="dialog"]').count() > 0:
            close_btn = page.locator(
                '[role="dialog"] [role="button"][aria-label="Close"], '
                '[role="dialog"] [role="button"][aria-label="Đóng"]'
            )
            if await close_btn.count() > 0:
                await close_btn.first.click(force=True, timeout=1500)
                await asyncio.sleep(0.25)
                acted = True

        if await page.locator('[role="dialog"]').count() > 0:
            dont_restore = page.locator(
                '[role="dialog"] [role="button"][aria-label*="restore"], '
                '[role="dialog"] [role="button"]:has-text("Don\'t restore"), '
                '[role="dialog"] [role="button"]:has-text("Không khôi phục")'
            )
            if await dont_restore.count() > 0:
                await dont_restore.last.click(force=True, timeout=1500)
                await asyncio.sleep(0.25)
                acted = True
    except Exception:
        pass
    return acted


async def wait_for_textbox_ready_async(page, timeout: float = 20.0) -> None:
    """Waits until a Messenger thread's textbox is present and no modal dialog blocks it."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if await page.locator('[role="dialog"]').count() > 0:
            await dismiss_messenger_dialogs_async(page)
            await asyncio.sleep(0.15)
            continue
        if await page.locator('div[role="textbox"]').count() > 0:
            return
        await asyncio.sleep(0.15)
    raise RuntimeError("Could not find message input box on page")


async def insert_messenger_lexical_text_async(page, textbox, message: str) -> None:
    """
    Clears any stale draft in Messenger's Lexical contenteditable textbox and inserts
    `message` once via `document.execCommand('insertText')`.
    """
    clean_message = message.replace("\r\n", "\n")

    await page.keyboard.press("Control+a")
    await page.keyboard.press("Backspace")
    await asyncio.sleep(0.08)

    await textbox.evaluate(
        "(el, txt) => { el.focus(); document.execCommand('insertText', false, txt); }",
        clean_message,
    )
    await asyncio.sleep(0.15)

    if clean_message.strip():
        current = await textbox.inner_text()
        if not current.strip():
            raise RuntimeError("Failed to insert message text into Messenger input box")


async def _default_browser_factory(profile_dir: str):
    from camoufox.async_api import AsyncCamoufox

    cm = AsyncCamoufox(
        headless=True,
        persistent_context=True,
        user_data_dir=profile_dir,
        humanize=False,
        i_know_what_im_doing=True,
    )
    browser = await cm.__aenter__()
    return browser, cm


class _WarmAccountSession:
    """
    Maintains one persistent warm browser instance per Facebook profile directory and
    allows multiple thread tabs to execute in parallel across separate thread IDs.
    """

    MAX_CACHED_TABS = 4
    MAX_PARALLEL_TABS = 4

    def __init__(self, profile_dir: str, browser_factory=None):
        self.profile_dir = os.path.abspath(profile_dir)
        self._browser_factory = browser_factory or _default_browser_factory
        self._uses_default_factory = browser_factory is None
        self.init_lock = asyncio.Lock()
        self.tab_semaphore = asyncio.Semaphore(self.MAX_PARALLEL_TABS)
        self.thread_locks: dict[str, asyncio.Lock] = {}
        self.thread_pages: OrderedDict[str, object] = OrderedDict()
        self.browser = None
        self._browser_cm = None
        self.anchor_page = None
        self.active_ops = 0
        self.last_used_mono = time.monotonic()

    def get_thread_lock(self, thread_id: str) -> asyncio.Lock:
        lock = self.thread_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self.thread_locks[thread_id] = lock
        return lock

    async def ensure_browser(self, timeout: float = 25.0) -> None:
        async with self.init_lock:
            if is_profile_streaming(self.profile_dir):
                await self._close_unlocked()
                deadline = time.monotonic() + timeout
                while is_profile_streaming(self.profile_dir):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Account is currently busy in interactive login stream")
                    await asyncio.sleep(0.3)

            if self.browser is not None:
                alive = False
                try:
                    if self.anchor_page is not None and not self.anchor_page.is_closed():
                        await self.anchor_page.evaluate("1")
                        alive = True
                except Exception:
                    alive = False
                if not alive:
                    await self._close_unlocked()

            if self.browser is None:
                if self._uses_default_factory:
                    os.makedirs(self.profile_dir, exist_ok=True)
                    await asyncio.to_thread(terminate_lingering_profile_browsers, self.profile_dir)

                result = await self._browser_factory(self.profile_dir)
                if isinstance(result, tuple) and len(result) == 2:
                    self.browser, self._browser_cm = result
                else:
                    self.browser, self._browser_cm = result, None

                existing_pages = getattr(self.browser, "pages", None) or []
                self.anchor_page = existing_pages[0] if existing_pages else await self.browser.new_page()

    async def _evict_oldest_tab_if_needed(self) -> None:
        while len(self.thread_pages) >= self.MAX_CACHED_TABS:
            evict_tid = None
            for tid in self.thread_pages.keys():
                if not self.get_thread_lock(tid).locked():
                    evict_tid = tid
                    break
            if evict_tid is None:
                break
            old_page = self.thread_pages.pop(evict_tid)
            try:
                if not old_page.is_closed():
                    await old_page.close()
            except Exception:
                pass

    async def _acquire_thread_page(self, thread_id: str, timeout: float = 25.0):
        await self.ensure_browser(timeout=timeout)
        url = f"https://www.facebook.com/messages/t/{thread_id}"

        page = self.thread_pages.get(thread_id)
        if page is not None:
            try:
                if not page.is_closed() and f"/messages/t/{thread_id}" in (getattr(page, "url", "") or ""):
                    await page.evaluate("1")
                    self.thread_pages.move_to_end(thread_id)
                    return page
            except Exception:
                pass
            self.thread_pages.pop(thread_id, None)
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                pass

        await self._evict_oldest_tab_if_needed()
        page = await self.browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        except Exception:
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                pass
            raise

        self.thread_pages[thread_id] = page
        self.thread_pages.move_to_end(thread_id)
        return page

    async def _discard_thread_page(self, thread_id: str) -> None:
        page = self.thread_pages.pop(thread_id, None)
        if page is not None:
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                pass

    async def _close_unlocked(self) -> None:
        pages = list(self.thread_pages.values())
        self.thread_pages.clear()
        for page in pages:
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                pass

        if self.anchor_page is not None:
            try:
                if not self.anchor_page.is_closed():
                    await self.anchor_page.close()
            except Exception:
                pass
            self.anchor_page = None

        cm = self._browser_cm
        browser = self.browser
        self._browser_cm = None
        self.browser = None

        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass
        elif browser is not None:
            try:
                close_fn = getattr(browser, "close", None)
                if close_fn:
                    await close_fn()
            except Exception:
                pass

        if self._uses_default_factory:
            await asyncio.to_thread(terminate_lingering_profile_browsers, self.profile_dir)

    async def close(self) -> None:
        async with self.init_lock:
            await self._close_unlocked()

    async def send_message(
        self, thread_id: str, message: str, timeout: float = 25.0
    ) -> tuple[bool, str | None, str | None]:
        screenshot_dir = os.path.abspath("data/error_screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        self.active_ops += 1
        self.last_used_mono = time.monotonic()
        try:
            async with self.get_thread_lock(thread_id):
                async with self.tab_semaphore:
                    sent_enter = False
                    page = None
                    for attempt in range(2):
                        try:
                            page = await self._acquire_thread_page(thread_id, timeout=timeout)
                            await wait_for_textbox_ready_async(page, timeout=timeout)
                            textbox = page.locator('div[role="textbox"]').first
                            try:
                                await textbox.click(timeout=2500)
                            except Exception:
                                await dismiss_messenger_dialogs_async(page)
                                await asyncio.sleep(0.2)
                                await textbox.click(timeout=3000)

                            await asyncio.sleep(0.1)
                            await insert_messenger_lexical_text_async(page, textbox, message)

                            sent_enter = True
                            await page.keyboard.press("Enter")

                            enter_started = time.monotonic()
                            retried_dialog = False
                            while time.monotonic() - enter_started < 4.5:
                                try:
                                    remaining = (await textbox.inner_text()).strip()
                                    if not remaining:
                                        break
                                except Exception:
                                    break

                                if (
                                    not retried_dialog
                                    and (time.monotonic() - enter_started) >= 0.6
                                    and await page.locator('[role="dialog"]').count() > 0
                                ):
                                    await dismiss_messenger_dialogs_async(page)
                                    # Re-focus and press Enter only if the text remained unsent
                                    if (await textbox.inner_text()).strip():
                                        await textbox.click(timeout=2500)
                                        await page.keyboard.press("Enter")
                                    retried_dialog = True

                                await asyncio.sleep(0.12)

                            # Short settle on warm persistent context so send payload flushes
                            await asyncio.sleep(0.35)
                            return True, None, None
                        except Exception as e:
                            if not sent_enter and attempt == 0:
                                logger.warning(f"Retrying stale tab/browser for thread {thread_id}: {e}")
                                await self._discard_thread_page(thread_id)
                                await self.close()
                                page = None
                                continue

                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            screenshot_path = os.path.join(
                                screenshot_dir, f"error_{thread_id}_{timestamp}.png"
                            )
                            if page is not None:
                                try:
                                    await page.screenshot(path=screenshot_path)
                                except Exception:
                                    screenshot_path = None
                            else:
                                screenshot_path = None

                            await self._discard_thread_page(thread_id)
                            return False, str(e), screenshot_path
        except Exception as e:
            return False, str(e), None
        finally:
            self.active_ops = max(0, self.active_ops - 1)
            self.last_used_mono = time.monotonic()

    async def fetch_recipient_name(self, thread_id: str, timeout: float = 18.0) -> str | None:
        from apps.messenger.services import extract_name_from_dom

        self.active_ops += 1
        self.last_used_mono = time.monotonic()
        try:
            async with self.get_thread_lock(thread_id):
                async with self.tab_semaphore:
                    for attempt in range(2):
                        try:
                            page = await self._acquire_thread_page(thread_id, timeout=timeout)
                            start_time = time.monotonic()
                            while time.monotonic() - start_time < timeout:
                                await dismiss_messenger_dialogs_async(page)
                                elements = await page.query_selector_all(
                                    'div[role="textbox"], [aria-label^="Conversation "], [aria-label^="Messages in conversation "]'
                                )
                                for el in elements:
                                    label = await el.get_attribute("aria-label")
                                    name = extract_name_from_dom(label)
                                    if name:
                                        return name
                                await asyncio.sleep(0.25)
                            return None
                        except Exception:
                            await self._discard_thread_page(thread_id)
                            if attempt == 0:
                                await self.close()
                                continue
                            raise
        finally:
            self.active_ops = max(0, self.active_ops - 1)
            self.last_used_mono = time.monotonic()


class AccountBrowserPool:
    """
    Process-wide warm browser pool running on a dedicated asyncio background thread.
    Keeps one Camoufox context open per account and runs multi-recipient tasks in parallel tabs.
    """

    def __init__(self, idle_timeout: float = 180.0, browser_factory=None):
        self._idle_timeout = idle_timeout
        self._browser_factory = browser_factory
        self._sessions: dict[str, _WarmAccountSession] = {}
        self._sessions_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._reaper_task = None
        self._closed = False
        self._start_loop_thread()

    def _start_loop_thread(self) -> None:
        ready = threading.Event()

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._reaper_task = loop.create_task(self._reaper_loop())
            ready.set()
            try:
                loop.run_forever()
            finally:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()

        self._thread = threading.Thread(target=_runner, name="CamoufoxBrowserPool", daemon=True)
        self._thread.start()
        ready.wait()

    async def _reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(15.0)
            now = time.monotonic()
            with self._sessions_lock:
                sessions = list(self._sessions.values())
            for session in sessions:
                if session.browser is not None and session.active_ops == 0:
                    if (now - session.last_used_mono) >= self._idle_timeout:
                        try:
                            await session.close()
                        except Exception:
                            pass

    def _get_session(self, profile_dir: str) -> _WarmAccountSession:
        key = os.path.abspath(profile_dir)
        with self._sessions_lock:
            session = self._sessions.get(key)
            if session is None:
                session = _WarmAccountSession(key, browser_factory=self._browser_factory)
                self._sessions[key] = session
            return session

    def _submit(self, coro) -> Future:
        if self._closed or self._loop is None:
            raise RuntimeError("AccountBrowserPool is closed")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def send_message(
        self, profile_dir: str, thread_id: str, message: str, timeout: float = 25.0
    ) -> tuple[bool, str | None, str | None]:
        session = self._get_session(profile_dir)
        return self._submit(session.send_message(thread_id, message, timeout=timeout)).result()

    def fetch_recipient_name(
        self, profile_dir: str, thread_id: str, timeout: float = 18.0
    ) -> str | None:
        session = self._get_session(profile_dir)
        return self._submit(session.fetch_recipient_name(thread_id, timeout=timeout)).result()

    def invalidate_profile(self, profile_dir: str) -> None:
        key = os.path.abspath(profile_dir)
        with self._sessions_lock:
            session = self._sessions.get(key)
        if session is not None and not self._closed and self._loop is not None:
            self._submit(session.close()).result(timeout=15.0)

    def close_all(self) -> None:
        if self._closed:
            return
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        if self._loop is not None and self._loop.is_running():
            async def _shutdown():
                for session in sessions:
                    try:
                        await session.close()
                    except Exception:
                        pass
                if self._reaper_task:
                    self._reaper_task.cancel()

            try:
                self._submit(_shutdown()).result(timeout=15.0)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._closed = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)


_POOL_LOCK = threading.Lock()
_GLOBAL_POOL: AccountBrowserPool | None = None


def get_browser_pool() -> AccountBrowserPool:
    """Returns the singleton process-wide `AccountBrowserPool` instance."""
    global _GLOBAL_POOL
    if _GLOBAL_POOL is None:
        with _POOL_LOCK:
            if _GLOBAL_POOL is None:
                _GLOBAL_POOL = AccountBrowserPool()
                atexit.register(_GLOBAL_POOL.close_all)
    return _GLOBAL_POOL
