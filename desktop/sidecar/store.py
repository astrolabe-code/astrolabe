#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ **SQLite 索引**（可删、可重建）

## 定位

```\n * 文件（.md） = 真相   —— 笔记内容、frontmatter\n * 本模块      = 索引   —— 只存锚点/编号/类型/时间/路径\n ```\n *
⚠ 任何"索引与文件不一致"的情况，以**文件为准**：`rescan()` 能从目录重建。

## 三张表

| 表 | 存什么 | 为什么必须在库里（不能只靠文件） |
|---|---|---|
| `project` | 代码目录、项目名、图版本 | 目录本身不记录"这个项目指向哪个代码仓库" |
| `node` / `edge` | 解析出来的代码结构 | 每次启动重解析太慢；且笔记要按锚点查 |
| `note` | 编号、类型、标题、文件路径、mtime | 排序/筛选/进度都要查，全文扫描太慢 |

⚠ 所有写操作都走 `with conn:`（事务），⛔ 不要手动 commit 到一半。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time

import library

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS project (
  id          INTEGER PRIMARY KEY,
  ref         TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  root        TEXT NOT NULL,           -- 代码目录绝对路径
  dir         TEXT NOT NULL,           -- 库内子目录名
  created_at  TEXT NOT NULL,
  parsed_at   TEXT,
  graph_rev   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS node (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  vid         INTEGER NOT NULL,
  kind        TEXT NOT NULL,           -- file / function / type
  name        TEXT NOT NULL,
  qname       TEXT,
  file_path   TEXT,
  line        INTEGER DEFAULT 0,
  line_end    INTEGER DEFAULT -1,
  UNIQUE (project_id, vid)
);
CREATE INDEX IF NOT EXISTS ix_node_name ON node (project_id, name);

CREATE TABLE IF NOT EXISTS edge (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  src_vid     INTEGER NOT NULL,
  dst_vid     INTEGER NOT NULL,
  kind        TEXT NOT NULL            -- call / include / ...
);
CREATE INDEX IF NOT EXISTS ix_edge_src ON edge (project_id, src_vid);

CREATE TABLE IF NOT EXISTS note (
  id          INTEGER PRIMARY KEY,
  ref         TEXT NOT NULL UNIQUE,    -- 短标识（前端路由用）
  project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  node_vid    INTEGER NOT NULL,
  kind        TEXT NOT NULL,
  no          INTEGER NOT NULL,        -- 「第几篇」全局递增
  title       TEXT NOT NULL DEFAULT '',
  rel_path    TEXT NOT NULL,           -- 相对库根的 .md 路径
  mtime       REAL NOT NULL DEFAULT 0,
  size        INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_note_no ON note (no);
CREATE INDEX IF NOT EXISTS ix_note_node ON note (project_id, node_vid);
"""


def connect(root: str) -> sqlite3.Connection:
    library.ensure_root(root)
    conn = sqlite3.connect(library.db_path(root))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- 项目


def get_or_create_project(conn: sqlite3.Connection, root: str, name: str, code_root: str) -> sqlite3.Row:
    d = library.project_dir_name(name)
    row = conn.execute("SELECT * FROM project WHERE dir = ?", (d,)).fetchone()
    if row:
        return row
    ref = "p_" + d.lower().replace(" ", "-")[:40]
    # ⚠ ref 可能撞（两个不同目录同名）⇒ 加后缀
    base, i = ref, 1
    while conn.execute("SELECT 1 FROM project WHERE ref = ?", (ref,)).fetchone():
        i += 1
        ref = f"{base}-{i}"
    with conn:
        conn.execute(
            "INSERT INTO project (ref, name, root, dir, created_at) VALUES (?,?,?,?,?)",
            (ref, name, code_root, d, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
    os.makedirs(os.path.join(root, d), exist_ok=True)
    return conn.execute("SELECT * FROM project WHERE ref = ?", (ref,)).fetchone()


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM node n WHERE n.project_id = p.id) AS node_count,
                  (SELECT COUNT(*) FROM note t WHERE t.project_id = p.id) AS note_count
           FROM project p ORDER BY p.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def find_project(conn: sqlite3.Connection, ref: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM project WHERE ref = ?", (ref,)).fetchone()


# ---------------------------------------------------------------- 图


def replace_graph(conn: sqlite3.Connection, project_id: int, nodes: list[dict], edges: list[dict]) -> None:
    """★ 整图替换（解析完一次性写入）

    ⚠ 用"先删后插"而不是 diff：解析结果是全量的，diff 复杂度不值这个钱。
    ⚠ 笔记的 `node_vid` 不受影响 —— 它指向 vid，而 vid 由代码内容决定（不是自增 id）。
    """
    with conn:
        conn.execute("DELETE FROM edge WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM node WHERE project_id = ?", (project_id,))
        conn.executemany(
            """INSERT INTO node (project_id, vid, kind, name, qname, file_path, line, line_end)
               VALUES (?,?,?,?,?,?,?,?)""",
            [
                (
                    project_id,
                    int(n.get("vid") or 0),
                    str(n.get("kind") or "other"),
                    str(n.get("name") or ""),
                    str(n.get("qname") or ""),
                    str(n.get("file_path") or ""),
                    int(n.get("line") or 0),
                    int(n.get("line_end") or -1),
                )
                for n in nodes
            ],
        )
        conn.executemany(
            "INSERT INTO edge (project_id, src_vid, dst_vid, kind) VALUES (?,?,?,?)",
            [
                (project_id, int(e.get("src_vid") or 0), int(e.get("dst_vid") or 0), str(e.get("kind") or "call"))
                for e in edges
            ],
        )
        conn.execute(
            "UPDATE project SET graph_rev = graph_rev + 1, parsed_at = ? WHERE id = ?",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), project_id),
        )


def nodes_of(conn: sqlite3.Connection, project_id: int, limit: int = 500, offset: int = 0) -> list[dict]:
    rows = conn.execute(
        """SELECT vid, kind, name, qname, file_path, line, line_end
           FROM node WHERE project_id = ?
           ORDER BY file_path, line LIMIT ? OFFSET ?""",
        (project_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def node_by_vid(conn: sqlite3.Connection, project_id: int, vid: int) -> dict | None:
    r = conn.execute(
        "SELECT vid, kind, name, qname, file_path, line, line_end FROM node WHERE project_id = ? AND vid = ?",
        (project_id, vid),
    ).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- 笔记


def next_no(conn: sqlite3.Connection) -> int:
    r = conn.execute("SELECT COALESCE(MAX(no), 0) + 1 AS n FROM note").fetchone()
    return int(r["n"])


def notes_of(conn: sqlite3.Connection, project_id: int, node_vid: int | None = None) -> list[dict]:
    sql = """SELECT n.*, COALESCE(nd.name,'') AS node_name, COALESCE(nd.file_path,'') AS file_path,
                    COALESCE(nd.line,0) AS line
             FROM note n LEFT JOIN node nd ON nd.project_id = n.project_id AND nd.vid = n.node_vid
             WHERE n.project_id = ?"""
    args: list = [project_id]
    if node_vid is not None:
        sql += " AND n.node_vid = ?"
        args.append(node_vid)
    sql += " ORDER BY n.no"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def insert_note(conn: sqlite3.Connection, row: dict) -> None:
    cols = ("ref", "project_id", "node_vid", "kind", "no", "title", "rel_path", "mtime", "size", "created_at")
    with conn:
        conn.execute(
            f"INSERT INTO note ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            tuple(row.get(c) for c in cols),
        )


def update_note(conn: sqlite3.Connection, ref: str, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE note SET {sets} WHERE ref = ?", (*fields.values(), ref))


def find_note(conn: sqlite3.Connection, ref: str) -> dict | None:
    r = conn.execute("SELECT * FROM note WHERE ref = ?", (ref,)).fetchone()
    return dict(r) if r else None


def delete_note(conn: sqlite3.Connection, ref: str) -> None:
    with conn:
        conn.execute("DELETE FROM note WHERE ref = ?", (ref,))


def stats(conn: sqlite3.Connection, project_id: int) -> dict:
    """覆盖率统计（个人版的「写作进度」）"""
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM node WHERE project_id = ? AND kind IN ('file','function','type')",
        (project_id,),
    ).fetchone()["c"]
    done = conn.execute(
        """SELECT COUNT(DISTINCT node_vid) AS c FROM note
           WHERE project_id = ? AND kind = 'summary'""",
        (project_id,),
    ).fetchone()["c"]
    by_kind = {
        r["kind"]: r["c"]
        for r in conn.execute(
            "SELECT kind, COUNT(*) AS c FROM note WHERE project_id = ? GROUP BY kind", (project_id,)
        ).fetchall()
    }
    return {"nodes": int(total), "summaryNodes": int(done), "notesByKind": by_kind}
