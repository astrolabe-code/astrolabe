#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ **查询驱动解析器** —— 用 `.scm` 有限枚举代替递归遍历

## 为什么换（所有者 2026-10-31）

```
原来   递归走整棵 AST（_walk）
       · 唯一的**无界递归**：恶意代码 1 万层嵌套 ⇒ RecursionError，成本由输入决定
       · 逻辑共享：改 C 的特例要动公共代码，容易把 Python 弄坏
现在   每种语言一份 `.scm`（只描述形状）+ 一个处理模块（只描述口径）
       · 游标在 tree-sitter 的 C 层迭代走树 ⇒ Python 侧**没有递归**
       · 工作量 = 节点数 × 模式数，两者都是可控量 ⇒ 成本可预估，才能做配额
```

## 这个文件只做三件事

```
① 跑查询，把匹配分成「定义 / 调用 / 导入」
② 定义按位置排序后逐个建节点（父先于子 ⇒ 作用域能一层层拼出来）
③ 调用找最近的**定义祖先**（沿 node.parent 上溯，⛔ 不遍历子树）
```

⚠ 各语言的差异（种类映射、ref 怎么拼、分隔符）全在 `langs/<lang>.py` 里，
  这里一行都不写死 —— 改一种语言不会碰到别的语言。
"""

from __future__ import annotations

import os

import tree_sitter
from tree_sitter import Language as TSLanguage
from tree_sitter import Parser as TSParser

from .base import ParseResult, ParsedEdge, ParsedField, ParsedNode

#: 查询文件目录（与 .scm 同目录）
_QUERY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries")


def _grammar(lang: str):
    """取 tree-sitter 的 Language 对象（延迟导入：缺语言包不影响别的语言）"""
    from .treesitter import _LANG_MODULES

    mod = _LANG_MODULES.get(lang)
    if mod is None:
        raise ValueError(f"没有 {lang} 的语法包")
    return TSLanguage(mod.language())


def _txt(node, src: bytes) -> str:
    return node.text.decode("utf-8", "ignore").strip() if node is not None else ""


class QueryParser:
    """一个语言一个实例（查询编译一次，复用）"""

    def __init__(self, lang: str):
        from . import langs

        self.lang = lang
        self.spec = langs.load(lang)
        if self.spec is None:
            raise RuntimeError(f"语言 {lang} 的处理模块不可用")

        qfile = os.path.join(_QUERY_DIR, self.spec.query_file)
        with open(qfile, "r", encoding="utf-8") as f:
            qtext = f.read()

        self._lang = _grammar(lang)
        self._query = tree_sitter.Query(self._lang, qtext)
        self._parser = TSParser(self._lang)

        #: 上一次解析的统计（定义/调用/被放弃的函数指针调用/形态分布）
        self.last_stats: dict = {}

    # ------------------------------------------------------------------

    def parse(self, source: bytes, path: str) -> ParseResult:
        result = ParseResult()
        try:
            tree = self._parser.parse(source)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"解析失败 {path}: {exc}")
            return result

        file_name = path.rsplit("/", 1)[-1]
        file_node = ParsedNode(kind="file", name=file_name, file_path=path, line=1, lang=self.lang)
        file_uid = file_node.uid
        result.nodes.append(file_node)

        stats = {"defs": 0, "calls": 0, "droppedCalls": 0, "imports": 0}
        by_shape: dict[str, int] = {}
        spec = self.spec

        try:
            matches = list(self._query.matches(tree.root_node))
        except Exception as exc:  # noqa: BLE001 —— 查询匹配出错只影响本文件
            result.errors.append(f"查询失败 {path}: {exc}")
            self.last_stats = stats
            return result

        # ---------------------------------------------------------- ① 定义
        # ⚠ 按**起始位置排序**：父（class / namespace）一定先于子（method），
        #   这样拼 qname 时父的 qname 已经算好了（不用递归、不用二次遍历）
        defs: list[tuple[int, str, str, str, object, dict]] = []
        for _pid, caps in matches:
            for cname, cnodes in caps.items():
                if not cname.startswith("def.") or cname.count(".") != 1:
                    continue
                kind = spec.def_kinds.get(cname)
                if not kind:
                    continue
                outer = cnodes[0]
                name_nodes = caps.get(f"{cname}.name") or []
                name = _txt(name_nodes[0], source) if name_nodes else ""
                if not name:
                    name = spec.def_name(cname, outer, source)
                if not name:
                    continue
                defs.append((outer.start_byte, cname, kind, name, outer, caps))
        defs.sort(key=lambda x: x[0])

        uid_of_node: dict[int, int] = {}
        qname_of_uid: dict[int, str] = {}

        for _pos, cname, kind, name, outer, caps in defs:
            # 父定义：沿 parent 链上溯（每层一次指针跟随）
            parent_uid = ""
            cur = outer.parent
            while cur is not None:
                got = uid_of_node.get(cur.id)
                if got:
                    parent_uid = got
                    break
                cur = cur.parent

            prefix = spec.def_scope(cname, caps, source)
            parts = [p for p in (qname_of_uid.get(parent_uid, ""), prefix, name) if p]
            qname = spec.sep.join(parts)

            parsed = ParsedNode(
                kind=kind,
                name=name,
                qname=qname,
                file_path=path,
                line=outer.start_point[0] + 1,
                line_end=outer.end_point[0] + 1,
                lang=self.lang,
                # ★ 签名：读源码时最想知道"它要什么参数"（⛔ 不进 canonical）
                signature=spec.signature(outer, source),
            )
            result.nodes.append(parsed)
            uid_of_node[outer.id] = parsed.uid
            qname_of_uid[parsed.uid] = qname
            stats["defs"] += 1

            # 包含边：父符号 → 子符号（顶层连文件）
            result.edges.append(
                ParsedEdge(
                    from_uid=parent_uid or file_uid,
                    to_uid=parsed.uid,
                    type="contains",
                    line=outer.start_point[0] + 1,
                )
            )

        # ---------------------------------------------------------- ①.5 继承 / 字段
        seen_field: set[tuple[str, str, int]] = set()
        for _pid, caps in matches:
            for cname in ("ext.base", "impl.base"):
                nodes_b = caps.get(cname) or []
                if not nodes_b:
                    continue
                owner_nodes = caps.get(cname.split(".", 1)[0] + ".owner") or []
                if not owner_nodes:
                    continue
                owner_uid = uid_of_node.get(owner_nodes[0].id)
                if not owner_uid:
                    continue
                base = spec.clean_type_name(_txt(nodes_b[0], source))
                if not base:
                    continue
                stats["relations"] = stats.get("relations", 0) + 1
                result.edges.append(
                    ParsedEdge(
                        from_uid=str(owner_uid),
                        to_uid=f"unresolved#type#{base}",
                        type="extends" if cname.startswith("ext") else "implements",
                        line=nodes_b[0].start_point[0] + 1,
                        confidence="syntax",
                    )
                )

            names = caps.get("field.name") or []
            owners = caps.get("field.owner") or []
            if not names or not owners:
                continue
            owner_uid = uid_of_node.get(owners[0].id)
            if not owner_uid:
                continue
            fname = _txt(names[0], source)
            if not fname:
                continue
            key = (str(owner_uid), fname, names[0].start_point[0] + 1)
            if key in seen_field:
                continue
            seen_field.add(key)
            types = caps.get("field.type") or []
            result.fields.append(
                ParsedField(
                    owner_uid=str(owner_uid),
                    name=fname,
                    type_text=spec.clean_type_name(_txt(types[0], source)) if types else "",
                    line=names[0].start_point[0] + 1,
                )
            )

        stats["fields"] = len(result.fields)

        # ---------------------------------------------------------- ② 调用 / 导入
        def owner_of(node) -> str:
            """★ 最近的定义祖先（沿 parent 上溯，⛔ 不遍历子树）"""
            cur = node.parent
            depth = 0
            while cur is not None and depth < 256:
                got = uid_of_node.get(cur.id)
                if got is not None:
                    return str(got)
                cur = cur.parent
                depth += 1
            return file_uid

        for _pid, caps in matches:
            # ---- 导入 / 包含
            for node in caps.get("imp") or []:
                for target in spec.import_targets(_txt(node, source)):
                    stats["imports"] += 1
                    result.edges.append(
                        ParsedEdge(
                            from_uid=file_uid,
                            to_uid=f"unresolved#include#{target}",
                            type=spec.import_edge_type,
                            line=node.start_point[0] + 1,
                            confidence="syntax",
                        )
                    )
            for node in caps.get("inc.path") or []:
                raw = _txt(node, source).strip('<>"')
                if raw:
                    stats["imports"] += 1
                    result.edges.append(
                        ParsedEdge(
                            from_uid=file_uid,
                            to_uid=f"unresolved#include#{raw}",
                            type=spec.import_edge_type,
                            line=node.start_point[0] + 1,
                            confidence="syntax",
                        )
                    )

            # ---- 调用
            for cname, cnodes in caps.items():
                if not cname.startswith("call.") or cname.count(".") != 1:
                    continue
                shape = cname.split(".", 1)[1]
                node = cnodes[0]
                recv, name = spec.call_parts(node, source, caps, cname)
                if not name:
                    continue
                by_shape[shape] = by_shape.get(shape, 0) + 1
                ref = spec.call_ref(shape, name, recv)
                if ref is None:
                    # ⚠ 目标是变量（函数指针/下标/转换后调用）⇒ 只计数，⛔ 不建边
                    stats["droppedCalls"] += 1
                    continue
                stats["calls"] += 1
                result.edges.append(
                    ParsedEdge(
                        from_uid=owner_of(node),
                        to_uid=ref,
                        type="calls",
                        line=node.start_point[0] + 1,
                        confidence="syntax",
                    )
                )

        stats["byShape"] = by_shape
        self.last_stats = stats
        return result
