# Facebook Messenger Automation

An automated Facebook Messenger messaging platform in Python using **Camoufox** (anti-detect browser), **Django 5.x**, **Django Channels** (WebSockets), **PostgreSQL**, and **Celery**.

The system enables scheduling one-off (New Year, birthdays, events) and recurring messages (daily, monthly, yearly) to specific recipients in **GMT+7** (`Asia/Bangkok`), with dynamic placeholders like `{name}` and live canvas browser streaming for account authentication.

---

## Features

- **Admin & Multi-Account Isolation**:
  - Private per-admin ownership of Messenger accounts, recipient threads, and schedules.
  - Global oversight for superusers.
- **Interactive Browser Login via WebSocket**:
  - Live streaming of Camoufox browser session over Django Channels onto an HTML5 `<canvas>`.
  - **Adaptive Frame Diffing**: Captures and transmits frames on interaction (clicks, typing, scroll) and idle diffing.
  - **Keyboard & Clipboard Handling**: Full support for pointer events and native `Ctrl+V` clipboard paste.
  - **Automatic Session Detection**: Inspects cookies for `c_user` to automatically mark accounts active and persist browser profiles to disk.
- **Recipient & Name Resolution**:
  - Ingests raw Facebook Thread IDs (e.g. `902973772639579`) or full Facebook URLs (`https://www.facebook.com/messages/t/902973772639579`).
  - Automated headless Camoufox background worker extracts recipient names from the Messenger DOM (`Write to <Name>` or `Conversation titled <Name>`).
- **Name-Centric Scheduling**:
  - Select recipients easily by **Name** in the schedule creator (with Thread ID context).
  - Supports dynamic placeholders (e.g. `Happy New Year {name}!`).
  - GMT+7 recurrence: `ONCE`, `DAILY`, `MONTHLY` (with month-end clamping), and `YEARLY`.
- **Worker & Audit Trail**:
  - Celery-Beat checks due messages every minute.
  - Automated message typing and dispatch via headless Camoufox.
  - Audit logging of all dispatches with failure screenshots.

---

## Tech Stack & Architecture

- **Runtime**: Python 3.12+ managed with `uv`.
- **System Environment**: Nix via `devenv` (bundles all required graphics/windowing shared libraries: GTK3, NSS, Cairo, Pango, X11, Mesa).
- **Web & Realtime**: Django 5.x + Django Channels running under ASGI (`daphne`).
- **Database**: PostgreSQL (or SQLite default).
- **Task Scheduling**: Celery + Celery-Beat with Redis.
- **Browser Automation**: `camoufox[geoip]`.

---

## Quick Start

### 1. Requirements & Nix Shell
Camoufox requires native graphics dependencies configured in `devenv.nix`. Enter the shell:
```bash
devenv shell
```

### 2. Install Dependencies
```bash
uv sync
```

### 3. Initialize Database & Admin User
```bash
devenv shell -- uv run python manage.py migrate
devenv shell -- uv run python manage.py init_admin
```
*(Default credentials: `admin` / `admin123`)*

### 4. Run Development Stack
You can start all services (Redis, Celery worker, Celery beat, Daphne ASGI server) using:
```bash
./run_dev.sh
```
Or start them individually:
```bash
# 1. Redis
redis-server --daemonize yes

# 2. Celery Worker & Beat
devenv shell -- uv run celery -A config worker --loglevel=info
devenv shell -- uv run celery -A config beat --loglevel=info

# 3. Daphne ASGI Web Server
devenv shell -- uv run daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

Open your browser at **http://127.0.0.1:8000** and sign in.

---

## Running Tests

Run the complete test suite:
```bash
devenv shell -- uv run pytest -v
```
All 12 unit and integration tests will run:
- Recurrence calculation & GMT+7 logic (`test_scheduler_engine.py`)
- Models and relationships (`test_models.py`)
- WebSocket consumer & Ctrl+V paste handling (`test_stream_consumer.py`)
- DOM name extraction service (`test_messenger_service.py`)
- Celery task dispatching (`test_celery_tasks.py`)
- Web views & recipient name dropdowns (`test_views.py`)
- Full End-to-End pipeline (`test_e2e_workflow.py`)
