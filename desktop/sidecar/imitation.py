#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **仿写**：一个节点下的多份代码卡（默写 / 重写）

## 为什么是"多份"

所有者：「仿写也不止写一段代码呀，它可能和笔记一样，有多份代码文件，
毕竟理解的深入，写出的代码也不同」。

```
<项目数据目录>/imitations/<vid>/
├── 第1版.py
├── 第2版.py
└── 第3版-用生成器重写.py     ← 文件名就是标题
```

## 三条硬边界

```
① ⛔ 只写 <data>/imitations/ —— 绝不碰用户源码目录
② 文件名净化：⛔ 路径分隔符 / `..` / 控制字符
③ 单份 ≤512KB
```
"""

from __future__ import annotations

import os
import re

#: 单份仿写最大字节数
MAX_TEXT_BYTES = 512 * 1024

#: 标题里不允许的字符（跨平台非法文件名 + 控制字符）
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class ImitationError(Exception):
    """可读错误（转成 400 返回）"""

    def __init__(self, message: str, code: str = "imitation"):
        super().__init__(message)
        self.message = message
        self.code = code


def _safe_title(title: str) -> str:
    """标题 → 安全文件名（不带扩展名）"""
    t = _BAD_CHARS.sub(" ", title or "").strip().strip(".")
    t = re.sub(r"\s+", " ", t).strip()
    return (t or "未命名")[:80]


def _root(data_dir: str, vid: int) -> str:
    if not isinstance(vid, int) or vid <= 0:
        raise ImitationError("缺少节点 id", "need_vid")
    return os.path.join(data_dir, "imitations", str(vid))


def _safe_name(name: str) -> str:
    n = (name or "").strip()
    if not n or "/" in n or "\\" in n or n in (".", ".."):
        raise ImitationError("文件名不合法", "bad_name")
    return n


def _path(data_dir: str, vid: int, name: str) -> str:
    return os.path.join(_root(data_dir, vid), _safe_name(name))


def _lines(text: str) -> int:
    return text.count("\n") + (0 if text.endswith("\n") or not text else 1)


def list_items(data_dir: str, vid: int) -> dict:
    """列出该节点下的所有仿写（按更新时间排序）"""
    root = _root(data_dir, vid)
    if not os.path.isdir(root):
        return {"items": [], "next": 1}

    items: list[dict] = []
    for fn in sorted(os.listdir(root)):
        p = os.path.join(root, fn)
        if not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
            with open(p, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        text = raw.decode("utf-8", "replace")
        stem, ext = os.path.splitext(fn)
        items.append(
            {
                "name": fn,
                "title": stem,
                "ext": ext.lstrip("."),
                "lines": _lines(text),
                "updated_at": int(st.st_mtime),
            }
        )
    items.sort(key=lambda x: x["updated_at"])
    return {"items": items, "next": len(items) + 1}


def read_item(data_dir: str, vid: int, name: str) -> dict:
    p = _path(data_dir, vid, name)
    if not os.path.isfile(p):
        raise ImitationError("这份仿写不存在（可能已被删除）", "missing")
    try:
        with open(p, "rb") as f:
            raw = f.read(MAX_TEXT_BYTES + 1)
    except OSError:
        raise ImitationError("没有权限读这个文件", "open_failed") from None
    if len(raw) > MAX_TEXT_BYTES:
        raise ImitationError(f"超过 {MAX_TEXT_BYTES // 1024} KB 上限", "too_large")
    if b"\x00" in raw:
        raise ImitationError("内容里有二进制字符", "binary")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ImitationError("不是 UTF-8 文本", "not_utf8") from None
    stem, ext = os.path.splitext(name)
    return {"name": name, "title": stem, "ext": ext.lstrip("."), "text": text}


def write_item(data_dir: str, vid: int, name: str, text: str) -> dict:
    """保存（不存在则创建）"""
    p = _path(data_dir, vid, name)
    data = text.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise ImitationError(f"超过 {MAX_TEXT_BYTES // 1024} KB 上限", "too_large")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, "wb") as f:
            f.write(data)
    except OSError:
        raise ImitationError("保存失败（没有写入权限）", "write_failed") from None
    stem, ext = os.path.splitext(name)
    return {"name": name, "title": stem, "ext": ext.lstrip("."), "lines": _lines(text)}


def create_item(data_dir: str, vid: int, ext: str) -> dict:
    """新建一份空白仿写，标题自动「第 N 版」"""
    ext = "".join(ch for ch in (ext or "txt") if ch.isalnum())[:10] or "txt"
    root = _root(data_dir, vid)
    os.makedirs(root, exist_ok=True)
    existing = {fn for fn in os.listdir(root) if os.path.isfile(os.path.join(root, fn))}
    n = len(existing) + 1
    while True:
        name = f"第{n}版.{ext}"
        if name not in existing:
            break
        n += 1
    p = os.path.join(root, name)
    with open(p, "wb") as f:
        f.write(b"")
    return {"name": name, "title": os.path.splitext(name)[0], "ext": ext, "lines": 0}


def remove_item(data_dir: str, vid: int, name: str) -> dict:
    p = _path(data_dir, vid, name)
    if not os.path.isfile(p):
        raise ImitationError("这份仿写不存在", "missing")
    try:
        os.remove(p)
    except OSError:
        raise ImitationError("删除失败（没有权限）", "remove_failed") from None
    return {"removed": name}


def rename_item(data_dir: str, vid: int, name: str, title: str) -> dict:
    """改名（标题 → 新文件名，扩展名不变）"""
    src = _path(data_dir, vid, name)
    if not os.path.isfile(src):
        raise ImitationError("这份仿写不存在", "missing")
    _, ext = os.path.splitext(name)
    new_name = f"{_safe_title(title)}{ext}"
    if new_name == name:
        return {"name": name, "title": os.path.splitext(name)[0]}
    dst = os.path.join(os.path.dirname(src), new_name)
    if os.path.exists(dst):
        raise ImitationError("同名的仿写已经存在", "exists")
    try:
        os.rename(src, dst)
    except OSError:
        raise ImitationError("改名失败（没有权限）", "rename_failed") from None
    return {"name": new_name, "title": os.path.splitext(new_name)[0]}
