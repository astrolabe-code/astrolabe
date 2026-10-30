#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ **笔记库**（vault）—— 一个文件夹装所有书

## 结构

```
<库根>/
├─ .astrolabe/
│   ├─ index.db          SQLite 索引（可删、可重建）
│   └─ config.json       库配置（名字 / 创建时间 / 版本）
├─ flask/                一个项目一个子目录
│   ├─ 0001-coalesce.md
│   └─ 0002-init.md
└─ redis/
    └─ 0001-dict.md
```

## 三条设计决定（所有者 2026-10-29 确认）

```
① 库中心，不是应用中心   程序只是"打开库的工具"，库在哪都行
② 一个库装所有项目       一个文件夹管全部，能用 Obsidian 一次打开
③ 默认位置按应用中心给   首次启动建议 <exe>/data/books/main，⛔ 不让人先做决定
```

⚠★ **索引跟着库走**（`.astrolabe/index.db`）：
  库整个拷走 ⇒ 笔记 + 索引 + 配置一起走；换库 ⇒ 索引自然重建，不会串味。
"""

from __future__ import annotations

import json
import os
import re
import time

INDEX_DIR = ".astrolabe"
DB_NAME = "index.db"
CONF_NAME = "config.json"


def data_dir() -> str:
    """程序的数据目录（`userData`，绿色版 ⇒ exe 同目录的 data/）"""
    return os.environ.get("ASTROLABE_DATA_DIR") or os.path.join(os.getcwd(), "data")


def default_root() -> str:
    """默认库根：`<数据目录>/notes`（绿色版 ⇒ 程序旁边）

    ⚠ 路径浅一点：用户可能真去文件管理器里翻它，`books/main` 这种嵌套没必要。
    """
    return os.path.join(data_dir(), "notes")


def pref_path() -> str:
    """★ 库位置的偏好文件 —— ⚠ **不能存在库里**（换库时鸡生蛋）"""
    return os.path.join(data_dir(), "config.json")


def load_pref() -> dict:
    try:
        with open(pref_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def save_pref(**kv) -> None:
    cur = load_pref()
    cur.update(kv)
    os.makedirs(os.path.dirname(pref_path()), exist_ok=True)
    with open(pref_path(), "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)


def resolve_root() -> str:
    """★★ 库根的三级取值：环境变量 → 用户指定 → 默认 ⚠

    ```\n * ASTROLABE_LIBRARY   调试/测试用（最高优先）
 * config.json 里的值    用户在界面里选过的位置
 * <数据目录>/notes      没指定过时的默认
 ```\n
    """
    env = (os.environ.get("ASTROLABE_LIBRARY") or "").strip()
    if env:
        return os.path.abspath(env)
    saved = str(load_pref().get("library_root") or "").strip()
    if saved:
        return os.path.abspath(saved)

    # ⚠ 向后兼容：老版本把库放在 `<数据目录>/books/main`。
    #   默认改成 `<数据目录>/notes` 之后，老用户的笔记不能"消失" ⚠
    legacy = os.path.join(data_dir(), "books", "main")
    if os.path.isdir(os.path.join(legacy, INDEX_DIR)):
        return os.path.abspath(legacy)

    return os.path.abspath(default_root())


def ensure_root(root: str) -> str:
    """建库（幂等）。已存在就只补缺失的目录/配置"""
    root = os.path.abspath(root)
    meta_dir = os.path.join(root, INDEX_DIR)
    os.makedirs(meta_dir, exist_ok=True)

    conf_path = os.path.join(meta_dir, CONF_NAME)
    if not os.path.exists(conf_path):
        conf = {
            "version": 1,
            "name": os.path.basename(root.rstrip(os.sep)) or "我的笔记",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        with open(conf_path, "w", encoding="utf-8") as f:
            json.dump(conf, f, ensure_ascii=False, indent=2)
        os.makedirs(os.path.join(root, ".trash"), exist_ok=True)

    return root


def db_path(root: str) -> str:
    return os.path.join(root, INDEX_DIR, DB_NAME)


def load_config(root: str) -> dict:
    p = os.path.join(root, INDEX_DIR, CONF_NAME)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def project_dir_name(name: str) -> str:
    """项目名 → 库内子目录名

    ⚠ 只允许安全字符；中文保留（Windows 支持，且用户看得懂更亲）
    """
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", (name or "").strip())
    s = re.sub(r"\s+", "-", s).strip(".-")
    return (s or "project")[:60]
