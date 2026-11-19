import re
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.tasks import refresh_thread_name_task

def clean_thread_id(raw_input: str, platform: str = MessengerAccount.Platform.MESSENGER) -> str:
    """
    Extracts thread ID from raw numbers, Zalo group IDs (g...), friend-item-<id>,
    or full Facebook URL like https://www.facebook.com/messages/t/902973772639579
    """
    raw = (raw_input or "").strip()
    if platform == MessengerAccount.Platform.ZALO:
        friend_match = re.search(r"friend-item-(g?\d+)", raw)
        if friend_match:
            return friend_match.group(1)
        zalo_match = re.search(r"\b(g?\d+)\b", raw)
        if zalo_match:
            return zalo_match.group(1)
        return raw

    match = re.search(r"/messages/t/(\d+)", raw)
    if match:
        return match.group(1)

    digits = re.findall(r"\d+", raw)
    if digits:
        return digits[0]
    return raw


@login_required
def threads_list_view(request):
    user = request.user
    if user.is_superuser:
        threads = RecipientThread.objects.select_related("account", "owner").all()
        accounts = MessengerAccount.objects.filter(status=MessengerAccount.Status.ACTIVE)
    else:
        threads = RecipientThread.objects.filter(owner=user).select_related("account")
        accounts = MessengerAccount.objects.filter(owner=user, status=MessengerAccount.Status.ACTIVE)

    if request.method == "POST":
        raw_thread = request.POST.get("thread_id", "")
        account_id = request.POST.get("account_id")

        try:
            if user.is_superuser:
                account = MessengerAccount.objects.get(id=account_id)
            else:
                account = MessengerAccount.objects.get(id=account_id, owner=user)
        except MessengerAccount.DoesNotExist:
            messages.error(request, "Selected Account not found.")
            return redirect("/threads/")

        thread_id = clean_thread_id(raw_thread, platform=account.platform)
        if not thread_id:
            messages.error(request, "Invalid Thread ID or URL provided.")
            return redirect("/threads/")

        thread, created = RecipientThread.objects.get_or_create(
            account=account,
            thread_id=thread_id,
            defaults={"owner": user, "name_status": RecipientThread.NameStatus.PENDING}
        )

        # Trigger background name refresh
        refresh_thread_name_task.delay(str(thread.id))
        messages.success(request, f"Thread {thread_id} added. Fetching recipient name in background...")
        return redirect("/threads/")

    search_query = request.GET.get("q", "").strip()
    platform_filter = request.GET.get("platform", "").strip().upper()
    if platform_filter in MessengerAccount.Platform.values:
        threads = threads.filter(account__platform=platform_filter)
    else:
        platform_filter = ""

    if search_query:
        threads = threads.filter(
            Q(recipient_name__icontains=search_query)
            | Q(thread_id__icontains=search_query)
            | Q(account__name__icontains=search_query)
        )

    return render(
        request,
        "messenger/threads.html",
        {
            "threads": threads,
            "accounts": accounts,
            "search_query": search_query,
            "platform_filter": platform_filter,
            "platforms": MessengerAccount.Platform.choices,
        },
    )


@login_required
def thread_refresh_view(request, thread_id):
    if request.user.is_superuser:
        thread = get_object_or_404(RecipientThread, id=thread_id)
    else:
        thread = get_object_or_404(RecipientThread, id=thread_id, owner=request.user)

    thread.name_status = RecipientThread.NameStatus.PENDING
    thread.save()
    refresh_thread_name_task.delay(str(thread.id))
    messages.info(request, f"Refreshing recipient name for thread {thread.thread_id}...")
    return redirect("/threads/")


@login_required
def thread_delete_view(request, thread_id):
    if request.user.is_superuser:
        thread = get_object_or_404(RecipientThread, id=thread_id)
    else:
        thread = get_object_or_404(RecipientThread, id=thread_id, owner=request.user)

    if request.method == "POST":
        thread.delete()
        messages.success(request, "Recipient thread removed.")
    return redirect("/threads/")
