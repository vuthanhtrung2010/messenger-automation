import os
import shutil
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import MessengerAccount
from apps.scheduler.tasks import sync_zalo_contacts_task, check_zalo_session_task

@login_required
def accounts_list_view(request):
    if request.user.is_superuser:
        accounts = MessengerAccount.objects.all()
    else:
        accounts = MessengerAccount.objects.filter(owner=request.user)
    return render(request, "accounts/list.html", {"accounts": accounts})


@login_required
def account_create_view(request):
    if request.method == "POST":
        name = request.POST.get("name", "New Account").strip() or "New Account"
        platform = request.POST.get("platform", MessengerAccount.Platform.MESSENGER)
        if platform not in MessengerAccount.Platform.values:
            platform = MessengerAccount.Platform.MESSENGER
        account = MessengerAccount.objects.create(
            owner=request.user,
            platform=platform,
            name=name,
            profile_dir="",
            status=MessengerAccount.Status.PENDING_LOGIN,
        )
        profile_path = os.path.abspath(f"data/profiles/{account.id}")
        account.profile_dir = profile_path
        account.save()
        return redirect(f"/accounts/{account.id}/stream/")
    
    return render(request, "accounts/add.html", {"platforms": MessengerAccount.Platform.choices})


@login_required
def account_stream_view(request, account_id):
    if request.user.is_superuser:
        account = get_object_or_404(MessengerAccount, id=account_id)
    else:
        account = get_object_or_404(MessengerAccount, id=account_id, owner=request.user)
    
    return render(request, "accounts/stream.html", {"account": account})


@login_required
def account_delete_view(request, account_id):
    if request.user.is_superuser:
        account = get_object_or_404(MessengerAccount, id=account_id)
    else:
        account = get_object_or_404(MessengerAccount, id=account_id, owner=request.user)
    
    if request.method == "POST":
        # Delete profile dir
        if account.profile_dir and os.path.exists(account.profile_dir):
            try:
                shutil.rmtree(account.profile_dir)
            except Exception as e:
                print(f"Error removing profile directory: {e}")
        account.delete()
        messages.success(request, "Account and associated profile removed.")
        return redirect("/accounts/")
    
    return render(request, "accounts/confirm_delete.html", {"account": account})


@login_required
def account_check_session_view(request, account_id):
    if request.user.is_superuser:
        account = get_object_or_404(MessengerAccount, id=account_id)
    else:
        account = get_object_or_404(MessengerAccount, id=account_id, owner=request.user)

    if request.method != "POST":
        return redirect("/accounts/")

    if account.platform == MessengerAccount.Platform.ZALO:
        check_zalo_session_task.delay(str(account.id))
        messages.info(
            request,
            f"Checking Zalo session for '{account.name}' in the background. Refresh in a few seconds.",
        )
    else:
        messages.info(request, "Session check is currently implemented for Zalo accounts.")

    return redirect("/accounts/")


@login_required
def account_sync_contacts_view(request, account_id):
    if request.user.is_superuser:
        account = get_object_or_404(MessengerAccount, id=account_id)
    else:
        account = get_object_or_404(MessengerAccount, id=account_id, owner=request.user)

    if request.method != "POST":
        return redirect("/accounts/")

    if account.platform != MessengerAccount.Platform.ZALO:
        messages.error(request, "Contact sync is only supported for Zalo accounts.")
        return redirect("/accounts/")

    sync_zalo_contacts_task.delay(str(account.id))
    messages.success(
        request,
        f"Syncing Zalo contacts for '{account.name}' in the background. Check Recipients in a few seconds.",
    )
    return redirect("/threads/")
