import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from apps.accounts.models import MessengerAccount
from config.asgi import application

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_websocket_stream_connect_and_paste_event():
    user = await User.objects.acreate_user(username="testadmin", password="password")
    account = await MessengerAccount.objects.acreate(
        owner=user,
        name="Stream Account",
        profile_dir="data/profiles/stream_test",
    )
    
    # Mock Camoufox browser context creation so unit test doesn't launch real browser
    mock_page = AsyncMock()
    mock_page.screenshot.return_value = b"\xff\xd8\xff\xe0test_jpeg_bytes"
    mock_context = AsyncMock()
    mock_context.cookies.return_value = [{"name": "c_user", "value": "12345678"}]
    mock_context.pages = [mock_page]
    
    with patch("apps.accounts.consumers.launch_browser_session") as mock_launch:
        mock_launch.return_value = (mock_context, mock_page)
        
        communicator = WebsocketCommunicator(
            application,
            f"/ws/accounts/{account.id}/stream/"
        )
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        assert connected
        
        # Send paste message
        await communicator.send_json_to({"type": "paste", "text": "pasted text from ctrl+v"})
        await asyncio.sleep(0.05)
        
        # Verify mock_page.keyboard.insert_text called
        mock_page.keyboard.insert_text.assert_called_with("pasted text from ctrl+v")
        
        # Send mouse click
        await communicator.send_json_to({"type": "mouse", "action": "click", "x": 100, "y": 200, "button": "left"})
        await asyncio.sleep(0.05)
        mock_page.mouse.click.assert_called_with(100, 200, button="left")
        
        await communicator.disconnect()
