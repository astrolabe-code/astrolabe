#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **给 Python 找到 `app/` 目录**（解析器与 vid 算法都在那里）

## 为什么单独一个模块

```\n * `codeparser/`（解析器）依赖它\n * `graph/identity.py`（vid 算法）也依赖它 —— **手补节点也要用**\n ```\n *
之前只在 `parser_bridge` 里加了 `sys.path`，于是：
**只要没先走过解析，手补节点就会 `ModuleNotFoundError: graph`**（实测踩到过）。

⇒ 统一在这里做，任何用到它们的模块 `import paths` 一下即可。

⚠ 打包后（PyInstaller）这些模块直接进了包，`_APP_CANDIDATES` 都不存在也没关系 ——
  只有在**源码运行**时才需要把 `app/` 加进 `sys.path`。
"""

from __future__ import annotations

import os
import sys

_CANDIDATES = [
    os.environ.get("ASTROLABE_APP_DIR") or "",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app")),
]


def ensure() -> str:
    """把 `app/` 挂到 `sys.path`；返回实际用的路径（找不到返回空串）"""
    for p in _CANDIDATES:
        if p and os.path.isdir(os.path.join(p, "codeparser")) and p not in sys.path:
            sys.path.insert(0, p)
            return p
    # 已经在包里（PyInstaller）⇒ 什么都别做
    return ""


ensure()
