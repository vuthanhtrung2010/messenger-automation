import re
import calendar
import datetime
from zoneinfo import ZoneInfo
from apps.scheduler.models import ScheduledMessage

def render_message_template(template: str, recipient_name: str | None) -> str:
    """
    Renders message template with recipient name or cleans up placeholder gracefully.
    """
    if not template:
        return ""
    
    name = (recipient_name or "").strip()
    if name:
        return template.replace("{name}", name)
    
    # If no name provided, remove " {name}" or "{name}" cleanly
    text = re.sub(r"\s*\{name\}", "", template)
    return text.strip()


def calculate_next_run(
    schedule_type: str,
    run_time: datetime.time,
    run_date: datetime.date | None = None,
    day_of_month: int | None = None,
    tz_name: str = "Asia/Bangkok",
    base_time: datetime.datetime | None = None,
) -> datetime.datetime | None:
    """
    Calculates the next execution datetime in UTC based on recurrence rule and timezone.
    """
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Bangkok")

    if base_time:
        now = base_time.astimezone(tz)
    else:
        now = datetime.datetime.now(tz)

    if schedule_type == ScheduledMessage.ScheduleType.ONCE:
        if not run_date:
            return None
        target = datetime.datetime.combine(run_date, run_time, tzinfo=tz)
        return target.astimezone(datetime.timezone.utc)

    elif schedule_type == ScheduledMessage.ScheduleType.DAILY:
        today_target = datetime.datetime.combine(now.date(), run_time, tzinfo=tz)
        if today_target > now:
            return today_target.astimezone(datetime.timezone.utc)
        tomorrow_target = today_target + datetime.timedelta(days=1)
        return tomorrow_target.astimezone(datetime.timezone.utc)

    elif schedule_type == ScheduledMessage.ScheduleType.MONTHLY:
        day = day_of_month or (run_date.day if run_date else 1)
        days_in_cur_month = calendar.monthrange(now.year, now.month)[1]
        clamped_cur_day = min(day, days_in_cur_month)
        cur_month_target = datetime.datetime(
            now.year, now.month, clamped_cur_day,
            run_time.hour, run_time.minute, run_time.second,
            tzinfo=tz
        )
        if cur_month_target > now:
            return cur_month_target.astimezone(datetime.timezone.utc)

        # Move to next month
        if now.month == 12:
            next_year = now.year + 1
            next_month = 1
        else:
            next_year = now.year
            next_month = now.month + 1

        days_in_next_month = calendar.monthrange(next_year, next_month)[1]
        clamped_next_day = min(day, days_in_next_month)
        next_month_target = datetime.datetime(
            next_year, next_month, clamped_next_day,
            run_time.hour, run_time.minute, run_time.second,
            tzinfo=tz
        )
        return next_month_target.astimezone(datetime.timezone.utc)

    elif schedule_type == ScheduledMessage.ScheduleType.YEARLY:
        target_month = run_date.month if run_date else now.month
        target_day = run_date.day if run_date else now.day
        
        # Handle leap-year Feb 29 for non-leap years
        days_in_target_month = calendar.monthrange(now.year, target_month)[1]
        clamped_day = min(target_day, days_in_target_month)
        
        this_year_target = datetime.datetime(
            now.year, target_month, clamped_day,
            run_time.hour, run_time.minute, run_time.second,
            tzinfo=tz
        )
        if this_year_target > now:
            return this_year_target.astimezone(datetime.timezone.utc)

        next_year = now.year + 1
        days_in_next_year_month = calendar.monthrange(next_year, target_month)[1]
        clamped_next_day = min(target_day, days_in_next_year_month)
        next_year_target = datetime.datetime(
            next_year, target_month, clamped_next_day,
            run_time.hour, run_time.minute, run_time.second,
            tzinfo=tz
        )
        return next_year_target.astimezone(datetime.timezone.utc)

    return None
