#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★ 解析后处理：把「类外定义」挂回它自己的类下

## 问题（实测 fmt 复现）

```cpp
// fmt/os.h
class buffered_file { void close(); };

// fmt/os.cc
void buffered_file::close() { … }     ← 定义在另一个文件里
```

`qname` 是对的（`buffered_file::close`），但 `contains` 边的**父级用的是词法父节点**：

```
修前   os.cc         → buffered_file::close     ← 挂在文件上（图中看不到这个成员）
修后   buffered_file → buffered_file::close     ← 挂回类下
```

Java / Python 不受影响（方法只能写在类体内），**只有 C++ 的类外定义会这样**，
而这种写法在 C++ 项目里极常见（声明在头文件、实现在 .cc）。

## 做法：查表，⛔ 不下钻

```
① 全项目建一次 qname → [uid] 索引（O(节点数)）
② 每条 contains 边：取目标 qname 的**父前缀**（跳过 <> 里的 :: 与 operator 那段）
③ 前缀唯一命中一个「容器」（class/struct/union/interface/module）⇒ 把边的源改过去
④ 命中 0 个或多个 ⇒ 原样保留（⛔ 不猜），只计数
```

⚠ 只是"拿名字查一次表"，不遍历子树、不递归 —— 与"有限枚举、不下钻"的原则一致。

## 为什么必须跨文件

类在 `.h`、方法在 `.cc` ⇒ 单文件内查不到。所以这一步放在**整项目解析完成之后**，
由两个写入方各调一次（两版共用同一份规则，避免各写一套）：

| 调用方 | 文件 |
|---|---|
| 个人版 | `desktop/sidecar/parser_bridge.py` |
| 网页版 | `app/graph/writer.py` |
"""

from __future__ import annotations

import time

from .base import ParseResult

#: 能"装下"别的定义的容器种类（只有它们才能当 contains 的父级）
CONTAINER_KINDS = frozenset({"class", "struct", "union", "interface", "record", "module", "type"})


def split_scope(qname: str, sep: str) -> str:
    """取 `A::B::f` 的父前缀 `A::B`（⚠ 跳过模板参数里的分隔符）

    ```
    A::B::f                              → A::B
    fmt::formatter<std::chrono::time_point<X>, char>::format
                                         → fmt::formatter<std::chrono::time_point<X>, char>
    A::operator bool                     → A          ← operator 那段不算作用域
    f                                    → ""         （没有父级）
    ```

    ⚠ 这是**文本切分**，但只用于"把已有的 qname 拆成父级"，
      ⛔ 不参与任何结构判断（结构由查询与 parent 链负责）。
    """
    if not qname:
        return ""

    # `A::operator foo` / `A::operator std::locale` —— operator 之后都是名字，不是作用域
    op = qname.rfind(f"{sep}operator")
    if op >= 0:
        return qname[:op]

    depth = 0
    last = -1
    i = 0
    n = len(qname)
    while i < n:
        ch = qname[i]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0 and qname.startswith(sep, i):
            last = i
            i += len(sep)
            continue
        i += 1
    return qname[:last] if last >= 0 else ""


def reparent_contains(result: ParseResult, deadline: float | None = None) -> dict[str, int]:
    """★ 把 `contains` 边从"词法父级"改挂到"名字所指的类"下（原地修改）

    Args:
        result: **整项目**解析结果（多文件已汇总）

    Returns:
        `{"moved":…, "ambiguous":…, "unresolved":…, "dropped":…}`
        —— ⚠ 只做统计，不改任何节点身份（vid 与 canonical 完全不受影响）
    """
    stats = {"moved": 0, "ambiguous": 0, "unresolved": 0, "dropped": 0, "truncated": 0}
    if not result.nodes or not result.edges:
        return stats

    uid_to_q: dict[str, str] = {}
    uid_to_kind: dict[str, str] = {}
    uid_to_sep: dict[str, str] = {}
    q_to_uids: dict[str, list[str]] = {}

    for n in result.nodes:
        q = n.qname or n.name
        if not q:
            continue
        uid_to_q[n.uid] = q
        uid_to_kind[n.uid] = str(n.kind)
        sep = "::" if (n.lang or "") in ("c", "cpp") else "."
        uid_to_sep[n.uid] = sep
        q_to_uids.setdefault(q, []).append(n.uid)

    # 已有边（用于去重：挪过去之后可能和另一条重复）
    existing = {(e.from_uid, e.to_uid, e.type) for e in result.edges}

    for _i, edge in enumerate(result.edges):
        # ★ 与解析共享同一份预算：超时就不再做归位（* 图不完整 ≠ 解析失败）
        if deadline is not None and _i % 500 == 0 and time.monotonic() > deadline:
            stats["truncated"] = 1
            break
        if edge.type != "contains":
            continue

        dst_q = uid_to_q.get(edge.to_uid)
        if not dst_q:
            continue
        sep = uid_to_sep.get(edge.to_uid, ".")
        prefix = split_scope(dst_q, sep)
        if not prefix:
            continue

        cur_src = edge.from_uid
        if uid_to_q.get(cur_src) == prefix:
            continue  # 已经挂对了

        cands = [
            u
            for u in (q_to_uids.get(prefix) or [])
            if uid_to_kind.get(u) in CONTAINER_KINDS and u != edge.to_uid
        ]
        if len(cands) > 1:
            stats["ambiguous"] += 1
            continue
        if not cands:
            stats["unresolved"] += 1
            continue

        target = cands[0]
        if target == cur_src:
            continue
        key = (target, edge.to_uid, edge.type)
        if key in existing:
            # 已有同样的边 ⇒ 把旧的这条去掉（否则图上两条重复）
            edge.type = "__drop__"
            stats["dropped"] += 1
            continue

        existing.discard((cur_src, edge.to_uid, edge.type))
        existing.add(key)
        edge.from_uid = target
        stats["moved"] += 1

    if stats["dropped"]:
        result.edges = [e for e in result.edges if e.type != "__drop__"]

    return stats
