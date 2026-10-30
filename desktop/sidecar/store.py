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
        ("node", "origin", "TEXT NOT NULL DEFAULT 'parsed'"),
        ("edge", "origin", "TEXT NOT NULL DEFAULT 'parsed'"),
        ("project", "parse_state", "TEXT NOT NULL DEFAULT 'none'"),
        ("project", "parse_error", "TEXT NOT NULL DEFAULT ''"),
    ):
        names = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in names:
            with conn:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def _backfill_parse_state(conn: sqlite3.Connection) -> None:
    """★★ 老库补状态（`parse_state` 是新加的列）⚠

    ```\n * 新列默认 'none' ⇒ 老项目全变成"没解析过" ⇒ **写笔记被门槛拦住**
 * 但它们明明有解析出来的节点 ⇒ 补成 'ok'
 * ```\n
    ⚠ 只在 `parse_state = 'none'` 时补，⛔ 不覆盖 failed（那是真的失败过）。
    """
    with conn:
        conn.execute(
            """UPDATE project SET parse_state = 'ok'
               WHERE parse_state = 'none'
                 AND EXISTS (SELECT 1 FROM node n
                             WHERE n.project_id = project.id AND n.origin = 'parsed')"""
        )


def connect(data_dir: str) -> sqlite3.Connection:
    """⚠ 参数是**项目的数据目录**（`<项目根>/.astrolabe/`），不是库根"""
    os.makedirs(data_dir, exist_ok=True)
    conn = sqlite3.connect(library.db_path(data_dir))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
    _backfill_parse_state(conn)
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
                  (SELECT COUNT(*) FROM node n WHERE n.project_id = p.id) AS node_count,
                  (SELECT COUNT(*) FROM note t WHERE t.project_id = p.id) AS note_count
           FROM project p ORDER BY p.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def find_project(conn: sqlite3.Connection, ref: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM project WHERE ref = ?", (ref,)).fetchone()


# ---------------------------------------------------------------- 图


def replace_graph(conn: sqlite3.Connection, project_id: int, nodes: list[dict], edges: list[dict]) -> dict:
    """整图替换（解析完一次性写入）；★ **笔记按 (kind, 文件, 名字) 迁移到新 vid**

    ## 为什么需要迁移

    ```\n * vid 是内容的函数 ⇒ 函数整体下移 10 行，vid 就变了 ⚠
 * 如果什么都不做，老笔记全部变成「节点已不存在」—— 用户写的字就"断"了
 * ```\n
    ## 匹配规则（**宁可不动，也不挂错**）

    ```
    旧节点 (kind, file_path, name) → 新图里同名同文件的节点
      · · 恰好 1 个   ⇒ 迁移 ✅
      · · 0 个        ⇒ 保持孤儿（真删了/改名了），如实计数
      · · 2 个以上    ⇒ **不迁移**（歧义 ⇒ 挂错更糟），如实计数
    ```

    ⚠★ 绝**不按名字单独匹配**：两个文件里都有 `init` 时，按名字迁移必然挂错位。

    ⚠ 只删 `origin='parsed'`，人手补的节点与边原样保留。
    """
    # ① 先把旧的两个映射拍下来（删掉就没了）
    old_nodes = {
        r["vid"]: {"kind": r["kind"], "file_path": r["file_path"], "name": r["name"]}
        for r in conn.execute(
            "SELECT vid, kind, file_path, name FROM node WHERE project_id = ?", (project_id,)
        ).fetchall()
    }
    notes = [
        dict(r)
        for r in conn.execute(
            "SELECT ref, rel_path, node_vid FROM note WHERE project_id = ?", (project_id,)
        ).fetchall()
    ]

    with conn:
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

    # ② 迁移锚点（新图已经就位，按内容找"同一个函数"）
    new_index: dict[tuple[str, str, str], list[dict]] = {}
    for r in conn.execute(
        "SELECT vid, kind, file_path, name, line FROM node WHERE project_id = ?", (project_id,)
    ).fetchall():
        key = (r["kind"], r["file_path"], r["name"])
        new_index.setdefault(key, []).append({"vid": r["vid"], "line": r["line"]})

    live = {r["vid"] for r in conn.execute("SELECT vid FROM node WHERE project_id = ?", (project_id,))}
    moved: list[dict] = []

    for n in notes:
        if n["node_vid"] in live:
            continue  # 锚点还在，不用动
        old = old_nodes.get(n["node_vid"])
        if not old:
            continue
        cands = new_index.get((old["kind"], old["file_path"], old["name"])) or []
        if len(cands) != 1:
            continue  # ⚠ 找不到 / 有歧义 ⇒ 不猜（挂错更糟）
        with conn:
            conn.execute(
                "UPDATE note SET node_vid = ? WHERE project_id = ? AND ref = ?",
                (cands[0]["vid"], project_id, n["ref"]),
            )
        moved.append(
            {"ref": n["ref"], "rel_path": n["rel_path"], "new_vid": cands[0]["vid"], "old_vid": n["node_vid"]}
        )

    return {"moved": moved}


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


def _next_local_vid(conn: sqlite3.Connection) -> int:
    """★ 空白结构的节点身份：**自增号**，不是内容哈希 ⚠

    ```\n * 非代码主题没有 file 和 line，哈希算出来的身份会强迫"同名合并"
 * 自增号 ⇒ 可以重名、改名不改身份、文档永远跟着走
 * ```\n
    ⚠ 空白项目里不存在解析出来的节点 ⇒ 不会和哈希 vid 撞车。
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'next_local_vid'").fetchone()
    cur = int(row["value"]) if row else 0
    nxt = cur + 1
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('next_local_vid', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(nxt),),
        )
    return nxt


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
    # ★ 不再按 kind 过滤：空白结构的类型是自由文本（人物/概念/…），
    #   写死 file/function/type 会让它的节点数恒为 0 ⚠
    # ⚠ 目录节点（kind='dir'）**不算**进写作进度：它是导航用的骨架，
    #   不是"该写笔记的地方"，算进去会让分母虚高、完成度永远上不去
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM node WHERE project_id = ? AND kind <> 'dir'", (project_id,)
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
    local: bool = False,
) -> int:
    """手补一个节点（解析器没识别出来的函数/文件）

    ★★ **必须填起止行号**（所有者 2026-10-29）：
      vid = hash(kind|file|name|line|line_end)，行号是这个身份的一部分。
      · · 填真实行号 ⇒ 将来解析器识别出这个函数时，**vid 一致、不会出现两个节点** ✅
      · · 填 -1      ⇒ 永远对不上，会并存两个同名节点 ⚠
      ⇒ 所以行号不是装饰，是**让两套来源能对齐**的唯一办法。
    """
    # ★ 空白结构：自增号 + 允许重名（⛔ 不用 INSERT OR REPLACE）
    if local:
        vid = _next_local_vid(conn)
        with conn:
            conn.execute(
                """INSERT INTO node (project_id, vid, kind, name, qname, file_path, line, line_end, origin)
                   VALUES (?,?,?,?,?,?,?,?, 'manual')""",
                (project_id, vid, kind, name, "", "", -1, -1),
            )
        return vid

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


def update_node_fields(
    conn: sqlite3.Connection, project_id: int, vid: int, local: bool = False, **fields
) -> dict:
    """★★★ 改节点字段 ⇒ **重算 vid ⇒ 级联迁移**（2026-10-29）⚠

    ## 为什么必须级联

    ```\n * vid = hash(kind|file|name|line|line_end) —— **它是内容的函数**
 * 改了行号/名字 ⇒ vid 必须跟着变，否则身份与内容脱钩
 *   ⇒ 重新解析时算出正确的 vid，图上会出现**两个同名节点** ⚠
 * ```\n
    ## 迁移什么

    ```
    ① note.node_vid        （库里的锚点）
    ② .md 的 frontmatter   （文件里的锚点 —— 由调用方改写，文件是真相）
    ③ edge.src_vid/dst_vid （关系跟着走）
    ```

    ⚠★ **新 vid 已存在 ⇒ 合并**：把笔记并过去、删掉旧节点，⛔ 不留两份。

    ⚠★ **匹配必须精确**：迁移只发生在"这一个旧 vid → 这一个新 vid"之间，
      绝不按名字猜 —— 两个文件里有同名函数时，按名字迁移必挂错位。
    """
    if local:
        # ★ 空白结构：**改名不换身份**（自增号是它的身份），所以不走哈希那条路
        row = conn.execute(
            "SELECT * FROM node WHERE project_id = ? AND vid = ?", (project_id, vid)
        ).fetchone()
        if row is None:
            return {"changed": False, "reason": "节点不存在"}
        allowed = {k: v for k, v in fields.items() if k in ("name", "kind") and v is not None}
        if allowed:
            sets = ", ".join(f"{k} = ?" for k in allowed)
            with conn:
                conn.execute(
                    f"UPDATE node SET {sets}, origin = 'manual' WHERE project_id = ? AND vid = ?",
                    (*allowed.values(), project_id, vid),
                )
        return {"changed": False, "old_vid": vid, "new_vid": vid, "merged": False, "notes": []}

    from graph import identity

    row = conn.execute(
        "SELECT * FROM node WHERE project_id = ? AND vid = ?", (project_id, vid)
    ).fetchone()
    if row is None:
        return {"changed": False, "reason": "节点不存在"}

    cur = dict(row)
    for k in ("name", "kind", "file_path", "line", "line_end"):
        if fields.get(k) is not None:
            cur[k] = fields[k]

    ln = int(cur["line"] or 0)
    end = int(cur["line_end"] if cur["line_end"] is not None else -1)
    if end >= 0 and end < ln:
        end = -1

    new_vid = identity.hash53(identity.canonical(cur["kind"], cur["file_path"], cur["name"], ln, end))

    notes = conn.execute(
        "SELECT ref, rel_path FROM note WHERE project_id = ? AND node_vid = ?", (project_id, vid)
    ).fetchall()
    merged = False

    with conn:
        conn.execute(
            """UPDATE node SET name = ?, kind = ?, file_path = ?, line = ?, line_end = ?, origin = 'manual'
               WHERE project_id = ? AND vid = ?""",
            (cur["name"], cur["kind"], cur["file_path"], ln, end, project_id, vid),
        )

        if new_vid != vid:
            # 新身份是否已被占用（比如解析器早就算出过同一个节点）
            clash = conn.execute(
                "SELECT 1 FROM node WHERE project_id = ? AND vid = ?", (project_id, new_vid)
            ).fetchone()
            if clash:
                merged = True
                conn.execute("DELETE FROM node WHERE project_id = ? AND vid = ?", (project_id, vid))
            else:
                conn.execute(
                    "UPDATE node SET vid = ? WHERE project_id = ? AND vid = ?",
                    (new_vid, project_id, vid),
                )
            # ★ 笔记与边无条件跟着走（合并时也过来）
            conn.execute(
                "UPDATE note SET node_vid = ? WHERE project_id = ? AND node_vid = ?",
                (new_vid, project_id, vid),
            )
            conn.execute(
                "UPDATE edge SET src_vid = ? WHERE project_id = ? AND src_vid = ?",
                (new_vid, project_id, vid),
            )
            conn.execute(
                "UPDATE edge SET dst_vid = ? WHERE project_id = ? AND dst_vid = ?",
                (new_vid, project_id, vid),
            )

    return {
        "changed": new_vid != vid,
        "old_vid": vid,
        "new_vid": new_vid,
        "merged": merged,
        "notes": [dict(n) for n in notes],
    }


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


# ---------------------------------------------------------------- 全文检索

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
