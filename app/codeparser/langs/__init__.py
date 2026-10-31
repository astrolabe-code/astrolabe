#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **语言注册表 + 失败隔离**

```\n load("c")  ⇒ (CSpec, 查询源码)     成功\n load("xx") ⇒ None                 该语言坏了，⛔ 不影响别的语言\n ```\n *
⚠★ 一条语言加载失败时**只降级它自己**：
   · 该语言的文件只产出"文件节点"
   · 其它语言照常
   · 项目**不算解析失败**（否则会连带禁止写笔记，那是完全错误的后果）
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

#: 语言名 → 处理模块名（都在本包里）
_MODULES = {
    "c": ".c",
    "cpp": ".cpp",
    "python": ".python",
    "java": ".java",
}

_loaded: dict[str, object] = {}


def load(language: str):
    """返回 `LangSpec` 实例；不可用则返回 None（⛔ 不抛异常）"""
    if language in _loaded:
        return _loaded[language]

    mod_name = _MODULES.get(language)
    if not mod_name:
        _loaded[language] = None
        return None

    try:
        import importlib

        mod = importlib.import_module(mod_name, __package__)
        spec = None
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if isinstance(obj, type) and issubclass(obj, object) and hasattr(obj, "query_file"):
                if getattr(obj, "language", "") == language:
                    spec = obj()
                    break
        if spec is None:
            raise RuntimeError("找不到 LangSpec 子类")
        _loaded[language] = spec
        return spec
    except Exception as exc:  # noqa: BLE001 —— ★ 隔离：坏一种不拖累其它
        log.warning("语言 %s 的处理模块不可用（该语言将退回遍历式解析器）：%s", language, exc)
        _loaded[language] = None
        return None
