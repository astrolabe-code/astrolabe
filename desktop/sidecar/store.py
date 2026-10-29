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
import paths  # noqa: F401 —— ★ 让 `graph.identity` 可导入（手补节点要用）

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
  -- ★ 来源：parsed（解析器给的）/ manual（人手补的）—— 图上要标出来
  origin      TEXT NOT NULL DEFAULT 'parsed',
  UNIQUE (project_id, vid)
);
CREATE INDEX IF NOT EXISTS ix_node_name ON node (project_id, name);

CREATE TABLE IF NOT EXISTS edge (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  src_vid     INTEGER NOT NULL,
  dst_vid     INTEGER NOT NULL,
  kind        TEXT NOT NULL,           -- call / include / ...
  origin      TEXT NOT NULL DEFAULT 'parsed'
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

-- ★★ 修补日志：谁 / 何时 / 改了什么 / **为什么**（`reason` 必填，见 `curate.py` 口径）
CREATE TABLE IF NOT EXISTS curate_log (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  action      TEXT NOT NULL,
  target      TEXT NOT NULL,
  reason      TEXT NOT NULL,
  detail      TEXT NOT NULL DEFAULT '',
  at          TEXT NOT NULL
);
"""


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """★ 老库补列（`CREATE TABLE IF NOT EXISTS` 不会给已存在的表加列）⚠"""
    for table, col, ddl in (
        ("node", "origin", "TEXT NOT NULL DEFAULT 'parsed'"),
        ("edge", "origin", "TEXT NOT NULL DEFAULT 'parsed'"),
    ):
        names = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in names:
            with conn:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def connect(root: str) -> sqlite3.Connection:
    library.ensure_root(root)
    conn = sqlite3.connect(library.db_path(root))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
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
        # ★★★ 只删**解析出来的**，⛔ 不碰人手补的（`origin='manual'`）⚠
        #
        # 之前是无条件 DELETE ⇒ 重新解析一次，手补的节点和边全没了，
        # 挂着它们的笔记还会变成「节点已不存在」。而改图恰恰是解析不准时的唯一兜底，
        # 删掉它等于把用户的工作一笔勾销。
        conn.execute("DELETE FROM edge WHERE project_id = ? AND origin = 'parsed'", (project_id,))
        conn.execute("DELETE FROM node WHERE project_id = ? AND origin = 'parsed'", (project_id,))
        conn.executemany(
            """INSERT OR REPLACE INTO node (project_id, vid, kind, name, qname, file_path, line, line_end, origin)
               VALUES (?,?,?,?,?,?,?,?,'parsed')""",
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
    """⚠ 带上节点信息（阅读页左栏要显示「挂在 xxx」）——
    单表查是拿不到 name/file_path 的，必须 join。"""
    r = conn.execute(
        """SELECT n.*, COALESCE(nd.name,'') AS node_name, COALESCE(nd.file_path,'') AS file_path,
                  COALESCE(nd.line,0) AS line
           FROM note n LEFT JOIN node nd ON nd.project_id = n.project_id AND nd.vid = n.node_vid
           WHERE n.ref = ?""",
        (ref,),
    ).fetchone()
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


# ---------------------------------------------------------------- 手工改图（`D127` 口径）

#: ★ 允许的动作 —— 与社区版 `web/views/curate.py` 的六种对齐
CURATE_ACTIONS = (
    "add_node",
    "update_node",
    "remove_node",
    "add_edge",
    "update_edge",
    "remove_edge",
    "reparse",
)


def log_curate(
    conn: sqlite3.Connection,
    project_id: int,
    action: str,
    target: str,
    reason: str,
    detail: dict | None = None,
) -> None:
    """★ 每次修补都要留痕（谁/何时/改了什么/为什么）⚠

    ⚠ `reason` **必填** —— 社区版的原话是：
      「用户全权负责」的技术前提是「可追溯」；没有审计，全权负责就变成没人负责。
      个人版虽然只有一个人，但半年后你自己也想知道"这条边当初为什么加上"。
    """
    if action not in CURATE_ACTIONS:
        raise ValueError(f"不认识的动作：{action}")
    if not (reason or "").strip():
        raise ValueError("reason 必填")
    with conn:
        conn.execute(
            "INSERT INTO curate_log (project_id, action, target, reason, detail, at) VALUES (?,?,?,?,?,?)",
            (
                project_id,
                action,
                target,
                reason.strip(),
                json.dumps(detail or {}, ensure_ascii=False),
                time.strftime("%Y-%m-%dT%H:%M:%S"),
            ),
        )


def curate_history(conn: sqlite3.Connection, project_id: int, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM curate_log WHERE project_id = ? ORDER BY id DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def manual_vids(conn: sqlite3.Connection, project_id: int) -> dict:
    """★ 哪些是人补的（图上要打标：`§2.3.12` 规则 2）"""
    nodes = [
        r["vid"]
        for r in conn.execute(
            "SELECT vid FROM node WHERE project_id = ? AND origin = 'manual'", (project_id,)
        ).fetchall()
    ]
    edges = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edge WHERE project_id = ? AND origin = 'manual'", (project_id,)
        ).fetchall()
    ]
    return {"nodes": nodes, "edges": edges}


def add_manual_node(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    kind: str,
    name: str,
    file_path: str,
    line: int,
    line_end: int = -1,
) -> int:
    """手补一个节点（解析器没识别出来的函数/文件）

    ★★ **必须填起止行号**（所有者 2026-10-29）：
      vid = hash(kind|file|name|line|line_end)，行号是这个身份的一部分。
      · · 填真实行号 ⇒ 将来解析器识别出这个函数时，**vid 一致、不会出现两个节点** ✅
      · · 填 -1      ⇒ 永远对不上，会并存两个同名节点 ⚠
      ⇒ 所以行号不是装饰，是**让两套来源能对齐**的唯一办法。
    """
    from graph import identity  # ⚠ 延迟导入：没有 app 目录时给明确错误

    ln = line if isinstance(line, int) and line >= 0 else 0
    end = line_end if isinstance(line_end, int) and line_end >= ln else -1
    vid = identity.hash53(identity.canonical(kind, file_path, name, ln, end))
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO node (project_id, vid, kind, name, qname, file_path, line, line_end, origin)
               VALUES (?,?,?,?,?,?,?,?, 'manual')""",
            (project_id, vid, kind, name, "", file_path, ln, end),
        )
    return vid


def update_node_fields(conn: sqlite3.Connection, project_id: int, vid: int, **fields) -> None:
    """改节点（名字/类型/文件/行）—— 改过的标成 manual"""
    allowed = {
        k: v
        for k, v in fields.items()
        if k in ("name", "kind", "file_path", "line", "line_end") and v is not None
    }
    if not allowed:
        return
    sets = ", ".join(f"{k} = ?" for k in allowed)
    with conn:
        conn.execute(
            f"UPDATE node SET {sets}, origin = 'manual' WHERE project_id = ? AND vid = ?",
            (*allowed.values(), project_id, vid),
        )


def remove_node(conn: sqlite3.Connection, project_id: int, vid: int) -> int:
    """删节点 + 它的所有边（返回删掉的边数）"""
    with conn:
        n = conn.execute(
            "DELETE FROM edge WHERE project_id = ? AND (src_vid = ? OR dst_vid = ?)",
            (project_id, vid, vid),
        ).rowcount
        conn.execute("DELETE FROM node WHERE project_id = ? AND vid = ?", (project_id, vid))
    return int(n)


def add_manual_edge(conn: sqlite3.Connection, project_id: int, src: int, dst: int, kind: str) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO edge (project_id, src_vid, dst_vid, kind, origin) VALUES (?,?,?,?, 'manual')",
            (project_id, src, dst, kind),
        )
    return int(cur.lastrowid or 0)


def remove_edge(conn: sqlite3.Connection, project_id: int, edge_id: int) -> bool:
    with conn:
        n = conn.execute("DELETE FROM edge WHERE project_id = ? AND id = ?", (project_id, edge_id)).rowcount
    return n > 0


def edges_of_node(conn: sqlite3.Connection, project_id: int, vid: int) -> dict:
    """某节点的出边/入边（带对端名字，供改图面板显示）"""
    out = conn.execute(
        """SELECT e.id, e.src_vid, e.dst_vid, e.kind, e.origin,
                  nd.name AS to_name, nd.file_path AS to_file
           FROM edge e LEFT JOIN node nd ON nd.project_id = e.project_id AND nd.vid = e.dst_vid
           WHERE e.project_id = ? AND e.src_vid = ? ORDER BY e.id""",
        (project_id, vid),
    ).fetchall()
    inn = conn.execute(
        """SELECT e.id, e.src_vid, e.dst_vid, e.kind, e.origin,
                  nd.name AS from_name, nd.file_path AS from_file
           FROM edge e LEFT JOIN node nd ON nd.project_id = e.project_id AND nd.vid = e.src_vid
           WHERE e.project_id = ? AND e.dst_vid = ? ORDER BY e.id""",
        (project_id, vid),
    ).fetchall()
    return {"out": [dict(r) for r in out], "in": [dict(r) for r in inn]}
