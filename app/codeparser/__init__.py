"""Astrolabe · 解析器（codeparser）

★ 归属：**公开版**源码（`/home/ma/astrolabe/app/`）——
  解析器与产出结构是 `S2.1` 认定的「**标准**」，**将来要开源**。
  ⚠ 企业版专属逻辑请放将来的 `enterprise/` 独立目录。

★ 对外只暴露这几样：接口、产出结构、注册表。
  ⚠ 下游【不要】直接 import `treesitter` / `asm` ——
     那是实现细节，换掉实现时下游不该受影响（JOB-MODEL.md J10.3 ④）。
"""

from .base import ParseResult, ParsedEdge, ParsedNode, Parser
from .registry import build_parsers, detect_lang

__all__ = [
    "Parser",
    "ParseResult",
    "ParsedNode",
    "ParsedEdge",
    "build_parsers",
    "detect_lang",
]
