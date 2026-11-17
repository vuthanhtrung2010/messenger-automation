from django.contrib import admin
from django.urls import path
from apps.core import views as core_views
from apps.accounts import views as account_views
from apps.messenger import views as messenger_views
from apps.scheduler import views as scheduler_views

urlpatterns = [
    path("admin/", admin.site.urls),
    
    # Core & Authentication
    path("", core_views.dashboard_view, name="dashboard"),
    path("login/", core_views.custom_login_view, name="login"),
    path("logout/", core_views.custom_logout_view, name="logout"),

    # Facebook Accounts
    path("accounts/", account_views.accounts_list_view, name="accounts_list"),
    path("accounts/add/", account_views.account_create_view, name="account_create"),
    path("accounts/<uuid:account_id>/stream/", account_views.account_stream_view, name="account_stream"),
    path("accounts/<uuid:account_id>/delete/", account_views.account_delete_view, name="account_delete"),

    # Recipients & Threads
    path("threads/", messenger_views.threads_list_view, name="threads_list"),
    path("threads/<uuid:thread_id>/refresh/", messenger_views.thread_refresh_view, name="thread_refresh"),
    path("threads/<uuid:thread_id>/delete/", messenger_views.thread_delete_view, name="thread_delete"),

    # Message Schedules
    path("schedules/", scheduler_views.schedules_list_view, name="schedules_list"),
    path("schedules/create/", scheduler_views.schedule_create_view, name="schedule_create"),
    path("schedules/<uuid:schedule_id>/test-send/", scheduler_views.schedule_test_send_view, name="schedule_test_send"),
    path("schedules/<uuid:schedule_id>/toggle/", scheduler_views.schedule_toggle_view, name="schedule_toggle"),
    path("schedules/<uuid:schedule_id>/delete/", scheduler_views.schedule_delete_view, name="schedule_delete"),

    # Delivery Audit Logs
    path("logs/", scheduler_views.delivery_logs_view, name="delivery_logs"),
]
