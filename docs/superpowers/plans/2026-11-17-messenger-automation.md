# Facebook Messenger Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete, production-ready Facebook Messenger automation platform in Python using Django, Camoufox, PostgreSQL, Celery, and WebSockets to schedule recurring and one-off messages in GMT+7.

**Architecture:** Django ASGI with Channels manages HTTP views and WebSocket screencasting of Camoufox instances for interactive login with Ctrl+V paste and session detection. Headless Camoufox automation executes background thread name fetching and message delivery orchestrated via Celery and Celery-Beat.

**Tech Stack:** Python 3.12+, uv, Django 5.x, Django Channels, Daphne, Celery, Redis, PostgreSQL, Camoufox[geoip], Playwright, Pillow, pytest-django.

**Spec:** `docs/superpowers/specs/2026-11-17-messenger-automation-design.md`

## Global Constraints
- Timezone: GMT+7 (`Asia/Bangkok`) for all scheduling definitions; UTC internally for stored execution timestamps (`next_run_at`).
- Isolation: Private per-admin ownership of accounts, threads, and schedules; superuser global oversight.
- Nix environment: Camoufox requires running with libraries defined in `devenv.nix`.
- No placeholders: All code blocks, tests, and configuration must be complete and executable.

---

### Task 1: Project Setup, Dependencies & Django Core Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `manage.py`
- Create: `config/__init__.py`
- Create: `config/settings.py`
- Create: `config/asgi.py`
- Create: `config/wsgi.py`
- Create: `config/urls.py`
- Create: `config/celery.py`
- Test: `tests/test_core_setup.py`

**Interfaces:**
- Produces: Runnable Django ASGI application with Channels and Celery app configuration.

- [ ] **Step 1: Write failing test for Django configuration**

```python
# tests/test_core_setup.py
import pytest
from django.conf import settings

def test_django_settings_configured():
    assert settings.INSTALLED_APPS is not None
    assert "channels" in settings.INSTALLED_APPS
    assert settings.ASGI_APPLICATION == "config.asgi.application"
    assert settings.TIME_ZONE == "Asia/Bangkok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core_setup.py -v`
Expected: FAIL (Django not yet installed/configured).

- [ ] **Step 3: Add dependencies and implement Django configuration**

Add required dependencies to `pyproject.toml`:
```bash
uv add "django>=5.1" "channels>=4.2" "daphne>=4.1" "channels-redis>=4.2" "celery[redis]>=5.4" "psycopg[binary]>=3.2" "pillow>=10.4" "pytest>=8.0" "pytest-django>=4.9" "pytest-asyncio>=0.24"
```

Create `config/celery.py`:
```python
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("messenger_automation")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

Create `config/settings.py` with standard settings, installed apps (`daphne`, `channels`, `django.contrib.admin`, `django.contrib.auth`, etc.), database settings (PostgreSQL with fallback to SQLite if DB env not set), `TIME_ZONE = "Asia/Bangkok"`, `USE_TZ = True`, and Channels / Celery broker configurations.

Create `config/asgi.py`:
```python
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

import apps.accounts.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            apps.accounts.routing.websocket_urlpatterns
        )
    ),
})
```

Create `manage.py` and `config/urls.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `devenv shell -- uv run pytest tests/test_core_setup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock manage.py config/ tests/test_core_setup.py
git commit -m "chore: setup django channels celery and core configuration"
```

---

### Task 2: Database Models & Migrations

**Files:**
- Create: `apps/accounts/models.py`
- Create: `apps/messenger/models.py`
- Create: `apps/scheduler/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `MessengerAccount(owner, name, fb_user_id, profile_dir, status, last_login_at)`
  - `RecipientThread(owner, account, thread_id, recipient_name, name_status, last_fetched_at)`
  - `ScheduledMessage(owner, account, recipient, message_template, schedule_type, run_time, run_date, day_of_month, timezone, status, next_run_at, last_run_at)`
  - `DeliveryLog(scheduled_message, recipient_thread, rendered_content, status, error_message, attempted_at, screenshot_path)`

- [ ] **Step 1: Write failing tests for models**

```python
# tests/test_models.py
import pytest
from django.contrib.auth.models import User
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage, DeliveryLog
import datetime

@pytest.mark.django_db
def test_create_models_hierarchy():
    user = User.objects.create_user(username="admin1", password="password")
    account = MessengerAccount.objects.create(
        owner=user,
        name="Personal Account",
        profile_dir="data/profiles/test_acc",
        status=MessengerAccount.Status.ACTIVE,
    )
    thread = RecipientThread.objects.create(
        owner=user,
        account=account,
        thread_id="902973772639579",
        recipient_name="John Doe",
        name_status=RecipientThread.NameStatus.FETCHED,
    )
    schedule = ScheduledMessage.objects.create(
        owner=user,
        account=account,
        recipient=thread,
        message_template="Hello {name}!",
        schedule_type=ScheduledMessage.ScheduleType.DAILY,
        run_time=datetime.time(8, 30),
    )
    log = DeliveryLog.objects.create(
        scheduled_message=schedule,
        rendered_content="Hello John Doe!",
        status=DeliveryLog.Status.SUCCESS,
    )
    assert account.owner == user
    assert thread.account == account
    assert schedule.recipient == thread
    assert log.scheduled_message == schedule
```

- [ ] **Step 2: Run test to verify it fails**

Run: `devenv shell -- uv run pytest tests/test_models.py -v`
Expected: FAIL (models not found).

- [ ] **Step 3: Implement models & create migrations**

Implement `MessengerAccount`, `RecipientThread`, `ScheduledMessage`, and `DeliveryLog` with `TextChoices` for statuses, foreign keys with `on_delete=models.CASCADE`, auto timestamps, and custom helper methods (e.g. `display_name` showing `f"{recipient_name} (Thread: {thread_id})" if recipient_name else thread_id`).

Run migrations:
```bash
devenv shell -- uv run python manage.py makemigrations accounts messenger scheduler
devenv shell -- uv run python manage.py migrate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `devenv shell -- uv run pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/ tests/test_models.py
git commit -m "feat: implement database models and migrations"
```

---

### Task 3: Scheduling Logic & Recurrence Engine

**Files:**
- Create: `apps/scheduler/services.py`
- Test: `tests/test_scheduler_engine.py`

**Interfaces:**
- Produces:
  - `calculate_next_run(schedule_type, run_time, run_date=None, day_of_month=None, tz_name="Asia/Bangkok", base_time=None) -> datetime (in UTC)`
  - `render_message_template(template: str, recipient_name: str | None) -> str`

- [ ] **Step 1: Write failing tests for recurrence engine**

```python
# tests/test_scheduler_engine.py
import datetime
from zoneinfo import ZoneInfo
from apps.scheduler.services import calculate_next_run, render_message_template
from apps.scheduler.models import ScheduledMessage

def test_render_message_template():
    assert render_message_template("Happy Birthday {name}!", "Alice") == "Happy Birthday Alice!"
    assert render_message_template("Happy New Year {name}!", None) == "Happy New Year!"

def test_calculate_daily_next_run():
    tz = ZoneInfo("Asia/Bangkok")
    base_time = datetime.datetime(2026, 11, 17, 8, 0, tzinfo=tz) # 8:00 AM
    target_time = datetime.time(9, 0) # 9:00 AM same day
    next_run = calculate_next_run(
        schedule_type=ScheduledMessage.ScheduleType.DAILY,
        run_time=target_time,
        tz_name="Asia/Bangkok",
        base_time=base_time,
    )
    expected_local = datetime.datetime(2026, 11, 17, 9, 0, tzinfo=tz)
    assert next_run == expected_local.astimezone(datetime.timezone.utc)

def test_calculate_monthly_month_end_clamping():
    tz = ZoneInfo("Asia/Bangkok")
    # Base: Jan 31
    base_time = datetime.datetime(2026, 1, 31, 10, 0, tzinfo=tz)
    # Day 31 of next month (Feb) should clamp to Feb 28
    next_run = calculate_next_run(
        schedule_type=ScheduledMessage.ScheduleType.MONTHLY,
        run_time=datetime.time(10, 0),
        day_of_month=31,
        tz_name="Asia/Bangkok",
        base_time=base_time,
    )
    expected_local = datetime.datetime(2026, 2, 28, 10, 0, tzinfo=tz)
    assert next_run == expected_local.astimezone(datetime.timezone.utc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `devenv shell -- uv run pytest tests/test_scheduler_engine.py -v`
Expected: FAIL (`calculate_next_run` not implemented).

- [ ] **Step 3: Implement recurrence engine and template rendering**

Implement `apps/scheduler/services.py`:
- `render_message_template(template, recipient_name)`:
  - If `recipient_name`, replace `{name}` with `recipient_name`.
  - If `recipient_name` is None or empty, replace ` {name}` or `{name}` cleanly.
- `calculate_next_run(...)`:
  - Uses `zoneinfo.ZoneInfo("Asia/Bangkok")`.
  - For `ONCE`: Combines `run_date` and `run_time`, returns UTC datetime (or None if in past).
  - For `DAILY`: Checks if today's `run_time` has passed; if yes, schedules for tomorrow; converts to UTC.
  - For `MONTHLY`: Takes `day_of_month` (1-31). Computes current or next month, clamps to `calendar.monthrange(year, month)[1]`, converts to UTC.
  - For `YEARLY`: Schedules for next occurrence of `run_date.month` and `run_date.day`.

- [ ] **Step 4: Run test to verify it passes**

Run: `devenv shell -- uv run pytest tests/test_scheduler_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/scheduler/services.py tests/test_scheduler_engine.py
git commit -m "feat: implement scheduling recurrence engine and template renderer"
```

---

### Task 4: Interactive WebSocket Screencast Consumer

**Files:**
- Create: `apps/accounts/consumers.py`
- Create: `apps/accounts/routing.py`
- Test: `tests/test_stream_consumer.py`

**Interfaces:**
- Produces: `BrowserStreamConsumer` handling:
  - WebSocket connect/disconnect
  - Interaction messages: `{"type": "mouse", "action": "...", "x": int, "y": int}`, `{"type": "keyboard", "action": "...", "key": str}`, `{"type": "paste", "text": str}`
  - Frame diffing streaming loop (only transmits changed frames)
  - Login detection: polls `c_user` cookie and marks account `ACTIVE`

- [ ] **Step 1: Write failing test for WebSocket consumer**

```python
# tests/test_stream_consumer.py
import pytest
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from apps.accounts.models import MessengerAccount
from config.asgi import application

@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_websocket_stream_connect_and_paste_event():
    user = await User.objects.acreate_user(username="testadmin", password="password")
    account = await MessengerAccount.objects.acreate(
        owner=user,
        name="Stream Account",
        profile_dir="data/profiles/stream_test",
    )
    communicator = WebsocketCommunicator(
        application,
        f"/ws/accounts/{account.id}/stream/"
    )
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    assert connected
    # Send paste message
    await communicator.send_json_to({"type": "paste", "text": "test paste string"})
    await communicator.disconnect()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `devenv shell -- uv run pytest tests/test_stream_consumer.py -v`
Expected: FAIL (`BrowserStreamConsumer` / routing not defined).

- [ ] **Step 3: Implement `BrowserStreamConsumer` and routing**

Implement `apps/accounts/routing.py`:
```python
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/accounts/(?P<account_id>[0-9a-f-]+)/stream/$", consumers.BrowserStreamConsumer.as_asgi()),
]
```

Implement `apps/accounts/consumers.py`:
- In `connect()`: authenticate user, ensure ownership of `MessengerAccount`, spawn async Camoufox browser context using `user_data_dir=account.profile_dir`.
- In `stream_loop()`:
  - Takes screenshot (`page.screenshot(type="jpeg", quality=60)`).
  - Calculates MD5 hash of image bytes. If changed or interaction occurred, sends binary frame over WebSocket: `await self.send(bytes_data=frame)`.
  - Periodic cookie inspection: checks `await context.cookies()` for `c_user`. If found: updates `account.status = ACTIVE`, `account.fb_user_id = c_user`, sends `{"type": "login_success", "fb_user_id": c_user}`.
- In `receive()`:
  - If text is JSON:
    - `"mouse"`: maps scaled canvas coordinates to `page.mouse.move(x, y)`, `down()`, `up()`.
    - `"keyboard"`: dispatches to `page.keyboard.down(key)` / `page.keyboard.up(key)`.
    - `"paste"`: calls `await page.keyboard.insert_text(text)`.
    - `"done"`: user manually signals login completion.
- In `disconnect()`: closes browser context cleanly and releases session resources.

- [ ] **Step 4: Run test to verify it passes**

Run: `devenv shell -- uv run pytest tests/test_stream_consumer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/accounts/ tests/test_stream_consumer.py
git commit -m "feat: implement interactive websocket screencast consumer with paste support"
```

---

### Task 5: Messenger Automation Service (Headless Camoufox)

**Files:**
- Create: `apps/messenger/services.py`
- Test: `tests/test_messenger_service.py`

**Interfaces:**
- Produces:
  - `fetch_thread_recipient_name(profile_dir: str, thread_id: str) -> str | None`
  - `send_thread_message(profile_dir: str, thread_id: str, message: str) -> tuple[bool, str | None, str | None]` (returns `(success, error_msg, screenshot_path)`)

- [ ] **Step 1: Write failing tests for Messenger service**

```python
# tests/test_messenger_service.py
import pytest
from unittest.mock import MagicMock, patch
from apps.messenger.services import extract_name_from_dom

def test_extract_name_from_dom():
    assert extract_name_from_dom("Write to Alice") == "Alice"
    assert extract_name_from_dom("Conversation titled Project Chat") == "Project Chat"
    assert extract_name_from_dom("Message actions") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `devenv shell -- uv run pytest tests/test_messenger_service.py -v`
Expected: FAIL (`extract_name_from_dom` not defined).

- [ ] **Step 3: Implement Messenger automation functions**

Implement `apps/messenger/services.py`:
- `extract_name_from_dom(aria_label: str) -> str | None`:
  - If label starts with `"Write to "`, strip prefix and return.
  - If label starts with `"Conversation titled "`, strip prefix and return.
- `fetch_thread_recipient_name(profile_dir: str, thread_id: str) -> str | None`:
  - Launches headless Camoufox with `profile_dir`.
  - Navigates to `https://www.facebook.com/messages/t/{thread_id}` (`wait_until="domcontentloaded"`).
  - Waits up to 10s for `div[role="textbox"][aria-label^="Write to "]` or `div[aria-label^="Conversation titled "]`.
  - Extracts and returns recipient name.
- `send_thread_message(profile_dir: str, thread_id: str, message: str)`:
  - Opens thread URL in headless Camoufox.
  - Locates `div[role="textbox"]`.
  - Focuses element, inserts message text, and presses `"Enter"`.
  - Waits for delivery confirmation. Captures error screenshot if exception occurs.

- [ ] **Step 4: Run test to verify it passes**

Run: `devenv shell -- uv run pytest tests/test_messenger_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/messenger/services.py tests/test_messenger_service.py
git commit -m "feat: implement messenger automation service for name extraction and sending"
```

---

### Task 6: Celery Tasks & Celery-Beat Integration

**Files:**
- Create: `apps/scheduler/tasks.py`
- Modify: `config/settings.py` (Celery beat schedule definition)
- Test: `tests/test_celery_tasks.py`

**Interfaces:**
- Produces:
  - `dispatch_scheduled_message(schedule_id: str)`
  - `refresh_thread_name_task(thread_id: str)`
  - `check_and_dispatch_due_messages()`

- [ ] **Step 1: Write failing test for Celery tasks**

```python
# tests/test_celery_tasks.py
import pytest
from unittest.mock import patch
from django.contrib.auth.models import User
from django.utils import timezone
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage, DeliveryLog
from apps.scheduler.tasks import dispatch_scheduled_message, check_and_dispatch_due_messages

@pytest.mark.django_db
@patch("apps.scheduler.tasks.send_thread_message")
def test_dispatch_scheduled_message(mock_send):
    mock_send.return_value = (True, None, None)
    user = User.objects.create_user(username="celery_test", password="password")
    account = MessengerAccount.objects.create(owner=user, name="Acc", profile_dir="data/profiles/acc")
    thread = RecipientThread.objects.create(owner=user, account=account, thread_id="123", recipient_name="Bob")
    schedule = ScheduledMessage.objects.create(
        owner=user,
        account=account,
        recipient=thread,
        message_template="Hi {name}",
        schedule_type=ScheduledMessage.ScheduleType.DAILY,
        status=ScheduledMessage.Status.ACTIVE,
        next_run_at=timezone.now(),
    )
    dispatch_scheduled_message(str(schedule.id))
    log = DeliveryLog.objects.filter(scheduled_message=schedule).first()
    assert log is not None
    assert log.status == DeliveryLog.Status.SUCCESS
    assert log.rendered_content == "Hi Bob"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `devenv shell -- uv run pytest tests/test_celery_tasks.py -v`
Expected: FAIL (`dispatch_scheduled_message` not found).

- [ ] **Step 3: Implement Celery tasks & Beat configuration**

Implement `apps/scheduler/tasks.py`:
- `dispatch_scheduled_message(schedule_id)`:
  - Fetches schedule, renders template with recipient name.
  - Calls `send_thread_message(schedule.account.profile_dir, schedule.recipient.thread_id, rendered_text)`.
  - Creates `DeliveryLog` record with outcome.
  - Updates `schedule.last_run_at = now()` and advances `schedule.next_run_at` via `calculate_next_run`.
- `refresh_thread_name_task(thread_id)`:
  - Calls `fetch_thread_recipient_name` and updates `RecipientThread.recipient_name`.
- `check_and_dispatch_due_messages()`:
  - Queries `ScheduledMessage.objects.filter(status='ACTIVE', next_run_at__lte=timezone.now())` and enqueues `dispatch_scheduled_message.delay(s.id)`.

Update `config/settings.py` with `CELERY_BEAT_SCHEDULE`:
```python
CELERY_BEAT_SCHEDULE = {
    "check-due-messages-every-minute": {
        "task": "apps.scheduler.tasks.check_and_dispatch_due_messages",
        "schedule": 60.0,
    },
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `devenv shell -- uv run pytest tests/test_celery_tasks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/scheduler/tasks.py config/settings.py tests/test_celery_tasks.py
git commit -m "feat: implement celery worker tasks and periodic beat scheduling"
```

---

### Task 7: Web UI (Views, Templates, Canvas Streaming JS, and Recipient Selection)

**Files:**
- Create: `apps/core/views.py`
- Create: `apps/accounts/views.py`
- Create: `apps/messenger/views.py`
- Create: `apps/scheduler/views.py`
- Create: `templates/base.html`
- Create: `templates/core/dashboard.html`
- Create: `templates/accounts/list.html`
- Create: `templates/accounts/stream.html`
- Create: `templates/messenger/threads.html`
- Create: `templates/scheduler/schedules.html`
- Create: `templates/scheduler/logs.html`
- Create: `static/js/stream_client.js`
- Test: `tests/test_views.py`

**Interfaces:**
- Produces:
  - Full web dashboard with stats
  - Stream view with Canvas element and native `Ctrl+V` paste interception
  - Schedule creation view with dropdown showing **Recipient Name** primarily (e.g. `Hồ Bách (Thread: 902973772639579)`)

- [ ] **Step 1: Write failing view tests**

```python
# tests/test_views.py
import pytest
from django.contrib.auth.models import User
from django.test import Client
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread

@pytest.mark.django_db
def test_dashboard_and_schedule_views_authenticated():
    user = User.objects.create_user(username="u1", password="pw")
    client = Client()
    client.force_login(user)
    
    # Dashboard
    res = client.get("/")
    assert res.status_code == 200
    
    # Schedules view has recipient option with name
    account = MessengerAccount.objects.create(owner=user, name="Acc1", profile_dir="data/p")
    RecipientThread.objects.create(owner=user, account=account, thread_id="999", recipient_name="Alice Smith")
    res = client.get("/schedules/")
    assert res.status_code == 200
    assert "Alice Smith (Thread: 999)" in res.content.decode()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `devenv shell -- uv run pytest tests/test_views.py -v`
Expected: FAIL (views/templates missing).

- [ ] **Step 3: Implement Views, Templates and JS Client**

Implement `apps/accounts/views.py`, `apps/messenger/views.py`, `apps/scheduler/views.py`, `apps/core/views.py`.

Implement `templates/scheduler/schedules.html`:
- Recipient select options format:
  ```html
  <select name="recipient_id" class="form-select">
    {% for thread in threads %}
      <option value="{{ thread.id }}">
        {% if thread.recipient_name %}
          {{ thread.recipient_name }} (Thread: {{ thread.thread_id }})
        {% else %}
          Thread: {{ thread.thread_id }}
        {% endif %}
      </option>
    {% endfor %}
  </select>
  ```

Implement `static/js/stream_client.js`:
- Connects to `ws://${location.host}/ws/accounts/${accountId}/stream/`
- Receives binary blobs, draws to `<canvas>` via `URL.createObjectURL(new Blob([data]))`
- Intercepts `paste` event on canvas/window:
  ```javascript
  window.addEventListener('paste', (e) => {
      const text = e.clipboardData.getData('text');
      if (text) {
          socket.send(JSON.stringify({ type: 'paste', text: text }));
      }
  });
  ```
- Canvas pointer listeners forwarding clicks, coordinates, and keyboard events.

- [ ] **Step 4: Run test to verify it passes**

Run: `devenv shell -- uv run pytest tests/test_views.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/ templates/ static/ tests/test_views.py
git commit -m "feat: implement web views templates canvas stream js and recipient dropdown"
```

---

### Task 8: End-to-End System Integration & Verification

**Files:**
- Create: `tests/test_e2e_workflow.py`
- Test: `tests/test_e2e_workflow.py`

**Interfaces:**
- Verifies: Full end-to-end integration: User login -> Account profile creation -> Thread name resolution -> Schedule creation with Recipient Name selection -> Celery task execution -> DeliveryLog creation.

- [ ] **Step 1: Write End-to-End integration test**

```python
# tests/test_e2e_workflow.py
import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from apps.accounts.models import MessengerAccount
from apps.messenger.models import RecipientThread
from apps.scheduler.models import ScheduledMessage, DeliveryLog
from apps.scheduler.tasks import dispatch_scheduled_message
from unittest.mock import patch

@pytest.mark.django_db
@patch("apps.scheduler.tasks.send_thread_message")
def test_full_pipeline_flow(mock_send):
    mock_send.return_value = (True, None, None)
    
    # 1. Create admin user
    user = User.objects.create_user(username="master_admin", password="password123")
    client = Client()
    client.login(username="master_admin", password="password123")
    
    # 2. Add Messenger Account
    account = MessengerAccount.objects.create(
        owner=user,
        name="Primary Account",
        profile_dir="data/profiles/primary_acc",
        status=MessengerAccount.Status.ACTIVE,
        fb_user_id="100080858341662"
    )
    
    # 3. Add Thread
    thread = RecipientThread.objects.create(
        owner=user,
        account=account,
        thread_id="902973772639579",
        recipient_name="Hồ Bách",
        name_status=RecipientThread.NameStatus.FETCHED,
    )
    
    # 4. Create Schedule via POST
    response = client.post("/schedules/create/", {
        "account_id": str(account.id),
        "recipient_id": str(thread.id),
        "message_template": "Happy New Year {name}!",
        "schedule_type": ScheduledMessage.ScheduleType.ONCE,
        "run_date": "2027-01-01",
        "run_time": "00:00:00",
    })
    assert response.status_code == 302
    
    schedule = ScheduledMessage.objects.get(recipient=thread)
    assert schedule.message_template == "Happy New Year {name}!"
    
    # 5. Execute scheduled dispatch
    dispatch_scheduled_message(str(schedule.id))
    
    # 6. Verify Delivery Log
    log = DeliveryLog.objects.filter(scheduled_message=schedule).first()
    assert log is not None
    assert log.status == DeliveryLog.Status.SUCCESS
    assert log.rendered_content == "Happy New Year Hồ Bách!"
```

- [ ] **Step 2: Run End-to-End test**

Run: `devenv shell -- uv run pytest tests/test_e2e_workflow.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_workflow.py
git commit -m "test: add end-to-end integration test verifying full automation pipeline"
```
