import datetime
import pytest
from django.contrib.auth.models import User
from django.test import Client
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage

@pytest.mark.django_db
def test_login_invalid_credentials_shows_error_and_preserves_username():
    User.objects.create_user(username="validadmin", password="correctpassword")
    client = Client()

    res = client.post("/login/", {
        "username": "validadmin",
        "password": "wrongpassword",
    })
    assert res.status_code == 200
    html = res.content.decode()
    assert 'role="alert"' in html
    assert "Username or password is incorrect" in html
    assert 'value="validadmin"' in html


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


@pytest.mark.django_db
def test_schedules_page_has_quick_presets_and_annual_fields():
    user = User.objects.create_user(username="u2", password="pw")
    client = Client()
    client.force_login(user)

    res = client.get("/schedules/")
    assert res.status_code == 200
    html = res.content.decode()
    assert "Now" in html
    assert "+1 day" in html
    assert "+1 week" in html
    assert "+1 month" in html
    assert 'name="annual_month"' in html
    assert 'name="annual_day"' in html


@pytest.mark.django_db
def test_create_yearly_schedule_without_year_and_feb29():
    user = User.objects.create_user(username="u3", password="pw")
    account = MessengerAccount.objects.create(owner=user, name="AccAnnual", profile_dir="data/p3")
    thread = RecipientThread.objects.create(
        owner=user, account=account, thread_id="888", recipient_name="Birthday Friend"
    )
    client = Client()
    client.force_login(user)

    res = client.post("/schedules/create/", {
        "recipient_id": str(thread.id),
        "schedule_type": ScheduledMessage.ScheduleType.YEARLY,
        "annual_month": "2",
        "annual_day": "29",
        "run_time": "08:00",
        "message_template": "Happy Birthday {name}",
    })
    assert res.status_code == 302

    schedule = ScheduledMessage.objects.get(recipient=thread)
    assert schedule.run_date == datetime.date(2000, 2, 29)
    assert schedule.next_run_at is not None
    assert schedule.schedule_label == "Yearly (Feb 29)"
    assert schedule.schedule_summary == "Yearly (Feb 29) · 08:00"

    page = client.get("/schedules/")
    assert page.status_code == 200
    html = page.content.decode()
    table_html = html.split("<!-- Schedules Table -->")[1].split("</table>")[0]
    assert "Yearly (Feb 29) · 08:00" in table_html
    # Sentinel year 2000 must never leak into the rendered table
    assert "2000" not in table_html.replace(str(schedule.id), "")


@pytest.mark.django_db
def test_create_yearly_schedule_rejects_invalid_month_day():
    user = User.objects.create_user(username="u4", password="pw")
    account = MessengerAccount.objects.create(owner=user, name="AccBad", profile_dir="data/p4")
    thread = RecipientThread.objects.create(
        owner=user, account=account, thread_id="777", recipient_name="Bad Date"
    )
    client = Client()
    client.force_login(user)

    res = client.post("/schedules/create/", {
        "recipient_id": str(thread.id),
        "schedule_type": ScheduledMessage.ScheduleType.YEARLY,
        "annual_month": "2",
        "annual_day": "30",
        "run_time": "08:00",
        "message_template": "Should not save",
    }, follow=True)
    assert res.status_code == 200
    assert ScheduledMessage.objects.count() == 0
    assert "Select a valid month and day for an annual schedule." in res.content.decode()
