#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ **笔记文件**（markdown + frontmatter）—— 个人版的真相源

## 为什么笔记存文件，不存数据库

所有者：

> 「sqlite 存储 markdown 文档内容怕是有点不容易哦，个人版可以直接把
>   markdown 文档存成文件，sqlite 只记录位置与对应关系就行」

⇒ 于是这个库的定位是：

```\n * 文件 = 真相（source of truth）—— 可读、可拷、可 git、可用任何编辑器打开\n * SQLite = 索引（可删、可重建）—— 只记锚点/编号/类型/时间/文件名\n ```\n *
⚠ 推论：**数据库损坏不丢笔记**，扫一遍目录就能重建。

## 文件格式

```markdown
---
no: 37
kind: pitfall
node: coalesce
anchor: src/net/tcp.c:412
title: 窗口太小时会退化
time: 2026-10-29T10:44:31+08:00
project: flask
---

正文（裸 markdown）
```

⚠ frontmatter 刻意用**单行 key: value**，不引 PyYAML ——
  少一个依赖、少一个打包风险，而这里只需要最简的一层。
"""

from __future__ import annotations

import os
import re

# ★ 文件名/标题里不能出现的字符（Windows 最严：\ / : * ? " < > |）
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# 只取第一段用于文件名的长度上限（Windows 路径总长有限）
_NAME_MAX = 40

FM_KEYS = ("no", "kind", "node", "anchor", "title", "time", "project")


def safe_name(name: str) -> str:
    """节点名 → 可用作文件名的片段"""
    s = _BAD.sub("_", (name or "").strip())
    s = re.sub(r"\s+", "_", s)
    return (s or "note")[:_NAME_MAX]


def file_name(no: int, node_name: str) -> str:
    """`0037-coalesce.md` —— ★ 编号做前缀：天然唯一、和界面 №037 一致、可排序 ⚠"""
    return f"{int(no):04d}-{safe_name(node_name)}.md"


def _one_line(v: object) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def dump(meta: dict, body: str) -> str:
    """写出一篇笔记的完整文本"""
    lines = ["---"]
    for k in FM_KEYS:
        if k in meta and meta[k] is not None:
            lines.append(f"{k}: {_one_line(meta[k])}")
    # ★ 额外的键也保留（将来加字段不用改这里）
    for k, v in meta.items():
        if k not in FM_KEYS and v is not None and not str(k).startswith("_"):
            lines.append(f"{k}: {_one_line(v)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + (body or "")


def parse(text: str) -> tuple[dict, str]:
    """拆成 (frontmatter 字典, 正文)

    ⚠ 解析失败（没有 frontmatter / 没闭合）⇒ 返回 ({}, 全文)，
      **不抛异常** —— 用户可能手写了一个笔记文件，不能因此让整库索引失败。
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text

    head = text[3:end]
    body = text[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]

    meta: dict[str, str] = {}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # ⚠ 只按**第一个**冒号切 —— `anchor: src/net/tcp.c:412` 的冒号要留着
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()

    if "no" in meta:
        try:
            meta["no"] = int(meta["no"])
        except ValueError:
            pass
    return meta, body


def read_file(path: str) -> tuple[dict, str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())


def write_file(path: str, meta: dict, body: str) -> None:
    """★ 原子写：先写 .tmp 再改名

    ⚠ 直接覆盖的风险：写到一半断电/崩溃 ⇒ 文件半截，笔记就毁了。
      改名在同一个文件系统里是原子的 ⇒ 要么旧内容、要么新内容 ✅
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(dump(meta, body))
    os.replace(tmp, path)
