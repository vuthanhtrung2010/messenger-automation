import pytest
import datetime
from unittest.mock import patch
from django.contrib.auth.models import User
from django.utils import timezone
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage, DeliveryLog
from apps.scheduler.tasks import dispatch_scheduled_message, check_and_dispatch_due_messages

@pytest.mark.django_db
@patch("apps.scheduler.tasks.send_thread_message")
def test_dispatch_scheduled_message(mock_send):
    mock_send.return_value = (True, None, None)
    user = User.objects.create_user(username="celery_test", password="password")
    account = MessengerAccount.objects.create(owner=user, name="Acc", profile_dir="data/profiles/acc")
    thread = RecipientThread.objects.create(owner=user, account=account, thread_id="123", recipient_name="Bob")
    schedule = ScheduledMessage.objects.create(
        owner=user,
        account=account,
        recipient=thread,
        message_template="Hi {name}",
        schedule_type=ScheduledMessage.ScheduleType.DAILY,
        run_time=datetime.time(8, 30),
        status=ScheduledMessage.Status.ACTIVE,
        next_run_at=timezone.now(),
    )
    
    dispatch_scheduled_message(str(schedule.id))
    
    log = DeliveryLog.objects.filter(scheduled_message=schedule).first()
    assert log is not None
    assert log.status == DeliveryLog.Status.SUCCESS
    assert log.rendered_content == "Hi Bob"
    
    schedule.refresh_from_db()
    assert schedule.last_run_at is not None
    assert schedule.next_run_at > schedule.last_run_at


@pytest.mark.django_db
@patch("apps.scheduler.tasks.send_thread_message")
def test_dispatch_once_failed_marks_paused_not_completed(mock_send):
    mock_send.return_value = (False, "Simulated timeout", "/tmp/err.png")
    user = User.objects.create_user(username="celery_fail_test", password="password")
    account = MessengerAccount.objects.create(owner=user, name="Acc", profile_dir="data/profiles/acc")
    thread = RecipientThread.objects.create(owner=user, account=account, thread_id="123", recipient_name="Bob")
    schedule = ScheduledMessage.objects.create(
        owner=user,
        account=account,
        recipient=thread,
        message_template="Hi {name}",
        schedule_type=ScheduledMessage.ScheduleType.ONCE,
        run_date=datetime.date(2026, 11, 18),
        run_time=datetime.time(8, 30),
        status=ScheduledMessage.Status.ACTIVE,
        next_run_at=timezone.now(),
    )

    result = dispatch_scheduled_message(str(schedule.id))
    assert result is False

    log = DeliveryLog.objects.filter(scheduled_message=schedule).first()
    assert log is not None
    assert log.status == DeliveryLog.Status.FAILED
    assert log.error_message == "Simulated timeout"
    assert log.screenshot_path == "/tmp/err.png"

    schedule.refresh_from_db()
    assert schedule.status == ScheduledMessage.Status.PAUSED
    assert schedule.next_run_at is None


@pytest.mark.django_db
@patch("apps.scheduler.tasks.send_thread_message")
def test_duplicate_beat_dispatch_is_ignored_via_expected_run_at(mock_send):
    mock_send.return_value = (True, None, None)
    user = User.objects.create_user(username="celery_dup_test", password="password")
    account = MessengerAccount.objects.create(owner=user, name="Acc", profile_dir="data/profiles/acc_dup")
    thread = RecipientThread.objects.create(owner=user, account=account, thread_id="456", recipient_name="Alice")
    due_at = timezone.now()
    schedule = ScheduledMessage.objects.create(
        owner=user,
        account=account,
        recipient=thread,
        message_template="Hi {name}",
        schedule_type=ScheduledMessage.ScheduleType.DAILY,
        run_time=datetime.time(8, 30),
        status=ScheduledMessage.Status.ACTIVE,
        next_run_at=due_at,
    )

    first = dispatch_scheduled_message(str(schedule.id), expected_run_at=due_at.isoformat())
    second = dispatch_scheduled_message(str(schedule.id), expected_run_at=due_at.isoformat())

    assert first is True
    assert second is False
    assert mock_send.call_count == 1
    assert DeliveryLog.objects.count() == 1
