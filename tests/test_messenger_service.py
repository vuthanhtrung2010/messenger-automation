import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pytest
from camoufox.sync_api import Camoufox
from apps.messenger.services import extract_name_from_dom, insert_messenger_lexical_text
from apps.messenger.browser_pool import AccountBrowserPool

def test_extract_name_from_dom():
    assert extract_name_from_dom("Write to Alice") == "Alice"
    assert extract_name_from_dom("Conversation titled Project Chat") == "Project Chat"
    assert extract_name_from_dom("Messages in conversation with Vũ Thành Trung") == "Vũ Thành Trung"
    assert extract_name_from_dom("Conversation with Vũ Thành Trung") == "Vũ Thành Trung"
    assert extract_name_from_dom("Write to ") is None
    assert extract_name_from_dom("Write to Hồ Bách") == "Hồ Bách"
    assert extract_name_from_dom("Conversation titled khtn sep26. 6-8pm Tue | Thu") == "khtn sep26. 6-8pm Tue | Thu"
    assert extract_name_from_dom("Message actions") is None
    assert extract_name_from_dom("") is None
    assert extract_name_from_dom(None) is None


def test_insert_messenger_lexical_text_prevents_doubling_and_clears_stale_draft():
    """
    Mimics Meta Lexical's handling of Firefox Juggler composition events (which double text
    on keyboard.insert_text) and verifies insert_messenger_lexical_text clears any stale
    draft and inserts the message exactly once.
    """
    with Camoufox(headless=True, humanize=False, i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content("""
        <div id="tb" role="textbox" contenteditable="true">stale</div>
        <script>
          const tb = document.getElementById("tb");
          let composing = false;
          tb.addEventListener("compositionstart", () => { composing = true; });
          tb.addEventListener("compositionend", () => { composing = false; });
          tb.addEventListener("input", (e) => {
            if (!composing && e.inputType === "insertCompositionText" && e.data) {
              tb.textContent += e.data;
            }
          });
        </script>
        """)
        textbox = page.locator('div[role="textbox"]').first
        textbox.click()
        sample = "ok — tiếng Việt 🎂\ndòng 2"
        insert_messenger_lexical_text(page, textbox, sample)
        assert textbox.inner_text().replace("\r\n", "\n").strip() == sample


def _make_fake_browser_factory(nav_delay: float = 0.0):
    stats = {
        "browser_launches": 0,
        "pages_created": 0,
        "goto_calls": [],
        "sent_messages": [],
    }

    class FakeLocator:
        def __init__(self, page, selector: str):
            self._page = page
            self._selector = selector

        @property
        def first(self):
            return self

        @property
        def last(self):
            return self

        async def count(self):
            if self._selector == 'div[role="textbox"]':
                return 1
            return 0

        async def click(self, timeout=None, force=False):
            return None

        async def evaluate(self, script, arg=None):
            if self._selector == 'div[role="textbox"]' and arg is not None:
                self._page._text = arg

        async def inner_text(self):
            return self._page._text

    class FakeKeyboard:
        def __init__(self, page):
            self._page = page

        async def press(self, key: str):
            if key == "Backspace":
                self._page._text = ""
            elif key == "Enter":
                stats["sent_messages"].append((self._page.url, self._page._text))
                self._page._text = ""

    class FakePage:
        def __init__(self, is_anchor: bool = False):
            self.url = "about:blank"
            self._text = ""
            self._closed = False
            self.keyboard = FakeKeyboard(self)
            if not is_anchor:
                stats["pages_created"] += 1

        def is_closed(self):
            return self._closed

        def locator(self, selector: str):
            return FakeLocator(self, selector)

        async def evaluate(self, expr: str):
            return 1

        async def goto(self, url: str, wait_until=None, timeout=None):
            if nav_delay > 0:
                await asyncio.sleep(nav_delay)
            self.url = url
            stats["goto_calls"].append(url)

        async def screenshot(self, path: str):
            return b""

        async def close(self):
            self._closed = True

    class FakeBrowser:
        def __init__(self):
            self._anchor = FakePage(is_anchor=True)
            self.pages = [self._anchor]

        async def new_page(self):
            p = FakePage(is_anchor=False)
            self.pages.append(p)
            return p

        async def close(self):
            for p in list(self.pages):
                await p.close()

    async def factory(profile_dir: str):
        stats["browser_launches"] += 1
        return FakeBrowser()

    return factory, stats


def test_browser_pool_shares_single_browser_and_runs_multiple_tabs_in_parallel(tmp_path):
    factory, stats = _make_fake_browser_factory(nav_delay=0.25)
    pool = AccountBrowserPool(idle_timeout=60.0, browser_factory=factory)
    profile_dir = str(tmp_path / "profile")

    try:
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = [
                ex.submit(pool.send_message, profile_dir, f"thread_{i}", f"msg-{i}")
                for i in range(3)
            ]
            results = [f.result(timeout=10) for f in futures]
        elapsed = time.monotonic() - start

        assert results == [(True, None, None)] * 3
        assert stats["browser_launches"] == 1
        assert stats["pages_created"] == 3
        # Note: includes fixed asyncio sleep settles (~0.68s per tab running in parallel), still well under 3x sequential
        assert len(stats["sent_messages"]) == 3
        assert elapsed < 1.25
    finally:
        pool.close_all()


def test_browser_pool_reuses_warm_cached_thread_tab(tmp_path):
    factory, stats = _make_fake_browser_factory(nav_delay=0.0)
    pool = AccountBrowserPool(idle_timeout=60.0, browser_factory=factory)
    profile_dir = str(tmp_path / "profile")

    try:
        res1 = pool.send_message(profile_dir, "thread_A", "first")
        res2 = pool.send_message(profile_dir, "thread_A", "second")

        assert res1 == (True, None, None)
        assert res2 == (True, None, None)
        assert stats["browser_launches"] == 1
        assert stats["pages_created"] == 1
        assert len(stats["goto_calls"]) == 1
        assert stats["sent_messages"] == [
            ("https://www.facebook.com/messages/t/thread_A", "first"),
            ("https://www.facebook.com/messages/t/thread_A", "second"),
        ]
    finally:
        pool.close_all()
