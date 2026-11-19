import datetime
from unittest.mock import patch
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
    assert '<script data-cfasync="false" src="https://cdn.tailwindcss.com"></script>' in html


@pytest.mark.django_db
def test_login_csrf_passes_behind_https_proxy():
    User.objects.create_user(username="proxyadmin", password="correctpassword")
    client = Client(enforce_csrf_checks=True)

    get_res = client.get(
        "/login/",
        HTTP_HOST="message-automation.trunghsgs.edu.vn",
        HTTP_X_FORWARDED_PROTO="https",
    )
    assert get_res.status_code == 200
    csrf_token = client.cookies["csrftoken"].value

    post_res = client.post(
        "/login/",
        {
            "username": "proxyadmin",
            "password": "correctpassword",
            "csrfmiddlewaretoken": csrf_token,
        },
        HTTP_HOST="message-automation.trunghsgs.edu.vn",
        HTTP_ORIGIN="https://message-automation.trunghsgs.edu.vn",
        HTTP_X_FORWARDED_PROTO="https",
    )
    assert post_res.status_code == 302


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


@pytest.mark.django_db
def test_create_once_schedule_rejects_past_date_and_preserves_draft():
    user = User.objects.create_user(username="u5", password="pw")
    account = MessengerAccount.objects.create(owner=user, name="AccPast", profile_dir="data/p5")
    thread = RecipientThread.objects.create(
        owner=user, account=account, thread_id="666", recipient_name="Past Date Test"
    )
    client = Client()
    client.force_login(user)

    res = client.post("/schedules/create/", {
        "recipient_id": str(thread.id),
        "schedule_type": ScheduledMessage.ScheduleType.ONCE,
        "run_date": "2020-01-01",
        "run_time": "12:00",
        "message_template": "Important future note",
    }, follow=True)
    assert res.status_code == 200
    html = res.content.decode()
    assert ScheduledMessage.objects.count() == 0
    assert "Target date for a one-off schedule cannot be earlier than today." in html
    assert "Important future note" in html
    assert 'min="' in html


@pytest.mark.django_db
@patch("apps.scheduler.views.timezone.now")
def test_create_once_schedule_rejects_past_time_today_and_allows_current_or_future_time(mock_now):
    # 2026-11-18 14:30:20+07:00 == 07:30:20 UTC
    mock_now.return_value = datetime.datetime(2026, 11, 18, 7, 30, 20, tzinfo=datetime.timezone.utc)
    user = User.objects.create_user(username="u6", password="pw")
    account = MessengerAccount.objects.create(owner=user, name="AccTime", profile_dir="data/p6")
    thread = RecipientThread.objects.create(
        owner=user, account=account, thread_id="555", recipient_name="Time Guard Test"
    )
    client = Client()
    client.force_login(user)

    bad_res = client.post("/schedules/create/", {
        "recipient_id": str(thread.id),
        "schedule_type": ScheduledMessage.ScheduleType.ONCE,
        "run_date": "2026-11-18",
        "run_time": "08:00",
        "message_template": "Earlier today",
    }, follow=True)
    assert bad_res.status_code == 200
    assert ScheduledMessage.objects.count() == 0
    assert "Scheduled time for a one-off schedule cannot be earlier than the current time." in bad_res.content.decode()

    ok_res = client.post("/schedules/create/", {
        "recipient_id": str(thread.id),
        "schedule_type": ScheduledMessage.ScheduleType.ONCE,
        "run_date": "2026-11-18",
        "run_time": "14:35",
        "message_template": "Five minutes ahead",
    })
    assert ok_res.status_code == 302
    assert ScheduledMessage.objects.count() == 1
