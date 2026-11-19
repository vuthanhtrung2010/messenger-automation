import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from apps.accounts.consumers import _detect_logged_in_user_id
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.messenger.views import clean_thread_id
from apps.scheduler.models import DeliveryLog, ScheduledMessage
from apps.scheduler.tasks import dispatch_scheduled_message, refresh_thread_name_task, sync_zalo_contacts_task, check_zalo_session_task


@pytest.mark.django_db
def test_zalo_account_creation_and_default_platform():
    user = User.objects.create_user(username="zalo_owner", password="pw")
    fb_acc = MessengerAccount.objects.create(owner=user, name="FB", profile_dir="/tmp/fb")
    assert fb_acc.platform == MessengerAccount.Platform.MESSENGER

    client = Client()
    client.force_login(user)
    resp = client.post("/accounts/add/", {"name": "My Zalo", "platform": "ZALO"})
    assert resp.status_code == 302
    zalo_acc = MessengerAccount.objects.get(name="My Zalo")
    assert zalo_acc.platform == MessengerAccount.Platform.ZALO
    assert resp.url == f"/accounts/{zalo_acc.id}/stream/"


def test_clean_thread_id_zalo():
    assert clean_thread_id("1009813263025811631", platform=MessengerAccount.Platform.ZALO) == "1009813263025811631"
    assert clean_thread_id("g1144235839147594573", platform=MessengerAccount.Platform.ZALO) == "g1144235839147594573"
    assert clean_thread_id("friend-item-6552977504498259804", platform=MessengerAccount.Platform.ZALO) == "6552977504498259804"


@pytest.mark.django_db
def test_account_check_session_view_active_and_expired():
    user = User.objects.create_user(username="zalo_checker", password="pw")
    acc = MessengerAccount.objects.create(
        owner=user,
        platform=MessengerAccount.Platform.ZALO,
        name="Zalo 1",
        profile_dir="/tmp/zalo1",
        status=MessengerAccount.Status.PENDING_LOGIN,
    )
    client = Client()
    client.force_login(user)

    with patch("apps.accounts.views.check_zalo_session_task.delay") as mock_delay:
        resp = client.post(f"/accounts/{acc.id}/check-session/")
        assert resp.status_code == 302
        mock_delay.assert_called_once_with(str(acc.id))

    with patch("apps.scheduler.tasks.check_zalo_session", return_value=(True, "472209375094224417")):
        assert check_zalo_session_task(str(acc.id)) is True

    acc.refresh_from_db()
    assert acc.status == MessengerAccount.Status.ACTIVE
    assert acc.fb_user_id == "472209375094224417"

    with patch("apps.scheduler.tasks.check_zalo_session", return_value=(False, None)):
        assert check_zalo_session_task(str(acc.id)) is False

    acc.refresh_from_db()
    assert acc.status == MessengerAccount.Status.EXPIRED


@pytest.mark.django_db
def test_account_sync_contacts_view():
    user = User.objects.create_user(username="zalo_syncer", password="pw")
    acc = MessengerAccount.objects.create(
        owner=user,
        platform=MessengerAccount.Platform.ZALO,
        name="Zalo Sync",
        profile_dir="/tmp/zalo_sync",
        status=MessengerAccount.Status.ACTIVE,
    )
    client = Client()
    client.force_login(user)

    with patch("apps.accounts.views.sync_zalo_contacts_task.delay") as mock_delay:
        resp = client.post(f"/accounts/{acc.id}/sync-contacts/")
        assert resp.status_code == 302
        assert resp.url == "/threads/"
        mock_delay.assert_called_once_with(str(acc.id))

    sample_contacts = [
        {"thread_id": "1009813263025811631", "name": "Võ Bình Minh"},
        {"thread_id": "1406981063191078954", "name": "Tuấn"},
    ]
    with patch("apps.scheduler.tasks.list_zalo_contacts", return_value=sample_contacts):
        result = sync_zalo_contacts_task(str(acc.id))
        assert result == {"created": 2, "updated": 0}

    threads = RecipientThread.objects.filter(account=acc)
    assert threads.count() == 2
    t1 = threads.get(thread_id="1009813263025811631")
    assert t1.recipient_name == "Võ Bình Minh"
    assert t1.name_status == RecipientThread.NameStatus.FETCHED


@pytest.mark.django_db
def test_zalo_dispatch_and_refresh_tasks():
    user = User.objects.create_user(username="zalo_worker", password="pw")
    acc = MessengerAccount.objects.create(
        owner=user,
        platform=MessengerAccount.Platform.ZALO,
        name="Zalo Worker",
        profile_dir="/tmp/zalo_worker",
        status=MessengerAccount.Status.ACTIVE,
    )
    thread = RecipientThread.objects.create(
        owner=user,
        account=acc,
        thread_id="6552977504498259804",
        recipient_name="My Documents",
        name_status=RecipientThread.NameStatus.PENDING,
    )

    with patch("apps.scheduler.tasks.fetch_zalo_recipient_name", return_value="My Documents"):
        res = refresh_thread_name_task(str(thread.id))
        assert res == "My Documents"

    thread.refresh_from_db()
    assert thread.name_status == RecipientThread.NameStatus.FETCHED

    sched = ScheduledMessage.objects.create(
        owner=user,
        account=acc,
        recipient=thread,
        message_template="Hello {name}!",
        schedule_type=ScheduledMessage.ScheduleType.ONCE,
        run_time=timezone.now().time(),
        next_run_at=timezone.now() - timedelta(minutes=1),
    )

    with patch("apps.scheduler.tasks.send_zalo_message", return_value=(True, "", "")) as mock_send:
        ok = dispatch_scheduled_message(str(sched.id))
        assert ok is True
        mock_send.assert_called_once_with(
            profile_dir=acc.profile_dir,
            thread_id="6552977504498259804",
            message="Hello My Documents!",
            recipient_name="My Documents",
        )

    assert DeliveryLog.objects.filter(scheduled_message=sched, status=DeliveryLog.Status.SUCCESS).exists()

    # Session expired error marks account EXPIRED
    sched2 = ScheduledMessage.objects.create(
        owner=user,
        account=acc,
        recipient=thread,
        message_template="Hi again",
        schedule_type=ScheduledMessage.ScheduleType.ONCE,
        run_time=timezone.now().time(),
        next_run_at=timezone.now() - timedelta(minutes=1),
    )
    with patch(
        "apps.scheduler.tasks.send_zalo_message",
        return_value=(False, "Zalo session expired or logged out. Please re-login.", "/tmp/err.png"),
    ):
        ok2 = dispatch_scheduled_message(str(sched2.id))
        assert ok2 is False

    acc.refresh_from_db()
    assert acc.status == MessengerAccount.Status.EXPIRED


def test_detect_logged_in_user_id_zalo():
    browser = MagicMock()
    page = MagicMock()

    # Case 1: zpw_sek present + #contact-search-input visible -> returns UID
    browser.cookies = AsyncMock(return_value=[{"name": "zpw_sek", "domain": ".chat.zalo.me", "value": "abc"}])
    loc = MagicMock()
    loc.count = AsyncMock(return_value=1)
    page.locator.return_value = loc
    page.evaluate = AsyncMock(return_value="472209375094224417")

    uid = asyncio.run(_detect_logged_in_user_id(MessengerAccount.Platform.ZALO, browser, page))
    assert uid == "472209375094224417"

    # Case 2: zpw_sek missing -> None
    browser.cookies = AsyncMock(return_value=[])
    uid2 = asyncio.run(_detect_logged_in_user_id(MessengerAccount.Platform.ZALO, browser, page))
    assert uid2 is None


@pytest.mark.django_db
def test_search_and_platform_filtering_on_threads_schedules_and_logs():
    user = User.objects.create_user(username="filter_user", password="pw")
    fb_acc = MessengerAccount.objects.create(
        owner=user, platform=MessengerAccount.Platform.MESSENGER, name="FB Personal", profile_dir="/tmp/fb"
    )
    zalo_acc = MessengerAccount.objects.create(
        owner=user, platform=MessengerAccount.Platform.ZALO, name="Zalo Personal", profile_dir="/tmp/zl"
    )
    fb_thread = RecipientThread.objects.create(
        owner=user, account=fb_acc, thread_id="111222", recipient_name="Alice FB", name_status=RecipientThread.NameStatus.FETCHED
    )
    zalo_thread = RecipientThread.objects.create(
        owner=user, account=zalo_acc, thread_id="333444", recipient_name="Bob Zalo", name_status=RecipientThread.NameStatus.FETCHED
    )

    fb_sched = ScheduledMessage.objects.create(
        owner=user, account=fb_acc, recipient=fb_thread, message_template="Hi Alice",
        schedule_type=ScheduledMessage.ScheduleType.DAILY, run_time=timezone.now().time(),
    )
    zalo_sched = ScheduledMessage.objects.create(
        owner=user, account=zalo_acc, recipient=zalo_thread, message_template="Chao Bob",
        schedule_type=ScheduledMessage.ScheduleType.DAILY, run_time=timezone.now().time(),
    )

    DeliveryLog.objects.create(
        scheduled_message=fb_sched, recipient_thread=fb_thread, rendered_content="Hi Alice", status=DeliveryLog.Status.SUCCESS
    )
    DeliveryLog.objects.create(
        scheduled_message=zalo_sched, recipient_thread=zalo_thread, rendered_content="Chao Bob", status=DeliveryLog.Status.SUCCESS
    )

    client = Client()
    client.force_login(user)

    # /threads/ platform + search
    r1 = client.get("/threads/?platform=ZALO")
    assert r1.status_code == 200
    assert list(r1.context["threads"]) == [zalo_thread]

    r2 = client.get("/threads/?q=Alice")
    assert r2.status_code == 200
    assert list(r2.context["threads"]) == [fb_thread]

    # /schedules/ platform + search
    r3 = client.get("/schedules/?platform=MESSENGER")
    assert r3.status_code == 200
    assert list(r3.context["schedules"]) == [fb_sched]

    r4 = client.get("/schedules/?q=Chao+Bob")
    assert r4.status_code == 200
    assert list(r4.context["schedules"]) == [zalo_sched]

    # /logs/ platform + search
    r5 = client.get("/logs/?platform=ZALO")
    assert r5.status_code == 200
    assert r5.context["logs"].count() == 1
    assert r5.context["logs"].first().recipient_thread == zalo_thread

    r6 = client.get("/logs/?q=Alice")
    assert r6.status_code == 200
    assert r6.context["logs"].count() == 1
    assert r6.context["logs"].first().recipient_thread == fb_thread
