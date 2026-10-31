#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★ **C++**的处理口径（配合 `queries/cpp.scm`）

```\n function → function     class/struct/union/enum → type\n namespace → module      macro → macro\n obj.f() / p->f() / ns::f() → qcall（分隔符用 `::`）\n ```\n *
⚠ 与 c.py 同一口径：**罕见声明符主动放弃**，不写通用下钻。
"""

from __future__ import annotations

from .base import LangSpec


class CppSpec(LangSpec):
    language = "cpp"
    query_file = "cpp.scm"
    #: C++ 的限定名分隔符
    sep = "::"
    import_edge_type = "includes"

    def_kinds = {
        "def.function": "function",
        "def.class": "class",
        "def.struct": "struct",
        "def.union": "union",
        "def.enum": "enum",
        "def.typedef": "typedef",
        "def.namespace": "module",
        "def.alias": "typedef",
        "def.operator": "function",
        "def.macro": "macro",
    }

    def def_name(self, cname: str, node, src: bytes) -> str:
        """★ 转换运算符的名字：`operator <类型>`

        ⚠ 只沿字段取（declarator.type），⛔ 不遍历子树 —— 与"不下钻"一致。
        """
        if cname != "def.operator":
            return ""
        decl = node.child_by_field_name("declarator")
        typ = decl.child_by_field_name("type") if decl is not None else None
        if typ is None:
            return ""
        return "operator " + typ.text.decode("utf-8", "ignore").strip()

    @staticmethod
    def _strip_template(name: str) -> str:
        """`f<int>` → `f`（名字清洗，⛔ 不涉及结构判断）

        ⚠ `ns::f<int>()` 的 name 字段是 template_function，文本带模板参数；
          不剥掉的话 qname 匹配永远对不上。
        """
        return name.split("<", 1)[0].strip()

    def call_parts(self, node, src: bytes, caps: dict, cname: str) -> tuple[str, str]:
        recv, name = super().call_parts(node, src, caps, cname)
        return recv, self._strip_template(name)

    def call_ref(self, shape: str, name: str, receiver: str) -> str | None:
        if shape in ("direct", "template"):
            # ★ `f<int>()` 是**直接调用**（只是名字带模板参数），不是函数指针
            if not receiver:
                return f"unresolved#call#{name}"
            return f"unresolved#qcall#{receiver}::{name}"
        if shape in ("member", "qualified", "member_template"):
            if not receiver:
                return None
            return f"unresolved#qcall#{receiver}::{name}"
        return None

    def def_node_types(self) -> tuple[str, ...]:
        return ("function_definition", "class_specifier", "struct_specifier", "namespace_definition")
