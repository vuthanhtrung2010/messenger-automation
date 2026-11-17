import os
import shutil
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import MessengerAccount

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
        account = MessengerAccount.objects.create(
            owner=request.user,
            name=name,
            profile_dir="",
            status=MessengerAccount.Status.PENDING_LOGIN,
        )
        profile_path = os.path.abspath(f"data/profiles/{account.id}")
        account.profile_dir = profile_path
        account.save()
        return redirect(f"/accounts/{account.id}/stream/")
    
    return render(request, "accounts/add.html")


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
