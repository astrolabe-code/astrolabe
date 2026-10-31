#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★ **C 语言**的处理口径（配合 `queries/c.scm`）

```\n def.function → function      def.struct/union/enum/typedef → type\n def.macro    → macro         inc.path → unresolved#include#<path>\n ```\n *
## 调用的三种命运

```\n direct                 ⇒ call#名字        按"全局唯一"判（C 没有模块系统，靠名字）\n ptr_member / member    ⇒ qcall#recv.name  带接收者；解析端按作用域/收窄判\n 解引用 / 下标 / 转换后   ⇒ **不建边**（目标是变量，静态看不出指向哪个函数）\n ```\n *
⚠ 最后一条是"宁可漏"：`(*fp)(a)` 里的 `fp` 是函数指针变量，
  把它连到某个叫 `fp` 的函数上是**错的**，所以宁可不连，只计数。
"""

from __future__ import annotations

from .base import LangSpec


class CSpec(LangSpec):
    language = "c"
    query_file = "c.scm"
    sep = "::"            # C 没有命名空间，但 struct 里的成员名按 `::` 拼更一致
    import_edge_type = "includes"

    def_kinds = {
        "def.function": "function",
        "def.struct": "struct",
        "def.union": "union",
        "def.enum": "enum",
        "def.typedef": "typedef",
        "def.macro": "macro",
    }

    def call_ref(self, shape: str, name: str, receiver: str) -> str | None:
        if shape == "direct":
            return f"unresolved#call#{name}"
        if shape in ("ptr_member", "member"):
            if not receiver:
                return None
            # C 的成员访问用 `.`/`->`，统一成 `.` 交给解析端拼 qname
            return f"unresolved#qcall#{receiver}.{name}"
        # deref1/2/3、deref1_ptr_member、deref1_member、subscript、cast
        # ⇒ 目标是变量/表达式，不是符号 ⇒ 不建边（计入 stats.fptrCalls）
        return None

    # ------------------------------------------------------------------

    def def_node_types(self) -> tuple[str, ...]:
        return ("function_definition",)
