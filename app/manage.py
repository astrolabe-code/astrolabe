#!/usr/bin/env python
"""Astrolabe · Django 管理入口。"""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "无法导入 Django —— 请确认已安装依赖（容器内已装；本机需 pip install -r requirements.txt）"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
