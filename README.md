# Facebook Messenger Automation

An automated Facebook Messenger messaging platform in Python using **Camoufox** (anti-detect browser), **Django 5.x**, **Django Channels** (WebSockets), **PostgreSQL / MySQL / SQLite**, and **Celery**.

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
- **Database Choices**:
  - **PostgreSQL** (`psycopg`)
  - **MySQL / MariaDB** (`mysqlclient` / `PyMySQL`)
  - **SQLite** (Default for zero-setup local development)
- **Task Scheduling**: Celery + Celery-Beat with Redis.
- **Browser Automation**: `camoufox[geoip]`.

---

## Comprehensive Setup Guide

### 1. Prerequisites (Nix & Devenv)
Camoufox requires native graphics and windowing system libraries (`libgtk-3`, `libX11`, `nss`, `dbus`, `mesa`). The provided `devenv.nix` and `devenv.yaml` configure these automatically:

```bash
# Enter the devenv nix shell
devenv shell
```

### 2. Environment Configuration (`.env`)
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` to configure your preferred database and settings:

#### Database Setup Options:

* **Option A: SQLite (Default, Zero-Setup)**:
  ```dotenv
  DB_ENGINE=sqlite
  DB_NAME=db.sqlite3
  ```

* **Option B: PostgreSQL**:
  ```bash
  # Create database and user (if not already existing)
  createdb messenger_automation
  ```
  In `.env`:
  ```dotenv
  DB_ENGINE=postgresql
  DB_NAME=messenger_automation
  DB_USER=postgres
  DB_PASSWORD=your_password
  DB_HOST=localhost
  DB_PORT=5432
  ```

* **Option C: MySQL / MariaDB**:
  ```sql
  CREATE DATABASE messenger_automation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  ```
  In `.env`:
  ```dotenv
  DB_ENGINE=mysql
  DB_NAME=messenger_automation
  DB_USER=root
  DB_PASSWORD=your_password
  DB_HOST=localhost
  DB_PORT=3306
  ```

---

### 3. Install Python Dependencies
Using `uv`:
```bash
devenv shell -- uv sync
```

---

### 4. Database Migrations & Admin Initialization
Run database migrations and initialize the default administrator account:
```bash
devenv shell -- uv run python manage.py migrate
devenv shell -- uv run python manage.py init_admin
```
*(Default credentials created: **username**: `admin`, **password**: `admin123`)*

To create your own custom superuser:
```bash
devenv shell -- uv run python manage.py createsuperuser
```

---

### 5. Running the Application Stack

You can launch all services (Redis, Celery Worker, Celery Beat, and Daphne ASGI server) with a single command:
```bash
./run_dev.sh
```

#### Running Services Manually:
If you prefer running services in separate terminals:

1. **Redis Server**:
   ```bash
   redis-server --daemonize yes
   ```

2. **Celery Worker**:
   ```bash
   devenv shell -- uv run celery -A config worker --loglevel=info
   ```

3. **Celery Beat (Periodic Scheduler)**:
   ```bash
   devenv shell -- uv run celery -A config beat --loglevel=info
   ```

4. **Daphne ASGI Web Server**:
   ```bash
   devenv shell -- uv run daphne -b 127.0.0.1 -p 8000 config.asgi:application
   ```

Now open **http://127.0.0.1:8000** in your browser.

---

## User Workflow Guide

### 1. Connect a Facebook Account
1. Log into the web dashboard.
2. Navigate to **Accounts** &rarr; click **+ Add / Connect Account**.
3. Give your account a label (e.g. `Personal Messenger`).
4. You are directed to the live stream canvas.
5. Log into Facebook inside the stream:
   - Click to focus fields and type your credentials.
   - Use <kbd>Ctrl+V</kbd> (or the toolbar **Paste** button) to paste text or 2FA codes.
6. The system automatically detects your `c_user` login cookie, records your Facebook User ID, saves the persistent browser profile to `data/profiles/<account_id>`, and redirects you back to the account list.

### 2. Add Recipients & Threads
1. Navigate to **Recipients & Threads**.
2. Select the Facebook Account to send messages from.
3. Paste the Thread ID (e.g. `902973772639579`) or the full conversation URL (`https://www.facebook.com/messages/t/902973772639579`).
4. Click **Add & Fetch Name**.
5. A background worker inspects the Messenger thread and fetches the recipient's human name (e.g. `Hồ Bách`).

### 3. Schedule Messages
1. Navigate to **Schedules**.
2. In the **Select Recipient** dropdown, choose the recipient by their human name:
   `Hồ Bách (Thread: 902973772639579)`.
3. Choose the recurrence rule:
   - `ONCE`: Specific date and time.
   - `DAILY`: Repeated every day at specific time (GMT+7).
   - `MONTHLY`: Repeated on a specific day of each month.
   - `YEARLY`: Annual event or birthday.
4. Type your message template. You can include `{name}`, which will dynamically resolve to the recipient's name at send time:
   ```text
   Happy Birthday {name}! Wishing you a fantastic year filled with happiness and success!
   ```
5. Click **Create Schedule**.
6. You can test your schedule immediately by clicking **Send Now**.

### 4. Audit & Logs
- Navigate to **Delivery Logs** to view timestamps (GMT+7), delivery statuses, rendered message bodies, and error screenshots if any send fails.

---

## Running Automated Tests

Run the full test suite using `pytest`:
```bash
devenv shell -- uv run pytest -v
```

All 12 test suites will run:
- Recurrence calculation & GMT+7 logic (`test_scheduler_engine.py`)
- Models and relationships (`test_models.py`)
- WebSocket consumer & Ctrl+V paste handling (`test_stream_consumer.py`)
- DOM name extraction service (`test_messenger_service.py`)
- Celery task dispatching (`test_celery_tasks.py`)
- Web views & recipient name dropdowns (`test_views.py`)
- Full End-to-End pipeline (`test_e2e_workflow.py`)
