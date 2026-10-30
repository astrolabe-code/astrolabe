#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **索引器** —— 让 SQLite 追上磁盘上的 .md

## 位置变了（2026-10-30）

```\n * 以前  <库根>/<项目目录>/*.md          一个库管所有项目\n * 现在  <项目根>/.astrolabe/notes/*.md  一个项目一个数据目录\n ```\n *
⚠ 因此这里不再"按第一段目录猜项目归属" —— 一个数据目录里只有一个项目。

## 增量规则

```
文件 mtime+size 与库里一致   ⇒ 跳过（⛔ 不读内容）
变了                         ⇒ 重新解析 frontmatter，更新那一行
库里有、文件没了             ⇒ **不删**（可能只是临时移走），只计数
```

⚠ 索引丢了不致命：`rescan` 能从 `notes/` 重建 —— 这正是"文件是真相"的意义。
"""

from __future__ import annotations

import os
import sqlite3
import time

import notefile
import store

NOTES = "notes"


def notes_dir(data_dir: str) -> str:
    return os.path.join(data_dir, NOTES)


def scan_files(data_dir: str) -> list[tuple[str, float, int]]:
    d = notes_dir(data_dir)
    out: list[tuple[str, float, int]] = []
    if not os.path.isdir(d):
        return out
    for fn in os.listdir(d):
        if not fn.lower().endswith(".md"):
            continue
        p = os.path.join(d, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append((f"{NOTES}/{fn}", st.st_mtime, st.st_size))
    return out


def rescan(data_dir: str, conn: sqlite3.Connection, project_name: str = "") -> dict:
    """把 `notes/` 里的 .md 同步进索引"""
    t0 = time.time()
    row = conn.execute("SELECT id FROM project LIMIT 1").fetchone()
    if row is None:
        return {"added": 0, "updated": 0, "skipped": 0, "orphan": 0, "elapsedMs": 0}
    pid = row["id"]

    added = updated = skipped = 0

    for rel, mtime, size in scan_files(data_dir):
        cur = conn.execute("SELECT * FROM note WHERE rel_path = ?", (rel,)).fetchone()
        if cur and abs(cur["mtime"] - mtime) < 1e-6 and cur["size"] == size:
            skipped += 1
            continue

        path = os.path.join(data_dir, rel)
        try:
            meta, _body = notefile.read_file(path)
        except OSError:
            continue

        no = meta.get("no")
        fields = {
            "project_id": pid,
            "node_vid": int(meta.get("node_vid") or 0),
            "kind": str(meta.get("kind") or "flash"),
            "title": str(meta.get("title") or ""),
            "mtime": mtime,
            "size": size,
        }

        if cur:
            store.update_note(conn, cur["ref"], **fields)
            store.fts_sync(conn, cur["ref"], str(meta.get("title") or ""), _body or "")
            updated += 1
            continue

        if not isinstance(no, int):
            no = store.next_no(conn)
        ref = str(meta.get("ref") or f"n{no:04d}-{os.urandom(3).hex()}")
        store.insert_note(
            conn,
            {
                **fields,
                "no": no,
                "ref": ref,
                "rel_path": rel,
                "created_at": str(meta.get("time") or time.strftime("%Y-%m-%dT%H:%M:%S")),
            },
        )
        store.fts_sync(conn, ref, str(meta.get("title") or ""), _body or "")
        added += 1

    known = {r["rel_path"] for r in conn.execute("SELECT rel_path FROM note").fetchall()}
    on_disk = {rel for rel, _m, _s in scan_files(data_dir)}

    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "orphan": len(known - on_disk),
        "elapsedMs": int((time.time() - t0) * 1000),
    }
