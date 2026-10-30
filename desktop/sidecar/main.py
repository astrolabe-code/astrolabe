#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ Astrolabe 个人版 · Python 边车（stdio 协议）

## 它是什么

```\n壳（Electron）── 换行分隔 JSON ──▶ 本进程\n           ◀──────────────────────\n```\n
**不监听任何端口**。这是"端口被占 / localhost 被安全策略封"这两类问题的根治办法。

## 协议

```json
→ {"id": 1, "method": "GET", "path": "/api/me/", "body": null}
← {"id": 1, "status": 200, "body": {"ok": true, "data": {...}}}
```

⚠ 一行一条，⛔ 不要格式化输出。
⚠ 任何异常都要**转成一行错误响应**，⛔ 不能抛到 stdout 里 —— 壳会解析失败。

## 数据在哪

```\n库根（vault）/            默认 <数据目录>/books/main，可用 ASTROLABE_LIBRARY 覆盖\n├─ .astrolabe/index.db    SQLite 索引（可删可重建）\n├─ flask/0001-xxx.md      笔记文件（真相源）\n└─ redis/…\n```\n
详见 `library.py` / `store.py` / `notefile.py` / `indexer.py` 各自的头部注释。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.parse

import autotitle
import indexer
import library
import projectstore
import notefile
import store

VERSION = "0.3.0"

# ★★★ 个人版**没有"库"这一层**（所有者 2026-10-30）：
#   一个源码目录 = 一本书，数据就在 `<源码>/.astrolabe/`。
#   ROOT 现在的含义 = **当前项目的数据目录**（不是库根）。
ROOT = ""
CONN = None
def _data_dir() -> str:
    """全局数据目录（exe 旁的 data/）：只放项目清单和空白结构的数据"""
    return library.data_dir()


def init() -> None:
    """启动：把清单里每个项目的索引跟磁盘对齐一遍（几百篇 = 几十毫秒）"""
    for entry in projectstore.list_all():
        try:
            _activate(entry)
            indexer.rescan(entry["data"], CONN, entry.get("name") or "")
        except Exception:  # noqa: BLE001 —— 某个项目坏了不能挡住启动
            continue


def _activate(entry: dict) -> None:
    """★ 把全局上下文切到这个项目（单线程 stdio ⇒ 切换是安全的）

    ⚠★ 每次都校验**索引文件还在不在**：
      · 文件被删/被换掉 ⇒ 旧连接指向的是已删除的 inode（幽灵库），
        继续用它会"看起来有数据"，实际写进去的是没人读的鬼文件
      · 所以这里重连 + 重建索引 —— 这正是"索引可丢可重建"的兑现
    """
    global ROOT, CONN
    data = entry["data"]
    db = library.db_path(data)
    if CONN is not None and ROOT == data and os.path.exists(db):
        return
    if CONN is not None:
        try:
            CONN.close()
        except Exception:  # noqa: BLE001
            pass
    ROOT = data
    fresh = not os.path.exists(db)
    CONN = store.connect(data)

    # ★ 索引重建时，项目行也在库里（一个数据目录只有一个项目）⇒ 得补回来
    if CONN.execute("SELECT 1 FROM project LIMIT 1").fetchone() is None:
        row = store.get_or_create_project(
            CONN, entry.get("name") or "", entry.get("root") or "", ref=entry["ref"]
        )
        # 空白结构没有解析这回事；源码项目则回到"未解析"（节点表也丢了）
        if not (entry.get("root") or "").strip():
            store.set_parse_state(CONN, row["id"], "ok", "")

    if fresh:
        try:
            indexer.rescan(data, CONN, entry.get("name") or "")
        except Exception:  # noqa: BLE001
            pass


def ok(data) -> tuple[int, dict]:
    return 200, {"ok": True, "data": data}


def bad(msg: str, code: int = 400) -> tuple[int, dict]:
    return code, {"ok": False, "error": msg}


# ---------------------------------------------------------------- 路由

R_PROJECT = re.compile(r"^/api/projects/([^/]+)/$")
R_NODES = re.compile(r"^/api/projects/([^/]+)/nodes/$")
R_PNOTES = re.compile(r"^/api/projects/([^/]+)/notes/$")
R_NOTE = re.compile(r"^/api/notes/([^/]+)/$")
R_SCAN = re.compile(r"^/api/fs/scan$")
R_PARSE = re.compile(r"^/api/projects/([^/]+)/parse$")
R_WPROG = re.compile(r"^/api/projects/([^/]+)/writing-progress/$")
R_RPATH = re.compile(r"^/api/projects/([^/]+)/reading-path/$")
R_GRAPH = re.compile(r"^/api/projects/([^/]+)/graph/$")
R_CURATE = re.compile(r"^/api/projects/([^/]+)/curate/$")
R_MANUAL = re.compile(r"^/api/projects/([^/]+)/manual/$")
R_EDGES = re.compile(r"^/api/projects/([^/]+)/edges/$")


def _data_dir_is_ours(data_dir: str, code_root: str) -> bool:
    """★ 那个 `.astrolabe/` 是不是**本程序为这个仓库**建的 ⚠

    ```\n * 有 index.db 且里面 project.root == 当前源码目录 ⇒ 是我们的 ⇒ 直接打开
 * 没有 index.db / root 对不上 / 打不开          ⇒ 不是（或认不出）⇒ 要问用户
 ```\n
    ⚠ 宁可多问一句，也不要往别人的数据目录里写东西。
    """
    db = os.path.join(data_dir, "index.db")
    if not os.path.isfile(db):
        return False
    try:
        import sqlite3 as _s

        c = _s.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = c.execute("SELECT root FROM project LIMIT 1").fetchone()
        finally:
            c.close()
        return bool(row) and os.path.abspath(str(row[0] or "")) == os.path.abspath(code_root)
    except Exception:  # noqa: BLE001
        return False


def _split_query(path: str) -> tuple[str, dict]:
    """拆出 query（⚠ 边车拿到的是 `/api/x/?a=1` 这种完整路径）"""
    if "?" not in path:
        return path, {}
    pure, qs = path.split("?", 1)
    q = urllib.parse.parse_qs(qs)
    return pure, {k: v[0] for k, v in q.items()}


def _project(ref: str):
    """★ 按 ref 找到项目并把上下文切过去（数据跟着项目走）"""
    entry = projectstore.get(ref)
    if entry is None:
        return None
    try:
        _activate(entry)
    except Exception:  # noqa: BLE001
        return None
    row = store.find_project(CONN, ref)
    return row


def handle(method: str, raw_path: str, body: dict | None) -> tuple[int, dict]:
    # ★ 换库要改这两个全局量 ⇒ global 声明必须放在函数最前面（Python 规则）
    global ROOT, CONN
    body = dict(body or {})
    path, query = _split_query(raw_path)
    # ★ GET 没有 body ⇒ 把 query 合进 body，后面的分支只认 body 一种取法
    for k, v in query.items():
        body.setdefault(k, v)

    # ------------------------------------------------ 固定几个
    if path == "/api/site-config/":
        return ok({"siteMode": "personal", "theme": "plain", "resumeDwellSeconds": 20})

    if path == "/api/me/":
        # ★ 个人版没有登录：永远是「本机用户」
        return ok({"authenticated": True, "username": "我", "display": "我", "is_staff": True})

    if path == "/api/ping":
        return ok({"pong": True, "version": VERSION, "library": ROOT, "dataDir": _data_dir()})

    if path == "/api/library/":
        # ★ 个人版没有"库"：这里只回全局数据目录 + 项目清单（只记路径）
        items = projectstore.list_all()
        total_notes = 0
        for it in items:
            try:
                _activate(it)
                total_notes += CONN.execute("SELECT COUNT(*) AS c FROM note").fetchone()["c"]
            except Exception:  # noqa: BLE001
                continue
        return ok({"dataDir": _data_dir(), "projects": items, "notes": total_notes})

    m = re.compile(r"^/api/projects/([^/]+)/rescan$").match(path)
    if m and method == "POST":
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        return ok(indexer.rescan(ROOT, CONN, p["name"]))

    # ------------------------------------------------ 扫描目录（建项目前先看一眼）
    if R_SCAN.match(path) and method == "POST":
        root = str(body.get("path") or "").strip()
        if not root or not os.path.isdir(root):
            return bad("目录不存在或不可读")
        return ok(_scan_dir(root))

    # ------------------------------------------------ 解析（把代码目录变成图）
    m = R_PARSE.match(path)
    if m and method == "POST":
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        if not (p["root"] or "").strip():
            return bad("这个项目没有源码目录（空白结构），不需要解析", 400)

        try:
            import parser_bridge  # ⚠ 延迟导入：缺 tree-sitter 时给明确错误，而不是起不来
        except Exception as exc:  # noqa: BLE001
            return bad(f"解析器不可用：{type(exc).__name__}: {exc}", 501)

        # ★★★ 重新解析是**修复手段**，不是日常操作（所有者 2026-10-29）⚠
        #   「只有解析出错了、没出完整的图，才能重新解析」
        existing = CONN.execute(
            "SELECT COUNT(*) AS c FROM node WHERE project_id = ? AND origin = 'parsed'", (p["id"],)
        ).fetchone()["c"]
        if existing and not body.get("force"):
            return 409, {
                "ok": False,
                "code": "graph_exists",
                "nodes": int(existing),
                "error": (
                    f"这个项目已经解析出 {existing} 个节点了。"
                    "重新解析是用来修复「图不完整 / 解析出错」的，不是日常操作 —— "
                    "确实要重建吗？（人手补的节点和边会保留）"
                ),
            }

        res = parser_bridge.parse_project(p["root"])
        st = res["stats"]
        # ★★ 什么算「解析成功、图完整」：出节点 且 没有解析错误 ⚠
        #   ⇒ 不满足就置 failed，**写笔记会被拒**（见下面 POST notes 的门槛）
        if not res["nodes"] or st.get("parseErrors", 0) > 0:
            msg = (
                "没有解析出任何节点 —— 目录可能不含支持的源码，或缺 tree-sitter 语法包"
                if not res["nodes"]
                else f"解析有 {st['parseErrors']} 处错误，图不完整"
            )
            store.set_parse_state(CONN, p["id"], "failed", msg, st)
            return bad(msg, 422)
        store.set_parse_state(CONN, p["id"], "ok", "", st)
        mig = store.replace_graph(CONN, p["id"], res["nodes"], res["edges"])

        # ★ 迁移过的笔记，**文件里的 frontmatter 也要跟着改**（否则索引重建会退回去）
        for m in mig.get("moved", []):
            abs_md = os.path.join(ROOT, m["rel_path"])
            if not os.path.exists(abs_md):
                continue
            node = store.node_by_vid(CONN, p["id"], m["new_vid"]) or {}
            meta, text = notefile.read_file(abs_md)
            meta["node_vid"] = m["new_vid"]
            meta["node"] = node.get("name") or meta.get("node", "")
            meta["anchor"] = f"{node.get('file_path', '')}:{node.get('line', 0)}"
            notefile.write_file(abs_md, meta, text)
            st = os.stat(abs_md)
            store.update_note(CONN, m["ref"], mtime=st.st_mtime, size=st.st_size)
        # ★ 重建要留痕（它是修复动作，半年后要能看出"哪天重来过"）
        if existing:
            try:
                store.log_curate(
                    CONN,
                    p["id"],
                    "reparse",
                    "graph",
                    str(body.get("reason") or "重新解析（修复图不完整）"),
                    {"nodes": res["stats"]["nodes"], "edges": res["stats"]["edges"]},
                )
            except ValueError:
                pass
        return ok({"stats": res["stats"], "project": dict(store.find_project(CONN, p["ref"]))})

    # ------------------------------------------------ 项目
    if path == "/api/projects/":
        if method == "GET":
            # ★ 清单 + 每个项目自己的统计（各开各的 DB）
            items = []
            for it in projectstore.list_all():
                try:
                    _activate(it)
                    row = store.find_project(CONN, it["ref"])
                    if row is None:
                        continue
                    d = dict(row)
                    d["root"] = it.get("root") or ""
                    d["data"] = it.get("data") or ""
                    st = store.parse_state_of(CONN, row["id"])
                    d["parse_state"] = st[0]
                    d["parse_error"] = st[1]
                    d["node_count"] = CONN.execute(
                        "SELECT COUNT(*) AS c FROM node WHERE project_id = ?", (row["id"],)
                    ).fetchone()["c"]
                    d["note_count"] = CONN.execute(
                        "SELECT COUNT(*) AS c FROM note WHERE project_id = ?", (row["id"],)
                    ).fetchone()["c"]
                    items.append(d)
                except Exception:  # noqa: BLE001
                    continue
            return ok({"items": items})

        if method == "POST":
            code_root = str(body.get("path") or "").strip()
            blank = bool(body.get("blank")) or not code_root

            # ★★★ 空白结构：**不用源码，就是写节点**（`B184`）
            #   它的数据放 `<数据目录>/structures/<名字>/`
            if blank:
                name = projectstore.unique_name(str(body.get("name") or "新结构"))
                root = library.blank_root(name)
                entry = {
                    "ref": projectstore.unique_ref("b_" + name.lower().replace(" ", "-")[:40]),
                    "name": name,
                    "root": "",
                    "data": library.ensure_data_dir(root),
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                projectstore.upsert(entry)
                _activate(entry)
                p = store.get_or_create_project(CONN, name, "", ref=entry["ref"])
                store.set_parse_state(CONN, p["id"], "ok", "")
                fresh = store.find_project(CONN, entry["ref"]) or p
                return ok({"project": {**dict(fresh), "root": ""}})

            if not os.path.isdir(code_root):
                return bad("代码目录不存在")
            code_root = os.path.abspath(code_root)

            # ★ 同一个**源码目录**只建一次（数据就在那个目录里，天然唯一）
            for it in projectstore.list_all():
                if os.path.abspath(it.get("root") or "") == code_root:
                    _activate(it)
                    return ok({"project": dict(store.find_project(CONN, it["ref"]))})

            # ★★★ 建之前先看：源码目录里**已经有个 `.astrolabe/`** ⇒ 必须问用户 ⚠
            #   （所有者 2026-10-30：「建的时候还是要查一下……提示用户覆盖还是换个地方」）
            data_dir = str(body.get("data_dir") or "").strip()
            if data_dir:
                data_dir = os.path.abspath(data_dir)
            else:
                data_dir = library.data_subdir(code_root)
                if os.path.isdir(data_dir) and not body.get("adopt"):
                    ours = _data_dir_is_ours(data_dir, code_root)
                    if not ours:
                        return 409, {
                            "ok": False,
                            "code": "data_exists",
                            "path": data_dir,
                            "error": (
                                "这个源码目录里已经有一个 .astrolabe/ 了，"
                                "但看起来不是本程序为这个仓库建的 —— 要接管它，还是换个地方放笔记？"
                            ),
                        }

            name = projectstore.unique_name(
                str(body.get("name") or os.path.basename(code_root.rstrip("/\\")) or "未命名")
            )
            entry = {
                "ref": projectstore.unique_ref("p_" + name.lower().replace(" ", "-")[:40]),
                "name": name,
                "root": code_root,
                # ★★ 数据就放在源码目录里的 `.astrolabe/`（⛔ 不占 `data/`）
                "data": library.ensure_dir_at(data_dir),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            projectstore.upsert(entry)
            _activate(entry)
            p = store.get_or_create_project(CONN, name, code_root, ref=entry["ref"])
            return ok({"project": dict(p)})

    m = R_PROJECT.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        if method == "GET":
            pstate, perr = store.parse_state_of(CONN, p["id"])
            d = dict(p)
            d["parse_state"] = pstate
            d["parse_error"] = perr
            return ok({"project": d, "stats": store.stats(CONN, p["id"])})

    # ★ 写作进度：个人版没有"读者"，所以只有作者视角这一个数字
    m = R_WPROG.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        st = store.stats(CONN, p["id"])
        noted = CONN.execute(
            "SELECT COUNT(DISTINCT node_vid) AS c FROM note WHERE project_id = ?", (p["id"],)
        ).fetchone()["c"]
        return ok({"nodes": st["nodes"], "summary": st["summaryNodes"], "noted": int(noted)})

    # ★ 导读路径：个人版暂时没有排序功能 ⇒ 空列表（组件会显示"还没排"，不报错）
    m = R_RPATH.match(path)
    if m:
        if not _project(m.group(1)):
            return bad("项目不存在", 404)
        return ok({"total": 0, "items": [], "stale": []})

    # ★★ 整张图（一次给全）—— 图谱页用，⛔ 不分页（个人版一个项目最多几千节点）
    m = R_GRAPH.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        nodes = CONN.execute(
            "SELECT vid, kind, name, qname, file_path, line, line_end, origin FROM node WHERE project_id = ?",
            (p["id"],),
        ).fetchall()
        edges = CONN.execute(
            "SELECT id, src_vid, dst_vid, kind, origin FROM edge WHERE project_id = ?", (p["id"],)
        ).fetchall()
        return ok(
            {
                "rev": int(p["graph_rev"] or 0),
                "nodes": [dict(r) for r in nodes],
                "edges": [
                    {"id": r["id"], "from": r["src_vid"], "to": r["dst_vid"], "type": r["kind"], "origin": r["origin"]}
                    for r in edges
                ],
            }
        )

    # ------------------------------------------------ 手工改图（六种动作）
    m = R_CURATE.match(path)
    if m and method == "POST":
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        action = str(body.get("action") or "")
        reason = str(body.get("reason") or "").strip()
        if not reason:
            return bad("必须填一句理由（改了什么、为什么）")
        try:
            if action == "add_node":
                vid = store.add_manual_node(
                    CONN,
                    p["id"],
                    kind=str(body.get("kind") or "function"),
                    name=str(body.get("name") or "").strip(),
                    file_path=str(body.get("file_path") or ""),
                    line=int(body.get("line") or 0),
                    line_end=int(body.get("line_end") if body.get("line_end") is not None else -1),
                    # ★ 空白结构（无源码）⇒ 自增号身份，不问文件行号
                    local=not (p["root"] or "").strip(),
                )
                store.log_curate(
                    CONN,
                    p["id"],
                    action,
                    str(vid),
                    reason,
                    {"name": body.get("name"), "line": body.get("line"), "line_end": body.get("line_end")},
                )
                return ok({"vid": vid})

            if action == "update_node":
                vid = int(body.get("vid") or 0)
                res = store.update_node_fields(
                    CONN,
                    p["id"],
                    vid,
                    name=body.get("name"),
                    kind=body.get("kind"),
                    file_path=body.get("file_path"),
                    line=body.get("line"),
                    line_end=body.get("line_end"),
                    local=not (p["root"] or "").strip(),
                )
                # ★★ vid 变了 ⇒ **笔记的 frontmatter 也要改**（文件是真相，
                #    只改库的话，下次索引重建会从文件里读回旧锚点）
                if res.get("changed"):
                    node = store.node_by_vid(CONN, p["id"], res["new_vid"]) or {}
                    for n in res.get("notes", []):
                        abs_md = os.path.join(ROOT, n["rel_path"])
                        if not os.path.exists(abs_md):
                            continue
                        meta, text = notefile.read_file(abs_md)
                        meta["node_vid"] = res["new_vid"]
                        meta["node"] = node.get("name") or meta.get("node", "")
                        meta["anchor"] = f"{node.get('file_path','')}:{node.get('line',0)}"
                        notefile.write_file(abs_md, meta, text)
                        st = os.stat(abs_md)
                        store.update_note(CONN, n["ref"], mtime=st.st_mtime, size=st.st_size)
                store.log_curate(
                    CONN,
                    p["id"],
                    action,
                    str(vid),
                    reason,
                    {"fields": list(body), "vidChanged": res.get("changed"), "newVid": res.get("new_vid")},
                )
                return ok({"vid": res.get("new_vid", vid), **res})

            if action == "remove_node":
                vid = int(body.get("vid") or 0)
                n = store.remove_node(CONN, p["id"], vid)
                store.log_curate(CONN, p["id"], action, str(vid), reason, {"edgesRemoved": n})
                return ok({"removed": vid, "edges": n})

            if action == "add_edge":
                src, dst = int(body.get("from") or 0), int(body.get("to") or 0)
                if not src or not dst or src == dst:
                    return bad("两端的节点不对")
                eid = store.add_manual_edge(CONN, p["id"], src, dst, str(body.get("type") or "call"))
                store.log_curate(CONN, p["id"], action, str(eid), reason, {"from": src, "to": dst})
                return ok({"id": eid})

            if action == "update_edge":
                # ⚠ 个人版只允许改类型（改端点 = 删了重加，语义更清楚）
                eid = int(body.get("id") or 0)
                with CONN:
                    CONN.execute(
                        "UPDATE edge SET kind = ?, origin = 'manual' WHERE project_id = ? AND id = ?",
                        (str(body.get("type") or "call"), p["id"], eid),
                    )
                store.log_curate(CONN, p["id"], action, str(eid), reason, {"type": body.get("type")})
                return ok({"id": eid})

            if action == "remove_edge":
                eid = int(body.get("id") or 0)
                okk = store.remove_edge(CONN, p["id"], eid)
                store.log_curate(CONN, p["id"], action, str(eid), reason)
                return ok({"removed": eid, "ok": okk})

            return bad(f"不认识的动作：{action}")
        except ValueError as exc:
            return bad(str(exc))
        except Exception as exc:  # noqa: BLE001
            return bad(f"{type(exc).__name__}: {exc}", 500)

    # ★ 哪些是人手补的（图上打标）+ 修补历史
    m = R_MANUAL.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        return ok({**store.manual_vids(CONN, p["id"]), "log": store.curate_history(CONN, p["id"], 20)})

    # ★ 某节点的出入边（改图面板用）
    m = R_EDGES.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        vid = int(body.get("vid") or 0)
        if not vid:
            return bad("缺少 vid")
        return ok(store.edges_of_node(CONN, p["id"], vid))

    m = R_NODES.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        limit = min(int(body.get("limit") or 500), 20000)
        offset = int(body.get("offset") or 0)
        items = store.nodes_of(CONN, p["id"], limit, offset)
        total = CONN.execute("SELECT COUNT(*) AS c FROM node WHERE project_id = ?", (p["id"],)).fetchone()["c"]
        return ok({"total": int(total), "limit": limit, "offset": offset, "items": items})

    # ------------------------------------------------ 笔记
    m = R_PNOTES.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)

        if method == "GET":
            nv = body.get("node_vid") or body.get("node_id")
            kind = (body.get("kind") or "").strip()
            items = store.notes_of(CONN, p["id"], int(nv) if nv else None)
            if kind:
                items = [n for n in items if n["kind"] == kind]
            return ok({"items": items, "total": len(items)})

        if method == "POST":
            # ★★★ **解析没成功就不许写**（所有者 2026-10-29）——
            #   图不完整时的笔记会挂在不存在的锚点上，等于白写
            pstate, perr = store.parse_state_of(CONN, p["id"])
            if pstate != "ok":
                return 409, {
                    "ok": False,
                    "code": "parse_not_ok",
                    "error": (
                        "这个项目还没解析成功，先修好图再写笔记"
                        + (f"：{perr}" if perr else "")
                    ),
                }
            node_vid = int(body.get("node_vid") or 0)
            node = store.node_by_vid(CONN, p["id"], node_vid)
            if node is None:
                return bad("必须指定 node_vid（笔记挂在哪个节点下）")
            text = str(body.get("body") or "")
            if not text.strip():
                return bad("正文不能为空")

            # ★ 编号单调 + 文件名再兜一层：万一磁盘上已经有同名文件，继续往后取号
            #   （⛔ 绝不覆盖已有笔记 —— 那是用户写的东西）
            for _ in range(50):
                no = store.next_no(CONN)
                fname = notefile.file_name(no, node["name"] or node["file_path"] or "note")
                # ★ 笔记统一放 `<数据目录>/notes/`（数据跟着项目走，不再有"库/项目目录"那层）
                rel = f"notes/{fname}"
                if not os.path.exists(os.path.join(ROOT, rel)):
                    break
            abs_path = os.path.join(ROOT, rel)

            ref = f"n{no:04d}"
            meta = {
                "no": no,
                # ★ ref 也写进文件：否则索引重建后 ref 会变（URL 全失效）
                "ref": ref,
                "kind": str(body.get("kind") or "flash"),
                "node": node["name"] or "",
                "anchor": f"{node['file_path']}:{node['line']}" if node["file_path"] else "",
                # ★ 名字留空 ⇒ 从正文推（`D112`）；用户写了就用用户的
                "title": str(body.get("title") or "").strip() or autotitle.auto_title(text),
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "project": p["dir"],
                "node_vid": node_vid,
            }
            # ★ 先写文件（真相），再写索引 —— 顺序不能反
            notefile.write_file(abs_path, meta, text)
            st = os.stat(abs_path)
            store.insert_note(
                CONN,
                {
                    "ref": ref,
                    "project_id": p["id"],
                    "node_vid": node_vid,
                    "kind": meta["kind"],
                    "no": no,
                    "title": meta["title"],
                    "rel_path": rel,
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "created_at": meta["time"],
                },
            )
            return ok({"note": {**store.find_note(CONN, ref), "node_name": node["name"]}})

    m = R_NOTE.match(path)
    if m:
        ref = m.group(1)
        # ★★★ 笔记 URL 里**没有项目信息**（`/api/notes/<ref>/`）⇒ 得挨个库里找 ⚠
        #   之前直接查全局 CONN，有多个项目时会查到别的项目的库里去（踩过：404）
        note = None
        for entry in projectstore.list_all():
            try:
                _activate(entry)
            except Exception:  # noqa: BLE001
                continue
            note = store.find_note(CONN, ref)
            if note is not None:
                break
        if note is None:
            return bad("笔记不存在", 404)
        abs_path = os.path.join(ROOT, note["rel_path"])

        if method == "GET":
            meta, text = notefile.read_file(abs_path) if os.path.exists(abs_path) else ({}, "")
            return ok({"note": note, "body": text, "meta": meta})

        if method == "PATCH":
            meta, text = notefile.read_file(abs_path)
            if "body" in body:
                text = str(body.get("body") or "")
            # ★ `title` 传空串 = **回到自动**（`D124`），⛔ 不是变成空标题
            if "title" in body:
                t = str(body.get("title") or "").strip()
                meta["title"] = t or autotitle.auto_title(text)
            for k in ("kind",):
                if k in body:
                    meta[k] = str(body.get(k) or "")
            notefile.write_file(abs_path, meta, text)
            st = os.stat(abs_path)
            upd = {"mtime": st.st_mtime, "size": st.st_size}
            if "title" in body:
                upd["title"] = meta.get("title") or ""
            if "kind" in body:
                upd["kind"] = str(body.get("kind") or "")
            store.update_note(CONN, ref, **upd)
            return ok({"note": store.find_note(CONN, ref)})

        if method == "DELETE":
            # ★ 删除 = 移到 trash/（可恢复），不是抹掉
            #   （数据目录现在是 `<项目根>/.astrolabe/`，回收站在它下面）
            trash = os.path.join(ROOT, "trash")
            os.makedirs(trash, exist_ok=True)
            if os.path.exists(abs_path):
                shutil.move(abs_path, os.path.join(trash, os.path.basename(abs_path)))
            store.delete_note(CONN, ref)
            return ok({"deleted": ref})

    return bad(f"未实现：{method} {path}", 404)


# ---------------------------------------------------------------- 扫描（建项目前的预览）

_EXTS = {
    ".py": "Python", ".c": "C", ".h": "C/C++", ".cpp": "C++", ".cc": "C++",
    ".java": "Java", ".js": "JS", ".ts": "TS", ".tsx": "TSX", ".jsx": "JSX",
    ".go": "Go", ".rs": "Rust", ".md": "Markdown",
}
_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target"}


def _scan_dir(root: str, limit: int = 200000) -> dict:
    t0 = time.time()
    counts: dict[str, int] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP and not d.startswith(".")]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in _EXTS:
                counts[ext] = counts.get(ext, 0) + 1
                total += 1
                if total >= limit:
                    break
        if total >= limit:
            break
    return {
        "root": root,
        "files": total,
        "byExt": [{"ext": k, "n": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])],
        "elapsedMs": int((time.time() - t0) * 1000),
    }


# ---------------------------------------------------------------- 主循环


def main() -> None:
    # ★ 强制 utf-8：Windows 控制台默认 cp936，中文会乱码
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

    init()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            print("[sidecar] 坏 JSON：%r" % line[:200], file=sys.stderr, flush=True)
            continue

        rid = req.get("id")
        try:
            status, payload = handle(
                str(req.get("method") or "GET"),
                str(req.get("path") or "/"),
                req.get("body"),
            )
        except Exception as exc:  # noqa: BLE001 —— 边车不能因为一个请求死掉
            status, payload = 500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        sys.stdout.write(json.dumps({"id": rid, "status": status, "body": payload}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
