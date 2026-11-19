import uuid
from django.db import models
from django.contrib.auth.models import User

class MessengerAccount(models.Model):
    class Platform(models.TextChoices):
        MESSENGER = "MESSENGER", "Facebook Messenger"
        ZALO = "ZALO", "Zalo"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        PENDING_LOGIN = "PENDING_LOGIN", "Pending Login"
        EXPIRED = "EXPIRED", "Expired"
        LOCKED = "LOCKED", "Locked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="messenger_accounts")
    platform = models.CharField(max_length=20, choices=Platform.choices, default=Platform.MESSENGER)
    name = models.CharField(max_length=255, help_text="Friendly label for this account")
    fb_user_id = models.CharField(max_length=100, blank=True, null=True, help_text="Platform User ID (e.g. Facebook c_user or Zalo UID)")
    profile_dir = models.CharField(max_length=500, help_text="Path to persistent Camoufox browser profile directory")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_LOGIN)
    last_login_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.fb_user_id or 'Not logged in'})"
