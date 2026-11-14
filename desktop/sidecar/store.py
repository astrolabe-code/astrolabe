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
  graph_rev   INTEGER NOT NULL DEFAULT 0,
  -- ★★ 解析状态：none（还没解析）/ ok（图完整，可以写）/ failed（解析出错，禁止写）⚠
  parse_state TEXT NOT NULL DEFAULT 'none',
  parse_error TEXT NOT NULL DEFAULT ''
);


-- ★★ 结构体/类的字段（`HAS_PROPERTY` 那种信息）⚠
--   ⛔ **不建节点、不建边**：字段上写笔记没有意义，但"它有哪些字段"对读源码有用
--   ⇒ 只在节点详情里列出来，图不受影响
CREATE TABLE IF NOT EXISTS node_field (
  id        INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  owner_vid INTEGER NOT NULL,
  name      TEXT NOT NULL,
  type_text TEXT NOT NULL DEFAULT '',
  line      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_field_owner ON node_field (project_id, owner_vid);


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
-- ★ 键值元数据：目前只放 `next_no`（编号单调递增，**永不复用**）
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- ★★ 全文检索索引（`note_fts`）—— 只做检索用，⛔ 不是真相
--   ⚠ 正文在这里有一份副本；但它是**派生数据**：
--     删掉整个 index.db，重扫 md 就能重建（"文件是真相"没变）
--   ⚠ trigram：中文没有空格，按"三字片段"切，子串匹配最贴近"我记得那句话"
CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
  ref UNINDEXED,
  title,
  body,
  tokenize='trigram'
);

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
        ("project", "parse_state", "TEXT NOT NULL DEFAULT 'none'"),
        ("project", "parse_error", "TEXT NOT NULL DEFAULT ''"),
    ):
        names = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in names:
            with conn:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")




def connect(data_dir: str) -> sqlite3.Connection:
    """⚠ 参数是**项目的数据目录**（`<项目根>/.astrolabe/`），不是库根"""
    os.makedirs(data_dir, exist_ok=True)
    conn = sqlite3.connect(library.db_path(data_dir))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
    return conn


# ---------------------------------------------------------------- 项目


def get_or_create_project(
    conn: sqlite3.Connection, name: str, code_root: str, ref: str | None = None
) -> sqlite3.Row:
    """取或建本库里的项目行（**每个数据目录只有一个项目**）

    ★ 个人版没有"库"，一个源码目录 = 一个数据目录 = 一个 sqlite。
      ⇒ 这张表实际上只有一行，"按目录/名字去重"那套逻辑已经不需要了。

    ⚠ `ref` 由调用方给（存在全局清单里），⛔ 这里不再自己编 ——
      否则清单里的 ref 和库里的 ref 对不上（踩过：TypeError: NoneType）。
    """
    row = conn.execute("SELECT * FROM project LIMIT 1").fetchone()
    if row:
        return row

    d = library.project_dir_name(name)
    ref = ref or ("p_" + d.lower().replace(" ", "-")[:40])
    with conn:
        conn.execute(
            "INSERT INTO project (ref, name, root, dir, created_at) VALUES (?,?,?,?,?)",
            (ref, name, os.path.abspath(code_root) if code_root else "", d, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
    return conn.execute("SELECT * FROM project WHERE ref = ?", (ref,)).fetchone()


def set_parse_state(
    conn: sqlite3.Connection, project_id: int, state: str, error: str = "", stats: dict | None = None
) -> None:
    """★★ 解析状态（**写笔记的门槛**）

    ```\n * ok      图可用 ⇒ 可以写笔记（空白项目建完直接给 ok）
 * failed  解析出错 / 没出节点 ⇒ **禁止写笔记**，只能重新解析
 * none    还没解析过
 ```\n
    ⚠ 所有者口径（2026-10-29）：
      「如果解析出错了，就不允许写笔记，只有用户点重新解析后，
        解析未出错、出图完整后，才允许写笔记。」
    """
    with conn:
        conn.execute(
            "UPDATE project SET parse_state = ?, parse_error = ?, parsed_at = ? WHERE id = ?",
            (
                state,
                (error or "")[:500],
                time.strftime("%Y-%m-%dT%H:%M:%S") if state != "none" else None,
                project_id,
            ),
        )


def parse_state_of(conn: sqlite3.Connection, project_id: int) -> tuple[str, str]:
    r = conn.execute(
        "SELECT parse_state, parse_error FROM project WHERE id = ?", (project_id,)
    ).fetchone()
    return (r["parse_state"], r["parse_error"]) if r else ("none", "")


def create_blank_project(conn: sqlite3.Connection, root: str, name: str) -> sqlite3.Row:
    """★★ 空白项目 —— **不用源码，就是写节点**（`B184`）⚠

    ```\n * 用途：把「锚定结构」这件事用到非代码主题上（小说人物 / 论文概念 / 业务模块…）
 * root 留空串 ⇒ 表示"没有源码"，解析端点会拒绝解析它
 * 节点与连线全靠手补（`curate` 的 add_node / add_edge）
 * ```\n
    ⚠ 空白项目**不去重**（每次都新建一本）：没有目录可当身份，用户可能就是想要两张板。
    """
    base = (name or "新结构").strip() or "新结构"
    nm = base
    d = library.project_dir_name(nm)
    i = 1
    while conn.execute("SELECT 1 FROM project WHERE name = ? OR dir = ?", (nm, d)).fetchone():
        nm = f"{base}{i}"
        d = library.project_dir_name(nm)
        i += 1

    ref = "b_" + d.lower().replace(" ", "-")[:40]
    base_ref, j = ref, 1
    while conn.execute("SELECT 1 FROM project WHERE ref = ?", (ref,)).fetchone():
        j += 1
        ref = f"{base_ref}-{j}"

    with conn:
        conn.execute(
            "INSERT INTO project (ref, name, root, dir, created_at) VALUES (?,?,?,?,?)",
            (ref, nm, "", d, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
    return conn.execute("SELECT * FROM project WHERE ref = ?", (ref,)).fetchone()


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM note t WHERE t.project_id = p.id) AS note_count
           FROM project p ORDER BY p.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def find_project(conn: sqlite3.Connection, ref: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM project WHERE ref = ?", (ref,)).fetchone()


# ---------------------------------------------------------------- 图


def next_no(conn: sqlite3.Connection) -> int:
    """★★ 下一个编号 —— **单调递增，永不复用**（`D…` 2026-10-29）⚠

    ```\n * ⛔ 原来用 `MAX(no)+1`：删掉最后一篇之后再建，编号会被**回收**
 *    ⇒ 文件可能和 `.trash/` 里的旧文件同名，恢复时容易挂错
 * ✅ 改成 meta 里的计数器：只增不减，编号即身份的一部分
 * ```\n
    ⚠ 第一次跑（老库）要跟现有 `MAX(no)` 对齐，否则会重复。
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'next_no'").fetchone()
    cur = int(row["value"]) if row else 0
    floor = int(conn.execute("SELECT COALESCE(MAX(no), 0) AS n FROM note").fetchone()["n"])
    nxt = max(cur, floor) + 1
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('next_no', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(nxt),),
        )
    return nxt


def notes_of(conn: sqlite3.Connection, project_id: int, node_vid: int | None = None) -> list[dict]:
    sql = """SELECT n.*, '' AS node_name, '' AS file_path,
                    0 AS line
             FROM note n              WHERE n.project_id = ?"""
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
        """SELECT n.*, '' AS node_name, '' AS file_path,
                  0 AS line
           FROM note n            WHERE n.ref = ?""",
        (ref,),
    ).fetchone()
    return dict(r) if r else None


def delete_note(conn: sqlite3.Connection, ref: str) -> None:
    with conn:
        conn.execute("DELETE FROM note WHERE ref = ?", (ref,))


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


_FTS_OK: dict[int, bool] = {}


def fts_available(conn: sqlite3.Connection) -> bool:
    """FTS5 是否可用（不可用时调用方退化成扫描文件）"""
    key = id(conn)
    if key not in _FTS_OK:
        try:
            conn.execute("SELECT 1 FROM note_fts LIMIT 1").fetchone()
            _FTS_OK[key] = True
        except sqlite3.Error:
            _FTS_OK[key] = False
    return _FTS_OK[key]


def fts_sync(conn: sqlite3.Connection, ref: str, title: str, body: str) -> None:
    """把一篇笔记写进检索索引（⚠ 先删后插，避免残留旧正文）"""
    if not fts_available(conn):
        return
    with conn:
        conn.execute("DELETE FROM note_fts WHERE ref = ?", (ref,))
        conn.execute(
            "INSERT INTO note_fts (ref, title, body) VALUES (?,?,?)", (ref, title or "", body or "")
        )


def fts_remove(conn: sqlite3.Connection, ref: str) -> None:
    if not fts_available(conn):
        return
    with conn:
        conn.execute("DELETE FROM note_fts WHERE ref = ?", (ref,))


def fts_search(conn: sqlite3.Connection, q: str, limit: int = 20) -> list[dict]:
    """★★ 搜笔记正文/标题（返回命中片段）

    ⚠ 用 `LIKE '%q%'` 而不是 `MATCH`：
      · trigram 索引能加速 3 字以上的 LIKE（SQLite 会自动走索引）
      · 两个字的中文词（「退化」）MATCH 命中不了，LIKE 可以
      · 用户记得的是"那几个字"，不是"词" ⇒ 子串匹配才是对路的
    """
    if not fts_available(conn) or not q.strip():
        return []
    like = f"%{q.strip()}%"
    rows = conn.execute(
        """SELECT ref, title, body FROM note_fts
           WHERE body LIKE ? OR title LIKE ?
           ORDER BY (CASE WHEN title LIKE ? THEN 0 ELSE 1 END), length(body)
           LIMIT ?""",
        (like, like, like, limit),
    ).fetchall()

    out = []
    for r in rows:
        body = r["body"] or ""
        pos = body.find(q.strip())
        if pos < 0:
            snippet = body[:60]
        else:
            a = max(0, pos - 26)
            b = min(len(body), pos + len(q.strip()) + 34)
            snippet = ("…" if a > 0 else "") + body[a:b].replace("\n", " ") + ("…" if b < len(body) else "")
        out.append({"ref": r["ref"], "title": r["title"], "snippet": snippet})
    return out
