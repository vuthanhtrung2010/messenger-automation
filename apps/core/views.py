from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage, DeliveryLog

@login_required
def dashboard_view(request):
    user = request.user
    if user.is_superuser:
        accounts = MessengerAccount.objects.all()
        threads = RecipientThread.objects.all()
        schedules = ScheduledMessage.objects.all()
        logs = DeliveryLog.objects.all()
    else:
        accounts = MessengerAccount.objects.filter(owner=user)
        threads = RecipientThread.objects.filter(owner=user)
        schedules = ScheduledMessage.objects.filter(owner=user)
        logs = DeliveryLog.objects.filter(scheduled_message__owner=user)

    active_accounts = accounts.filter(status=MessengerAccount.Status.ACTIVE).count()
    total_threads = threads.count()
    active_schedules = schedules.filter(status=ScheduledMessage.Status.ACTIVE).count()
    delivered_count = logs.filter(status=DeliveryLog.Status.SUCCESS).count()

    recent_logs = logs.select_related("recipient_thread", "scheduled_message")[:5]
    upcoming_schedules = schedules.filter(
        status=ScheduledMessage.Status.ACTIVE,
        next_run_at__isnull=False
    ).select_related("recipient", "account").order_by("next_run_at")[:5]

    context = {
        "active_accounts": active_accounts,
        "total_threads": total_threads,
        "active_schedules": active_schedules,
        "delivered_count": delivered_count,
        "recent_logs": recent_logs,
        "upcoming_schedules": upcoming_schedules,
    }
    return render(request, "core/dashboard.html", context)


def custom_login_view(request):
    if request.user.is_authenticated:
        return redirect("/")

    error = None
    username_error = None
    password_error = None
    username = ""

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        if not username:
            username_error = "Enter your username"
        if not password:
            password_error = "Enter your password"

        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect(request.GET.get("next", "/"))
            else:
                error = "Username or password is incorrect"

    return render(request, "auth/login.html", {
        "error": error,
        "username": username,
        "username_error": username_error,
        "password_error": password_error,
    })


def custom_logout_view(request):
    logout(request)
    return redirect("/login/")
