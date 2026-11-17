#!/usr/bin/env bash
set -e

echo "=== Facebook Messenger Automation Services ==="
echo "1. Checking/Starting Redis server..."
if ! pgrep -x "redis-server" > /dev/null; then
    redis-server --daemonize yes
    echo "Started redis-server in background."
else
    echo "redis-server is already running."
fi

echo "2. Applying database migrations..."
devenv shell -- uv run python manage.py migrate

echo "3. Starting Celery Worker & Celery Beat in background..."
devenv shell -- uv run celery -A config worker --loglevel=info &
CELERY_WORKER_PID=$!
devenv shell -- uv run celery -A config beat --loglevel=info &
CELERY_BEAT_PID=$!

trap "echo 'Stopping background workers...'; kill $CELERY_WORKER_PID $CELERY_BEAT_PID 2>/dev/null || true; exit" SIGINT SIGTERM

echo "4. Starting Django ASGI Web Server (Daphne) on http://127.0.0.1:8000..."
devenv shell -- uv run daphne -b 0.0.0.0 -p 8000 config.asgi:application
