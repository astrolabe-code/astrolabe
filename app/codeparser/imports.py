#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★ 导入 / 包含的**文件级**解析（`imports` / `includes` 边）

## 所有者口径（2026-11-01，逐字）

> 「这种连线，不要做的太复杂了，我看 **文件级依赖** 就差不多了，更细一点当然可以，
>  但奇异太多的话，**连线会误导初学者，还不如不连**，让用户学习之后，自己连，
>  你觉得呢？**我这不是专业的调用分析图谱工具，不需要做那么细**。」
>
> 「注意就是在正确的基础上，尽量多的连。**有歧义的，宁可不连，也不要猜**。」

⇒ 三条规矩：

```
① 只连**文件 → 文件**（⛔ 不连到符号、不连到包）
② 只在「项目里确实存在且**唯一**」时才连（外部依赖连不上 = 正确结果）
③ 同一对文件只留**一条**边（`import` 五次不该画五条平行线）
```

## 为什么必须两版共用

修之前实测（同一份源码）：

```
Java   个人版 0%   网页版 19%     ← 同一个概念写了两套阶梯
Python 个人版 7%   网页版 26%
```

个人版只按 `/` 切模块名，`org.apache.commons.lang3.ArrayUtils` 永远切不出 `ArrayUtils`
⇒ Java 一条都连不上。**同一份代码两个版本给出不同结果**，这本身就是 bug。

## 各语言的映射（都只做"名字 → 文件路径"）

| 写法 | 映射 |
|---|---|
| Python `a.b.c` | `a/b/c.py` 或 `a/b/c/__init__.py` |
| Python `from .base import X` | 相对导入：先按当前文件目录展开，再匹配 |
| Python `from . import enc` | 当前包的 `__init__.py`（文件级：依赖的是这个包）|
| Java `a.b.C` | `a/b/C.java` |
| Java `import static a.b.C.m` | 末段不是类名 ⇒ 去掉，仍映射到 `C.java` |
| Java `a.b.*` | **不连**（通配，无法唯一）|
| C/C++ `#include "x.h"` | **先同目录**（展开 `../`），再按路径后缀 |
| C/C++ `#include <x.h>` | 只按路径后缀（系统头文件自然连不上）|

⚠ 后缀匹配 = `p == rel or p.endswith("/" + rel)`：
  `fmt/format.h` 能对上 `include/fmt/format.h`，但**同一后缀命中多个就不连**。

⛔ 不做：符号级导入、包节点、标准库路径推断、别名追踪。
"""

from __future__ import annotations

import posixpath

from .base import ParseResult

#: 计算成"文件级依赖"的边类型（与各语言的 `import_edge_type` 对齐）
_IMPORT_EDGE_TYPES = ("imports", "includes")
_REF_PREFIX = "unresolved#include#"


def _norm(p: str) -> str:
    """规范化相对路径（去掉 `./`、处理 `../`）—— 纯文本运算，不碰文件系统"""
    out = posixpath.normpath(p.replace("\\", "/"))
    return "" if out == "." else out.lstrip("./")


def _suffix_hits(paths: list[str], rel: str) -> list[str]:
    """按后缀匹配（`fmt/format.h` ↔ `include/fmt/format.h`）"""
    if not rel:
        return []
    return [p for p in paths if p == rel or p.endswith("/" + rel)]


def _python_rels(module: str, importer: str) -> list[str]:
    """Python 模块名 → 候选相对路径（`a.b.c` / `.base` / `..util`）"""
    if module.startswith("."):
        depth = len(module) - len(module.lstrip("."))
        rest = module[depth:].replace(".", "/")
        base = posixpath.dirname(importer)
        for _ in range(depth - 1):
            base = posixpath.dirname(base)
        rel = posixpath.join(base, rest) if rest else base
        return [_norm(rel)]
    return [_norm(module.replace(".", "/"))]


def _java_rel(target: str) -> str | None:
    """Java 全限定名 → `a/b/C.java`；通配 / 静态成员按规则收窄"""
    if "*" in target:
        return None                       # ⛔ 通配无法唯一，不连
    segs = [s for s in target.split(".") if s]
    if len(segs) >= 2 and not segs[-1][:1].isupper():
        # `import static a.b.C.method;` ⇒ 末段是成员名，类名在上一段
        segs = segs[:-1]
    if not segs:
        return None
    return _norm("/".join(segs) + ".java")


def resolve_imports(result: ParseResult) -> dict[str, int]:
    """★ 把 `unresolved#include#<目标>` 就地解析成**文件节点 uid**（两版共用）

    Args:
        result: **整项目**解析结果（多文件已汇总）

    Returns:
        `{"total": 导入条数, "resolved": 连上的条数, "ambiguous": 多候选没连,
          "external": 语料里没有（外部依赖）, "merged": 去重掉的重复边}`
    """
    stats = {"total": 0, "resolved": 0, "ambiguous": 0, "external": 0, "merged": 0}

    file_uid: dict[str, str] = {}
    uid_lang: dict[str, str] = {}
    uid_path: dict[str, str] = {}
    for n in result.nodes:
        if n.kind == "file" and n.file_path:
            file_uid[n.file_path] = n.uid
        if n.uid:
            uid_lang[n.uid] = n.lang or ""
            if n.file_path:
                uid_path[n.uid] = n.file_path

    paths = list(file_uid)
    if not paths:
        return stats

    for edge in result.edges:
        if edge.type not in _IMPORT_EDGE_TYPES:
            continue
        ref = edge.to_uid or ""
        if not ref.startswith(_REF_PREFIX):
            continue

        stats["total"] += 1
        raw = ref[len(_REF_PREFIX) :].strip()
        lang = uid_lang.get(edge.from_uid, "")
        importer = uid_path.get(edge.from_uid, "")

        cands: list[str] = []
        if lang in ("c", "cpp"):
            quoted = raw.startswith('"')
            target = raw.strip('<>"').strip()
            if not target:
                stats["external"] += 1
                continue
            if quoted and importer:
                # ★ `"x.h"` 是**相对当前文件目录**：先试同目录（可含 ../）
                same = _norm(posixpath.join(posixpath.dirname(importer), target))
                if same in file_uid:
                    cands = [same]
            if not cands:
                cands = _suffix_hits(paths, _norm(target))
        elif lang == "python":
            for rel in _python_rels(raw, importer):
                cands = _suffix_hits(paths, rel + ".py") or _suffix_hits(paths, rel + "/__init__.py")
                if cands:
                    break
        elif lang == "java":
            rel = _java_rel(raw)
            if rel is None:
                stats["external"] += 1
                continue
            cands = _suffix_hits(paths, rel)
        else:
            # 不认识的语言：按路径后缀试一次（保守）
            cands = _suffix_hits(paths, _norm(raw.strip('<>"')))

        if len(cands) == 1:
            edge.to_uid = file_uid[cands[0]]
            stats["resolved"] += 1
        elif len(cands) > 1:
            stats["ambiguous"] += 1          # ⛔ 多候选：不猜
        else:
            stats["external"] += 1           # 语料里没有 ⇒ 外部依赖，正确

    # ---------------------------------------------------------------- 去重
    # 同一对文件只留一条（`import` 五次不该画五条平行线）
    best: dict[tuple[str, str, str], int] = {}
    for idx, edge in enumerate(result.edges):
        if edge.type not in _IMPORT_EDGE_TYPES:
            continue
        key = (edge.from_uid, edge.to_uid, edge.type)
        line = edge.line if edge.line is not None else 1 << 30
        cur = best.get(key)
        if cur is None:
            best[key] = idx
        else:
            prev_line = result.edges[cur].line
            prev_line = prev_line if prev_line is not None else 1 << 30
            if line < prev_line:
                best[key] = idx

    if len(best) < sum(1 for e in result.edges if e.type in _IMPORT_EDGE_TYPES):
        keep = set(best.values())
        before = len(result.edges)
        result.edges = [
            e
            for i, e in enumerate(result.edges)
            if e.type not in _IMPORT_EDGE_TYPES or i in keep
        ]
        stats["merged"] = before - len(result.edges)

    return stats
