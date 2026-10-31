#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **一种语言一个处理文件** —— 这里定义那份"契约"

## 所有者原话（逐字，2026-10-31）

> 「呢这不能查询语句一个文件呀，配套的处理文件也要一个文件呀。
>   这样改坏了一种语言的处理，其他不崩呀。」

## 拆分方式

```
 queries/<lang>.scm     只描述「长什么样」（有限枚举，不下钻）
 langs/<lang>.py        只描述「取到之后算什么」（种类、怎么拼 ref）
 ```

⚠★ 铁律：**改 C 只动 c.scm + c.py**，另外三种语言一个字节都不碰。
  ⇒ 一个语言坏了，只是它自己退回遍历式解析器，⛔ 不许拖累别的语言。

## 子类要填的（都有默认值，只填需要改的）

```
 language / query_file   必填
 def_kinds               捕获名 → 节点种类
 sep                     限定名分隔符（python/java "."，c/cpp "::"）
 call_ref(shape, name, receiver)   一次调用怎么变成待解析的 ref
 call_parts(node, src, caps, cname) 从哪取"接收者 + 名字"（默认读查询捕获）
 def_scope(cname, caps, src)       定义自带的作用域前缀（如 `int C::f()` 的 C）
 import_targets(text)              一段 import 文本 → 目标列表
```

⚠★ 全类都**不做递归**：作用域靠"沿 parent 上溯"，名字靠查询捕获或字段，
  没有一处"往下遍历子树找东西"。
"""

from __future__ import annotations


class LangSpec:
    """一种语言的"口径"—— 子类只填与别人不同的部分"""

    #: 语言名（与 registry 里的键一致）
    language: str = ""
    #: 查询文件名（`queries/<query_file>`）
    query_file: str = ""

    #: 限定名分隔符：python/java 用 `.`，c/cpp 用 `::`
    sep: str = "."

    #: 定义捕获名 → 节点种类：`"def.function" -> "function"`
    def_kinds: dict[str, str] = {}

    #: 导入边用哪个类型名
    import_edge_type: str = "imports"

    # ---------------------------------------------------------------- 调用

    def call_parts(self, node, src: bytes, caps: dict, cname: str) -> tuple[str, str]:
        """从查询捕获里取「接收者」和「被调用名」

        ⚠ 默认就按捕获名读（`@call.x.receiver` / `@call.x.name`）。
          需要按 AST 字段取的（比如 Java 的 `method_invocation`）自己覆盖。
        """
        name_nodes = caps.get(f"{cname}.name") or []
        recv_nodes = caps.get(f"{cname}.receiver") or []
        name = name_nodes[0].text.decode("utf-8", "ignore").strip() if name_nodes else ""
        recv = recv_nodes[0].text.decode("utf-8", "ignore").strip() if recv_nodes else ""
        return recv, name

    def call_ref(self, shape: str, name: str, receiver: str) -> str | None:
        """把一次调用变成待解析的 ref

        返回 `None` 表示**这条调用不产生边**（目标是变量，静态看不出指向谁）。
        """
        raise NotImplementedError

    # ---------------------------------------------------------------- 定义

    def def_name(self, cname: str, node, src: bytes) -> str:
        """定义名不由 `.name` 捕获给出时的兜底（⚠ 默认没有）

        ★ C 曾在这里沿 declarator 链迭代取名，能把 `int (*f(int))(void)` 认出来；
          但那等于"通用下钻"，与"有限枚举"的原则相反，已删除。
          不常见的声明形态**主动放弃**，用户真要看就在改图里手补。
        """
        return ""

    @staticmethod
    def clean_type_name(text: str) -> str:
        """`Base<T>` → `Base`；`::std::string` → `std::string`

        ⚠ 只是名字清洗，⛔ 不参与结构判断（基类名带模板参数时，qname 匹配会对不上）
        """
        t = text.strip()
        if "<" in t:
            t = t.split("<", 1)[0].strip()
        return t.lstrip(":")

    def signature(self, node, src: bytes) -> str:
        """★ 函数/类型声明的那一行（**给读源码的人看**，不是给机器用）

        取「节点起点 → body 起点」这段文本：C 得到 `static int f(int a)`，
        Python 得到 `def f(a, b) -> int`，Java 得到 `public void run(int x)`。

        ⚠ 只做文本切片（一次），⛔ 不遍历子树、不进 canonical、不参与任何判定。
        """
        body = node.child_by_field_name("body")
        end = body.start_byte if body is not None else node.end_byte
        raw = src[node.start_byte:end].decode("utf-8", "ignore")
        return " ".join(raw.split())[:200]

    def def_scope(self, cname: str, caps: dict, src: bytes) -> str:
        """定义自带的作用域前缀（`int C::f() {}` 里的 `C`）

        ⚠ 与"父级作用域"不同：父级靠 node.parent 上溯，这里只是名字里自带的。
        """
        nodes = caps.get(f"{cname}.scope") or []
        return nodes[0].text.decode("utf-8", "ignore").strip() if nodes else ""

    # ---------------------------------------------------------------- 导入

    def import_targets(self, text: str) -> list[str]:
        """一段 import 语句 → 目标列表（默认交给 treesitter 里的现成解析）"""
        try:
            from ..treesitter import _import_targets

            return list(_import_targets(text, self.language))
        except Exception:  # noqa: BLE001
            return []

    def def_node_types(self) -> tuple[str, ...]:
        """哪些 AST 节点类型算"定义一个作用域"（仅作说明用，解析走 parent 链）"""
        return ()
