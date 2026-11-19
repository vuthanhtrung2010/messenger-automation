import os
import json
import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from channels.generic.websocket import AsyncWebsocketConsumer
from apps.accounts.models import MessengerAccount
from apps.accounts.profile_lock import terminate_lingering_profile_browsers
from apps.messenger.browser_pool import mark_profile_streaming

logger = logging.getLogger(__name__)

_ACCOUNT_LOCKS: dict[str, asyncio.Lock] = {}


def _get_account_lock(account_id: str) -> asyncio.Lock:
    if account_id not in _ACCOUNT_LOCKS:
        _ACCOUNT_LOCKS[account_id] = asyncio.Lock()
    return _ACCOUNT_LOCKS[account_id]


async def launch_browser_session(profile_dir: str, platform: str = MessengerAccount.Platform.MESSENGER):
    """
    Launches an async Camoufox browser context with persistent profile.
    """
    from camoufox.async_api import AsyncCamoufox

    os.makedirs(profile_dir, exist_ok=True)
    mark_profile_streaming(profile_dir, True)
    try:
        await asyncio.to_thread(terminate_lingering_profile_browsers, profile_dir)

        kwargs = dict(
            headless=True,
            persistent_context=True,
            user_data_dir=profile_dir,
            humanize=False,
            i_know_what_im_doing=True,
            viewport={"width": 1280, "height": 800},
        )
        if platform == MessengerAccount.Platform.ZALO:
            kwargs["firefox_user_prefs"] = {
                "dom.storageManager.prompt.testing": True,
                "dom.storageManager.prompt.testing.allow": True,
            }

        camoufox = AsyncCamoufox(**kwargs)
        browser = await camoufox.__aenter__()
    except Exception:
        mark_profile_streaming(profile_dir, False)
        raise

    try:
        browser._camoufox_cm = camoufox
        browser._profile_dir = profile_dir
    except Exception:
        pass

    page = browser.pages[0] if browser.pages else await browser.new_page()
    login_url = (
        "https://chat.zalo.me"
        if platform == MessengerAccount.Platform.ZALO
        else "https://www.facebook.com/login"
    )
    try:
        await page.goto(login_url, wait_until="commit", timeout=20000)
    except Exception as e:
        print(f"Error loading initial login page: {e}")
    return browser, page


async def _detect_logged_in_user_id(platform: str, browser, page) -> str | None:
    """Returns the authenticated platform user ID if logged in, otherwise None."""
    cookies = await browser.cookies()
    if platform == MessengerAccount.Platform.ZALO:
        has_sek = any(
            c.get("name") == "zpw_sek" and "zalo.me" in c.get("domain", "")
            for c in cookies
        )
        if not has_sek:
            return None
        try:
            if await page.locator("#contact-search-input").count() == 0:
                return None
            uid = await page.evaluate(
                "() => localStorage.getItem('sh_z_recentuid') || localStorage.getItem('sh_zlast_uid')"
            )
            return str(uid).strip() if uid else "zalo_active"
        except Exception:
            return None

    fb_cookies = {
        c["name"]: c["value"]
        for c in cookies
        if "facebook.com" in c.get("domain", "")
    }
    return fb_cookies.get("c_user")


async def close_browser_session(browser, profile_dir: str | None = None):
    pdir = profile_dir
    if browser is not None:
        cm = getattr(browser, "_camoufox_cm", None)
        pdir = profile_dir or getattr(browser, "_profile_dir", None)
        try:
            await browser.close()
        except Exception:
            pass
        if cm is not None and not isinstance(cm, asyncio.Future):
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass
        if pdir and not isinstance(pdir, asyncio.Future) and isinstance(pdir, str):
            await asyncio.to_thread(terminate_lingering_profile_browsers, pdir)
    elif profile_dir and isinstance(profile_dir, str):
        await asyncio.to_thread(terminate_lingering_profile_browsers, profile_dir)

    if pdir and not isinstance(pdir, asyncio.Future) and isinstance(pdir, str):
        mark_profile_streaming(pdir, False)


class BrowserStreamConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_id = None
        self.account = None
        self.browser = None
        self.page = None
        self.stream_task = None
        self.is_running = False
        self.force_frame = False
        self.logged_in_notified = False
        self.last_interaction_time = 0.0
        self.last_cookie_check_time = 0.0
        self.browser_ready = asyncio.Event()
        self._move_in_flight = False

    async def connect(self):
        self.account_id = str(self.scope["url_route"]["kwargs"]["account_id"])
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        try:
            if user.is_superuser:
                self.account = await MessengerAccount.objects.aget(id=self.account_id)
            else:
                self.account = await MessengerAccount.objects.aget(id=self.account_id, owner=user)
        except MessengerAccount.DoesNotExist:
            await self.close(code=4404)
            return

        await self.accept()
        self.is_running = True
        self.stream_task = asyncio.create_task(self.stream_loop())

    async def stream_loop(self):
        lock = _get_account_lock(self.account_id)
        async with lock:
            if not self.is_running:
                return
            try:
                await self.send(text_data=json.dumps({
                    "type": "status",
                    "state": "starting",
                    "message": "Starting browser"
                }))
                self.browser, self.page = await launch_browser_session(
                    self.account.profile_dir,
                    platform=self.account.platform,
                )
                self.last_interaction_time = asyncio.get_event_loop().time()
                self.browser_ready.set()
                await self.send(text_data=json.dumps({
                    "type": "status",
                    "state": "active",
                    "message": "Live stream"
                }))
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.exception("WebSocket stream failed for account %s: %s", self.account_id, e)
                try:
                    await self.send(text_data=json.dumps({"type": "error", "message": str(e)}))
                    await self.close()
                except Exception:
                    pass
                return

            last_hash = None
            try:
                while self.is_running:
                    try:
                        frame = await self.page.screenshot(
                            type="jpeg",
                            quality=55,
                            scale="css",
                            animations="disabled",
                        )
                        frame_hash = hashlib.md5(frame).hexdigest()

                        now = asyncio.get_event_loop().time()
                        is_active = (now - self.last_interaction_time) < 3.0

                        if frame_hash != last_hash or self.force_frame:
                            self.force_frame = False
                            last_hash = frame_hash
                            await self.send(bytes_data=frame)

                        # Check cookies/session at most once every 2.0 seconds
                        if not self.logged_in_notified and (now - self.last_cookie_check_time) >= 2.0:
                            self.last_cookie_check_time = now
                            platform_uid = await _detect_logged_in_user_id(
                                self.account.platform, self.browser, self.page
                            )
                            if platform_uid:
                                self.logged_in_notified = True
                                self.account.fb_user_id = platform_uid
                                self.account.status = MessengerAccount.Status.ACTIVE
                                self.account.last_login_at = datetime.now(timezone.utc)
                                await self.account.asave()

                                # Flush and close browser immediately so profile is unlocked for tasks
                                await close_browser_session(self.browser, self.account.profile_dir)
                                self.browser = None
                                self.page = None
                                self.is_running = False

                                await self.send(text_data=json.dumps({
                                    "type": "login_success",
                                    "fb_user_id": platform_uid
                                }))
                                await self.close()
                                break

                        if is_active:
                            await asyncio.sleep(0.03)
                        else:
                            await asyncio.sleep(0.25)
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        await asyncio.sleep(0.3)
            finally:
                if self.browser is not None:
                    await close_browser_session(self.browser, self.account.profile_dir)
                    self.browser = None
                    self.page = None

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except Exception:
            return

        msg_type = data.get("type")
        self.last_interaction_time = asyncio.get_event_loop().time()
        self.force_frame = True

        if not self.browser_ready.is_set():
            try:
                await asyncio.wait_for(self.browser_ready.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                return

        if not self.page:
            return

        try:
            if msg_type == "paste":
                text = data.get("text", "")
                if text:
                    await self.page.keyboard.insert_text(text)

            elif msg_type == "mouse":
                action = data.get("action")
                x = data.get("x", 0)
                y = data.get("y", 0)
                btn = data.get("button", "left")

                if action == "move":
                    if self._move_in_flight:
                        return
                    self._move_in_flight = True
                    try:
                        await self.page.mouse.move(x, y)
                    finally:
                        self._move_in_flight = False
                elif action == "down":
                    await self.page.mouse.move(x, y)
                    await self.page.mouse.down(button=btn)
                elif action == "up":
                    await self.page.mouse.move(x, y)
                    await self.page.mouse.up(button=btn)
                elif action == "click":
                    await self.page.mouse.click(x, y, button=btn)
                elif action == "wheel":
                    dx = data.get("deltaX", 0)
                    dy = data.get("deltaY", 0)
                    await self.page.mouse.wheel(dx, dy)

            elif msg_type == "keyboard":
                action = data.get("action")
                key = data.get("key", "")
                if action == "down":
                    await self.page.keyboard.down(key)
                elif action == "up":
                    await self.page.keyboard.up(key)

            elif msg_type == "done":
                platform_uid = await _detect_logged_in_user_id(
                    self.account.platform, self.browser, self.page
                )
                self.account.fb_user_id = platform_uid or self.account.fb_user_id
                self.account.status = MessengerAccount.Status.ACTIVE
                self.account.last_login_at = datetime.now(timezone.utc)
                await self.account.asave()

                await close_browser_session(self.browser, self.account.profile_dir)
                self.browser = None
                self.page = None
                self.is_running = False

                await self.send(text_data=json.dumps({
                    "type": "login_success",
                    "fb_user_id": self.account.fb_user_id
                }))
                await self.close()
        except Exception as e:
            print(f"Error handling consumer message {msg_type}: {e}")

    async def disconnect(self, close_code):
        self.is_running = False
        if self.stream_task:
            self.stream_task.cancel()
            try:
                await self.stream_task
            except (asyncio.CancelledError, Exception):
                pass
        if self.browser is not None:
            pdir = self.account.profile_dir if self.account else None
            await close_browser_session(self.browser, pdir)
            self.browser = None
            self.page = None
