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
#: 同文件其它函数：**少而全**
#   ⚠ 所有者 2026-11-17：「你给那么多函数签名，还不如给ai少点签名，多点源码」
#     原来 15 个「名字+行号」价值很低，改成 5 个带源码。
MAX_SIBLINGS = 5
#: 同文件函数源码最多给多少行
MAX_SIBLING_LINES = 60

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


# ★★ 常见「空文件」的语义提示
#
# 所有者原话（2026-11-17）：
# 「这是Python包的格式，是什么问题导致模型会问没有代码？ai不知道这是包格式吗？」
#
# 根因是两件事叠在一起：`__init__.py` 常为 0 字节，被当成「读取失败」，
# 而 prompt 又没告诉模型这是什么文件 ⇒ 它只能问「源码在哪」。
# 这里把「文件名 → 它本来就没有代码」这层常识补上。
_FILE_HINTS = {
    "__init__.py": "Python 包的标记文件：通常为空，或只做 re-export（把子模块暴露出去）——没有代码是正常的",
    "__main__.py": "Python 包的可执行入口（`python -m 包名` 时运行）",
    "mod.rs": "Rust 的模块声明文件：通常只有 `pub mod` / `pub use`，不写实现",
    "lib.rs": "Rust crate 的根：声明所有模块，可能只有 `mod` 与 `pub use`",
    "main.rs": "Rust 二进制入口：通常只有 `fn main()` 与模块声明",
    "index.js": "目录入口：打包器默认从这里找导出，常只有 re-export",
    "index.ts": "目录入口：打包器默认从这里找导出，常只有 re-export",
    "index.tsx": "目录入口：常只有 re-export",
    "setup.py": "Python 的打包脚本",
    "conftest.py": "pytest 的共享夹具声明文件",
}


def file_hint(rel: str) -> str:
    """按文件名给出「这个文件本来长什么样」的提示；认不出就返回空串。"""
    name = str(rel or "").replace("\\", "/").rsplit("/", 1)[-1]
    return _FILE_HINTS.get(name, "")


def _slice(
    text: str | None, line: int, line_end: int, limit: int = MAX_NODE_LINES
) -> tuple[str, bool]:
    """按节点行号截源码，返回 `(片段, 是否被截断)`。

    ⚠ 三种情况必须区分开（之前混成一个「读不到源码」，把模型带偏）：
      · `None`   ⇒ 文件读不出来（权限 / 编码 / 被删）
      · `""`     ⇒ 文件是空的 —— 对 `__init__.py` 这类是**正常**的
      · 有内容   ⇒ 正常截取
    """
    if text is None:
        return "（源码读取失败：文件打不开或编码不支持）", False
    if not text.strip():
        return "（空文件 —— 这个文件本身没有代码，不是读取失败）", False
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
    cache: dict[str, str | None] = {}

    def text_of(rel: str) -> str | None:
        if rel not in cache:
            try:
                cache[rel] = str(source.read(root, rel).get("text") or "")
            except Exception:  # noqa: BLE001 —— 读失败用 None 区分「空文件」
                cache[rel] = None
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

    if str(node.get("kind") or "") == "dir":
        # ⚠ 目录没有源码：⛔ 不要让 `_slice` 报「读取失败」，那会把模型带偏
        # ⚠ 这里读不到 children（它在后面才查），数量由 prompt 侧渲染时补
        node_code = "（这是一个目录节点，没有源码；它包含的文件与子目录见下方列表）"
        node_cut = False
    else:
        node_code, node_cut = _slice(
            text_of(str(node.get("file") or "")),
            node.get("line") or 1,
            node.get("line_end") or 0,
        )

    # ---- 4) 同文件其它函数：少而全（5 个带源码，其余只报数量）
    siblings: list[dict] = []
    siblings_more = 0
    rel_self = str(node.get("file") or "")
    if rel_self:
        try:
            conn2 = graphdb._open(data_dir)
            sib_rows = conn2.execute(
                "MATCH (c:Code) WHERE c.file = $f AND c.vid <> $v "
                "RETURN c.vid, c.name, c.line, c.line_end ORDER BY c.line",
                {"f": rel_self, "v": int(vid)},
            ).get_all()
            siblings_more = max(0, len(sib_rows) - MAX_SIBLINGS)
            for r in sib_rows[:MAX_SIBLINGS]:
                code, _cut = _slice(
                    text_of(rel_self),
                    int(r[2] or 1),
                    int(r[3] or 0),
                    limit=MAX_SIBLING_LINES,
                )
                siblings.append(
                    {"name": str(r[1] or ""), "line": int(r[2] or 0), "snippet": code}
                )
        except Exception:  # noqa: BLE001
            siblings = []

    # ---- 4.5) 目录节点：`kind='dir'` 的 file 是目录路径，读不到源码
    #   ★ 所有者原话（2026-11-17）：「有些节点是dir的目录类型，可以提问这个目录本身，
    #     也可以是其下的文件呀」⇒ 给它列出直接子项（contains 出边）。
    children: list[dict] = []
    if str(node.get("kind") or "") == "dir":
        try:
            conn3 = graphdb._open(data_dir)
            rows = conn3.execute(
                "MATCH (d:Code)-[r:Rel]->(c:Code) WHERE d.vid = $v AND r.kind = 'contains' "
                "RETURN c.vid, c.kind, c.name, c.line ORDER BY c.kind, c.name LIMIT 40",
                {"v": int(vid)},
            ).get_all()
            children = [
                {
                    "vid": int(r[0]),
                    "kind": str(r[1] or ""),
                    "name": str(r[2] or ""),
                    "line": int(r[3] or 0),
                }
                for r in rows
            ]
        except Exception:  # noqa: BLE001
            children = []

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
        "siblings_more": siblings_more,
        # ★ 目录节点才有：它的直接子项（文件 / 子目录）
        "children": children,
        "downstream": [x for x in (pack_node(v) for v in down_ids) if x],
        "upstream": [x for x in (pack_node(v) for v in up_ids) if x],
        "flows": flows,
        # ★ 文件语义：`__init__.py` 这类「本来就没代码」的文件，提前告诉模型
        "file_hint": file_hint(rel_self),
        "suspicious": _suspicious(node_code),
        "dropped": dropped,
    }
