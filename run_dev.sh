#!/usr/bin/env bash
set -e

if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

SERVER_HOST="${DJANGO_HOST:-0.0.0.0}"
SERVER_PORT="${DJANGO_PORT:-${PORT:-8000}}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        -p|--port)
            SERVER_PORT="$2"
            shift 2
            ;;
        --port=*)
            SERVER_PORT="${1#*=}"
            shift
            ;;
        -H|--host)
            SERVER_HOST="$2"
            shift 2
            ;;
        --host=*)
            SERVER_HOST="${1#*=}"
            shift
            ;;
        -h|--help)
            echo "Usage: ./run_dev.sh [--port <port>] [--host <host>]"
            echo "Defaults can also be set via DJANGO_PORT (or PORT) and DJANGO_HOST in .env"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./run_dev.sh [--port <port>] [--host <host>]"
            exit 1
            ;;
    esac
done

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

echo "3. Starting Celery Worker (shared warm-browser threads) & Celery Beat in background..."
pkill -f "celery -A config" 2>/dev/null || true
pkill -f "camoufox.*$PWD/data/profiles" 2>/dev/null || true
rm -f celerybeat-schedule*
sleep 0.5
devenv shell -- uv run celery -A config worker --pool=threads --concurrency=6 --loglevel=info &
CELERY_WORKER_PID=$!
devenv shell -- uv run celery -A config beat --loglevel=info &
CELERY_BEAT_PID=$!

trap "echo 'Stopping background workers...'; kill $CELERY_WORKER_PID $CELERY_BEAT_PID 2>/dev/null || true; pkill -f 'celery -A config' 2>/dev/null || true; pkill -f \"camoufox.*$PWD/data/profiles\" 2>/dev/null || true; exit" SIGINT SIGTERM

echo "4. Starting Django ASGI Web Server (Daphne with auto-reload) on http://127.0.0.1:${SERVER_PORT} (bound to ${SERVER_HOST}:${SERVER_PORT})..."
devenv shell -- uv run python manage.py runserver "${SERVER_HOST}:${SERVER_PORT}"
