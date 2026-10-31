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


def _callee_parts(node, callee, src: bytes, lang: str) -> tuple[str, str]:
    """★ 按**语法结构**取「接收者」和「被调用名」，⛔ 不靠切字符串 ⚠

    各语言的形态不同，一律从 tree-sitter 的字段上取：

    ```\n     python  call > function: attribute(object, attribute)   ⇒ a.run → ("a", "run")\n     java    method_invocation(object, name)                ⇒ a.run → ("a", "run")\n     cpp     call_expression > function: field_expression(argument, field) ⇒ p->f → ("p","f")\n             call_expression > function: qualified_identifier(scope, name) ⇒ ns::f → ("ns","f")\n     c/裸名  identifier                                       ⇒ f → ("", "f")\n ```\n
    ⚠ 只在**结构上确实有接收者**时才返回非空，返回空串表示"裸名"，
      后续按"名字全局唯一"判定 —— ⛔ 绝不从文本里猜（`a.run` 里 a 是变量还是类，
      字符串看不出来，AST 也只告诉你有 receiver，不告诉它是什么类型）。
    """
    # ---- Java：callee 是 name 字段，接收者在父节点的 object 上
    if node.type == "method_invocation":
        obj = node.child_by_field_name("object")
        name = _text(callee, src)
        return (_text(obj, src) if obj is not None else ""), name

    t = callee.type

    # ---- Python：a.run → attribute
    if t == "attribute":
        obj = callee.child_by_field_name("object")
        attr = callee.child_by_field_name("attribute")
        if obj is not None and attr is not None:
            return _text(obj, src), _text(attr, src)

    # ---- C++：p->f / p.f → field_expression
    if t == "field_expression":
        obj = callee.child_by_field_name("argument")
        fld = callee.child_by_field_name("field")
        if obj is not None and fld is not None:
            return _text(obj, src), _text(fld, src)

    # ---- C++：ns::f → qualified_identifier
    if t == "qualified_identifier":
        scope = callee.child_by_field_name("scope")
        name = callee.child_by_field_name("name")
        if scope is not None and name is not None:
            return _text(scope, src), _text(name, src)

    # ---- C++：foo<int>() → template_function
    if t == "template_function":
        name = callee.child_by_field_name("name")
        if name is not None:
            return "", _callee_name(_text(name, src))

    # ---- 其它：裸名（identifier / field_identifier / …）
    return "", _callee_name(_text(callee, src))


def _callee_name(text: str) -> str:
    """从调用表达式里取出「被调用者」的**简单名**。

    ⚠ 它现在只负责**把名字洗干净**（去模板参数、去残留符号），
      **不负责判断有没有接收者** —— 那件事由 `_callee_parts` 按 AST 字段做。

    ⚠★ 旧的注释写着「宁可多连也不要漏连」，与现在的口径**相反**：
      现在的判准是「宁可漏了，也不要错了」（所有者 2026-10-30），
      所以名字取不准时**不连**，而不是硬连一条待确认的边。
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
        #: 限定名分隔符：C/C++ 用 `::`，其余用 `.`
        self._sep = "::" if lang in ("c", "cpp") else "."
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
        file_node = ParsedNode(
            kind="file", name=file_name, file_path=path, line=1, lang=self.lang
        )
        # ★★ `file_uid` 必须**从节点本身取**，⛔ 不能手拼 ⚠
        #   uid 的格式里带行号（`…@1`），手拼就会和 `by_uid` 索引对不上
        #   ⇒ 所有「文件 → 顶层符号」的 contains 边会整批失配（实测踩到）
        file_uid = file_node.uid
        result.nodes.append(file_node)

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
        scope: tuple[str, ...] = (),
    ) -> None:
        """遍历子树提取节点与边。

        ★ `owner_uid` = 「当前所在符号」的 uid（默认 = 文件）——
          这样**调用边就是「函数 → 函数」**，而不是「文件 → 函数」。
          ⚠ 这是图能不能用来"沿调用链读代码"的关键（README 的「做法 1」）。

        ★★ `scope` = 当前所处的**作用域名字栈**（`("A",)` 表示「在类 A 里面」）⚠
          用途有三个（对标 GitNexus 的 `HAS_METHOD` / 限定名那套）：
            · 写进 `qname` ⇒ 界面上能显示 `A.run`，而不是两个都叫 `run`
            · 写进 `uid`   ⇒ 同一文件里同名方法不再撞车
            · 包含边指向**父符号**（类 → 方法），而不是一律指向文件
          ⛔ 不参与 `vid` 计算 ⇒ 已写笔记的锚点不受影响 ✅
        """
        spec = self._spec
        if owner_uid is None:
            owner_uid = file_uid

        # ---- 定义（函数 / 类型 / 宏 …）----
        child_owner = owner_uid  # 默认：子节点仍归当前符号
        defined_name = ""        # ★ 本层识别出的定义名（供子作用域用，⛔ 不存实例状态）
        definition = spec["definitions"].get(node.type)
        if definition is not None:
            kind, name_field, sig_field = definition

            # ★★ C/C++ 的 struct/union/enum：**只有带 body 才算定义** ⚠
            #   `int f(struct S *p)` 里的 `struct S` 只是一次引用，
            #   不拦的话会多出一个 `f::S` 节点（实测：同一个 S 出现两次，qname 还是错的）
            if (
                self.lang in ("c", "cpp")
                and node.type in ("struct_specifier", "union_specifier", "enum_specifier")
                and node.child_by_field_name("body") is None
            ):
                name = ""
            else:
                name = _dig_name(_first_named(node, name_field), src)
            if name:
                signature = ""
                sig_node = _first_named(node, sig_field) if sig_field else None
                if sig_node is not None:
                    signature = _text(sig_node, src)[:500]

                # ★ 限定名：`A.run`（python/java）或 `ns::Class::method`（cpp）
                qname = self._sep.join(scope + (name,)) if scope else name

                parsed = ParsedNode(
                    kind=kind,
                    name=name,
                    qname=qname,
                    file_path=path,
                    line=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    lang=self.lang,
                    signature=signature,
                    # ⚠★★ `B176`：此处曾传 `doc=self._leading_comment(node, src)` ——
                    #   ★ 那是【逐字的注释正文】，★ 是节点里唯一属于"源码内容"的东西 ⚠
                    #   ⇒ ★ 已删除（连同下面那个 `_leading_comment` 方法）✅
                    extra={"ts_type": node.type},
                )
                result.nodes.append(parsed)
                # ★★ 包含边：**父符号 → 子符号**（类连方法），不再一律连文件 ⚠
                #    顶层符号的 owner 就是文件 ⇒ 文件只在最外层出现
                result.edges.append(
                    ParsedEdge(from_uid=owner_uid, to_uid=parsed.uid, type="contains")
                )
                # ★ 进入这个定义后，其子树里的调用【归属它】
                child_owner = parsed.uid
                defined_name = name

        # ---- 调用 ----
        call_type, call_field = spec["call"]
        if node.type == call_type:
            callee = _first_named(node, call_field)
            if callee is not None:
                raw = _text(callee, src)
                # ★★ 接收者与名字从 **AST 字段**取（不是切字符串）
                recv, simple = _callee_parts(node, callee, src, self.lang)
                if simple:
                    # ★ 有接收者才记 qcall（解析阶段能按作用域精确匹配）；
                    #   裸名按 `call#名字` 走"全局唯一"那条判准
                    ref = (
                        f"unresolved#qcall#{recv}{self._sep}{simple}"
                        if recv
                        else f"unresolved#call#{simple}"
                    )
                    result.edges.append(
                        ParsedEdge(
                            from_uid=owner_uid,   # ★ 调用发生的所在符号
                            to_uid=ref,
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

        # ★ 进入定义体后，作用域多一层（`A` → `A.run`）
        child_scope = scope
        if defined_name:
            # 本层识别出一个定义 ⇒ 它的名字进作用域（`A` → 子节点在 `A` 里）
            child_scope = scope + (defined_name,)

        for child in node.children:
            self._walk(child, src, path, file_uid, result, child_owner, child_scope)

    # ------------------------------------------------------------------

    # ⚠★★ `B176`（2026-10-12）：**本处曾有一个 `_leading_comment()` 静态方法** ——
    #   ★ 它的唯一用途是给 `ParsedNode.doc` 取「紧邻的上一行注释正文」。
    #   ★★ 所有者裁定「节点里只保存函数签名 + 它所在的文件」⇒ ★ 注释属于**逐字的源码内容** ⚠
    #   ⇒ ★ **连同 `doc` 一起删除**：解析产物里不再有任何逐字代码 ✅
    #   ★ 依据：`docs/backend-decisions.md` `B176`
