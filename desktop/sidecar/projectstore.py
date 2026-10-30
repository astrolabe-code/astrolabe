#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **项目清单**（个人版唯一的全局状态）

## 为什么还需要一个「清单」

```\n * 数据已经跟着源码目录走了（`<源码>/.astrolabe/`）\n * 但软件得知道"我读过哪几个目录" ⇒ 这份清单只记路径，⛔ 不记内容\n ```\n *
所有者：「个人版怎么还有库跟这种东西？库在个人版里目前无意义，
有意义的只是源码目录的地址。你直接把数据放在源码目录里不就完了？」

```\n * 笔记、索引、回收站  ⇒ 都在 <源码目录>/.astrolabe/（跟着代码走）\n * 这份清单          ⇒ 在 <数据目录>/projects.json（只记路径，几百字节）\n * 空白结构（无源码） ⇒ 在 <数据目录>/structures/<名字>/.astrolabe/\n ```\n *
⚠ 清单丢了不致命：笔记还在源码目录里，重新导入一次就能扫回来。
"""

from __future__ import annotations

import json
import os

import library


def _path() -> str:
    return os.path.join(library.data_dir(), "projects.json")


def load() -> list[dict]:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def list_all() -> list[dict]:
    """按创建时间倒序（最近的在前面）"""
    return sorted(load(), key=lambda x: str(x.get("created_at") or ""), reverse=True)


def get(ref: str) -> dict | None:
    for it in load():
        if it.get("ref") == ref:
            return it
    return None


def upsert(entry: dict) -> dict:
    items = load()
    for i, it in enumerate(items):
        if it.get("ref") == entry.get("ref"):
            items[i] = {**it, **entry}
            _save(items)
            return items[i]
    items.append(entry)
    _save(items)
    return entry


def remove(ref: str) -> None:
    _save([it for it in load() if it.get("ref") != ref])


def unique_name(base: str) -> str:
    """名字不能重：重了加 1、2、3……（所有者 2026-10-30：「后面加个数字标号」）"""
    base = (base or "未命名").strip() or "未命名"
    names = {str(it.get("name") or "") for it in load()}
    if base not in names:
        return base
    i = 1
    while f"{base}{i}" in names:
        i += 1
    return f"{base}{i}"


def unique_ref(base: str) -> str:
    refs = {str(it.get("ref") or "") for it in load()}
    if base not in refs:
        return base
    i = 1
    while f"{base}-{i}" in refs:
        i += 1
    return f"{base}-{i}"
