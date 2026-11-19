import os
import fcntl
import contextlib
import logging
from celery import shared_task
from django.utils import timezone
from apps.accounts.models import MessengerAccount
from apps.scheduler.models import ScheduledMessage, DeliveryLog
from apps.messenger.models import RecipientThread
from apps.scheduler.services import render_message_template, calculate_next_run
from apps.messenger.services import send_thread_message, fetch_thread_recipient_name
from apps.messenger.zalo_service import send_zalo_message, fetch_zalo_recipient_name, list_zalo_contacts, check_zalo_session

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _try_schedule_dispatch_lock(schedule_id: str):
    """Non-blocking per-schedule file lock so concurrent Beat/worker deliveries cannot overlap."""
    lock_dir = os.path.abspath("data/locks")
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, f"schedule_{schedule_id}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


@shared_task
def dispatch_scheduled_message(schedule_id: str, expected_run_at: str | None = None):
    """
    Executes sending of a single scheduled message and updates its schedule state.
    When triggered by Beat (`expected_run_at` provided), skips duplicate deliveries
    that were already processed for that occurrence.
    """
    with _try_schedule_dispatch_lock(schedule_id) as acquired:
        if not acquired:
            logger.warning(f"ScheduledMessage {schedule_id} dispatch already in progress; skipping duplicate.")
            return False

        try:
            schedule = ScheduledMessage.objects.select_related("account", "recipient").get(id=schedule_id)
        except ScheduledMessage.DoesNotExist:
            logger.error(f"ScheduledMessage {schedule_id} not found.")
            return False

        if expected_run_at is not None:
            current_run_at = schedule.next_run_at.isoformat() if schedule.next_run_at else None
            if schedule.status != ScheduledMessage.Status.ACTIVE or current_run_at != expected_run_at:
                logger.info(
                    f"Skipping duplicate scheduled dispatch for {schedule_id} "
                    f"(expected {expected_run_at}, current status={schedule.status}, next_run_at={current_run_at})."
                )
                return False

        recipient = schedule.recipient
        account = schedule.account

        rendered_text = render_message_template(schedule.message_template, recipient.recipient_name)
        if account.platform == MessengerAccount.Platform.ZALO:
            success, error_msg, screenshot_path = send_zalo_message(
                profile_dir=account.profile_dir,
                thread_id=recipient.thread_id,
                message=rendered_text,
                recipient_name=recipient.recipient_name,
            )
            if not success and "session expired" in (error_msg or "").lower():
                account.status = MessengerAccount.Status.EXPIRED
                account.save(update_fields=["status", "updated_at"])
        else:
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
            schedule.status = (
                ScheduledMessage.Status.COMPLETED if success else ScheduledMessage.Status.PAUSED
            )
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
        if thread.account.platform == MessengerAccount.Platform.ZALO:
            name = fetch_zalo_recipient_name(thread.account.profile_dir, thread.thread_id)
        else:
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
        expected_iso = schedule.next_run_at.isoformat() if schedule.next_run_at else None
        dispatch_scheduled_message.delay(str(schedule.id), expected_iso)
        count += 1
    return count


@shared_task
def sync_zalo_contacts_task(account_id: str):
    """
    Asynchronously syncs Zalo contacts from localStorage into RecipientThread records.
    """
    try:
        account = MessengerAccount.objects.get(id=account_id)
    except MessengerAccount.DoesNotExist:
        return None

    if account.platform != MessengerAccount.Platform.ZALO:
        return None

    try:
        contacts = list_zalo_contacts(account.profile_dir)
    except Exception as e:
        logger.error(f"Failed to sync Zalo contacts for account {account_id}: {e}")
        if "expired" in str(e).lower() or "logged out" in str(e).lower():
            account.status = MessengerAccount.Status.EXPIRED
            account.save(update_fields=["status", "updated_at"])
        return None

    created_count = 0
    updated_count = 0
    now = timezone.now()
    for c in contacts:
        tid = (c.get("thread_id") or "").strip()
        cname = (c.get("name") or "").strip()
        if not tid or not cname:
            continue
        obj, created = RecipientThread.objects.get_or_create(
            account=account,
            thread_id=tid,
            defaults={
                "owner": account.owner,
                "recipient_name": cname,
                "name_status": RecipientThread.NameStatus.FETCHED,
                "last_fetched_at": now,
            },
        )
        if created:
            created_count += 1
        elif obj.recipient_name != cname or obj.name_status != RecipientThread.NameStatus.FETCHED:
            obj.recipient_name = cname
            obj.name_status = RecipientThread.NameStatus.FETCHED
            obj.last_fetched_at = now
            obj.save(update_fields=["recipient_name", "name_status", "last_fetched_at", "updated_at"])
            updated_count += 1

    return {"created": created_count, "updated": updated_count}


@shared_task
def check_zalo_session_task(account_id: str):
    """
    Asynchronously checks if a Zalo account's browser session is still logged in.
    """
    try:
        account = MessengerAccount.objects.get(id=account_id)
    except MessengerAccount.DoesNotExist:
        return None

    if account.platform != MessengerAccount.Platform.ZALO:
        return None

    try:
        is_active, zalo_uid = check_zalo_session(account.profile_dir)
    except Exception as e:
        logger.error(f"Failed to check Zalo session for account {account_id}: {e}")
        return None

    if is_active:
        account.status = MessengerAccount.Status.ACTIVE
        if zalo_uid:
            account.fb_user_id = zalo_uid
        account.last_login_at = timezone.now()
        account.save()
        return True

    account.status = MessengerAccount.Status.EXPIRED
    account.save(update_fields=["status", "updated_at"])
    return False
