#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ 边车自测（协议级，不起壳）

```bash
cd desktop/sidecar && python3 selftest.py
```

⚠ 用一个**临时库**（`/tmp/astrolabe-selftest`），⛔ 不碰真实数据。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = "/tmp/astrolabe-selftest"


class Sidecar:
    def __init__(self) -> None:
        env = {
            **os.environ,
            "ASTROLABE_LIBRARY": os.path.join(TMP, "lib"),
            "ASTROLABE_DATA_DIR": TMP,
            "PYTHONIOENCODING": "utf-8",
        }
        self.p = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "main.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=HERE,
            text=True,
            encoding="utf-8",
        )
        self.seq = 0

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        self.seq += 1
        self.p.stdin.write(json.dumps({"id": self.seq, "method": method, "path": path, "body": body}) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            err = self.p.stderr.read()[:600]
            raise RuntimeError(f"边车无响应：{err}")
        return json.loads(line)

    def close(self) -> None:
        self.p.stdin.close()
        self.p.wait(timeout=5)


def main() -> None:
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP, exist_ok=True)
    sc = Sidecar()
    fails = []

    def check(name: str, cond: bool, extra: str = "") -> None:
        print(("  ✅ " if cond else "  ❌ ") + name + (("  " + extra) if extra else ""))
        if not cond:
            fails.append(name)

    try:
        r = sc.call("GET", "/api/ping")
        check("ping", r["body"].get("ok") is True, r["body"].get("data", {}).get("library", ""))

        r = sc.call("GET", "/api/library/")
        check("库初始化", r["body"]["data"]["projects"] == [])

        code_root = os.path.abspath(os.path.join(HERE, "..", "..", "app"))
        r = sc.call("POST", "/api/projects/", {"path": code_root, "name": "itsdangerous"})
        proj = r["body"]["data"]["project"]
        check("建项目", proj["ref"].startswith("p_"), proj["dir"])

        # ★★ 真解析（需要 tree-sitter；没有就退化成手工塞两个节点）
        lib = os.path.join(TMP, "lib")
        r = sc.call("POST", f"/api/projects/{proj['ref']}/parse")
        parsed = r["body"].get("ok") is True
        if parsed:
            st = r["body"]["data"]["stats"]
            check("真解析出节点", st["nodes"] > 0, json.dumps(st, ensure_ascii=False))
            nodes = sc.call("GET", f"/api/projects/{proj['ref']}/nodes/", {"limit": 20000})["body"]["data"]["items"]
            check("节点已落库", len(nodes) == st["nodes"], f'{len(nodes)}/{st["nodes"]}')
            vid = int(next(n for n in nodes if n["kind"] != "file")["vid"])
        else:
            print("  ⏭ 跳过真解析（" + str(r["body"].get("error"))[:40] + "）")
            db = sqlite3.connect(os.path.join(lib, ".astrolabe", "index.db"))
            db.executemany(
                "INSERT INTO node (project_id, vid, kind, name, qname, file_path, line, line_end) VALUES (?,?,?,?,?,?,?,?)",
                [
                    (proj["id"], 1001, "function", "coalesce", "tcp.coalesce", "src/net/tcp.c", 412, 460),
                    (proj["id"], 1002, "function", "init", "tcp.init", "src/net/tcp.c", 12, 30),
                ],
            )
            db.commit()
            db.close()
            vid = 1001

        r = sc.call("GET", f"/api/projects/{proj['ref']}/nodes/")
        check("节点列表", len(r["body"]["data"]["items"]) > 0)

        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/notes/",
            {"node_vid": vid, "kind": "pitfall", "body": "这里为什么要乘 2？没找到注释。", "title": "窗口太小时会退化"},
        )
        note = r["body"]["data"]["note"]
        check("建笔记", note["no"] == 1, note["rel_path"])
        abs_md = os.path.join(lib, note["rel_path"])
        check("文件已落盘", os.path.exists(abs_md), note["rel_path"])

        text = open(abs_md, encoding="utf-8").read()
        check("frontmatter 有 no/kind/anchor", "no: 1" in text and "kind: pitfall" in text and "anchor: " in text and "node: " in text)

        r = sc.call("GET", f"/api/notes/{note['ref']}/")
        check("读回正文", "为什么要乘 2" in r["body"]["data"]["body"])

        r = sc.call("PATCH", f"/api/notes/{note['ref']}/", {"body": "改过了：其实是为了对齐。"})
        check("改正文", r["body"]["ok"] and "对齐" in open(abs_md, encoding="utf-8").read())

        r = sc.call("GET", f"/api/projects/{proj['ref']}/notes/")
        check("项目笔记列表", len(r["body"]["data"]["items"]) == 1)

        # ★ 第二个笔记：编号必须递增，文件名不同
        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/notes/",
            {"node_vid": vid, "kind": "summary", "body": "整条连接建立流程", "title": "init"},
        )
        n2 = r["body"]["data"]["note"]
        check("编号递增", n2["no"] == 2, n2["rel_path"])
        check("文件名不同", n2["rel_path"] != note["rel_path"])

        # ★ 索引重建：删掉 DB 后应能从文件恢复（这是"文件是真相"的核心验证）
        os.remove(os.path.join(lib, ".astrolabe", "index.db"))
        r = sc.call("GET", "/api/library/")
        note_count = r["body"]["data"]["notes"]
        check("重建索引后仍有 2 篇", note_count == 2, f"notes={note_count}")

        r = sc.call("DELETE", f"/api/notes/{note['ref']}/")
        check("删除", r["body"]["ok"] is True)
        check("文件移到 .trash", os.path.exists(os.path.join(lib, ".trash", os.path.basename(abs_md))))

        st = sc.call("GET", f"/api/projects/{proj['ref']}/")
        check("统计", st["body"]["data"]["stats"]["summaryNodes"] == 1, json.dumps(st["body"]["data"]["stats"]))
    finally:
        sc.close()

    print()
    if fails:
        print(f"❌ {len(fails)} 项失败：" + "、".join(fails))
        sys.exit(1)
    print("✅ 全部通过")


if __name__ == "__main__":
    main()
