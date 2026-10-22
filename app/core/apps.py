"""★ `core` 的 AppConfig —— **只为了在启动时注册信号** ⚠"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # ⚠ 必须 import：* 信号是在 `search.sync` 模块导入时注册的 ⚠
        from search import sync  # noqa: F401
