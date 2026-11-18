import os
from django.core.asgi import get_asgi_application
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = ASGIStaticFilesHandler(get_asgi_application())

import apps.accounts.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            apps.accounts.routing.websocket_urlpatterns
        )
    ),
})
