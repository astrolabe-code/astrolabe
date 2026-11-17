#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **AI 上下文包**：为「出思考题 / 给学习建议」组装一个节点周围的全部材料

## 为什么要单独一个模块

所有者原话（2026-11-17）：

> 「你这代码就只是当前一段代码给 ai，显然不够，一些函数就是一句调用，
>   你让 ai 怎么出题呢？ai 必须先根据节点图，看一遍所有源码，
>   才能问出有价值的问题以及学习安排」
>
> 「上下文节点的源码都要看」

所以出题 ≠ 把当前函数贴给模型。要给它**这个节点在代码里的位置**：

```
当前节点完整源码
它调用谁的完整源码        ← 关键：一句调用的函数，答案在下一层
谁调用它的完整源码
它在哪几条执行流里
同文件还有哪些函数（签名）
代码里的可疑点（魔数 / 位运算 / 吞错误）
```

## 借鉴 GitNexus 的什么

它的 `MODULE_USER_PROMPT` 把 **源码 + 模块内调用 + 跨模块出/入 + 执行流**
一起发给模型（`generator.js` 的 `generateLeafPage`），并按 30k token 截断。
我们照这个结构，但按**节点粒度**做，预算小得多（约 8k–15k token）。

⚠ 和它的一个差异：它只给「调用关系」（名字），我们**给到源码**。
原因是节点粒度太细 —— `do_read` 可能只有一行 `return read(...)`，
不给下一层源码，模型只能问「这个函数做什么」这种废话。

## 三条边界

```
① ⛔ 不碰 SQLite（笔记在 main.py 里合并）—— 这里只管图和源码
② ⛔ 不写任何文件
③ 源码有界：单节点 ≤200 行、邻居 ≤12 个；被截掉的在返回里明说
```
"""

from __future__ import annotations

import os
import re

import graphdb
import source

#: 单个节点最多给多少行（超过就截，并在返回里标记）
MAX_NODE_LINES = 200
#: 上下游各最多给几个邻居的完整源码
MAX_NEIGHBORS = 12
#: 每次最多带几条执行流
MAX_FLOWS = 2

#: 可疑点：魔数 / 位运算 / 错误处理 / 并发
_SUSPICIOUS = (
    (re.compile(r"\b(4096|1024|512|256|0x7[fF]|0x[fF]{2})\b"), "魔数"),
    (re.compile(r"&\s*0x[0-9a-fA-F]+|\bxor\b|>>\s*\d+"), "位运算"),
    (re.compile(r"\bvolatile\b|\b__asm__\b|\bbarrier\b"), "并发/架构相关"),
    (re.compile(r"\bTODO\b|\bFIXME\b|\bXXX\b"), "作者留的疑问"),
    (re.compile(r"\bgoto\s+\w+|errno|EINTR|EAGAIN"), "错误处理"),
    (re.compile(r"\b(malloc|calloc|realloc|free|kfree|kmalloc)\b"), "内存管理"),
    (re.compile(r"\b(lock|unlock|mutex|spin_lock|atomic)\b"), "加锁/并发"),
    (re.compile(r"\(\s*(int|long|size_t|ssize_t|unsigned)\s*\)"), "类型转换"),
    (re.compile(r"\b(read|write|recv|send|open|close)\s*\("), "系统调用"),
)


def _slice(text: str, line: int, line_end: int, limit: int = MAX_NODE_LINES) -> tuple[str, bool]:
    """按节点行号截源码，返回 `(片段, 是否被截断)`。"""
    lines = str(text or "").splitlines()
    start = max(0, int(line or 1) - 1)
    end = int(line_end or 0)
    if end <= start:
        end = start + 60
    end = min(end, len(lines))
    truncated = False
    if end - start > limit:
        end = start + limit
        truncated = True
    if end <= start:
        return "（读不到源码）", False
    return "\n".join(lines[start:end]), truncated


def _suspicious(code: str) -> list[str]:
    """扫一遍代码，给出**定位线索**。纯规则，⛔ 不判断对错。

    ⚠ 所有者原话（2026-11-17）：「可疑点这个仅仅是正则扫描还不够，
      ai 还要自己去发现，不是每个可疑点都是这些魔数之类的」
      ⇒ 这里只负责把注意力引到某一行，**真正的判断由模型通读源码完成**。
    """
    hits: list[str] = []
    seen: set[str] = set()
    for pattern, label in _SUSPICIOUS:
        for m in pattern.finditer(code or ""):
            key = f"{label}:{m.group(0)}"
            if key in seen:
                continue
            seen.add(key)
            hits.append(f"{label}：{m.group(0)}")
            if len(hits) >= 6:
                return hits
    return hits


def build(
    data_dir: str,
    root: str,
    vid: int,
    max_neighbors: int = MAX_NEIGHBORS,
    max_flows: int = MAX_FLOWS,
) -> dict:
    """组装一个节点的上下文包。

    返回结构（全部是纯数据，`ai.py` 负责渲染成 prompt）：

    ```python
    {
      "node":    {vid, kind, name, qname, file, line, line_end, signature},
      "snippet": "源码",
      "lang":    "c",
      "truncated_node": False,
      "siblings": [{name, line}],                    # 同文件的其它函数
      "downstream": [{vid, name, file, line, snippet, truncated}],
      "upstream":   [...],
      "flows":   [{length, labels: ["main", "read", ...]}],
      "suspicious": ["魔数：4096", ...],
      "dropped": {"downstream": 3, "upstream": 1},   # 因上限被丢掉的个数
    }
    ```
    """
    node = graphdb.get_code(data_dir, vid)
    if not node:
        raise ValueError("节点不存在")

    # ---- 1) 一次读全图边：度数 + 邻接（⛔ 不逐节点查）
    conn = graphdb._open(data_dir)
    rows = conn.execute("MATCH (a:Code)-[r:Rel]->(b:Code) RETURN a.vid, b.vid, r.kind").get_all()
    deg: dict[int, int] = {}
    out_map: dict[int, set[int]] = {}
    in_map: dict[int, set[int]] = {}
    for a, b, _kind in rows:
        a, b = int(a), int(b)
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
        out_map.setdefault(a, set()).add(b)
        in_map.setdefault(b, set()).add(a)
    # ⚠ `_open` 是共享缓存连接，⛔ 不能 close（关掉会让后续查询拿到失效连接）

    # ---- 2) 邻居：按「是否在流程里 → 度数」排序，取前 N 个
    def order(vids: set[int]) -> list[int]:
        return sorted(vids, key=lambda v: (-deg.get(v, 0), v))

    down_ids = order(out_map.get(int(vid), set()))
    up_ids = order(in_map.get(int(vid), set()))
    dropped = {
        "downstream": max(0, len(down_ids) - max_neighbors),
        "upstream": max(0, len(up_ids) - max_neighbors),
    }
    down_ids = down_ids[:max_neighbors]
    up_ids = up_ids[:max_neighbors]

    # ---- 3) 文件缓存：同一文件的多个节点只读一次
    cache: dict[str, str] = {}

    def text_of(rel: str) -> str:
        if rel not in cache:
            try:
                cache[rel] = str(source.read(root, rel).get("text") or "")
            except Exception:  # noqa: BLE001 —— 源码读不到不该让整个包失败
                cache[rel] = ""
        return cache[rel]

    def pack_node(v: int) -> dict | None:
        n = graphdb.get_code(data_dir, v)
        if not n:
            return None
        rel = str(n.get("file") or "")
        code, cut = _slice(text_of(rel), n.get("line") or 1, n.get("line_end") or 0)
        return {
            "vid": int(v),
            "name": str(n.get("name") or ""),
            "file": rel,
            "line": int(n.get("line") or 0),
            "signature": str(n.get("signature") or ""),
            "snippet": code,
            "truncated": cut,
        }

    node_code, node_cut = _slice(
        text_of(str(node.get("file") or "")), node.get("line") or 1, node.get("line_end") or 0
    )

    # ---- 4) 同文件其它函数（只给名字 + 行号，帮助判断文件职责）
    siblings: list[dict] = []
    rel_self = str(node.get("file") or "")
    if rel_self:
        try:
            conn2 = graphdb._open(data_dir)
            sib_rows = conn2.execute(
                "MATCH (c:Code) WHERE c.file = $f AND c.vid <> $v "
                "RETURN c.name, c.line ORDER BY c.line LIMIT 15",
                {"f": rel_self, "v": int(vid)},
            ).get_all()
            siblings = [{"name": str(r[0] or ""), "line": int(r[1] or 0)} for r in sib_rows]
        except Exception:  # noqa: BLE001
            siblings = []

    # ---- 5) 执行流（复用已有实现）
    flows: list[dict] = []
    try:
        for f in (graphdb.flows_of(data_dir, int(vid)).get("items") or [])[:max_flows]:
            steps = [int(x) for x in (f.get("steps") or [])]
            labels = []
            for s in steps[:12]:
                n = graphdb.get_code(data_dir, s)
                labels.append(str((n or {}).get("name") or s))
            flows.append({"length": int(f.get("length") or len(steps)), "labels": labels})
    except Exception:  # noqa: BLE001
        flows = []

    return {
        "node": {
            "vid": int(vid),
            "kind": str(node.get("kind") or ""),
            "name": str(node.get("name") or ""),
            "qname": str(node.get("qname") or ""),
            "file": rel_self,
            "line": int(node.get("line") or 0),
            "line_end": int(node.get("line_end") or 0),
            "signature": str(node.get("signature") or ""),
        },
        "snippet": node_code,
        "lang": "",
        "truncated_node": node_cut,
        "siblings": siblings,
        "downstream": [x for x in (pack_node(v) for v in down_ids) if x],
        "upstream": [x for x in (pack_node(v) for v in up_ids) if x],
        "flows": flows,
        "suspicious": _suspicious(node_code),
        "dropped": dropped,
    }
