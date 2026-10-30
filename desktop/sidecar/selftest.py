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
        check("清单为空", r["body"]["data"]["projects"] == [])

        # ★ 用临时目录当"源码目录"（⚠ 数据会写进它里面的 .astrolabe/，
        #   所以绝不能指向真实仓库）
        code_root = os.path.join(TMP, "src")
        os.makedirs(code_root, exist_ok=True)
        shutil.copy(
            os.path.join(HERE, "..", "..", "app", "codeparser", "scanner.py"),
            os.path.join(code_root, "scanner.py"),
        )
        r = sc.call("POST", "/api/projects/", {"path": code_root, "name": "itsdangerous"})
        proj = r["body"]["data"]["project"]
        check("建项目", proj["ref"].startswith("p_"), proj["dir"])

        # ★★ 真解析（需要 tree-sitter；没有就退化成手工塞两个节点）
        lib = os.path.join(code_root, ".astrolabe")  # 数据跟着源码目录
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
            db = sqlite3.connect(os.path.join(lib, "index.db"))
            db.executemany(
                "INSERT INTO node (project_id, vid, kind, name, qname, file_path, line, line_end) VALUES (?,?,?,?,?,?,?,?)",
                [
                    (proj["id"], 1001, "function", "coalesce", "tcp.coalesce", "src/net/tcp.c", 412, 460),
                    (proj["id"], 1002, "function", "init", "tcp.init", "src/net/tcp.c", 12, 30),
                ],
            )
            # ★ 没有 tree-sitter 时手工塞节点 ⇒ 同时把状态改成 ok
            #   （否则"解析没成功不许写笔记"的门槛会挡住后面的用例 —— 这是对的）
            db.execute("UPDATE project SET parse_state = 'ok', parse_error = '' WHERE id = ?", (proj["id"],))
            db.commit()
            db.close()
            vid = 1001

        r = sc.call("GET", f"/api/projects/{proj['ref']}/nodes/")
        check("节点列表", len(r["body"]["data"]["items"]) > 0)

        # ★★ 解析没成功 ⇒ **禁止写笔记**（所有者 2026-10-29）
        empty_dir = os.path.join(TMP, "empty-src")
        os.makedirs(empty_dir, exist_ok=True)
        open(os.path.join(empty_dir, "a.txt"), "w").write("no source here")
        bad = sc.call("POST", "/api/projects/", {"path": empty_dir, "name": "空项目"})["body"]["data"]["project"]
        sc.call("POST", f"/api/projects/{bad['ref']}/parse", {})
        st = sc.call("GET", f"/api/projects/{bad['ref']}/")["body"]["data"]["project"]
        check("解析失败 ⇒ 状态 failed", st.get("parse_state") == "failed", st.get("parse_error", "")[:40])
        r = sc.call("POST", f"/api/projects/{bad['ref']}/notes/", {"node_vid": 1, "kind": "flash", "body": "x"})
        check("解析失败 ⇒ 写笔记被拒", r["status"] == 409 and r["body"].get("code") == "parse_not_ok")

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

        # ★★ 同名笔记：文件名必须不同（⛔ 绝不覆盖）
        for i in range(3):
            sc.call(
                "POST",
                f"/api/projects/{proj['ref']}/notes/",
                {"node_vid": vid, "kind": "flash", "title": "同名笔记", "body": f"第 {i} 篇"},
            )
        rows = sc.call("GET", f"/api/projects/{proj['ref']}/notes/")["body"]["data"]["items"]
        same = [x["rel_path"] for x in rows if x["title"] == "同名笔记"]
        check("同名笔记文件名互不相同", len(set(same)) == 3, ", ".join(same))

        # ★★ 编号不复用：删最后一篇再建，编号要往后走
        last = rows[-1]
        sc.call("DELETE", f"/api/notes/{last['ref']}/")
        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/notes/",
            {"node_vid": vid, "kind": "flash", "title": "删了再建", "body": "x"},
        )
        check("编号不复用", r["body"]["data"]["note"]["no"] > last["no"], f'{last["no"]} → {r["body"]["data"]["note"]["no"]}')

        # ★★ 改 vid（改行号）⇒ 笔记必须跟着走，且文件里的 frontmatter 同步
        before_note = sc.call("GET", f"/api/notes/{note['ref']}/")["body"]["data"]["note"]
        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/curate/",
            {"action": "update_node", "vid": vid, "line": (before_note["line"] or 0) + 7,
             "line_end": (before_note["line"] or 0) + 30, "reason": "行号纠错"},
        )
        migrated = r["body"]["data"]
        after_note = sc.call("GET", f"/api/notes/{note['ref']}/")["body"]["data"]["note"]
        check(
            "改 vid 后笔记跟着走",
            migrated.get("changed") is True
            and after_note["node_vid"] == migrated["new_vid"]
            and after_note["node_name"] == before_note["node_name"],
            f'{migrated.get("old_vid")} → {migrated.get("new_vid")}',
        )
        md = open(os.path.join(lib, after_note["rel_path"]), encoding="utf-8").read()
        check("frontmatter 里的 node_vid 同步", ("node_vid: %s" % migrated["new_vid"]) in md)
        vid = migrated["new_vid"]  # ★ 身份已经变了，后面的用例都用新 vid

        # ★ 第二个笔记：编号必须递增，文件名不同
        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/notes/",
            {"node_vid": vid, "kind": "summary", "body": "整条连接建立流程", "title": "init"},
        )
        n2 = r["body"]["data"]["note"]
        check("编号递增", n2["no"] > note["no"], "%s -> %s" % (note["no"], n2["no"]))
        check("文件名不同", n2["rel_path"] != note["rel_path"])

        # ★ 索引重建：删掉 DB 后应能**从文件恢复**（"文件是真相"的核心验证）
        before_count = sc.call("GET", "/api/library/")["body"]["data"]["notes"]
        os.remove(os.path.join(lib, "index.db"))
        after_count = sc.call("GET", "/api/library/")["body"]["data"]["notes"]
        check(
            "重建索引后笔记数不变",
            after_count == before_count and before_count > 0,
            "%s -> %s" % (before_count, after_count),
        )

        r = sc.call("DELETE", f"/api/notes/{note['ref']}/")
        check("删除", r["body"]["ok"] is True)
        check("文件移到 .trash", os.path.exists(os.path.join(lib, "trash", os.path.basename(abs_md))))

        # ★★ 手工改图（六种动作走一遍）
        r = sc.call("POST", f"/api/projects/{proj['ref']}/curate/", {"action": "add_node"})
        check("改图缺 reason 被拒", r["body"].get("ok") is False)

        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/curate/",
            {"action": "add_node", "kind": "function", "name": "手补函数", "file_path": "x.py", "line": 9,
             "reason": "解析器没识别出来"},
        )
        new_vid = r["body"]["data"]["vid"]
        check("加节点", bool(new_vid), str(new_vid))

        r = sc.call("GET", f"/api/projects/{proj['ref']}/nodes/", {"limit": 20000})
        added = [n for n in r["body"]["data"]["items"] if n["vid"] == new_vid]
        check("手补节点能查到", len(added) == 1, added[0]["name"] if added else "")

        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/curate/",
            {"action": "add_edge", "from": new_vid, "to": vid, "type": "call", "reason": "补一条调用"},
        )
        eid = r["body"]["data"]["id"]
        check("加边", bool(eid), str(eid))

        r = sc.call("GET", f"/api/projects/{proj['ref']}/edges/?vid={new_vid}")
        check("边的出入表", len(r["body"]["data"]["out"]) == 1)

        r = sc.call("GET", f"/api/projects/{proj['ref']}/manual/")
        m = r["body"]["data"]
        check("人工项被标记", new_vid in m["nodes"] and eid in m["edges"], json.dumps(m["nodes"]))

        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/curate/",
            {"action": "remove_edge", "id": eid, "reason": "连错了"},
        )
        check("删边", r["body"].get("ok") is True)

        r = sc.call(
            "POST",
            f"/api/projects/{proj['ref']}/curate/",
            {"action": "remove_node", "vid": new_vid, "reason": "多余节点"},
        )
        check("删节点", r["body"].get("ok") is True)

        r = sc.call("GET", f"/api/projects/{proj['ref']}/manual/")
        check("修补历史有记录", len(r["body"]["data"]["log"]) >= 4, str(len(r["body"]["data"]["log"])))

        # ★★ 回归：重新解析必须**保住**人补的节点
        #   之前的 bug：replace_graph 无条件 DELETE ⇒ 手补的节点和边全被清光
        if parsed:
            sc.call(
                "POST",
                f"/api/projects/{proj['ref']}/curate/",
                {"action": "add_node", "kind": "function", "name": "重解析保留测试",
                 "file_path": "keep.py", "line": 1, "reason": "回归用例"},
            )
            sc.call("POST", f"/api/projects/{proj['ref']}/parse")
            after = sc.call("GET", f"/api/projects/{proj['ref']}/nodes/", {"limit": 20000})["body"]["data"]["items"]
            check(
                "重解析后人补节点仍在",
                any(n["name"] == "重解析保留测试" for n in after),
                f"共 {len(after)} 个",
            )

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
