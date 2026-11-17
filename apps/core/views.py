from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
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
    
    recent_logs = logs.select_related("recipient_thread", "scheduled_message")[:8]
    upcoming_schedules = schedules.filter(
        status=ScheduledMessage.Status.ACTIVE,
        next_run_at__isnull=False
    ).select_related("recipient", "account").order_by("next_run_at")[:8]

    context = {
        "active_accounts": active_accounts,
        "total_threads": total_threads,
        "active_schedules": active_schedules,
        "recent_logs": recent_logs,
        "upcoming_schedules": upcoming_schedules,
    }
    return render(request, "core/dashboard.html", context)


def custom_login_view(request):
    if request.user.is_authenticated:
        return redirect("/")
    
    error = None
    if request.method == "POST":
        u = request.POST.get("username")
        p = request.POST.get("password")
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            return redirect(request.GET.get("next", "/"))
        else:
            error = "Invalid username or password"

    return render(request, "auth/login.html", {"error": error})


def custom_logout_view(request):
    logout(request)
    return redirect("/login/")
