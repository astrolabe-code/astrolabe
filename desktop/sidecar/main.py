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
import notefile
import store

VERSION = "0.2.0"

ROOT = library.resolve_root()
CONN = None


def _data_dir() -> str:
    return os.environ.get("ASTROLABE_DATA_DIR") or os.path.join(os.getcwd(), "data")


def init() -> None:
    global CONN
    library.ensure_root(ROOT)
    CONN = store.connect(ROOT)
    # ★ 启动即对齐磁盘（几百个文件 = 几十毫秒）
    indexer.rescan(ROOT, CONN)


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


def _split_query(path: str) -> tuple[str, dict]:
    """拆出 query（⚠ 边车拿到的是 `/api/x/?a=1` 这种完整路径）"""
    if "?" not in path:
        return path, {}
    pure, qs = path.split("?", 1)
    q = urllib.parse.parse_qs(qs)
    return pure, {k: v[0] for k, v in q.items()}


def _project(ref: str):
    p = store.find_project(CONN, ref)
    if p is None:
        return None
    return p


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
        cfg = library.load_config(ROOT)
        items = store.list_projects(CONN)
        return ok(
            {
                "root": ROOT,
                "name": cfg.get("name") or os.path.basename(ROOT),
                "projects": items,
                "notes": CONN.execute("SELECT COUNT(*) AS c FROM note").fetchone()["c"],
                "defaultRoot": library.default_root(),
            }
        )

    # ★★ 换笔记存放位置（用户指定；⛔ 不是只能靠环境变量）
    if path == "/api/library/switch" and method == "POST":
        target = str(body.get("path") or "").strip()
        copy = bool(body.get("copy"))
        if not target:
            return bad("要指定一个目录")
        target = os.path.abspath(target)
        if target == ROOT:
            return bad("这就是当前的位置")

        try:
            os.makedirs(target, exist_ok=True)
            if copy:
                # 把现有笔记整个搬过去（⚠ 只搬 .md 和 .astrolabe，不搬别的）
                for name in os.listdir(ROOT):
                    if name.startswith(".") and name != library.INDEX_DIR:
                        continue
                    src = os.path.join(ROOT, name)
                    dst = os.path.join(target, name)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    elif not os.path.exists(dst):
                        shutil.copy2(src, dst)
            library.save_pref(library_root=target)

            # ★ 切库：关旧连接、建新库、重建索引
            old = CONN
            ROOT = target
            library.ensure_root(ROOT)
            CONN = store.connect(ROOT)
            indexer.rescan(ROOT, CONN)
            try:
                old.close()
            except Exception:
                pass
            return ok(
                {
                    "root": ROOT,
                    "copied": copy,
                    "projects": len(store.list_projects(CONN)),
                    "notes": CONN.execute("SELECT COUNT(*) AS c FROM note").fetchone()["c"],
                "defaultRoot": library.default_root(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return bad(f"切换失败：{type(exc).__name__}: {exc}", 500)

    if path == "/api/library/rescan" and method == "POST":
        return ok(indexer.rescan(ROOT, CONN))

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
            return ok({"items": store.list_projects(CONN)})
        if method == "POST":
            code_root = str(body.get("path") or "").strip()
            blank = bool(body.get("blank")) or not code_root

            # ★★★ 空白项目：**不用源码，就是写节点**（`B184` 所有者原话）
            #   非代码主题的结构化尝试 —— 节点和连线全靠手补，状态直接给 ok
            if blank:
                name = str(body.get("name") or "").strip() or "新结构"
                p = store.create_blank_project(CONN, ROOT, name)
                store.set_parse_state(CONN, p["id"], "ok", "")
                return ok({"project": dict(store.find_project(CONN, p["ref"]))})

            if not os.path.isdir(code_root):
                return bad("代码目录不存在")
            name = str(body.get("name") or os.path.basename(code_root.rstrip("/\\")) or "未命名")
            p = store.get_or_create_project(CONN, ROOT, name, code_root)
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
                rel = f"{p['dir']}/{fname}"
                if not os.path.exists(os.path.join(ROOT, rel)):
                    break
            abs_path = os.path.join(ROOT, rel)

            meta = {
                "no": no,
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
            ref = f"n{no:04d}"
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
        note = store.find_note(CONN, ref)
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
            # ★ 删除 = 移到 .trash（可恢复），不是抹掉
            trash = os.path.join(ROOT, ".trash")
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
