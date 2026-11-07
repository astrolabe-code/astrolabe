#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **卡片盒的链**：深入（parent）＋ 引用（links）

## 定稿（D139，2026-11-07）

```
深入 = 生长：在这张笔记基础上继续写，新开一张空白卡，挂成子代
参见 = 引用：像论文引文，对象是**已经写好**的卡，⛔ 不产生新卡
看链 = 思考模式白板（纯读，可连可断）
```

两层关系加起来才是卢曼卡片盒：编号延续（树状，一张卡一个前驱、
可有多个后继）＋ 交叉引用（多对多，成网）。
⛔ 防环只校验 parent；虚线引用随便连，成环也没关系。

## 为什么是全局一份

所有者：「跨节点引用在白板上要能在看见，搜到，哪怕夸项目也是。」
⇒ `links.json` 从各项目数据目录搬到**全局数据目录**（`library.data_dir()`），
一份管所有项目；卡片 id 必须带项目，否则各项目独立的 `n0001` 会撞车：

```
note:<project_ref>/<note_ref>
```

⛔ 仿写不进这张表 ——「仿写是检验学习的，不是用来思考的」。
旧格式（`note:n0001`、`copy:…`）在 `load()` 里自动忽略，不迁移。
"""

from __future__ import annotations

import json
import os
import tempfile

import library


class LinkError(Exception):
    def __init__(self, message: str, code: str = "link"):
        super().__init__(message)
        self.message = message
        self.code = code


def note_id(project_ref: str, ref: str) -> str:
    """★ 卡片 id 必须带项目：各项目 SQLite 独立编号，n0001 会重复"""
    return f"note:{project_ref}/{ref}"


def _valid_id(card: str) -> bool:
    return isinstance(card, str) and card.startswith("note:") and "/" in card[5:]


def parse_id(card: str) -> tuple[str, str]:
    """`note:<项目>/<笔记ref>` → (项目, 笔记ref)"""
    if not _valid_id(card):
        raise LinkError("卡片 id 不合法", "bad_id")
    project, ref = card[5:].split("/", 1)
    return project, ref


def _path() -> str:
    return os.path.join(library.data_dir(), "links.json")


def load() -> dict:
    """读全局关系表；⛔ 旧格式 id 与 copy: 记录一律忽略（D139 已裁定不迁移）"""
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}

    table: dict = {}
    for cid, rec in raw.items():
        if not _valid_id(cid) or not isinstance(rec, dict):
            continue
        parent = rec.get("parent")
        links = [x for x in (rec.get("links") or []) if _valid_id(x)]
        table[cid] = {
            "parent": parent if _valid_id(parent) else None,
            "links": links,
        }
    return table


def save(table: dict) -> None:
    """原子写（临时文件 + 替换），避免中途崩溃留下半个 JSON"""
    root = library.data_dir()
    os.makedirs(root, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=root, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(table, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path())
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise LinkError("写 links.json 失败", "write_failed") from None


def _rec(table: dict, card: str) -> dict:
    if not _valid_id(card):
        raise LinkError("卡片 id 不合法", "bad_id")
    rec = table.get(card)
    if not isinstance(rec, dict):
        rec = {}
        table[card] = rec
    rec.setdefault("parent", None)
    rec["links"] = [x for x in (rec.get("links") or []) if _valid_id(x)]
    return rec


def _would_cycle(table: dict, child: str, parent: str) -> bool:
    """parent 链向上走，若撞回 child 就是环"""
    seen: set[str] = set()
    cur: str | None = parent
    while cur and cur not in seen:
        if cur == child:
            return True
        seen.add(cur)
        r = table.get(cur)
        cur = r.get("parent") if isinstance(r, dict) else None
    return False


def set_parent(child: str, parent: str | None) -> dict:
    """★★ 挂 / 改 / 断「深入」边；`parent` 为空 = 断链

    · 一张卡只有一个父亲：已有父亲时**替换**旧边（D139 裁定）
    · 只校验 parent 不成环；断链不动卡片、不动它的子代（子树跟着它一起脱离）
    """
    table = load()
    rec = _rec(table, child)
    old = rec.get("parent")
    new_parent = (parent or "").strip() or None
    if new_parent:
        if not _valid_id(new_parent):
            raise LinkError("父卡 id 不合法", "bad_id")
        if new_parent == child:
            raise LinkError("不能把自己挂到自己下面", "cycle")
        if _would_cycle(table, child, new_parent):
            raise LinkError("不能把祖先挂到自己的后代下面", "cycle")
        _rec(table, new_parent)
    rec["parent"] = new_parent
    save(table)
    return {"child": child, "parent": new_parent, "replaced": old}


def add_reference(a: str, b: str) -> dict:
    """★★ 挂一条「参见」（双向可见）：两边都写，⛔ 不新建卡"""
    if a == b:
        raise LinkError("不能引用自己", "same_card")
    table = load()
    ra, rb = _rec(table, a), _rec(table, b)
    if b not in ra["links"]:
        ra["links"].append(b)
    if a not in rb["links"]:
        rb["links"].append(a)
    save(table)
    return {"a": a, "b": b}


def remove_reference(a: str, b: str) -> dict:
    """去一条「参见」（双向都清）"""
    table = load()
    for x, y in ((a, b), (b, a)):
        rec = table.get(x)
        if isinstance(rec, dict):
            rec["links"] = [i for i in (rec.get("links") or []) if i != y]
    save(table)
    return {"a": a, "b": b}


def on_delete(card: str) -> dict:
    """★★ 删卡：子代接回父卡（⛔ 不跟着删）、指向它的引用清掉"""
    table = load()
    rec = table.pop(card, None) or {}
    parent = rec.get("parent")

    moved: list[str] = []
    for cid, r in table.items():
        if isinstance(r, dict) and r.get("parent") == card:
            r["parent"] = parent
            moved.append(cid)

    cleared: list[str] = []
    for cid, r in table.items():
        if isinstance(r, dict) and card in (r.get("links") or []):
            r["links"] = [i for i in r["links"] if i != card]
            cleared.append(cid)

    save(table)
    return {"moved": moved, "cleared": cleared}


def info(card: str) -> dict:
    table = load()
    rec = table.get(card) if isinstance(table.get(card), dict) else {}
    children = [
        cid
        for cid, r in table.items()
        if isinstance(r, dict) and r.get("parent") == card
    ]
    return {
        "parent": rec.get("parent"),
        "links": list(rec.get("links") or []),
        "children": children,
    }


def all_info() -> dict:
    """整张表（列表接口 / 白板一次拿全）"""
    table = load()
    out: dict[str, dict] = {}
    for cid in table:
        out[cid] = info_of(table, cid)
    return out


def info_of(table: dict, cid: str) -> dict:
    rec = table.get(cid) if isinstance(table.get(cid), dict) else {}
    return {
        "parent": rec.get("parent"),
        "links": list(rec.get("links") or []),
        "children": [
            x
            for x, y in table.items()
            if isinstance(y, dict) and y.get("parent") == cid
        ],
    }


def related(ids: list[str]) -> list[str]:
    """★ 白板用：给定当前节点的一批卡，返回「它们 + 所有相连的卡」"""
    table = load()
    seed = {c for c in ids if _valid_id(c)}
    out = set(seed)
    for cid in seed:
        r = table.get(cid)
        if isinstance(r, dict):
            if r.get("parent"):
                out.add(r["parent"])
            out.update(r.get("links") or [])
    for cid, r in table.items():
        if not isinstance(r, dict):
            continue
        if cid in seed:
            out.update(r.get("links") or [])
        if r.get("parent") in seed:
            out.add(cid)
    return sorted(out)
