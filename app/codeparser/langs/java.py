#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★ **Java**的处理口径（配合 `queries/java.scm`）

```\n class/interface/enum/record → type     method/constructor → method\n a.m() / this.m() / Class.m() → qcall   裸 m() → call\n ```\n *
⚠ 与旧的遍历式实现保持一致：Java 的方法类型是 `method`（kinds.py 里有 id=4），
  而 Python/C++ 的方法仍是 `function` —— 这是历史口径，暂不改（改了会让
  存量项目的节点类型漂移）。
"""

from __future__ import annotations

from .base import LangSpec


class JavaSpec(LangSpec):
    language = "java"
    query_file = "java.scm"
    sep = "."

    def_kinds = {
        "def.class": "class",
        "def.interface": "interface",
        "def.enum": "enum",
        "def.record": "record",
        "def.method": "method",
    }

    def call_ref(self, shape: str, name: str, receiver: str) -> str | None:
        if shape == "invocation":
            if receiver:
                return f"unresolved#qcall#{receiver}.{name}"
            return f"unresolved#call#{name}"
        return None

    def def_node_types(self) -> tuple[str, ...]:
        return (
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
            "method_declaration",
            "constructor_declaration",
        )

    def call_parts(self, node, src: bytes, caps: dict, cname: str) -> tuple[str, str]:
        """★ `method_invocation` 的接收者在 `object` 字段，名字在 `name` 字段

        ⚠ 和 C 的 `field_expression` 一样，必须**从字段取**，⛔ 不能切文本。
          没有 object 就是裸调用（`m()`）。
        """
        return self.invocation_parts(node, src)

    @staticmethod
    def invocation_parts(node, src: bytes) -> tuple[str, str]:
        """★ `method_invocation` 的接收者在 `object` 字段，名字在 `name` 字段

        ⚠ 和 C 的 `field_expression` 一样，必须**从字段取**，⛔ 不能切文本。
        """
        obj = node.child_by_field_name("object")
        name = node.child_by_field_name("name")
        return (
            obj.text.decode("utf-8", "ignore").strip() if obj is not None else "",
            name.text.decode("utf-8", "ignore").strip() if name is not None else "",
        )
