import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.tasks import refresh_thread_name_task

def clean_thread_id(raw_input: str) -> str:
    """
    Extracts thread ID from raw numbers or full Facebook URL like https://www.facebook.com/messages/t/902973772639579
    """
    raw = (raw_input or "").strip()
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
        thread_id = clean_thread_id(raw_thread)
        
        if not thread_id:
            messages.error(request, "Invalid Thread ID or URL provided.")
            return redirect("/threads/")

        try:
            if user.is_superuser:
                account = MessengerAccount.objects.get(id=account_id)
            else:
                account = MessengerAccount.objects.get(id=account_id, owner=user)
        except MessengerAccount.DoesNotExist:
            messages.error(request, "Selected Facebook Account not found.")
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

    return render(request, "messenger/threads.html", {"threads": threads, "accounts": accounts})


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
