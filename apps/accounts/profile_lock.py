import os
import time
import fcntl
import signal
import contextlib


def cleanup_stale_profile_locks(profile_dir: str) -> None:
    """
    Removes Firefox/Camoufox profile lock files if present.
    """
    abs_dir = os.path.abspath(profile_dir)
    for lock_name in ("lock", ".parentlock"):
        lock_path = os.path.join(abs_dir, lock_name)
        if os.path.lexists(lock_path):
            try:
                os.unlink(lock_path)
            except OSError:
                pass


def terminate_lingering_profile_browsers(profile_dir: str) -> None:
    """
    Finds and terminates any lingering camoufox-bin / firefox processes holding `profile_dir`,
    then cleans up lock files.
    """
    abs_dir = os.path.abspath(profile_dir)
    if not os.path.exists("/proc"):
        cleanup_stale_profile_locks(abs_dir)
        return

    my_pid = os.getpid()
    matching_pids: list[int] = []

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == my_pid:
            continue
        cmdline_path = f"/proc/{pid}/cmdline"
        try:
            with open(cmdline_path, "rb") as f:
                raw = f.read()
            if not raw:
                continue
            cmdline = raw.decode("utf-8", errors="ignore").replace("\x00", " ")
            if abs_dir in cmdline and ("camoufox" in cmdline or "firefox" in cmdline):
                matching_pids.append(pid)
        except OSError:
            continue

    for pid in matching_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    if matching_pids:
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            still_alive = [p for p in matching_pids if os.path.exists(f"/proc/{p}")]
            if not still_alive:
                break
            time.sleep(0.1)

        for pid in matching_pids:
            if os.path.exists(f"/proc/{pid}"):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        time.sleep(0.1)

    cleanup_stale_profile_locks(abs_dir)


@contextlib.contextmanager
def acquire_profile_lock(profile_dir: str, timeout: float = 60.0):
    """
    Cross-process file lock ensuring only one Camoufox instance accesses a given
    profile_dir at a time across Celery workers and ASGI processes.
    """
    abs_dir = os.path.abspath(profile_dir)
    os.makedirs(os.path.dirname(abs_dir), exist_ok=True)
    lock_file_path = f"{abs_dir}.ops.lock"
    fd = os.open(lock_file_path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for profile lock on {abs_dir}")
                time.sleep(0.25)

        terminate_lingering_profile_browsers(abs_dir)
        yield
    finally:
        try:
            terminate_lingering_profile_browsers(abs_dir)
        except Exception:
            pass
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass
