import uuid
from django.db import models
from django.contrib.auth.models import User
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread

class ScheduledMessage(models.Model):
    class ScheduleType(models.TextChoices):
        ONCE = "ONCE", "One-off (Specific Date)"
        DAILY = "DAILY", "Daily (Repeated)"
        MONTHLY = "MONTHLY", "Monthly (Specific Day of Month)"
        YEARLY = "YEARLY", "Yearly (Annual Event / Birthday)"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        COMPLETED = "COMPLETED", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scheduled_messages")
    account = models.ForeignKey(MessengerAccount, on_delete=models.CASCADE, related_name="schedules")
    recipient = models.ForeignKey(RecipientThread, on_delete=models.CASCADE, related_name="schedules")
    message_template = models.TextField(help_text="Message body. Supports dynamic placeholder {name}.")
    schedule_type = models.CharField(max_length=20, choices=ScheduleType.choices, default=ScheduleType.ONCE)
    run_time = models.TimeField(help_text="Time of day in GMT+7 (e.g. 08:30:00)")
    run_date = models.DateField(blank=True, null=True, help_text="Specific date for ONCE or YEARLY")
    day_of_month = models.PositiveSmallIntegerField(blank=True, null=True, help_text="Day of month 1-31 for MONTHLY")
    timezone = models.CharField(max_length=50, default="Asia/Bangkok")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    next_run_at = models.DateTimeField(blank=True, null=True, db_index=True, help_text="Next scheduled run time in UTC")
    last_run_at = models.DateTimeField(blank=True, null=True, help_text="Timestamp of last execution in UTC")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_run_at", "-created_at"]

    def __str__(self):
        return f"{self.schedule_type} to {self.recipient.display_name}"


class DeliveryLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scheduled_message = models.ForeignKey(
        ScheduledMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs"
    )
    recipient_thread = models.ForeignKey(
        RecipientThread, on_delete=models.SET_NULL, null=True, blank=True, related_name="delivery_logs"
    )
    rendered_content = models.TextField(help_text="Actual message text dispatched to Facebook Messenger")
    status = models.CharField(max_length=20, choices=Status.choices)
    error_message = models.TextField(blank=True, null=True)
    screenshot_path = models.CharField(max_length=500, blank=True, null=True)
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-attempted_at"]

    def __str__(self):
        return f"[{self.status}] to {self.recipient_thread} at {self.attempted_at}"
