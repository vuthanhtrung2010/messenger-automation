import pytest
from camoufox.sync_api import Camoufox
from apps.messenger.services import extract_name_from_dom, insert_messenger_lexical_text

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
