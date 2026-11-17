import pytest
from apps.messenger.services import extract_name_from_dom

def test_extract_name_from_dom():
    assert extract_name_from_dom("Write to Alice") == "Alice"
    assert extract_name_from_dom("Conversation titled Project Chat") == "Project Chat"
    assert extract_name_from_dom("Write to Hồ Bách") == "Hồ Bách"
    assert extract_name_from_dom("Conversation titled khtn sep26. 6-8pm Tue | Thu") == "khtn sep26. 6-8pm Tue | Thu"
    assert extract_name_from_dom("Message actions") is None
    assert extract_name_from_dom("") is None
    assert extract_name_from_dom(None) is None
