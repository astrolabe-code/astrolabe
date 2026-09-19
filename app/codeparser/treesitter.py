"""Astrolabe · 解析器：tree-sitter 实现（C / C++ / Python / Java）

★ 归属：**公开版**源码。

★★ 依据 JOB-MODEL.md J10.3：
   · 产出统一 `ParseResult` —— ★ **不暴露 tree-sitter 的节点类型**（否则下游被绑死）
   · ★ 新增语言 = 在 `LANGS` 加一条；**下游代码完全不用改**

⚠ 能力边界（`backend-ecosystem-refs.md` C2）：
   tree-sitter 只能做**语法级**。C/C++ 的精确调用图依赖重载决议 / 模板实例化 /
   宏展开 / 跨编译单元信息 —— 那些需要 `compile_commands` + clangd。
   ★ 因此本实现产出的边的 `confidence` **一律标 `syntax`**，❌ 绝不谎报为 `semantic`。
"""

from __future__ import annotations

import re

import tree_sitter_c
import tree_sitter_cpp
import tree_sitter_java
import tree_sitter_python
from tree_sitter import Language, Node
from tree_sitter import Parser as _TSParser

from .base import ParsedEdge, ParsedNode, ParseResult, Parser

# ===========================================================================
# tree-sitter 语法包
# ===========================================================================

_LANG_MODULES = {
    "c": tree_sitter_c,
    "cpp": tree_sitter_cpp,
    "python": tree_sitter_python,
    "java": tree_sitter_java,
}

# ===========================================================================
# ★★ 语言定义表 —— **新增语言只改这里**
#
#   definitions: AST 节点类型 → (节点 kind, 名字所在字段, 参数/签名所在字段)
#   call:        AST 调用节点类型 → 被调用者字段
#   imports:     [AST 导入节点类型, ...]
# ===========================================================================

LANGS: dict[str, dict] = {
    "python": {
        "definitions": {
            "function_definition": ("function", "name", "parameters"),
            "class_definition": ("type", "name", None),
        },
        "call": ("call", "function"),
        "imports": ["import_statement", "import_from_statement"],
    },
    "c": {
        "definitions": {
            # ⚠ C 的函数名藏在嵌套的 declarator 里 —— 由 _extract_name 递归处理
            "function_definition": ("function", "declarator", "declarator"),
            "struct_specifier": ("type", "name", None),
            "union_specifier": ("type", "name", None),
            "enum_specifier": ("type", "name", None),
            "preproc_function_def": ("macro", "name", "parameters"),
            "preproc_def": ("macro", "name", None),
            "type_definition": ("type", "declarator", None),
        },
        "call": ("call_expression", "function"),
        "imports": ["preproc_include"],
    },
    "cpp": {
        "definitions": {
            "function_definition": ("function", "declarator", "declarator"),
            "class_specifier": ("type", "name", None),
            "struct_specifier": ("type", "name", None),
            "enum_specifier": ("type", "name", None),
            "namespace_definition": ("type", "name", None),
            "preproc_function_def": ("macro", "name", "parameters"),
            "preproc_def": ("macro", "name", None),
            "alias_declaration": ("type", "name", None),
        },
        "call": ("call_expression", "function"),
        "imports": ["preproc_include"],
    },
    "java": {
        "definitions": {
            "method_declaration": ("method", "name", "parameters"),
            "constructor_declaration": ("method", "name", "parameters"),
            "class_declaration": ("type", "name", None),
            "interface_declaration": ("type", "name", None),
            "enum_declaration": ("type", "name", None),
        },
        "call": ("method_invocation", "name"),
        "imports": ["import_declaration"],
    },
}

#: 用于「名字」定位的节点类型（★ 处理 C 的嵌套 declarator）
_NAME_NODE_TYPES = {
    "identifier",
    "field_identifier",
    "type_identifier",
    "namespace_identifier",
    "operator_name",
    "destructor_name",
    "scoped_identifier",
    "qualified_identifier",
}


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _first_named(node: Node, field: str | None) -> Node | None:
    if not field:
        return None
    child = node.child_by_field_name(field)
    return child


def _dig_name(node: Node | None, src: bytes, depth: int = 5) -> str:
    """在子树里找出「名字」—— ★ 处理 C/C++ 的 declarator 嵌套。

    例：`function_definition > declarator: function_declarator > declarator: identifier`
    """
    if node is None or depth <= 0:
        return ""
    if node.type in _NAME_NODE_TYPES:
        return _text(node, src)
    field_child = node.child_by_field_name("declarator")
    if field_child is not None:
        got = _dig_name(field_child, src, depth - 1)
        if got:
            return got
    for child in node.named_children:
        if child.type in _NAME_NODE_TYPES:
            return _text(child, src)
        got = _dig_name(child, src, depth - 1)
        if got:
            return got
    return ""


def _callee_name(text: str) -> str:
    """从调用表达式里取出「被调用者」的**简单名**。

    ⚠ tree-sitter 是语法级的：`self.bar(x)` 拿到的是 `self.bar`，
      `ns::foo(x)` 拿到 `ns::foo`，`foo<int>(x)` 拿到 `foo<int>`。
      这里统一取【最后一段】—— ★ 宁可多连，也不要漏连：
      漏连 = 调用链断了（图失去价值）；多连 = 多一条待人工确认的边（`confidence=syntax` 已如实标注）。
    """
    t = " ".join(text.split())
    t = re.sub(r"<[^<>]*>", "", t)          # 去模板参数：foo<int> → foo
    t = t.replace("::", ".").replace("->", ".")
    t = t.rsplit(".", 1)[-1]                # 取最后一段
    t = re.sub(r"[()*&\[\]]", "", t)        # 去残留符号
    return t.strip()


#: Python：`from x.y import z` / `import x, y as z`
_PY_FROM_RE = re.compile(r"^\s*from\s+([\w\.]+)\s+import\b")
_PY_IMPORT_RE = re.compile(r"^\s*import\s+(.+)")
#: C / C++：`#include <stdio.h>` / `#include "a/b.h"`
_C_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]')
#: Java：`import java.util.List;` / `import static a.b.C.d;`
_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w\.\*]+)")


def _import_targets(text: str, lang: str) -> list[str]:
    """从导入 / 包含语句的**原文**里抽出目标列表。

    ⚠ 抽不出来就返回空 —— ❌ 不要猜（`codeparser/base.py` 的原则）。
    """
    t = " ".join(text.split())

    if lang == "python":
        m = _PY_FROM_RE.match(t)
        if m:
            return [m.group(1)]
        m = _PY_IMPORT_RE.match(t)
        if m:
            out = []
            for part in m.group(1).split(","):
                name = part.strip().split(" as ")[0].strip()
                if name:
                    out.append(name)
            return out
        return []

    if lang in ("c", "cpp"):
        m = _C_INCLUDE_RE.match(t)
        return [m.group(1)] if m else []

    if lang == "java":
        m = _JAVA_IMPORT_RE.match(t)
        return [m.group(1)] if m else []

    return []


class TreeSitterParser(Parser):
    """基于 tree-sitter 的语法级解析器。"""

    def __init__(self, lang: str):
        if lang not in _LANG_MODULES:
            raise ValueError(f"TreeSitterParser 不支持的语言：{lang}")
        if lang not in LANGS:
            raise ValueError(f"缺少语言定义（LANGS）：{lang}")

        self.lang = lang
        self._spec = LANGS[lang]
        self._ts_lang = Language(_LANG_MODULES[lang].language())
        self._parser = _TSParser(self._ts_lang)

    # ------------------------------------------------------------------

    def parse(self, source: bytes, path: str) -> ParseResult:
        result = ParseResult()

        try:
            tree = self._parser.parse(source)
        except Exception as exc:  # noqa: BLE001
            # ★ 失败不该让整个项目解析失败 —— 记错误、返回空结果
            result.errors.append(f"解析失败 {path}: {exc}")
            return result

        # ---- ① 文件节点（每文件一个，与 AsmSymbolParser 保持一致）----
        file_name = path.rsplit("/", 1)[-1]
        file_uid = f"file#{path}#{file_name}"
        result.nodes.append(
            ParsedNode(
                kind="file", name=file_name, file_path=path, line=1, lang=self.lang
            )
        )

        # ---- ② 遍历 AST 提取 ----
        try:
            self._walk(tree.root_node, source, path, file_uid, result)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"提取失败 {path}: {exc}")

        return result

    # ------------------------------------------------------------------

    def _walk(
        self,
        node: Node,
        src: bytes,
        path: str,
        file_uid: str,
        result: ParseResult,
        owner_uid: str | None = None,
    ) -> None:
        """遍历子树提取节点与边。

        ★ `owner_uid` = 「当前所在符号」的 uid（默认 = 文件）——
          这样**调用边就是「函数 → 函数」**，而不是「文件 → 函数」。
          ⚠ 这是图能不能用来"沿调用链读代码"的关键（README 的「做法 1」）。
        """
        spec = self._spec
        if owner_uid is None:
            owner_uid = file_uid

        # ---- 定义（函数 / 类型 / 宏 …）----
        child_owner = owner_uid  # 默认：子节点仍归当前符号
        definition = spec["definitions"].get(node.type)
        if definition is not None:
            kind, name_field, sig_field = definition
            name = _dig_name(_first_named(node, name_field), src)
            if name:
                signature = ""
                sig_node = _first_named(node, sig_field) if sig_field else None
                if sig_node is not None:
                    signature = _text(sig_node, src)[:500]

                parsed = ParsedNode(
                    kind=kind,
                    name=name,
                    file_path=path,
                    line=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    lang=self.lang,
                    signature=signature,
                    doc=self._leading_comment(node, src),
                    extra={"ts_type": node.type},
                )
                result.nodes.append(parsed)
                # ★ 文件 → 符号：包含边
                result.edges.append(
                    ParsedEdge(from_uid=file_uid, to_uid=parsed.uid, type="contains")
                )
                # ★ 进入这个定义后，其子树里的调用【归属它】
                child_owner = parsed.uid

        # ---- 调用 ----
        call_type, call_field = spec["call"]
        if node.type == call_type:
            callee = _first_named(node, call_field)
            if callee is not None:
                raw = _text(callee, src)
                simple = _callee_name(raw)
                if simple:
                    # ⚠ 跨文件调用此时无法确定目标文件 ⇒ ★ 延迟解析（见 base.py）
                    result.edges.append(
                        ParsedEdge(
                            from_uid=owner_uid,   # ★ 调用发生的所在符号
                            to_uid=f"unresolved#call#{simple}",
                            type="calls",
                            line=node.start_point[0] + 1,
                            confidence="syntax",
                            extra={"callee_raw": raw[:200]},
                        )
                    )

        # ---- 导入 / 包含 ----
        if node.type in spec.get("imports", []):
            for target in _import_targets(_text(node, src), self.lang):
                result.edges.append(
                    ParsedEdge(
                        from_uid=file_uid,
                        to_uid=f"unresolved#include#{target}",
                        type="includes" if self.lang in ("c", "cpp") else "imports",
                        line=node.start_point[0] + 1,
                        confidence="syntax",
                    )
                )

        for child in node.children:
            self._walk(child, src, path, file_uid, result, child_owner)

    # ------------------------------------------------------------------

    @staticmethod
    def _leading_comment(node: Node, src: bytes) -> str:
        """尽量取紧邻的上一行注释作为 `doc`（⚠ 尽力而为，取不到就空）。"""
        prev = node.prev_sibling
        if prev is None:
            return ""
        if prev.type in ("comment", "line_comment", "block_comment"):
            text = _text(prev, src)
            # 去掉注释符号，只留正文
            for prefix in ("///", "//!", "//", "#", "/*", "*", "*/"):
                text = text.replace(prefix, "")
            return text.strip()[:1000]
        return ""
