"""Astrolabe · 解析器：汇编（轻量符号提取）

★ 归属：**公开版**源码。

★★ 依据 `B116`（方案 A）：
   一期**不做指令级解析**，只做**符号提取**；❌ **不建汇编内部调用图**。

   ★ 理由：读内核的人真正关心的是「**入口点在哪**」「**汇编与 C 的边界在哪**」，
     而不是汇编内部的跳转 —— 后者大多是**宏展开**的产物，价值低。

★★★ 硬约束（B116 ③）：
   ⚠ 本实现的产出**必须与 `TreeSitterParser` 结构完全一致**（同为 `ParseResult`），
     否则将来换成自写语法时**接不进来**。

⚠ 将来升级路径（`B116`）：用户按 tree-sitter 规则自写语法 ⇒
  在 `registry.py` 把 "asm" 那一行换成 `TreeSitterParser("asm")` **即可，下游不改**。
"""

from __future__ import annotations

import re

from .base import ParsedEdge, ParsedNode, ParseResult, Parser

# ===========================================================================
# ★ 符号提取规则（面向「入口点」与「跨语言边界」）
#
# ⚠ 一期只覆盖最常见的几种；`S11` 类待定项 —— 等有真实内核源码时再补全。
# ===========================================================================

#: 形如 ENTRY(name) / GLOBAL(name) / SYMBOL_NAME(name) / SYM_FUNC_START(name)
_SYMBOL_MACROS = re.compile(
    r"^\s*(?:"
    r"ENTRY|ENDPROC|GLOBAL|SYMBOL_NAME|"
    r"SYM_FUNC_START|SYM_FUNC_END|SYM_CODE_START|SYM_CODE_END|"
    r"SYM_DATA_START|SYM_DATA_END|"
    r"FUNC_START|FUNC_END|"
    r"ASM_FUNC"
    r")\s*\(?\s*([A-Za-z_][A-Za-z0-9_.$]*)?",
    re.MULTILINE,
)

#: EXPORT_SYMBOL(name) / EXPORT_SYMBOL_GPL(name) —— ★ 与 C 的边界
_EXPORT_SYMBOL = re.compile(
    r"\bEXPORT_SYMBOL(?:_GPL)?\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
)

#: 标签定义：^name:（★ 用作「可能的入口点」，但置信度低于宏）
_LABEL = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.$]*)\s*:", re.MULTILINE)

#: #include "xxx.h" / #include <xxx.h> —— ★ 与 C 的边界（汇编含预处理时）
_INCLUDE = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.MULTILINE)


class AsmSymbolParser(Parser):
    """汇编符号提取器（★ 轻量 —— 不做指令级解析）。"""

    lang = "asm"

    def parse(self, source: bytes, path: str) -> ParseResult:
        result = ParseResult()

        try:
            text = source.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001  —— 理论上不会发生（errors=replace）
            result.errors.append(f"解码失败 {path}: {exc}")
            return result

        # ---- ① 文件节点（与其它语言一致：每文件一个）----
        result.nodes.append(
            ParsedNode(
                kind="file",
                name=path.rsplit("/", 1)[-1],
                file_path=path,
                line=1,
                lang=self.lang,
            )
        )

        seen: set[str] = set()

        def _add_symbol(name: str, line: int, extra: dict | None = None) -> None:
            """★ 去重：同名符号只记一次（汇编里同一个宏可能多次出现）。"""
            if not name or name in seen:
                return
            seen.add(name)
            result.nodes.append(
                ParsedNode(
                    kind="function",
                    name=name,
                    file_path=path,
                    line=line,
                    lang=self.lang,
                    extra=extra or {},
                )
            )

        # ---- ② 入口点宏（★ 这是最可靠的一类）----
        for m in _SYMBOL_MACROS.finditer(text):
            name = m.group(1)
            if not name:
                continue
            line = text.count("\n", 0, m.start()) + 1
            _add_symbol(name, line, {"asm_source": "macro"})

        # ---- ③ EXPORT_SYMBOL（★ 汇编 ↔ C 的边界）----
        for m in _EXPORT_SYMBOL.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            result.nodes.append(
                ParsedNode(
                    kind="function",
                    name=name,
                    file_path=path,
                    line=line,
                    lang=self.lang,
                    extra={"asm_source": "export_symbol"},
                )
            )

        # ---- ④ 标签（置信度较低 —— 单独标注，便于将来过滤）----
        for m in _LABEL.finditer(text):
            name = m.group(1)
            if name.startswith(".") or name in seen:
                continue  # 本地标签（.Lxx）不算入口点
            line = text.count("\n", 0, m.start()) + 1
            _add_symbol(name, line, {"asm_source": "label"})

        # ---- ⑤ #include：★ 建「包含」边（与 C 的边界）----
        for m in _INCLUDE.finditer(text):
            target = m.group(1)
            line = text.count("\n", 0, m.start()) + 1
            result.edges.append(
                ParsedEdge(
                    from_uid=f"file#{path}#{path.rsplit('/', 1)[-1]}",
                    to_uid=f"unresolved#include#{target}",  # ★ 延迟解析（见 base.py）
                    type="includes",
                    line=line,
                    confidence="syntax",
                )
            )

        # ---- ⑥ 文件 → 符号 的包含边 ----
        file_uid = f"file#{path}#{path.rsplit('/', 1)[-1]}"
        for node in result.nodes:
            if node.kind == "function":
                result.edges.append(
                    ParsedEdge(from_uid=file_uid, to_uid=node.uid, type="contains")
                )

        return result
