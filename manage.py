#!/usr/bin/env python
import os
import sys
from pathlib import Path


def _apply_runserver_port_defaults(argv: list[str]) -> list[str]:
    """
    Supports `--port/-p` and `--host` flags plus `DJANGO_PORT` / `PORT` / `DJANGO_HOST`
    environment variables for `manage.py runserver`.
    """
    if len(argv) < 2 or argv[1] != "runserver":
        return list(argv)

    if "-h" in argv[2:] or "--help" in argv[2:]:
        return list(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except Exception:
        pass

    cli_port = None
    cli_host = None
    cleaned: list[str] = [argv[0], argv[1]]
    positional_addrport_idx: int | None = None

    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg in ("--port", "-p") and i + 1 < len(argv):
            cli_port = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--port="):
            cli_port = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--host" and i + 1 < len(argv):
            cli_host = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--host="):
            cli_host = arg.split("=", 1)[1]
            i += 1
            continue

        if not arg.startswith("-") and positional_addrport_idx is None:
            positional_addrport_idx = len(cleaned)
        cleaned.append(arg)
        i += 1

    if positional_addrport_idx is not None and cli_port is None and cli_host is None:
        return cleaned

    host = cli_host or os.environ.get("DJANGO_HOST", "0.0.0.0")
    port = cli_port or os.environ.get("DJANGO_PORT") or os.environ.get("PORT") or "8000"

    if positional_addrport_idx is not None:
        existing = cleaned[positional_addrport_idx]
        if ":" in existing:
            existing_host, existing_port = existing.rsplit(":", 1)
            host = cli_host or existing_host
            port = cli_port or existing_port
        else:
            port = cli_port or existing
            host = cli_host or os.environ.get("DJANGO_HOST", "127.0.0.1")

    try:
        port_num = int(port)
        if not (1 <= port_num <= 65535):
            raise ValueError
    except ValueError as exc:
        raise SystemExit(f"Invalid Django server port: {port!r}. Expected 1-65535.") from exc

    addrport = f"{host}:{port_num}"
    if positional_addrport_idx is not None:
        cleaned[positional_addrport_idx] = addrport
    else:
        cleaned.append(addrport)

    return cleaned


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(_apply_runserver_port_defaults(sys.argv))


if __name__ == "__main__":
    main()
