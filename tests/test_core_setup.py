import pytest
from django.conf import settings
from manage import _apply_runserver_port_defaults

def test_django_settings_configured():
    assert settings.INSTALLED_APPS is not None
    assert "channels" in settings.INSTALLED_APPS
    assert settings.ASGI_APPLICATION == "config.asgi.application"
    assert settings.TIME_ZONE == "Asia/Bangkok"
    assert hasattr(settings, "DJANGO_HOST")
    assert hasattr(settings, "DJANGO_PORT")


def test_manage_runserver_port_option(monkeypatch):
    monkeypatch.setenv("DJANGO_HOST", "0.0.0.0")
    monkeypatch.setenv("DJANGO_PORT", "9001")

    # Uses DJANGO_HOST / DJANGO_PORT when no positional addrport is given
    assert _apply_runserver_port_defaults(["manage.py", "runserver"]) == [
        "manage.py", "runserver", "0.0.0.0:9001",
    ]

    # Supports --port / -p and --host flags
    assert _apply_runserver_port_defaults(["manage.py", "runserver", "--port", "8085"]) == [
        "manage.py", "runserver", "0.0.0.0:8085",
    ]
    assert _apply_runserver_port_defaults(["manage.py", "runserver", "--host", "127.0.0.1", "-p", "8085"]) == [
        "manage.py", "runserver", "127.0.0.1:8085",
    ]

    # Preserves explicit positional addrport
    assert _apply_runserver_port_defaults(["manage.py", "runserver", "127.0.0.1:7777"]) == [
        "manage.py", "runserver", "127.0.0.1:7777",
    ]

    # Leaves non-runserver commands untouched
    assert _apply_runserver_port_defaults(["manage.py", "migrate"]) == ["manage.py", "migrate"]
