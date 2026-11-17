import pytest
from django.contrib.auth.models import User
from django.test import Client
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread

@pytest.mark.django_db
def test_dashboard_and_schedule_views_authenticated():
    user = User.objects.create_user(username="u1", password="pw")
    client = Client()
    client.force_login(user)
    
    # Dashboard view
    res = client.get("/")
    assert res.status_code == 200
    
    # Accounts view
    res = client.get("/accounts/")
    assert res.status_code == 200
    
    # Threads view
    res = client.get("/threads/")
    assert res.status_code == 200
    
    # Schedules view has recipient option with name
    account = MessengerAccount.objects.create(owner=user, name="Acc1", profile_dir="data/p")
    RecipientThread.objects.create(owner=user, account=account, thread_id="999", recipient_name="Alice Smith")
    res = client.get("/schedules/")
    assert res.status_code == 200
    assert "Alice Smith (Thread: 999)" in res.content.decode()
