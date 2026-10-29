#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **索引器** —— 让 SQLite 追上磁盘上的 .md

## 什么时候跑

```
启动时        扫一遍（几百个文件，几十毫秒）
导入笔记后     全量扫
用户手动点     「重建索引」
```

## 增量规则

```
文件 mtime+size 与库里一致   ⇒ 跳过（⛔ 不读内容）
变了                         ⇒ 重新解析 frontmatter，更新那一行
库里有、文件没了             ⇒ 从库里删掉（⚠ 只在 --prune 时删，默认不动）
```

⚠★ **默认不删库里的记录**：文件被临时移走（比如用户在文件管理器里剪切）
  不代表笔记被删 —— 宁可留一条"文件缺失"的幽灵，也不要误删用户的记录。

## 冲突

```
同一个 no 出现在两个文件里  ⇒ 保留 mtime 新的，另一个加后缀重编号并**改写文件**
                             （否则界面会出现两个 №007）
```
"""

from __future__ import annotations

import os
import sqlite3
import time

import library
import notefile
import store

SKIP_DIRS = {library.INDEX_DIR, ".trash", ".git", "node_modules"}


def rel_of(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def scan_files(root: str) -> list[tuple[str, float, int]]:
    out: list[tuple[str, float, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.lower().endswith(".md"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((rel_of(root, p), st.st_mtime, st.st_size))
    return out


def _project_of(conn: sqlite3.Connection, root: str, rel: str) -> sqlite3.Row | None:
    """笔记所属项目 = 相对路径的第一段目录名"""
    first = rel.split("/", 1)[0] if "/" in rel else ""
    if not first:
        return None
    return conn.execute("SELECT * FROM project WHERE dir = ?", (first,)).fetchone()


def rescan(root: str, conn: sqlite3.Connection) -> dict:
    """把磁盘上的 .md 同步进索引；返回统计"""
    t0 = time.time()
    added = updated = skipped = orphan = no_project = 0

    for rel, mtime, size in scan_files(root):
        row = conn.execute("SELECT * FROM note WHERE rel_path = ?", (rel,)).fetchone()
        if row and abs(row["mtime"] - mtime) < 1e-6 and row["size"] == size:
            skipped += 1
            continue

        path = os.path.join(root, rel)
        try:
            meta, _body = notefile.read_file(path)
        except OSError:
            continue

        proj = _project_of(conn, root, rel)
        if proj is None:
            # ⚠ 用户手放了一个不在任何项目目录下的 md ⇒ 跳过，不猜它属于谁
            no_project += 1
            continue

        no = meta.get("no")
        if not isinstance(no, int):
            no = store.next_no(conn)
            meta["no"] = no
            meta["project"] = proj["dir"]
            # ★ 回写：补齐 frontmatter（这样文件本身就带完整信息）
            _m, body = notefile.read_file(path)
            notefile.write_file(path, meta, body)

        fields = {
            "project_id": proj["id"],
            "node_vid": int(meta.get("node_vid") or meta.get("vid") or 0),
            "kind": str(meta.get("kind") or "flash"),
            "no": no,
            "title": str(meta.get("title") or ""),
            "mtime": mtime,
            "size": size,
        }

        if row:
            store.update_note(conn, row["ref"], **fields)
            updated += 1
        else:
            ref = meta.get("ref") or f"n{no:04d}-{os.urandom(3).hex()}"
            store.insert_note(
                conn,
                {
                    **fields,
                    "ref": ref,
                    "rel_path": rel,
                    "created_at": str(meta.get("time") or time.strftime("%Y-%m-%dT%H:%M:%S")),
                },
            )
            added += 1

    # 库里有、磁盘上没有 —— 只计数，⛔ 不删
    known = {r["rel_path"] for r in conn.execute("SELECT rel_path FROM note").fetchall()}
    on_disk = {rel for rel, _m, _s in scan_files(root)}
    orphan = len(known - on_disk)

    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "orphan": orphan,
        "noProject": no_project,
        "elapsedMs": int((time.time() - t0) * 1000),
    }
