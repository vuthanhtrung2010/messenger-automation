import pytest
from django.conf import settings

def test_django_settings_configured():
    assert settings.INSTALLED_APPS is not None
    assert "channels" in settings.INSTALLED_APPS
    assert settings.ASGI_APPLICATION == "config.asgi.application"
    assert settings.TIME_ZONE == "Asia/Bangkok"
