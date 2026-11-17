import os
import json
import asyncio
import hashlib
from datetime import datetime, timezone
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import User
from apps.accounts.models import MessengerAccount

async def launch_browser_session(profile_dir: str):
    """
    Launches an async Camoufox browser context with persistent profile.
    """
    from camoufox.async_api import AsyncCamoufox
    
    os.makedirs(profile_dir, exist_ok=True)
    camoufox = AsyncCamoufox(
        headless=True,
        persistent_context=True,
        user_data_dir=profile_dir,
        humanize=True,
        i_know_what_im_doing=True,
        viewport={"width": 1280, "height": 800},
    )
    browser = await camoufox.__aenter__()
    page = browser.pages[0] if browser.pages else await browser.new_page()
    try:
        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
    except Exception as e:
        print(f"Error loading initial login page: {e}")
    return browser, page


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
        self.last_interaction_time = 0

    async def connect(self):
        self.account_id = self.scope["url_route"]["kwargs"]["account_id"]
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

        try:
            self.browser, self.page = await launch_browser_session(self.account.profile_dir)
            self.stream_task = asyncio.create_task(self.stream_loop())
        except Exception as e:
            await self.send(text_data=json.dumps({"type": "error", "message": str(e)}))
            await self.close()

    async def stream_loop(self):
        last_hash = None
        while self.is_running:
            try:
                # Capture frame
                frame = await self.page.screenshot(type="jpeg", quality=60)
                frame_hash = hashlib.md5(frame).hexdigest()

                now = asyncio.get_event_loop().time()
                is_active = (now - self.last_interaction_time) < 2.0

                if frame_hash != last_hash or self.force_frame:
                    self.force_frame = False
                    last_hash = frame_hash
                    await self.send(bytes_data=frame)

                # Cookie inspection for auto login detection
                if not self.logged_in_notified:
                    cookies = await self.browser.cookies()
                    fb_cookies = {
                        c["name"]: c["value"]
                        for c in cookies
                        if "facebook.com" in c.get("domain", "")
                    }
                    if "c_user" in fb_cookies:
                        self.logged_in_notified = True
                        fb_id = fb_cookies["c_user"]
                        self.account.fb_user_id = fb_id
                        self.account.status = MessengerAccount.Status.ACTIVE
                        self.account.last_login_at = datetime.now(timezone.utc)
                        await self.account.asave()
                        await self.send(text_data=json.dumps({
                            "type": "login_success",
                            "fb_user_id": fb_id
                        }))

                # Sleep duration based on interaction state
                if is_active:
                    await asyncio.sleep(0.06)  # ~15 FPS during active interaction
                else:
                    await asyncio.sleep(0.5)   # 2 FPS when idle to check mutations/cookie
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(1.0)

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
                    await self.page.mouse.move(x, y)
                elif action == "down":
                    await self.page.mouse.down(button=btn)
                elif action == "up":
                    await self.page.mouse.up(button=btn)
                elif action == "click":
                    await self.page.mouse.click(x, y, button=btn)

            elif msg_type == "keyboard":
                action = data.get("action")
                key = data.get("key", "")
                if action == "down":
                    await self.page.keyboard.down(key)
                elif action == "up":
                    await self.page.keyboard.up(key)

            elif msg_type == "done":
                # Manual finish trigger
                cookies = await self.browser.cookies()
                fb_cookies = {
                    c["name"]: c["value"]
                    for c in cookies
                    if "facebook.com" in c.get("domain", "")
                }
                fb_id = fb_cookies.get("c_user", "")
                self.account.fb_user_id = fb_id or self.account.fb_user_id
                self.account.status = MessengerAccount.Status.ACTIVE
                self.account.last_login_at = datetime.now(timezone.utc)
                await self.account.asave()
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
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
