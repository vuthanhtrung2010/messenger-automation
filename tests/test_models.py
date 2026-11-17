import pytest
from django.contrib.auth.models import User
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage, DeliveryLog
import datetime

@pytest.mark.django_db
def test_create_models_hierarchy():
    user = User.objects.create_user(username="admin1", password="password")
    account = MessengerAccount.objects.create(
        owner=user,
        name="Personal Account",
        profile_dir="data/profiles/test_acc",
        status=MessengerAccount.Status.ACTIVE,
    )
    thread = RecipientThread.objects.create(
        owner=user,
        account=account,
        thread_id="902973772639579",
        recipient_name="John Doe",
        name_status=RecipientThread.NameStatus.FETCHED,
    )
    schedule = ScheduledMessage.objects.create(
        owner=user,
        account=account,
        recipient=thread,
        message_template="Hello {name}!",
        schedule_type=ScheduledMessage.ScheduleType.DAILY,
        run_time=datetime.time(8, 30),
    )
    log = DeliveryLog.objects.create(
        scheduled_message=schedule,
        rendered_content="Hello John Doe!",
        status=DeliveryLog.Status.SUCCESS,
    )
    assert account.owner == user
    assert thread.account == account
    assert schedule.recipient == thread
    assert log.scheduled_message == schedule
    assert thread.display_name == "John Doe (Thread: 902973772639579)"
