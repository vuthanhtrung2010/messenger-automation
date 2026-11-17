import uuid
from django.db import models
from django.contrib.auth.models import User
from apps.accounts.models import MessengerAccount

class RecipientThread(models.Model):
    class NameStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        FETCHED = "FETCHED", "Fetched"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recipient_threads")
    account = models.ForeignKey(MessengerAccount, on_delete=models.CASCADE, related_name="threads")
    thread_id = models.CharField(max_length=100, help_text="Facebook thread ID (e.g. 902973772639579)")
    recipient_name = models.CharField(max_length=255, blank=True, null=True, help_text="Fetched recipient or group name")
    name_status = models.CharField(max_length=20, choices=NameStatus.choices, default=NameStatus.PENDING)
    last_fetched_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("account", "thread_id")

    @property
    def display_name(self) -> str:
        if self.recipient_name:
            return f"{self.recipient_name} (Thread: {self.thread_id})"
        return f"Thread: {self.thread_id}"

    def __str__(self):
        return self.display_name
