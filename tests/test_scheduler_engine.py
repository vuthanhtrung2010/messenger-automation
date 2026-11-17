import datetime
from zoneinfo import ZoneInfo
import pytest
from apps.scheduler.services import calculate_next_run, render_message_template
from apps.scheduler.models import ScheduledMessage

def test_render_message_template():
    assert render_message_template("Happy Birthday {name}!", "Alice") == "Happy Birthday Alice!"
    assert render_message_template("Happy New Year {name}!", None) == "Happy New Year!"
    assert render_message_template("Hello {name}, wishing you well", "") == "Hello, wishing you well"
    assert render_message_template("Direct message without tags", "Bob") == "Direct message without tags"

def test_calculate_once_future():
    tz = ZoneInfo("Asia/Bangkok")
    base_time = datetime.datetime(2026, 11, 17, 8, 0, tzinfo=tz)
    target_date = datetime.date(2027, 1, 1)
    target_time = datetime.time(0, 0)
    next_run = calculate_next_run(
        schedule_type=ScheduledMessage.ScheduleType.ONCE,
        run_time=target_time,
        run_date=target_date,
        tz_name="Asia/Bangkok",
        base_time=base_time,
    )
    expected_local = datetime.datetime(2027, 1, 1, 0, 0, tzinfo=tz)
    assert next_run == expected_local.astimezone(datetime.timezone.utc)

def test_calculate_daily_next_run():
    tz = ZoneInfo("Asia/Bangkok")
    base_time = datetime.datetime(2026, 11, 17, 8, 0, tzinfo=tz) # 8:00 AM
    target_time = datetime.time(9, 0) # 9:00 AM same day
    next_run = calculate_next_run(
        schedule_type=ScheduledMessage.ScheduleType.DAILY,
        run_time=target_time,
        tz_name="Asia/Bangkok",
        base_time=base_time,
    )
    expected_local = datetime.datetime(2026, 11, 17, 9, 0, tzinfo=tz)
    assert next_run == expected_local.astimezone(datetime.timezone.utc)

    # If run_time has passed today, schedule for tomorrow
    target_time_passed = datetime.time(7, 0) # 7:00 AM (already passed)
    next_run_tomorrow = calculate_next_run(
        schedule_type=ScheduledMessage.ScheduleType.DAILY,
        run_time=target_time_passed,
        tz_name="Asia/Bangkok",
        base_time=base_time,
    )
    expected_tomorrow = datetime.datetime(2026, 11, 18, 7, 0, tzinfo=tz)
    assert next_run_tomorrow == expected_tomorrow.astimezone(datetime.timezone.utc)

def test_calculate_monthly_month_end_clamping():
    tz = ZoneInfo("Asia/Bangkok")
    # Base: Jan 31 at 10:00 AM
    base_time = datetime.datetime(2026, 1, 31, 10, 0, tzinfo=tz)
    # Day 31 of next month (Feb 2026 is non-leap, 28 days) should clamp to Feb 28
    next_run = calculate_next_run(
        schedule_type=ScheduledMessage.ScheduleType.MONTHLY,
        run_time=datetime.time(10, 0),
        day_of_month=31,
        tz_name="Asia/Bangkok",
        base_time=base_time,
    )
    expected_local = datetime.datetime(2026, 2, 28, 10, 0, tzinfo=tz)
    assert next_run == expected_local.astimezone(datetime.timezone.utc)

def test_calculate_yearly_next_run():
    tz = ZoneInfo("Asia/Bangkok")
    # Base: 2026-11-17
    base_time = datetime.datetime(2026, 11, 17, 8, 0, tzinfo=tz)
    # Event: Nov 20 (upcoming this year)
    next_run = calculate_next_run(
        schedule_type=ScheduledMessage.ScheduleType.YEARLY,
        run_time=datetime.time(12, 0),
        run_date=datetime.date(2020, 11, 20), # date from past year
        tz_name="Asia/Bangkok",
        base_time=base_time,
    )
    expected_local = datetime.datetime(2026, 11, 20, 12, 0, tzinfo=tz)
    assert next_run == expected_local.astimezone(datetime.timezone.utc)
