"""Astrolabe · WSGI 入口（兼容用；生产以 ASGI 为主）。"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")

application = get_wsgi_application()
