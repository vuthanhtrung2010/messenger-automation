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
