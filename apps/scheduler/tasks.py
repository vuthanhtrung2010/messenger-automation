import logging
from celery import shared_task
from django.utils import timezone
from apps.scheduler.models import ScheduledMessage, DeliveryLog
from apps.messenger.models import RecipientThread
from apps.scheduler.services import render_message_template, calculate_next_run
from apps.messenger.services import send_thread_message, fetch_thread_recipient_name

logger = logging.getLogger(__name__)

@shared_task
def dispatch_scheduled_message(schedule_id: str):
    """
    Executes sending of a single scheduled message and updates its schedule state.
    """
    try:
        schedule = ScheduledMessage.objects.select_related("account", "recipient").get(id=schedule_id)
    except ScheduledMessage.DoesNotExist:
        logger.error(f"ScheduledMessage {schedule_id} not found.")
        return False

    recipient = schedule.recipient
    account = schedule.account

    rendered_text = render_message_template(schedule.message_template, recipient.recipient_name)
    success, error_msg, screenshot_path = send_thread_message(
        profile_dir=account.profile_dir,
        thread_id=recipient.thread_id,
        message=rendered_text,
    )

    # Record delivery log
    DeliveryLog.objects.create(
        scheduled_message=schedule,
        recipient_thread=recipient,
        rendered_content=rendered_text,
        status=DeliveryLog.Status.SUCCESS if success else DeliveryLog.Status.FAILED,
        error_message=error_msg,
        screenshot_path=screenshot_path,
    )

    now = timezone.now()
    schedule.last_run_at = now

    if schedule.schedule_type == ScheduledMessage.ScheduleType.ONCE:
        schedule.status = ScheduledMessage.Status.COMPLETED
        schedule.next_run_at = None
    else:
        schedule.next_run_at = calculate_next_run(
            schedule_type=schedule.schedule_type,
            run_time=schedule.run_time,
            run_date=schedule.run_date,
            day_of_month=schedule.day_of_month,
            tz_name=schedule.timezone,
            base_time=now,
        )

    schedule.save()
    return success


@shared_task
def refresh_thread_name_task(thread_id_uuid: str):
    """
    Asynchronously refreshes the recipient name of a thread using Camoufox.
    """
    try:
        thread = RecipientThread.objects.select_related("account").get(id=thread_id_uuid)
    except RecipientThread.DoesNotExist:
        return None

    try:
        name = fetch_thread_recipient_name(thread.account.profile_dir, thread.thread_id)
    except Exception as e:
        logger.error(f"Failed to fetch recipient name for thread {thread.thread_id}: {e}")
        name = None

    if name:
        thread.recipient_name = name
        thread.name_status = RecipientThread.NameStatus.FETCHED
        thread.last_fetched_at = timezone.now()
    else:
        thread.name_status = RecipientThread.NameStatus.FAILED
    thread.save()
    return name


@shared_task
def check_and_dispatch_due_messages():
    """
    Periodic task (every 1 minute via Celery Beat) finding due messages and dispatching workers.
    """
    due_messages = ScheduledMessage.objects.filter(
        status=ScheduledMessage.Status.ACTIVE,
        next_run_at__lte=timezone.now(),
    )
    count = 0
    for schedule in due_messages:
        dispatch_scheduled_message.delay(str(schedule.id))
        count += 1
    return count
