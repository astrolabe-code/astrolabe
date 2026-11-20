#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 工具集（暴露给模型的只读工具 + 执行器）。

从 main.py 抽出 —— 这里只管「模型能调什么、调了怎么执行」，
⛔ 不管 HTTP 路由、不管图库写入。
"""

import re

import ai_core.client as ai
import board
import graphdb
import qa
import store
from ai_core import context
from ai_core.log import _log

_CYPHER_DENY = (
    "CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP", "ALTER",
    "COPY", "INSTALL", "LOAD", "FOREACH", "CALL", "ATTACH", "DETACH",
)


def _cypher_guard(query: str) -> str:
    """只读校验：拒绝写关键字，强制 MATCH + RETURN + LIMIT。

    所有者原话（2026-11-18）：
    「你只要告诉ai可以用cypher查询，不比你写的更灵活？
      只要检查ai写的查询语句只是查询，没有任何修改功能就行。」

    ⚠ 做法很粗但够用：先把单/双引号里的字符串挖掉（避免 'SET' 这种字面量误判），
      再按单词边界匹配写关键字。
    ⛔ 绝不拼接任何用户/模型的字符串进查询以外的地方。
    """
    q = str(query or "").strip()
    if not q:
        return "缺少 query"
    scrubbed = re.sub(r"'(?:[^'\\]|\\.)*'", "''", q)
    scrubbed = re.sub(r'"(?:[^"\\]|\\.)*"', '""', scrubbed)
    up = re.sub(r"\s+", " ", scrubbed.upper())

    for word in _CYPHER_DENY:
        if re.search(rf"\b{word}\b", up):
            return f"拒绝执行：语句里出现 {word}，这里只允许只读查询"
    if not re.search(r"\bMATCH\b", up):
        return "查询必须包含 MATCH"
    if not re.search(r"\bRETURN\b", up):
        return "查询必须包含 RETURN"
    if not re.search(r"\bLIMIT\b", up):
        return "请加上 LIMIT（最多 200 行）"
    return ""


def _cypher_columns(query: str) -> list[str]:
    """从 RETURN 子句猜列名（`a.name AS x` → `x`；`a.name` → `name`）。

    ⚠ 只是为了给 Markdown 表格加表头。猜错不影响数据，只影响表头文字，
      所以这里宁简勿繁：取每项最后一个标识符。
    """
    m = re.search(
        r"\bRETURN\b(.*?)(?:\bLIMIT\b|\bORDER\b|\bSKIP\b|\bUNION\b|$)",
        query,
        re.S | re.I,
    )
    if not m:
        return []
    body = m.group(1)
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in body:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))

    cols: list[str] = []
    for raw in parts:
        item = raw.strip()
        if not item:
            continue
        alias = re.search(r"\bAS\s+([A-Za-z_]\w*)\s*$", item, re.I)
        if alias:
            cols.append(alias.group(1))
            continue
        ids = re.findall(r"[A-Za-z_]\w*", item)
        cols.append(ids[-1] if ids else f"col{len(cols) + 1}")
    return cols


def _markdown_table(cols: list[str], rows: list) -> str:
    """把结果拼成 Markdown 表格（值与表头里的 `|` 转义，否则会破坏表格）。"""
    width = len(rows[0]) if rows else 0
    head = cols[:width] or [f"col{i + 1}" for i in range(width)]
    head += [f"col{i + 1}" for i in range(len(head), width)]

    def cell(v) -> str:
        return "—" if v is None or v == "" else str(v).replace("|", "\\|")

    lines = ["| " + " | ".join(head) + " |", "|" + "|".join([" --- "] * width) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(cell(c) for c in r) + " |")
    return "\n".join(lines)


READ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cypher",
            "description": (
                "直接查代码图谱（只读 cypher）——想怎么连就怎么连，比专用工具灵活。\n"
                "\n"
                "图谱结构（LadybugDB）：\n"
                "  节点表 Code(vid, kind, name, qname, rel_path, line, lineEnd, signature, origin)\n"
                "    kind: dir / file / function / method / class / interface / struct / union /\n"
                "          enum / typedef / record / macro / module / package / variable /\n"
                "          constant / field / type\n"
                "    origin: 'manual' 表示用户手工补的节点（确切），其它是解析产出\n"
                "  关系表 Rel(kind, origin, line)，方向 a -> b 表示 a 依赖 b\n"
                "    kind: call / invoke / contains / import / include / extend / implement\n"
                "\n"
                "规则：\n"
                "  ① 只能 MATCH / OPTIONAL MATCH / WHERE / RETURN / WITH / ORDER BY / LIMIT\n"
                "     CREATE / MERGE / DELETE / SET / REMOVE / DROP / CALL 一律拒绝\n"
                "  ② 必须带 LIMIT（≤200），否则不执行\n"
                "  ③ 图里只有行号与 rel_path，没有源码正文 —— 读代码用 read_file（它读文件）\n"
                "     想知道某个目录包含什么，查 Rel 的 contains 边\n"
                "  ④ 不区分大小写，字段名区分（lineEnd 是驼峰）\n"
                "\n"
                "例（照抄改名字即可）：\n"
                "  ① 谁调用了它（上游）\n"
                "     MATCH (a:Code)-[r:Rel {kind:'call'}]->(b:Code {name:'do_work'})\n"
                "     RETURN a.name, a.rel_path, a.line LIMIT 30\n"
                "  ② 它调用了谁（下游）\n"
                "     MATCH (a:Code {name:'do_work'})-[r:Rel {kind:'call'}]->(b:Code)\n"
                "     RETURN b.name, b.rel_path, b.line LIMIT 30\n"
                "  ③ 上下游一起看（不限定方向）\n"
                "     MATCH (a:Code)-[r:Rel]-(b:Code {name:'do_work'})\n"
                "     WHERE r.kind = 'call' OR r.kind = 'invoke'\n"
                "     RETURN a.name, b.name, r.kind LIMIT 40\n"
                "  ④ 某个文件里有哪些节点\n"
                "     MATCH (c:Code) WHERE c.rel_path = 'path/to/file.py'\n"
                "     RETURN c.kind, c.name, c.line ORDER BY c.line LIMIT 100\n"
                "  ⑤ 某个目录下有什么\n"
                "     MATCH (d:Code {name:'some_dir'})-[r:Rel {kind:'contains'}]->(c:Code)\n"
                "     RETURN c.kind, c.name LIMIT 50\n"
                "  ⑥ 某个类的所有方法\n"
                "     MATCH (c:Code {name:'SomeClass'})-[r:Rel {kind:'contains'}]->(m:Code)\n"
                "     WHERE m.kind = 'method' RETURN m.name, m.line LIMIT 50\n"
                "  ⑦ 按名字模糊找（不确定全名时）\n"
                "     MATCH (c:Code) WHERE c.name CONTAINS 'handle'\n"
                "     RETURN c.kind, c.name, c.rel_path, c.line LIMIT 40\n"
                "  ⑧ 只看用户手工补的边\n"
                "     MATCH (a:Code)-[r:Rel {origin:'manual'}]->(b:Code)\n"
                "     RETURN a.name, b.name, r.kind LIMIT 30\n"
                "\n"
                "输出是 Markdown 表格（列名取自 RETURN 子句）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Cypher 语句（只读，必须带 LIMIT）"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "按节点的 rel_path 与行号范围，读那个**文件**里对应的那段代码。\n"
                "图谱里只有行号和路径，没有源码正文。\n"
                "只返回这段切片，**不返回上下游**（那用 cypher 查 Rel）。\n"
                "没有对应文件的节点（比如目录，line=0）返回空。\n"
                "\n"
                "WHEN TO USE: 你已经定位到某个节点，想读它对应的那段代码。\n"
                "AFTER THIS: 想看它和谁相连，用 cypher 查 Rel；想知道作者写过什么，用 read_notes。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "节点名"},
                    "uid": {"type": "string", "description": "精确 uid（可选）"},
                    "max_lines": {
                        "type": "integer",
                        "description": "源码最多多少行（默认 120，上限 400）",
                        "default": 120,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_board",
            "description": (
                "读某个节点关联的**白板**：每块白板的名字，以及它上面摆了哪几条笔记。\n"
                "白板是作者把若干条笔记摆在画布上形成的思考布局。\n"
                "\n"
                "WHEN TO USE: 想知道作者把哪些笔记放在一起比过、并成了什么结构。\n"
                "AFTER THIS: 想知道某条笔记写了什么，用 search_notes 或 read_notes。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "节点名"},
                    "uid": {"type": "string", "description": "精确 uid（可选）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_notes",
            "description": (
                "读某个节点下**用户自己写的笔记**（类型、标题、正文摘要）。\n\n"
                "WHEN TO USE: 想知道作者怎么理解这段代码、踩过什么坑、还困惑什么时"
                "—— 这些在代码里看不到。\n"
                "AFTER THIS: 想找别处提到过的概念，用 search_notes。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "节点名"},
                    "uid": {"type": "string", "description": "精确 uid（可选）"},
                    "limit": {
                        "type": "integer",
                        "description": "最多读几篇（默认 3，上限 8）",
                        "default": 3,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": (
                "在用户笔记的正文/标题里做全文搜索，返回标题与命中片段。\n\n"
                "WHEN TO USE: 不确定某个概念在哪提过、或想找「我以前是不是记过这个」时"
                "—— 比逐个节点 read_notes 快。\n"
                "AFTER THIS: 拿到标题后再用 read_notes 或 read_file 深入。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "关键词"},
                    "limit": {
                        "type": "integer",
                        "description": "最多返回几条（默认 5，上限 20）",
                        "default": 5,
                    },
                },
                "required": ["q"],
            },
        },
    },
]


def _make_tool_executor(project):
    """构造只读工具执行器。⛔ 任何分支都不写：不落库、不改图、不执行代码。"""

    def by_uid(uid: str) -> dict | None:
        try:
            return graphdb.get_code(context.root(), int(uid))
        except Exception:  # noqa: BLE001
            return None

    def resolve(args: dict) -> tuple[dict | None, str]:
        """按 uid 或名字定位唯一节点；同名时给候选清单，⛔ 不默认取第一个。"""
        uid = str(args.get("uid") or "").strip()
        if uid:
            node = by_uid(uid)
            return (node, "") if node else (None, f"uid={uid} 不存在")
        name = str(args.get("name") or "").strip()
        if not name:
            return None, "需要 name 或 uid"
        try:
            rows = graphdb.search_code(context.root(), name, 10) or []
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            return None, f"没有找到「{name}」，可以先用 cypher 按名字查一下"
        if len(rows) == 1:
            return rows[0], ""
        exact = [r for r in rows if str(r.get("name") or "") == name]
        if len(exact) == 1:
            return exact[0], ""
        lines = [f"「{name}」匹配到 {len(rows)} 个节点，请用 uid 指定："]
        for r in rows[:10]:
            lines.append(
                f"- uid={r.get('vid')}  {r.get('kind')}  {r.get('name')}  "
                f"@ {r.get('rel_path')}:{r.get('line')}"
            )
        return None, "\n".join(lines)

    def snippet_of(node: dict, limit: int) -> str:
        """读 rel_path 指向的文件，按节点行号截一段。"""
        try:
            text = str(source.read(project["root"], node.get("rel_path") or "").get("text") or "")
        except Exception:  # noqa: BLE001
            return "（源码读取失败：文件打不开或编码不支持）"
        if not text.strip():
            return "（空文件 —— 这个文件本来就没有代码）"
        lines = text.splitlines()
        start = max(0, int(node.get("line") or 1) - 1)
        end = int(node.get("line_end") or 0)
        if end <= start:
            end = start + 40
        end = min(end, start + limit, len(lines))
        if end <= start:
            return "（行号对不上，读不到这一段）"
        body = "\n".join(lines[start:end])
        if end < len(lines) and (node.get("line_end") or 0) > end:
            body += "\n…（已截断，需要更多请调高 max_lines）"
        return body

    def note_body(rel_path: str, limit: int = 800) -> str:
        try:
            _meta, txt = notefile.read_file(os.path.join(context.root(), str(rel_path or "")))
            return " ".join(str(txt or "").split())[:limit]
        except Exception:  # noqa: BLE001
            return "（读不到正文）"

    def run(tool: str, args: dict) -> str:
        # ---------------- 直接查图
        if tool == "cypher":
            query = str(args.get("query") or "")
            why = _cypher_guard(query)
            if why:
                return why
            try:
                rows = graphdb._open(context.root()).execute(query).get_all()
            except Exception as exc:  # noqa: BLE001
                return f"查询失败：{exc}"
            if not rows:
                return "（没有匹配结果）"
            shown = rows[:80]
            table = _markdown_table(_cypher_columns(query), shown)
            tail = "" if len(rows) <= 80 else f"\n\n（共 {len(rows)} 行，上面是前 80 行）"
            return table + tail

        # ---------------- 搜笔记
        if tool == "search_notes":
            q = str(args.get("q") or "").strip()
            if not q:
                return "缺少参数 q"
            limit = min(20, max(1, int(args.get("limit") or 5)))
            try:
                hits = store.fts_search(context.conn(), q, limit * 2)
            except Exception as exc:  # noqa: BLE001
                return f"搜索失败：{exc}"
            if not hits:
                return f"笔记里没有提到「{q}」"
            try:
                refs = [str(h.get("ref") or "") for h in hits]
                marks = ",".join("?" * len(refs))
                keep = {
                    str(r[0])
                    for r in context.conn().execute(
                        f"SELECT ref FROM note WHERE project_id = ? AND ref IN ({marks})",
                        (project["id"], *refs),
                    ).fetchall()
                }
                hits = [h for h in hits if str(h.get("ref") or "") in keep]
            except Exception:  # noqa: BLE001
                pass
            if not hits:
                return f"本项目笔记里没有提到「{q}」"
            return "\n".join(
                f"- {h.get('title') or '（无标题）'}\n  {h.get('snippet') or ''}"
                for h in hits[:limit]
            )

        # ---------------- 读白板
        if tool == "read_board":
            node, err = resolve(args)
            if not node:
                return err
            vid = int(node.get("vid") or 0)
            try:
                boards = [b for b in board.list_boards(context.root()) if int(b.get("vid") or 0) == vid]
            except Exception as exc:  # noqa: BLE001
                return f"读白板失败：{exc}"
            if not boards:
                return f"「{node.get('name')}」下没有白板"
            # 笔记 id → 标题（白板的 board[] 存的是笔记 id）
            titles: dict[int, str] = {}
            try:
                for r in store.notes_of(context.conn(), project["id"]):
                    titles[int(r.get("id") or 0)] = str(r.get("title") or "（无标题）")
            except Exception:  # noqa: BLE001
                pass
            out = []
            for b in boards[:5]:
                data = board.load(context.root(), str(b.get("id") or "")) or {}
                ids = [int(x) for x in (data.get("board") or []) if str(x).isdigit()]
                names = [titles.get(i) or f"笔记 {i}" for i in ids[:20]]
                out.append(
                    f"【{b.get('name') or '白板'}】放了 {len(ids)} 条笔记："
                    f"{'、'.join(names) if names else '（空）'}"
                )
            return "\n".join(out)

        # ---------------- 读笔记
        if tool == "read_notes":
            node, err = resolve(args)
            if not node:
                return err
            try:
                rows = store.notes_of(context.conn(), project["id"], int(node.get("vid") or 0))
            except Exception as exc:  # noqa: BLE001
                return f"读笔记失败：{exc}"
            if not rows:
                return f"「{node.get('name')}」这个节点上还没有笔记"

            # ★★ 默认只给**清单**（全部，最多 30 条）：
            #   一个节点下可能有十几篇、分属五个标签，只给前几篇会让模型
            #   以为「就这些」。正文按需展开，⛔ 不一上来就灌。
            lines = [f"「{node.get('name')}」下有 {len(rows)} 篇笔记："]
            for i, r in enumerate(rows[:30], 1):
                k = ai.KIND_LABELS.get(str(r.get("kind") or ""), "笔记")
                lines.append(f"{i}. [{k}] {r.get('title') or '（无标题）'}")
            if len(rows) > 30:
                lines.append(f"（还有 {len(rows) - 30} 篇未列出）")

            if bool(args.get("with_body")):
                limit = min(20, max(1, int(args.get("limit") or 3)))
                lines.append("")
                for r in rows[:limit]:
                    k = ai.KIND_LABELS.get(str(r.get("kind") or ""), "笔记")
                    lines.append(
                        f"【{k}】{r.get('title') or '（无标题）'}\n"
                        f"{note_body(r.get('rel_path') or '')}"
                    )
            else:
                lines.append("（要看正文，传 with_body=true）")
            return "\n".join(lines)

        # ---------------- 读代码（只按 rel_path + 行号取文件片段）
        if tool == "read_file":
            node, err = resolve(args)
            if not node:
                return err
            rel = str(node.get("rel_path") or "").strip()
            line = int(node.get("line") or 0)
            # ⛔ 没有对应文件或没有行号范围的节点（如目录，line=0）⇒ 返回空
            if not rel or line <= 0:
                return ""
            max_lines = min(400, max(40, int(args.get("max_lines") or 120)))
            return snippet_of(node, max_lines)

        return f"未知工具：{tool}"

    return run
