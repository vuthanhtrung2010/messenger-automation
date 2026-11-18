from datetime import datetime, date, time
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage, DeliveryLog
from apps.scheduler.services import calculate_next_run
from apps.scheduler.tasks import dispatch_scheduled_message

@login_required
def schedules_list_view(request):
    user = request.user
    if user.is_superuser:
        schedules = ScheduledMessage.objects.select_related("account", "recipient", "owner").all()
        threads = RecipientThread.objects.select_related("account").all()
        accounts = MessengerAccount.objects.filter(status=MessengerAccount.Status.ACTIVE)
    else:
        schedules = ScheduledMessage.objects.filter(owner=user).select_related("account", "recipient")
        threads = RecipientThread.objects.filter(owner=user).select_related("account")
        accounts = MessengerAccount.objects.filter(owner=user, status=MessengerAccount.Status.ACTIVE)

    return render(request, "scheduler/schedules.html", {
        "schedules": schedules,
        "threads": threads,
        "accounts": accounts,
    })


@login_required
def schedule_create_view(request):
    user = request.user
    if request.method == "POST":
        recipient_id = request.POST.get("recipient_id")
        account_id = request.POST.get("account_id")
        template = request.POST.get("message_template", "").strip()
        schedule_type = request.POST.get("schedule_type", ScheduledMessage.ScheduleType.ONCE)
        raw_time = request.POST.get("run_time", "08:00")
        raw_date = request.POST.get("run_date")
        raw_day_of_month = request.POST.get("day_of_month")

        if not recipient_id or not template:
            messages.error(request, "Recipient and Message body are required.")
            return redirect("/schedules/")

        try:
            if user.is_superuser:
                recipient = RecipientThread.objects.get(id=recipient_id)
            else:
                recipient = RecipientThread.objects.get(id=recipient_id, owner=user)
        except RecipientThread.DoesNotExist:
            messages.error(request, "Selected Recipient Thread not found.")
            return redirect("/schedules/")

        # If account_id provided use it, otherwise inherit recipient's account
        account = recipient.account
        if account_id:
            try:
                account = MessengerAccount.objects.get(id=account_id)
            except MessengerAccount.DoesNotExist:
                pass

        # Parse time (HH:MM or HH:MM:SS)
        try:
            time_parts = [int(p) for p in raw_time.split(":")]
            if len(time_parts) == 2:
                parsed_time = time(time_parts[0], time_parts[1])
            else:
                parsed_time = time(time_parts[0], time_parts[1], time_parts[2])
        except Exception:
            parsed_time = time(8, 0)

        # Parse date
        parsed_date = None
        if raw_date:
            try:
                parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except Exception:
                parsed_date = None

        # Parse day of month
        parsed_day_of_month = None
        if raw_day_of_month:
            try:
                parsed_day_of_month = int(raw_day_of_month)
            except Exception:
                parsed_day_of_month = None

        # Calculate next_run_at in UTC
        next_run_at = calculate_next_run(
            schedule_type=schedule_type,
            run_time=parsed_time,
            run_date=parsed_date,
            day_of_month=parsed_day_of_month,
            tz_name="Asia/Bangkok",
        )

        ScheduledMessage.objects.create(
            owner=user,
            account=account,
            recipient=recipient,
            message_template=template,
            schedule_type=schedule_type,
            run_time=parsed_time,
            run_date=parsed_date,
            day_of_month=parsed_day_of_month,
            timezone="Asia/Bangkok",
            status=ScheduledMessage.Status.ACTIVE,
            next_run_at=next_run_at,
        )

        messages.success(request, f"Scheduled message created for {recipient.display_name}.")
        return redirect("/schedules/")

    return redirect("/schedules/")


@login_required
def schedule_test_send_view(request, schedule_id):
    if request.user.is_superuser:
        schedule = get_object_or_404(ScheduledMessage, id=schedule_id)
    else:
        schedule = get_object_or_404(ScheduledMessage, id=schedule_id, owner=request.user)

    dispatch_scheduled_message.delay(str(schedule.id))
    messages.info(request, f"Test dispatch initiated for {schedule.recipient.display_name}. Check Delivery Logs in a few seconds.")
    return redirect("/schedules/")


@login_required
def schedule_toggle_view(request, schedule_id):
    if request.user.is_superuser:
        schedule = get_object_or_404(ScheduledMessage, id=schedule_id)
    else:
        schedule = get_object_or_404(ScheduledMessage, id=schedule_id, owner=request.user)

    if schedule.status == ScheduledMessage.Status.ACTIVE:
        schedule.status = ScheduledMessage.Status.PAUSED
    elif schedule.status == ScheduledMessage.Status.PAUSED:
        schedule.status = ScheduledMessage.Status.ACTIVE
        schedule.next_run_at = calculate_next_run(
            schedule.schedule_type, schedule.run_time, schedule.run_date,
            schedule.day_of_month, schedule.timezone
        )
    schedule.save()
    messages.success(request, f"Schedule status updated to {schedule.status}.")
    return redirect("/schedules/")


@login_required
def schedule_delete_view(request, schedule_id):
    if request.user.is_superuser:
        schedule = get_object_or_404(ScheduledMessage, id=schedule_id)
    else:
        schedule = get_object_or_404(ScheduledMessage, id=schedule_id, owner=request.user)

    if request.method == "POST":
        schedule.delete()
        messages.success(request, "Scheduled message removed.")
    return redirect("/schedules/")


@login_required
def delivery_logs_view(request):
    user = request.user
    if user.is_superuser:
        logs = DeliveryLog.objects.select_related("recipient_thread", "scheduled_message").all()
    else:
        logs = DeliveryLog.objects.filter(scheduled_message__owner=user).select_related("recipient_thread", "scheduled_message")

    return render(request, "scheduler/logs.html", {"logs": logs})
