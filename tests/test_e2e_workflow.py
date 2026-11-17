import pytest
import datetime
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage, DeliveryLog
from apps.scheduler.tasks import dispatch_scheduled_message
from unittest.mock import patch

@pytest.mark.django_db
@patch("apps.scheduler.tasks.send_thread_message")
def test_full_pipeline_flow(mock_send):
    mock_send.return_value = (True, None, None)
    
    # 1. Create admin user and authenticate
    user = User.objects.create_user(username="master_admin", password="password123")
    client = Client()
    logged_in = client.login(username="master_admin", password="password123")
    assert logged_in
    
    # 2. Add Messenger Account
    account = MessengerAccount.objects.create(
        owner=user,
        name="Primary Account",
        profile_dir="data/profiles/primary_acc",
        status=MessengerAccount.Status.ACTIVE,
        fb_user_id="100080858341662"
    )
    
    # 3. Add Thread
    thread = RecipientThread.objects.create(
        owner=user,
        account=account,
        thread_id="902973772639579",
        recipient_name="Hồ Bách",
        name_status=RecipientThread.NameStatus.FETCHED,
    )
    
    # 4. Create Schedule via POST
    response = client.post("/schedules/create/", {
        "account_id": str(account.id),
        "recipient_id": str(thread.id),
        "message_template": "Happy New Year {name}!",
        "schedule_type": ScheduledMessage.ScheduleType.ONCE,
        "run_date": "2027-01-01",
        "run_time": "00:00",
    })
    assert response.status_code == 302
    
    schedule = ScheduledMessage.objects.get(recipient=thread)
    assert schedule.message_template == "Happy New Year {name}!"
    assert schedule.schedule_type == ScheduledMessage.ScheduleType.ONCE
    
    # 5. Execute scheduled dispatch
    success = dispatch_scheduled_message(str(schedule.id))
    assert success is True
    
    # 6. Verify Delivery Log
    log = DeliveryLog.objects.filter(scheduled_message=schedule).first()
    assert log is not None
    assert log.status == DeliveryLog.Status.SUCCESS
    assert log.rendered_content == "Happy New Year Hồ Bách!"
    
    # Verify schedule state updated to COMPLETED for one-off
    schedule.refresh_from_db()
    assert schedule.status == ScheduledMessage.Status.COMPLETED
    assert schedule.next_run_at is None
    assert schedule.last_run_at is not None
