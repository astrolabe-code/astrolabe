"""Astrolabe · 解析器：语言注册表

★ 归属：**公开版**源码。

★★ 依据 JOB-MODEL.md J10.3 ②：
   语言 → 实现的映射**只在这一处**维护 —— ★ **替换实现即改一行**。

★ 将来用户自写汇编语法（按 tree-sitter 规则）时，只需：
     · 写出语法包并安装
     · 把下面 "asm" 那一行的实现换掉
   ⇒ ⚠ **不需要修改任何下游代码**（这是 B116 的验收方式）
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import Parser

log = logging.getLogger("astrolabe.codeparser")

#: 扩展名 → 语言标识
#: ⚠ `.S`（大写，含预处理的汇编）与 `.s` 在 Linux 内核里都常见
EXT_TO_LANG: dict[str, str] = {
    # C
    ".c": "c",
    ".h": "c",
    # C++
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    # Python
    ".py": "python",
    ".pyi": "python",
    # Java
    ".java": "java",
    # 汇编（B116 方案 A：轻量符号提取）
    ".s": "asm",
    ".S": "asm",
    ".asm": "asm",
}


def detect_lang(path: str) -> str | None:
    """按扩展名判断语言；不认识返回 None（★ 调用方应跳过该文件，❌ 不要报错）。"""
    suffix = Path(path).suffix
    if suffix in EXT_TO_LANG:
        return EXT_TO_LANG[suffix]
    return EXT_TO_LANG.get(suffix.lower())


def build_parsers() -> dict[str, Parser]:
    """构造「语言 → Parser 实例」的注册表。

    ★★ 这是本模块唯一的职责 —— **改这里一行，就换了某语言的实现**。
    """
    # 延迟导入：避免未安装的语言包导致整个模块 import 失败
    from .asm import AsmSymbolParser

    parsers: dict[str, Parser] = {}

    # ---- tree-sitter 系列（C / C++ / Python / Java）----
    #
    # ★★ `B132`：**这里曾经是静默降级的，代价很大** ——
    #   worker 容器跑的是旧镜像（tree-sitter 没装）⇒ 四种语言**全部注册失败**，
    #   却**一条日志都没有**，唯一症状是作业报「扫描到 56 个候选、跳过原因：无解析器:python」。
    #   ⇒ ★ 结论：**能力缺失必须可见**（大声说出来），❌ 不要静默降级。
    try:
        from .treesitter import TreeSitterParser
    except ImportError as exc:
        log.warning(
            "tree-sitter 不可用 ⇒ C / C++ / Python / Java 解析器【全部未注册】（只剩汇编）：%s", exc
        )
    else:
        for lang in ("c", "cpp", "python", "java"):
            try:
                parsers[lang] = TreeSitterParser(lang)
            except Exception as exc:  # noqa: BLE001  —— 某一语言坏掉不该拖累其它语言
                log.warning("语言 %s 的 tree-sitter 语法包不可用，已跳过：%s", lang, exc)

    # ---- 汇编：★ 一期用轻量符号提取（B116 方案 A）----
    parsers["asm"] = AsmSymbolParser()

    # ★★★ 将来：自写汇编语法就绪后，替换下面这一行即可
    #   from .treesitter import TreeSitterParser
    #   parsers["asm"] = TreeSitterParser("asm")

    return parsers
