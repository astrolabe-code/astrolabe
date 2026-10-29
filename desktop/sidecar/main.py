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

import indexer
import library
import notefile
import store

VERSION = "0.2.0"

ROOT = os.path.abspath(os.environ.get("ASTROLABE_LIBRARY") or library.default_root())
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


def _project(ref: str):
    p = store.find_project(CONN, ref)
    if p is None:
        return None
    return p


def handle(method: str, path: str, body: dict | None) -> tuple[int, dict]:
    body = body or {}

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
            }
        )

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
        try:
            import parser_bridge  # ⚠ 延迟导入：缺 tree-sitter 时给明确错误，而不是起不来
        except Exception as exc:  # noqa: BLE001
            return bad(f"解析器不可用：{type(exc).__name__}: {exc}", 501)

        res = parser_bridge.parse_project(p["root"])
        if not res["nodes"]:
            return bad(
                "没有解析出任何节点 —— 目录可能不含支持的源码，或缺 tree-sitter 语法包",
                422,
            )
        store.replace_graph(CONN, p["id"], res["nodes"], res["edges"])
        return ok({"stats": res["stats"], "project": dict(store.find_project(CONN, p["ref"]))})

    # ------------------------------------------------ 项目
    if path == "/api/projects/":
        if method == "GET":
            return ok({"items": store.list_projects(CONN)})
        if method == "POST":
            code_root = str(body.get("path") or "").strip()
            if not code_root or not os.path.isdir(code_root):
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
            return ok(
                {
                    "project": dict(p),
                    "stats": store.stats(CONN, p["id"]),
                }
            )

    m = R_NODES.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)
        return ok({"items": store.nodes_of(CONN, p["id"], int(body.get("limit") or 500))})

    # ------------------------------------------------ 笔记
    m = R_PNOTES.match(path)
    if m:
        p = _project(m.group(1))
        if not p:
            return bad("项目不存在", 404)

        if method == "GET":
            nv = body.get("node_vid")
            return ok({"items": store.notes_of(CONN, p["id"], int(nv) if nv else None)})

        if method == "POST":
            node_vid = int(body.get("node_vid") or 0)
            node = store.node_by_vid(CONN, p["id"], node_vid)
            if node is None:
                return bad("必须指定 node_vid（笔记挂在哪个节点下）")
            text = str(body.get("body") or "")
            if not text.strip():
                return bad("正文不能为空")

            no = store.next_no(CONN)
            fname = notefile.file_name(no, node["name"] or node["file_path"] or "note")
            rel = f"{p['dir']}/{fname}"
            abs_path = os.path.join(ROOT, rel)

            meta = {
                "no": no,
                "kind": str(body.get("kind") or "flash"),
                "node": node["name"] or "",
                "anchor": f"{node['file_path']}:{node['line']}" if node["file_path"] else "",
                "title": str(body.get("title") or "").strip(),
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
            for k in ("title", "kind"):
                if k in body:
                    meta[k] = str(body.get(k) or "")
            notefile.write_file(abs_path, meta, text)
            st = os.stat(abs_path)
            upd = {"mtime": st.st_mtime, "size": st.st_size}
            for k in ("title", "kind"):
                if k in body:
                    upd[k] = str(body.get(k) or "")
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
