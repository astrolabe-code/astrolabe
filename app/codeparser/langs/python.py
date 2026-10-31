#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★ **Python**的处理口径（配合 `queries/python.scm`）

```\n def.function → function     class → type\n self.f()     → qcall#self.f   ⇒ 解析端用所在类补全\n a.f()        → qcall#a.f      ⇒ 不知道 a 的类型，靠"名字唯一/收窄"判\n f()          → call#f\n ```\n"""

from __future__ import annotations

from .base import LangSpec


class PythonSpec(LangSpec):
    language = "python"
    query_file = "python.scm"
    sep = "."

    def_kinds = {
        "def.function": "function",
        "def.class": "class",
    }

    def call_ref(self, shape: str, name: str, receiver: str) -> str | None:
        if shape == "direct":
            return f"unresolved#call#{name}"
        if shape == "member":
            if not receiver:
                return None
            return f"unresolved#qcall#{receiver}.{name}"
        return None

    def def_node_types(self) -> tuple[str, ...]:
        return ("function_definition", "class_definition")
