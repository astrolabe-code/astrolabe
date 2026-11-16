"""LadybugDB 图库：**只存代码结构**（Code 节点 + Rel 边）。

```cypher
CREATE NODE TABLE Code(vid INT64, kind, name, qname, file, line, lineEnd, signature, origin,
                       PRIMARY KEY(vid))
CREATE REL TABLE  Rel (FROM Code TO Code, kind, origin, line)
```

⛔ 笔记 / 白板**不在这里**：
  · 笔记元数据（含锚点 node_vid）在 SQLite 的 `note` 表
  · 白板布局在 `boards/*.json`
  · 「某个节点上有哪些笔记」= SQLite 一次 WHERE，⛔ 不需要图边

主键 = `vid` = `hash53(canon)`，canon 由解析器统一算；撞了按 assign_vids 的规则加盐。
"""

from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_cache: dict[str, tuple] = {}

BATCH = 500
MAX_HOPS = 30

_SCHEMA = [
    "CREATE NODE TABLE IF NOT EXISTS Code("
    "vid INT64, kind STRING, name STRING, qname STRING,"
    "file STRING, line INT64, lineEnd INT64, signature STRING, origin STRING,"
    "PRIMARY KEY(vid))",
    "CREATE REL TABLE IF NOT EXISTS Rel("
    "FROM Code TO Code, kind STRING, origin STRING, line INT64, MANY_MANY)",
]


def available() -> bool:
    try:
        import ladybug  # noqa: F401
    except Exception:
        return False
    return True


def db_path(data_dir: str) -> str:
    return os.path.join(data_dir, "graph.lbug")


def _open(data_dir: str):
    """懒连接并建表。图是真相 ⇒ 打不开就直接报错，⛔ 不静默降级。"""
    with _lock:
        hit = _cache.get(data_dir)
        if hit:
            return hit[1]
        try:
            import ladybug as lb
        except Exception as e:  # pragma: no cover - 环境缺包
            raise RuntimeError(f"LadybugDB 不可用（pip install ladybug）：{e}") from None
        os.makedirs(data_dir, exist_ok=True)
        try:
            db = lb.Database(db_path(data_dir))
            conn = lb.Connection(db)
            for q in _SCHEMA:
                conn.execute(q)
        except Exception as e:
            raise RuntimeError(
                f"打开图库失败：{e}\n"
                "（图库结构变更过？删掉 graph.lbug 重新解析一次即可）"
            ) from None
        _cache[data_dir] = (db, conn)
        return conn


def close(data_dir: str | None = None) -> None:
    with _lock:
        keys = [data_dir] if data_dir else list(_cache)
        for k in keys:
            _cache.pop(k, None)


def _code_rows(nodes: list[dict]) -> list[dict]:
    return [
        {
            "vid": int(n["vid"]),
            "kind": str(n.get("kind") or ""),
            "name": str(n.get("name") or ""),
            "qname": str(n.get("qname") or ""),
            "file": str(n.get("file_path") or n.get("file") or ""),
            "line": int(n.get("line") or 0),
            "lineEnd": int(n.get("line_end") or -1),
            "signature": str(n.get("signature") or ""),
            "origin": str(n.get("origin") or "parsed"),
        }
        for n in nodes
    ]


def _edge_rows(edges: list[dict]) -> list[dict]:
    return [
        {
            "a": int(e["src_vid"]),
            "b": int(e["dst_vid"]),
            "kind": str(e.get("kind") or "call"),
            "origin": str(e.get("origin") or "parsed"),
            "line": int(e.get("line") or 0),
        }
        for e in edges
    ]


def sync_code(data_dir: str, nodes: list[dict], edges: list[dict]) -> dict:
    """整体替换代码图（只换解析产物，人工补的节点/边保留）。

    ⛔ 笔记 / 白板不在这里：它们的锚点在 SQLite 的 note.node_vid 和 boards/*.json 里。
    """
    conn = _open(data_dir)
    manual_nodes = conn.execute(
        "MATCH (c:Code) WHERE c.origin = 'manual' "
        "RETURN c.vid, c.kind, c.name, c.qname, c.file, c.line, c.lineEnd, c.signature"
    ).get_all()
    manual_edges = conn.execute(
        "MATCH (a:Code)-[r:Rel]->(b:Code) WHERE r.origin = 'manual' "
        "RETURN a.vid, b.vid, r.kind, r.line"
    ).get_all()

    rows = _code_rows(nodes)
    parsed_vids = {int(n["vid"]) for n in nodes}
    for vid, kind, name, qname, file, line, line_end, signature in manual_nodes:
        # 解析器这次也产出了同一个 vid ⇒ 用解析产物那份（同名同文件同行号视为同一节点）
        if int(vid) in parsed_vids:
            continue
        rows.append(
            {
                "vid": int(vid),
                "kind": str(kind or ""),
                "name": str(name or ""),
                "qname": str(qname or ""),
                "file": str(file or ""),
                "line": int(line or 0),
                "lineEnd": int(line_end) if line_end is not None else -1,
                "signature": str(signature or ""),
                "origin": "manual",
            }
        )

    # ★ vid 撞不撞车交给数据库判断（主键索引 O(log n)），
    #   ⛔ 不预读全表、不自己建索引；真撞了在插入时捕获再重算（见 _create_code）

    # ★★ 只去掉「属性完全一样」的重复边；不同 kind / origin / line 的边全部保留
    #    （图上两点之间只画一条，是展示层聚合的事，⛔ 不在存储层砍数据）
    erows: list[dict] = []
    seen: set[tuple] = set()

    def ekey(e: dict) -> tuple:
        return (int(e["a"]), int(e["b"]), str(e["kind"]), str(e["origin"]), int(e["line"]))

    for e in _edge_rows(edges):
        key = ekey(e)
        if key in seen:
            continue
        seen.add(key)
        erows.append(e)
    for a, b, kind, line in manual_edges:
        row = {
            "a": int(a),
            "b": int(b),
            "kind": str(kind or "call"),
            "origin": "manual",
            "line": int(line or 0),
        }
        key = ekey(row)
        if key in seen:
            continue
        seen.add(key)
        erows.append(row)

    remounted = 0
    missed = 0

    # ---------------- 尝试 1：批量（正常路径，快）----------------
    try:
        conn.execute("BEGIN TRANSACTION")
        _clear_code(conn)
        for i in range(0, len(rows), BATCH):
            conn.execute(
                "UNWIND $rows AS r CREATE (:Code {vid: r.vid, kind: r.kind, "
                "name: r.name, qname: r.qname, file: r.file, line: r.line, "
                "lineEnd: r.lineEnd, signature: r.signature, origin: r.origin})",
                {"rows": rows[i : i + BATCH]},
            )
        for i in range(0, len(erows), BATCH):
            conn.execute(
                "UNWIND $rows AS r MATCH (a:Code {vid: r.a}), (b:Code {vid: r.b}) "
                "CREATE (a)-[:Rel {kind: r.kind, origin: r.origin, line: r.line}]->(b)",
                {"rows": erows[i : i + BATCH]},
            )
        conn.execute("COMMIT")
    except Exception as exc:  # noqa: BLE001
        try:
            conn.execute("ROLLBACK")
        except Exception:  # noqa: BLE001 —— 语句失败时 Kùzu 已自动结束事务
            pass
        if not _is_dup_pk(exc):
            raise

        # ---------------- 尝试 2：撞主键 ⇒ 逐条插、撞一个换一个 ----------------
        # ⚠ 必须走自动提交（语句失败会终止事务，没法在事务里重试）
        _clear_code(conn)
        remap: dict[int, int] = {}
        for row in rows:
            before = int(row["vid"])
            _create_code(conn, row)
            if int(row["vid"]) != before:
                remap[before] = int(row["vid"])
        if remap:
            # 节点换了 vid ⇒ 边两端跟着换，否则边指向不存在的节点
            for e in erows:
                e["a"] = remap.get(e["a"], e["a"])
                e["b"] = remap.get(e["b"], e["b"])
        for e in erows:
            conn.execute(
                "MATCH (a:Code {vid:$a}), (b:Code {vid:$b}) "
                "CREATE (a)-[:Rel {kind:$k, origin:$o, line:$l}]->(b)",
                {"a": e["a"], "b": e["b"], "k": e["kind"], "o": e["origin"], "l": e["line"]},
            )

    return {"nodes": len(rows), "edges": len(erows)}


def clear(data_dir: str) -> None:
    """清空代码图（笔记/白板不在图里，不受影响）。"""
    conn = _open(data_dir)
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute("MATCH ()-[r:Rel]->() DELETE r")
        conn.execute("MATCH (c:Code) DELETE c")
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:  # noqa: BLE001
            pass
        raise


def nodes(data_dir: str, limit: int = 500, offset: int = 0, kinds: list[str] | None = None) -> dict:
    conn = _open(data_dir)
    if kinds:
        where = " WHERE c.kind IN $kinds"
        params = {"kinds": kinds}
    else:
        where = ""
        params = {}
    total = conn.execute(f"MATCH (c:Code){where} RETURN count(c)", params).get_next()[0]
    # ★ 入口节点排最前（main / __main__），其余按文件、行号 —— 与旧版分页排序一致
    items = conn.execute(
        f"MATCH (c:Code){where} RETURN c.vid, c.kind, c.name, c.qname, c.file, c.line, "
        f"c.lineEnd, c.signature, c.origin "
        f"ORDER BY CASE WHEN c.name = 'main' OR c.name = '__main__' THEN 0 ELSE 1 END, "
        f"c.file, c.line SKIP {int(offset)} LIMIT {int(limit)}",
        params,
    ).get_all()
    cols = ["vid", "kind", "name", "qname", "file_path", "line", "line_end", "signature", "origin"]
    return {
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
        "items": [dict(zip(cols, r)) for r in items],
    }


def has_code(data_dir: str) -> bool:
    conn = _open(data_dir)
    return int(conn.execute("MATCH (c:Code) RETURN count(c)").get_next()[0]) > 0


_TYPE_PRIORITY = {"call": 0, "calls": 0, "extends": 1, "implements": 1,
                  "include": 2, "includes": 2, "imports": 2, "contains": 3}


def graph_full(data_dir: str) -> dict:
    """整张代码图（图谱页用）。★ 两点之间**聚合成一条展示边**，details 带全部原始边。"""
    conn = _open(data_dir)
    nodes = conn.execute(
        "MATCH (c:Code) RETURN c.vid, c.kind, c.name, c.qname, c.file, c.line, c.lineEnd, c.origin"
    ).get_all()
    edges = conn.execute(
        "MATCH (a:Code)-[r:Rel]->(b:Code) RETURN a.vid, b.vid, r.kind, r.origin, r.line "
        "ORDER BY a.vid, b.vid, r.kind, r.line"
    ).get_all()

    groups: dict[tuple[int, int], list[dict]] = {}
    for a, b, kind, origin, line in edges:
        key = (min(a, b), max(a, b))
        groups.setdefault(key, []).append(
            {"from": a, "to": b, "type": kind, "origin": origin, "line": line}
        )

    shown = []
    # 端点对排序固定 ⇒ 渲染用的数字 id 稳定
    for idx, key in enumerate(sorted(groups), 1):
        items = sorted(groups[key], key=lambda x: (_TYPE_PRIORITY.get(x["type"], 4), x["line"]))
        head = items[0]
        shown.append(
            {
                "id": idx,
                "from": head["from"],
                "to": head["to"],
                "type": head["type"],
                "origin": "manual" if any(x["origin"] == "manual" for x in items) else "parsed",
                "line": head["line"],
                "count": len(items),
                "details": items,
            }
        )

    ncols = ["vid", "kind", "name", "qname", "file_path", "line", "line_end", "origin"]
    return {"nodes": [dict(zip(ncols, r)) for r in nodes], "edges": shown}

def neighbors(data_dir: str, vid: int, depth: int = 1) -> dict:
    conn = _open(data_dir)
    d = max(1, min(MAX_HOPS, int(depth)))
    out = conn.execute(
        f"MATCH (a:Code {{vid:$v}})-[:Rel*1..{d}]->(b:Code) "
        "RETURN DISTINCT b.vid, b.kind, b.name, b.qname, b.file, b.line, b.origin",
        {"v": int(vid)},
    ).get_all()
    back = conn.execute(
        f"MATCH (b:Code)-[:Rel*1..{d}]->(a:Code {{vid:$v}}) "
        "RETURN DISTINCT b.vid, b.kind, b.name, b.qname, b.file, b.line, b.origin",
        {"v": int(vid)},
    ).get_all()
    # ★ `origin` 用来区分「解析器产出的」和「作者手工补的」
    cols = ["vid", "kind", "name", "qname", "file_path", "line", "origin"]
    return {
        "depth": d,
        "downstream": [dict(zip(cols, r)) for r in out],
        "upstream": [dict(zip(cols, r)) for r in back],
    }


def degrees(data_dir: str) -> dict[int, int]:
    """每个节点的度数（入度 + 出度），一次全图查询。

    ★ 给 AI 上下文的邻居排序用：核心函数比叶子函数更值得放进 prompt。
    ⚠ 不逐节点查询 —— 几千条边一次读进内存，比 N 次点查快一个数量级。
    """
    conn = _open(data_dir)
    rows = conn.execute("MATCH (a:Code)-[r:Rel]->(b:Code) RETURN a.vid, b.vid").get_all()
    deg: dict[int, int] = {}
    for a, b in rows:
        a, b = int(a), int(b)
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    return deg


def _canon(kind: str, file: str, name: str, line: int, line_end: int) -> str:
    """规范串（与解析器同一口径）。"""
    try:
        from graph import identity  # noqa: PLC0415 —— app/ 目录由 paths 注入

        return identity.canonical(kind, file, name, line, line_end)
    except Exception:  # pragma: no cover - 没有 app 目录时退化成同构写法
        return f"{kind}|{file}|{name}|{line}|{line_end}"


def _hash(text: str) -> int:
    try:
        from graph import identity  # noqa: PLC0415

        return int(identity.hash53(text))
    except Exception:  # pragma: no cover —— ⚠ 口径必须与 identity.hash53 完全一致
        import hashlib

        # ★ 53 位掩码是 JS Number.MAX_SAFE_INTEGER 的边界；
        #   少这一步（旧版用 7 字节 = 56 位）会产出前端 Number() 装不下的 vid
        mask = (1 << 53) - 1
        return (
            int.from_bytes(
                hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big"
            )
            & mask
        )


def _new_vid(kind: str, file: str, name: str, line: int, line_end: int) -> int:
    """与解析器完全一致的 vid 算法（⛔ 不要自己算哈希）。"""
    return _hash(_canon(kind, file, name, line, line_end))


def _dedupe(rows: list[dict], key) -> list[dict]:
    """按主键去重：后出现的覆盖先出现的（⛔ 不让脏数据撞主键）。"""
    seen: dict = {}
    for r in rows:
        seen[key(r)] = r
    return list(seen.values())


def _is_dup_pk(exc) -> bool:
    """是不是主键冲突（唯一约束）—— 只认这一种，别的错误照常抛。"""
    return "duplicated primary key" in str(exc).lower()


_CODE_CREATE = (
    "CREATE (:Code {vid:$vid, kind:$kind, name:$name, qname:$qname, "
    "file:$file, line:$line, lineEnd:$lineEnd, signature:$signature, origin:$origin})"
)


def _create_code(conn, row: dict, attempt: int = 0) -> bool:
    """插一个节点（自动提交）。返回 True = 新插入，False = 同内容的节点已存在。

    ★ 只在数据库报 `duplicated primary key` 之后才判断，⛔ 不预查：
      · 撞的是「同 kind/文件/名字/行号」⇒ 同一个节点，跳过（⛔ 绝不造重复节点）
      · 撞的是「别的内容」⇒ 哈希碰撞，加盐重算 vid 再试（与 assign_vids 同规则）
    """
    try:
        conn.execute(_CODE_CREATE, row)
        return True
    except Exception as exc:  # noqa: BLE001
        if not _is_dup_pk(exc) or attempt > 8:
            raise
        canon = _canon(row["kind"], row["file"], row["name"], row["line"], row["lineEnd"])
        cur = _get_code(conn, int(row["vid"]))
        if cur is not None and (
            _canon(cur["kind"], cur["file"], cur["name"], cur["line"], cur["line_end"]) == canon
        ):
            return False
        row["vid"] = _hash(f"{canon}|{attempt + 1}")
        return _create_code(conn, row, attempt + 1)

def _clear_code(conn) -> None:
    conn.execute("MATCH ()-[r:Rel]->() DELETE r")
    conn.execute("MATCH (c:Code) DETACH DELETE c")


def _get_code(conn, vid: int) -> dict | None:
    rows = conn.execute(
        "MATCH (c:Code {vid:$v}) RETURN c.vid, c.kind, c.name, c.qname, c.file, "
        "c.line, c.lineEnd, c.signature, c.origin",
        {"v": int(vid)},
    ).get_all()
    if not rows:
        return None
    return dict(
        zip(
            ["vid", "kind", "name", "qname", "file", "line", "line_end", "signature", "origin"],
            rows[0],
        )
    )


def add_code(
    data_dir: str,
    kind: str,
    name: str,
    qname: str,
    file: str,
    line: int,
    line_end: int,
    signature: str = "",
) -> int:
    """手工补一个代码节点（origin=manual），返回 vid。

    ★ 直接插、撞了再判断（单条插入是日常路径，不预查）：
      · 同 kind/文件/名字/行号 ⇒ 重复添加，报错
      · 不同内容 ⇒ 哈希碰撞，自动换个 vid（用户无感）
    """
    conn = _open(data_dir)
    row = {
        "vid": _hash(_canon(kind, file, name, line, line_end)),
        "kind": kind,
        "name": name,
        "qname": qname or name,
        "file": file,
        "line": line,
        "lineEnd": line_end,
        "signature": signature,
        "origin": "manual",
    }
    if _create_code(conn, row):
        return int(row["vid"])
    raise ValueError("已经有一个完全相同的节点（同 kind / 文件 / 名字 / 行号）")

def update_code(data_dir: str, vid: int, patch: dict) -> dict:
    """改节点字段；vid 变了就换身份，并把边与笔记锚点一起迁过去。"""
    conn = _open(data_dir)
    cur = _get_code(conn, vid)
    if cur is None:
        raise ValueError("节点不存在")

    def pick(key: str, fallback):
        v = patch.get(key)
        return fallback if v is None or v == "" else v

    nk = str(pick("kind", cur["kind"]))
    nn = str(pick("name", cur["name"]))
    nf = str(pick("file_path", cur["file"]))
    nl = int(pick("line", cur["line"]))
    ne = int(pick("line_end", cur["line_end"]))
    new_vid = _new_vid(nk, nf, nn, nl, ne)

    if new_vid == vid:
        conn.execute(
            "MATCH (c:Code {vid:$v}) SET c.kind=$k, c.name=$n, c.qname=$q, c.file=$f, "
            "c.line=$l, c.lineEnd=$e, c.origin='manual'",
            {"v": vid, "k": nk, "n": nn, "q": patch.get("qname") or cur["qname"], "f": nf, "l": nl, "e": ne},
        )
        return {"vid": vid, "old_vid": vid, "changed": True}

    if _get_code(conn, new_vid) is not None:
        raise ValueError("改完会和已有节点重名（同 kind/文件/名字/行号），请换个名字")

    outs = conn.execute(
        "MATCH (c:Code {vid:$v})-[r:Rel]->(b:Code) RETURN b.vid, r.kind, r.origin, r.line",
        {"v": vid},
    ).get_all()
    ins = conn.execute(
        "MATCH (a:Code)-[r:Rel]->(c:Code {vid:$v}) RETURN a.vid, r.kind, r.origin, r.line",
        {"v": vid},
    ).get_all()
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute("MATCH (c:Code {vid:$v}) DETACH DELETE c", {"v": vid})
        conn.execute(
            "CREATE (:Code {vid:$vid, kind:$k, name:$n, qname:$q, "
            "file:$f, line:$l, lineEnd:$e, signature:$s, origin:'manual'})",
            {
                "vid": new_vid,
                "k": nk,
                "n": nn,
                "q": f"{nf}:{nn}" if nf else nn,
                "f": nf,
                "l": nl,
                "e": ne,
                "s": cur["signature"] or "",
            },
        )
        for peer, kind, origin, line in outs:
            conn.execute(
                "MATCH (a:Code {vid:$a}), (b:Code {vid:$b}) "
                "CREATE (a)-[:Rel {kind:$k, origin:$o, line:$l}]->(b)",
                {"a": new_vid, "b": peer, "k": kind, "o": origin, "l": line},
            )
        for peer, kind, origin, line in ins:
            conn.execute(
                "MATCH (a:Code {vid:$a}), (b:Code {vid:$b}) "
                "CREATE (a)-[:Rel {kind:$k, origin:$o, line:$l}]->(b)",
                {"a": peer, "b": new_vid, "k": kind, "o": origin, "l": line},
            )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:  # noqa: BLE001 —— 事务已被自动回滚时再回滚会抛
            pass
        raise
    return {"vid": new_vid, "old_vid": vid, "changed": True}


def remove_code(data_dir: str, vid: int) -> int:
    """删节点并连带删掉所有边；返回删掉的边数。"""
    conn = _open(data_dir)
    if _get_code(conn, vid) is None:
        raise ValueError("节点不存在")
    edges = int(
        conn.execute(
            "MATCH (c:Code {vid:$v})-[r:Rel]->() RETURN count(r)", {"v": vid}
        ).get_next()[0]
    ) + int(
        conn.execute(
            "MATCH ()-[r:Rel]->(c:Code {vid:$v}) RETURN count(r)", {"v": vid}
        ).get_next()[0]
    )
    conn.execute("MATCH (c:Code {vid:$v}) DETACH DELETE c", {"v": vid})
    return edges


def add_rel(data_dir: str, src: int, dst: int, kind: str = "call") -> None:
    """加一条边。★ 只拒绝属性完全相同的重复边；两点之间允许多条不同属性的边。"""
    conn = _open(data_dir)
    if not int(src) or not int(dst):
        raise ValueError("两端都要有 vid")
    if int(src) == int(dst):
        raise ValueError("不能连自己")
    if _get_code(conn, src) is None:
        raise ValueError("起点节点不存在")
    if _get_code(conn, dst) is None:
        raise ValueError("终点节点不存在")
    dup = int(
        conn.execute(
            "MATCH (a:Code {vid:$a})-[r:Rel]->(b:Code {vid:$b}) "
            "WHERE r.kind = $k AND r.line = $l RETURN count(r)",
            {"a": int(src), "b": int(dst), "k": kind or "call", "l": 0},
        ).get_next()[0]
    )
    if dup:
        raise ValueError("已经有一条属性完全相同的边了")
    conn.execute(
        "MATCH (a:Code {vid:$a}), (b:Code {vid:$b}) "
        "CREATE (a)-[:Rel {kind:$k, origin:'manual', line:0}]->(b)",
        {"a": int(src), "b": int(dst), "k": kind or "call"},
    )


# ★ 两点之间可有多条边 ⇒ 必须按「方向 + kind + line」定位到具体一条
_REL_BY_ATTR = (
    "MATCH (a:Code {vid:$a})-[r:Rel]->(b:Code {vid:$b}) "
    "WHERE r.kind = $k AND r.line = $l "
)


def remove_rel(data_dir: str, src: int, dst: int, kind: str, line: int = 0) -> int:
    """删一条边（按全部属性定位）。"""
    conn = _open(data_dir)
    params = {"a": int(src), "b": int(dst), "k": str(kind), "l": int(line)}
    found = int(conn.execute(_REL_BY_ATTR + "RETURN count(r)", params).get_next()[0])
    if not found:
        raise ValueError("这条边不存在")
    conn.execute(_REL_BY_ATTR + "DELETE r", params)
    return found


def update_rel(data_dir: str, src: int, dst: int, old_kind: str, new_kind: str, line: int = 0) -> None:
    """改一条边的类型（按全部属性定位到那一条）。"""
    conn = _open(data_dir)
    kind = (new_kind or "").strip()
    if not kind:
        return
    params = {"a": int(src), "b": int(dst), "k": str(old_kind), "l": int(line)}
    got = conn.execute(_REL_BY_ATTR + "RETURN r.kind", params).get_all()
    if not got:
        raise ValueError("这条边不存在")
    if str(got[0][0]) == kind:
        return
    conn.execute(
        _REL_BY_ATTR + "SET r.kind = $new, r.origin = 'manual'",
        {**params, "new": kind},
    )


def flows_of(
    data_dir: str,
    vid: int,
    min_steps: int = 3,
    max_flows: int = 5,
    max_up: int = 8,
    max_down: int = 12,
    flow_kinds: tuple[str, ...] = ("call", "calls", "invoke", "invokes"),
) -> dict:
    """某个节点所在的**执行流**（入口 → … → 终点），现算、不存库。

    ★ 借鉴 GitNexus 的 `Process`：它的 `minSteps = 3` ——
      两步只是「A 调 B」，三步以上才是真正的多跳流程，短的直接丢掉。
    ★ 只走调用类边：`contains` / `imports` 表达的是结构，不是执行顺序。
    ★ 不新增表、不改 schema：几千条边一次读进内存，路径搜索是毫秒级。

    返回 `{"items": [{"id", "steps": [vid...], "length"}], "total": N}`；
    `steps` 里 vid 只出现一次，顺序即执行顺序（前端按 index + 1 显示 step）。
    """
    target = int(vid)
    conn = _open(data_dir)
    rows = conn.execute(
        "MATCH (a:Code)-[r:Rel]->(b:Code) RETURN a.vid, b.vid, r.kind"
    ).get_all()

    out_map: dict[int, list[int]] = {}
    in_map: dict[int, list[int]] = {}
    for a, b, kind in rows:
        if str(kind) not in flow_kinds:
            continue
        out_map.setdefault(int(a), []).append(int(b))
        in_map.setdefault(int(b), []).append(int(a))

    if target not in out_map and target not in in_map:
        return {"items": [], "total": 0}

    def up_paths(start: int) -> list[list[int]]:
        """向上到入口；最多 3 条（第一跳不同），每次选「入度最小」的更像入口。"""
        firsts = (in_map.get(start) or [])[:3]
        if not firsts:
            return [[start]]
        paths: list[list[int]] = []
        for first in firsts:
            path = [start, first]
            cur = first
            for _ in range(max_up - 1):
                ups = in_map.get(cur) or []
                if not ups:
                    break
                cur = min(ups, key=lambda x: len(in_map.get(x) or []))
                if cur in path:
                    break
                path.append(cur)
            paths.append(list(reversed(path)))
        return paths

    def down_path(start: int) -> list[int]:
        """向下找最长链（深度受限、每层最多 3 个分支，避免组合爆炸）。"""
        best = [start]

        def dfs(cur: int, path: list[int], depth: int) -> None:
            nonlocal best
            if len(path) > len(best):
                best = list(path)
            if depth >= max_down:
                return
            for nxt in (out_map.get(cur) or [])[:3]:
                if nxt in path:
                    continue
                dfs(nxt, path + [nxt], depth + 1)

        dfs(start, [start], 0)
        return best

    seen: set[tuple[int, ...]] = set()
    items: list[dict] = []
    for up in up_paths(target):
        full = up[:-1] + down_path(target)  # up 末尾就是 target，避免重复
        if len(full) < min_steps:
            continue
        key = tuple(full)
        if key in seen:
            continue
        seen.add(key)
        items.append({"id": f"flow:{full[0]}", "steps": full, "length": len(full)})
        if len(items) >= max_flows:
            break

    return {"items": items, "total": len(items)}


def _louvain(adj: dict[int, set[int]], max_iter: int = 20) -> dict[int, int]:
    """Louvain 的**移动阶段**：返回 `{节点: 社区 id}`。

    ⚠ 单独抽出来是为了能脱离图库单测（推理只依赖邻接表）。
    ★ 节点按 vid 排序遍历 ⇒ 同一份图每次结果一致，分组不会乱跳。

    ⚠⚠ 计算增益前必须**先把节点从原社区摘出去**（`total[ci] -= deg`），
       否则「自己」的度数会算进目标社区的 Σtot，导致三角形被拆散
       （实测：两个三角形 + 一条弱连接，错误版本分成 4 组）。
    """
    nodes = sorted(adj)
    deg = {n: len(adj[n]) for n in nodes}
    m2 = sum(deg.values()) or 1  # 2m
    comm = {n: n for n in nodes}
    total = {n: deg[n] for n in nodes}

    for _ in range(max_iter):
        moved = False
        for n in nodes:
            ci = comm[n]
            degn = deg[n]
            if not adj[n]:
                continue
            total[ci] = total.get(ci, 0) - degn  # ★ 先摘出来

            cnt: dict[int, int] = {}
            for m in adj[n]:
                cnt[comm[m]] = cnt.get(comm[m], 0) + 1

            best, best_gain = ci, 0.0
            for c, k in cnt.items():
                gain = k - total.get(c, 0) * degn / m2
                if gain > best_gain:
                    best, best_gain = c, gain

            if best != ci:
                comm[n] = best
                total[best] = total.get(best, 0) + degn
                moved = True
            else:
                total[ci] = total.get(ci, 0) + degn  # 放回去
        if not moved:
            break
    return comm


def communities_of(
    data_dir: str,
    min_size: int = 2,
    max_items: int = 8,
    max_nodes: int = 300,
    max_iter: int = 20,
) -> dict:
    """把节点聚成「一伙的」（Louvain 的移动阶段，纯 Python、无第三方依赖）。

    ★ 借鉴 GitNexus 的 `Community`（它用 Leiden 算 label / keywords / cohesion），
      但**不落库**：每次现算，结果只用于「建议先读哪几块」。
    ★ 不引入 igraph / leidenalg —— 绿色版不该为一个聚类多背几十 MB。
    ★ 只用 `vid` 排序遍历，保证同一份图每次算出同样的分组（不抖）。

    返回 `{"items": [{id, label, keywords, size, cohesion, nodes}], "total"}`；
    `cohesion` = 社区内部的**无向密度**（内部边数 / 可能边数），0~1。
    """
    from collections import Counter

    conn = _open(data_dir)
    rows = conn.execute("MATCH (a:Code)-[r:Rel]->(b:Code) RETURN a.vid, b.vid").get_all()

    adj: dict[int, set[int]] = {}
    for a, b in rows:
        a, b = int(a), int(b)
        if a == b:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    if not adj:
        return {"items": [], "total": 0}

    meta = {
        int(v): (str(f or ""), str(nm or ""))
        for v, f, nm in conn.execute(
            "MATCH (c:Code) RETURN c.vid, c.file, c.name"
        ).get_all()
    }

    nodes = sorted(adj)
    deg = {n: len(adj[n]) for n in nodes}
    comm = _louvain(adj, max_iter)

    groups: dict[int, list[int]] = {}
    for n in nodes:
        groups.setdefault(comm[n], []).append(n)

    def key_of(f: str) -> str:
        parts = str(f).replace("\\", "/").split("/")
        return parts[0] if len(parts) > 1 else parts[0].rsplit(".", 1)[0]

    items: list[dict] = []
    for members in groups.values():
        n = len(members)
        if n < min_size:
            continue
        ms = set(members)
        inner = sum(len(adj[v] & ms) for v in members) // 2
        possible = n * (n - 1) / 2 or 1
        words = Counter(key_of(meta.get(v, ("", ""))[0]) for v in members)
        top = [w for w, _ in words.most_common(3) if w]
        label = top[0] if top else meta.get(max(members, key=lambda v: deg[v]), ("", ""))[1]
        items.append(
            {
                "id": f"comm:{min(members)}",
                "label": label or "未命名",
                "keywords": top,
                "size": n,
                "cohesion": round(inner / possible, 4),
                "nodes": members[:max_nodes],
            }
        )

    items.sort(key=lambda x: -x["size"])
    return {"items": items[:max_items], "total": len(items)}


def edges_of(data_dir: str, vid: int) -> dict:
    """单跳出入边。图库的边没有主键 ⇒ id 用 src-dst-kind 合成。"""
    conn = _open(data_dir)
    out = conn.execute(
        "MATCH (a:Code {vid:$v})-[r:Rel]->(b:Code) "
        "RETURN a.vid, b.vid, r.kind, r.origin, r.line, b.name, b.file ORDER BY r.kind",
        {"v": int(vid)},
    ).get_all()
    inc = conn.execute(
        "MATCH (a:Code)-[r:Rel]->(b:Code {vid:$v}) "
        "RETURN a.vid, b.vid, r.kind, r.origin, r.line, a.name, a.file ORDER BY r.kind",
        {"v": int(vid)},
    ).get_all()

    def row(r, upwards: bool):
        src, dst, kind, origin, line, name, file = r
        return {
            "id": f"{src}-{dst}-{kind}-{line}",
            "src_vid": src,
            "dst_vid": dst,
            "kind": kind,
            "origin": origin,
            "line": line,
            "from_name" if upwards else "to_name": name,
            "from_file" if upwards else "to_file": file,
        }

    return {"out": [row(r, False) for r in out], "in": [row(r, True) for r in inc]}


def shortest_path(data_dir: str, from_vid: int, to_vid: int, max_hops: int = 10) -> dict:
    """最短调用路径（只往下游走）。返回 {found, hops, vids}。"""
    conn = _open(data_dir)
    d = max(1, min(MAX_HOPS, int(max_hops)))
    rows = conn.execute(
        f"MATCH p = (a:Code {{vid:$a}})-[:Rel* SHORTEST 1..{d}]->(b:Code {{vid:$b}}) "
        'RETURN length(p), properties(nodes(p), "vid")',
        {"a": int(from_vid), "b": int(to_vid)},
    ).get_all()
    if not rows:
        return {"found": False, "hops": 0, "vids": []}
    hops, vids = rows[0]
    return {"found": True, "hops": int(hops), "vids": [int(v) for v in vids]}


def get_code(data_dir: str, vid: int) -> dict | None:
    """单个节点；同时给 file / file_path 两种键名，兼容老的调用方。"""
    row = _get_code(_open(data_dir), vid)
    if row is None:
        return None
    row["file_path"] = row["file"]
    return row


def search_code(data_dir: str, q: str, limit: int = 8) -> list[dict]:
    """按名字 / 限定名 / 文件搜节点（命令面板用）。"""
    conn = _open(data_dir)
    key = str(q or "").strip()
    if not key:
        return []
    rows = conn.execute(
        "MATCH (c:Code) WHERE c.name CONTAINS $q OR c.qname CONTAINS $q OR c.file CONTAINS $q "
        "RETURN c.vid, c.kind, c.name, c.file, c.line "
        "ORDER BY (CASE WHEN c.name CONTAINS $q THEN 0 ELSE 1 END), size(c.name) "
        f"LIMIT {int(limit)}",
        {"q": key},
    ).get_all()
    cols = ["vid", "kind", "name", "file_path", "line"]
    return [dict(zip(cols, r)) for r in rows]


def manual_ids(data_dir: str) -> dict:
    """哪些是人手补的：节点 vid 列表 + 边的三元组 id 列表。"""
    conn = _open(data_dir)
    nodes = [
        int(r[0])
        for r in conn.execute("MATCH (c:Code) WHERE c.origin = 'manual' RETURN c.vid").get_all()
    ]
    edges = [
        f"{a}-{b}"
        for a, b, k in conn.execute(
            "MATCH (a:Code)-[r:Rel]->(b:Code) WHERE r.origin = 'manual' "
            "RETURN a.vid, b.vid, r.kind"
        ).get_all()
    ]
    return {"nodes": nodes, "edges": edges}


def code_vids(data_dir: str) -> set[int]:
    """图库里现存的所有 vid（用来判断笔记锚点还有没有主人）。"""
    conn = _open(data_dir)
    return {int(r[0]) for r in conn.execute("MATCH (c:Code) RETURN c.vid").get_all()}


def counts(data_dir: str) -> dict:
    conn = _open(data_dir)
    return {
        "code": int(conn.execute("MATCH (c:Code) RETURN count(c)").get_next()[0]),
        "edges": int(conn.execute("MATCH ()-[r:Rel]->() RETURN count(r)").get_next()[0]),
        "dirs": int(
            conn.execute("MATCH (c:Code) WHERE c.kind = 'dir' RETURN count(c)").get_next()[0]
        ),
    }
