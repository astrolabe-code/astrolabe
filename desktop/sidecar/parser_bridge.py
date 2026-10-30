#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **解析器桥** —— 把 `codeparser` 的产出变成索引里能落库的节点与边

## 为什么是"桥"而不是"重写"

```\n * `codeparser/`（892 行）不依赖 Django ⇒ **原样复用**，一行不改\n * `graph/identity.py`（vid 算法）也不依赖 Django ⇒ 直接 import\n * `graph/writer.py` 依赖 ORM ⇒ **不复用**，这里重写一份「纯字典」版本\n ```\n *
⚠★ vid 必须和社区版**完全一致**（同一段代码算出来的 vid 相同），
  所以只能调 `identity.canonical` / `identity.assign_vids`，⛔ 不要自己算哈希。

## 边怎么解析

沿用 `graph/writer.py::_resolve` 的口径（三种引用形态），但**更保守**：

```
unresolved#call#<name>   同名只有 1 个 ⇒ 连；⚠ 同名多个 ⇒ **不连**（宁可漏不要错）
unresolved#include#<x>   按文件名/模块名分层匹配，唯一才连
```

⚠ 社区版是"同名取路径最短者"，会**连错**；个人版没有人工兜底（用户不会去改图），
  错边比漏边伤害大得多 ⇒ 这里选择"唯一才连"。
"""

from __future__ import annotations

import os
import sys

import paths  # noqa: F401 —— ★ 统一把 `app/` 挂到 sys.path（见 paths.py）

import filefilter  # noqa: E402
from codeparser.scanner import scan_and_parse  # noqa: E402
from graph import identity  # noqa: E402

_UNRESOLVED = "unresolved#"


def _index(nodes_with_vid):
    by_uid: dict[str, int] = {}
    by_name: dict[str, list[tuple[int, str, int]]] = {}
    by_basename: dict[str, list[int]] = {}
    by_stem: dict[str, list[int]] = {}

    for rec, uid in nodes_with_vid:
        vid = rec["vid"]
        by_uid.setdefault(uid, vid)
        by_name.setdefault(rec["name"], []).append((vid, rec["file_path"], rec["line"]))
        base = os.path.basename(rec["file_path"] or "")
        if base:
            by_basename.setdefault(base, []).append(vid)
            by_stem.setdefault(os.path.splitext(base)[0], []).append(vid)
    return by_uid, by_name, by_basename, by_stem


def _resolve(ref: str, idx, stats: dict) -> int | None:
    by_uid, by_name, by_basename, by_stem = idx
    if not ref:
        return None

    if not ref.startswith(_UNRESOLVED):
        vid = by_uid.get(ref)
        if vid is None:
            stats["unresolvedUid"] += 1
        return vid

    parts = ref.split("#", 2)
    what = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""

    if what == "call":
        cands = by_name.get(value) or []
        if len(cands) == 1:
            return cands[0][0]
        # ⚠ 0 个 = 库里没这段（外部函数）；多个 = 同名歧义 ⇒ 都不连
        stats["ambiguousCall" if len(cands) > 1 else "unresolvedCall"] += 1
        return None

    if what in ("include", "in"):
        raw = value.strip().strip('<>"').strip()
        if not raw:
            return None
        base = raw.rsplit("/", 1)[-1]
        for bucket, key in ((by_basename, raw), (by_basename, base),
                            (by_stem, base.rsplit(".", 1)[0])):
            vids = bucket.get(key) or []
            if len(vids) == 1:
                return vids[0]
        stats["unresolvedInclude"] += 1
        return None

    return None


def parse_project(root: str, max_files: int = 5000) -> dict:
    """解析一个代码目录 ⇒ {nodes, edges, stats}

    ⚠ 节点、边的字段名与 `store.replace_graph` 对齐；调用方只管落库。
    """
    # ★★★ 文件过滤（移植所有者那份 `ignore.py` + `code_scanner.py`）⚠
    #   · 默认忽略 + 仓库 .gitignore + 隐藏项 + 软链/硬链 + 300KB 上限 + 扩展名白名单
    #   · ⛔ 不改变节点身份（vid 只由 kind|file|name|line|line_end 决定）
    accept_dir, accept_file = filefilter.make_acceptors(root)
    result, scan = scan_and_parse(
        root, max_files=max_files, accept_dir=accept_dir, accept_file=accept_file
    )

    records: list[tuple[dict, str]] = []
    canons: list[str] = []
    for pn in result.nodes:
        canon = identity.canonical(pn.kind, pn.file_path, pn.name, pn.line, pn.line_end)
        canons.append(canon)
        records.append(
            (
                {
                    "kind": str(pn.kind) if not isinstance(pn.kind, int) else str(pn.kind),
                    "name": pn.name or "",
                    "qname": getattr(pn, "qname", "") or "",
                    "file_path": pn.file_path or "",
                    "line": int(pn.line or 0),
                    "line_end": int(pn.line_end if pn.line_end is not None else -1),
                },
                pn.uid,
            )
        )

    vids = identity.assign_vids(canons)
    for (rec, _uid), canon in zip(records, canons):
        rec["vid"] = vids[canon]

    idx = _index(records)
    stats = {
        "nodes": len(records),
        "edges": 0,
        "ambiguousCall": 0,
        "unresolvedCall": 0,
        "unresolvedInclude": 0,
        "unresolvedUid": 0,
        "parseErrors": len(result.errors),
        "scanFiles": getattr(scan, "parsed", 0) if hasattr(scan, "parsed") else 0,
    }

    edges: list[dict] = []
    seen: set[tuple[int, int, str]] = set()
    for pe in result.edges:
        src = _resolve(pe.from_uid, idx, stats)
        dst = _resolve(pe.to_uid, idx, stats)
        if src is None or dst is None or src == dst:
            continue
        key = (src, dst, str(pe.type))
        if key in seen:
            continue
        seen.add(key)
        edges.append({"src_vid": src, "dst_vid": dst, "kind": str(pe.type)})

    # ---------------------------------------------------------------- 路径节点
    # ★★ 目录树也是结构（所有者那份 `process_path_struct.py` 的做法）⚠
    #   用途：在图上能顺着文件夹走，而不是一屏散落的函数
    #   · 每个中间目录一个 `dir` 节点，父子之间一条 `contains` 边
    #   · vid 仍走 canonical（kind=dir，name=相对目录，无文件无行号）⇒ 确定性
    dir_nodes: dict[str, dict] = {}
    tree_edges: list[dict] = []

    def _ensure_dir(rel_dir: str) -> int | None:
        """建（或取）一个目录节点，返回 vid；rel_dir 为空表示根，返回 None"""
        if not rel_dir:
            return None
        if rel_dir in dir_nodes:
            return dir_nodes[rel_dir]["vid"]
        canon = identity.canonical("dir", "", rel_dir, 0, -1)
        vid = identity.hash53(canon)
        dir_nodes[rel_dir] = {
            "kind": "dir",
            "name": os.path.basename(rel_dir),
            "qname": rel_dir,
            "file_path": "",
            "line": 0,
            "line_end": -1,
            "vid": vid,
        }
        parent = rel_dir.rsplit("/", 1)[0] if "/" in rel_dir else ""
        pv = _ensure_dir(parent)
        if pv is not None:
            tree_edges.append({"src_vid": pv, "dst_vid": vid, "kind": "contains"})
        return vid

    file_vid: dict[str, int] = {}
    for rec, _uid in records:
        if rec["kind"] == "file" and rec["file_path"]:
            file_vid.setdefault(rec["file_path"], rec["vid"])

    for path in sorted(file_vid):
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        pv = _ensure_dir(parent)
        if pv is not None:
            tree_edges.append({"src_vid": pv, "dst_vid": file_vid[path], "kind": "contains"})

    for e in tree_edges:
        key = (e["src_vid"], e["dst_vid"], e["kind"])
        if key in seen:
            continue
        seen.add(key)
        edges.append(e)

    stats["dirNodes"] = len(dir_nodes)
    stats["treeEdges"] = len(tree_edges)
    stats["edges"] = len(edges)
    return {
        "nodes": [r for r, _u in records] + list(dir_nodes.values()),
        "edges": edges,
        "stats": stats,
    }
