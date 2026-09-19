"""Astrolabe · ASGI 入口

★ DEPLOYMENT.md：生产用 gunicorn + uvicorn worker（ASGI 就绪）
⇒ 将来并发上来时【随时可切换】，不用重构（ARCHITECTURE.md A7 第 5 条）
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")

application = get_asgi_application()
