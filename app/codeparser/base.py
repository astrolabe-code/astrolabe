"""Astrolabe · 解析器：统一接口与产出结构

★ 归属：**公开版**源码（`/home/ma/astrolabe/app/`）——
  解析器与产出结构是 `S2.1` 认定的「**标准**」，**将来要开源**。
  ⚠ 企业版专属逻辑请放将来的 `enterprise/` 独立目录，❌ 不要写进本包。

--------------------------------------------------------------------------------
★★ 设计约束（JOB-MODEL.md J10.3）—— 这是本模块最重要的部分：

  ① 统一接口：`Parser.parse(source, path) -> ParseResult`
  ② ★ 语言 → 实现 走【注册表】（registry.py），替换即改一行
  ③ ★★ **ParseResult 必须【不暴露 tree-sitter 的节点类型】**
      —— 否则下游被绑死在 tree-sitter 上，自写的解析器（如汇编）就接不进来
  ④ ★★ `AsmSymbolParser` 的产出**必须与 `TreeSitterParser` 结构完全一致**
      —— 这是「将来能无缝替换」的成败关键（B116）

⚠ 另见：
  GRAPH-SCHEMA.md S2/S3 —— 节点 / 边的字段语义
  GRAPH-STORAGE.md G3.5 —— 三层标识（node_id / vid / uid）
--------------------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ============================================================ 节点

#: 节点 kind —— 与 `graph/models.py` 的枚举保持一致（GRAPH-SCHEMA.md S2）
NodeKind = Literal[
    "file", "dir",
    "function", "method", "type", "macro",
    "variable", "constant", "field",
]


@dataclass(slots=True)
class ParsedNode:
    """解析产出的一个节点。

    ★ 这些字段**直接对应** `GRAPH-SCHEMA.md` S2 的节点字段（图的写入方按此落库）。

    ⚠ 注意：**不含 `pkg_id` / `vid`** ——
      · `pkg_id` 是【导出时】由打包器发的号（WEBAPKG-SPEC）
      · `vid` 是【入库时】由 PG 发的号（B117）
      ⇒ 解析器只负责「这条记录是什么」，不负责「它编号几」
    """

    kind: NodeKind
    name: str
    file_path: str          # 相对路径，'/' 分隔
    line: int               # 1-based，★ 锚点的落点
    lang: str               # c / cpp / python / java / asm

    line_end: int | None = None
    qname: str = ""         # 限定名（C++/Java 的 ns::Class::method）
    signature: str = ""     # ★ 签名原文（人能读、便于 AI 理解；重载靠它区分）
    doc: str = ""           # 注释 / 文档串

    # ★ 扩展位（GRAPH-SCHEMA.md S1 / S10：语言特有信息）
    extra: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        """★ 人类可读标签（`<kind>#<path>#<名字>`）。

        ⚠ `uid` **允许偶发重复**（`B117`）—— 它只用于【展示与匹配】，
          ❌ **不得作为挂载依据**（挂载靠入库后的 `vid`）。
        """
        return f"{self.kind}#{self.file_path}#{self.name}"


# ============================================================ 边

#: 边 type —— 与 `graph/models.py` 的常量保持一致（GRAPH-SCHEMA.md S3）
EdgeType = Literal[
    "calls", "imports", "includes", "defines",
    "contains", "overrides", "implements",
]


@dataclass(slots=True)
class ParsedEdge:
    """解析产出的一条边。

    ⚠ `from_uid` / `to_uid` 是**延迟解析的引用**：解析单个文件时，
      目标节点可能还没被解析出来 —— 所以先记 `uid` 字符串，
      ★ 由「图写入方」在**全项目解析完成后**统一按 `uid` 解析成节点主键。
      （同文件内能确定的，也统一走这条路，保持一条路径、少一类 bug。）
    """

    from_uid: str
    to_uid: str
    type: EdgeType

    line: int | None = None          # 该关系发生的位置（如调用点）
    # ★ 语法级拿不到精确调用图时【如实标注】（GRAPH-SCHEMA.md S3）
    confidence: str = "syntax"

    extra: dict = field(default_factory=dict)


# ============================================================ 产出

#: 置信度（GRAPH-SCHEMA.md S3）—— ★ 语法级解析**绝不会**谎报为 semantic
Confidence = Literal["syntax", "semantic"]


@dataclass(slots=True)
class ParseResult:
    """★ 统一产出结构 —— **所有 Parser 实现都必须返回它**。

    ★★ 这是 `B116` 的成败关键：
       `TreeSitterParser`（C/C++/Python/Java）与 `AsmSymbolParser`（汇编）
       产出**同一种** `ParseResult` ⇒ ★ 下游消费代码**只写一份**。
    """

    nodes: list[ParsedNode] = field(default_factory=list)
    edges: list[ParsedEdge] = field(default_factory=list)

    # ★ 诊断信息（不落图，只用于日志 / 排查；⚠ 不要往这里塞业务数据）
    errors: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.nodes and not self.edges


# ============================================================ 接口

class Parser:
    """解析器接口（★ 按【图语义】定义，❌ 不暴露任何实现细节）。

    ⚠ 实现者必须遵守：
      · `parse()` **不得抛异常**给调用方 —— 失败应记入 `ParseResult.errors`
        （★ 一个文件解析失败，不该让整个项目解析失败）
      · 返回的 `ParseResult` **结构必须与其它实现完全一致**（`B116`）
    """

    #: 本实现支持的语言标识（如 "python" / "c" / "asm"）
    lang: str = ""

    def parse(self, source: bytes, path: str) -> ParseResult:
        """解析**单个文件**。

        Args:
            source: 文件内容（bytes —— ★ 让实现自己处理编码，避免上一层的解码歧义）
            path:   相对路径（用于生成 uid）

        Returns:
            ParseResult —— ★ 失败时返回带 `errors` 的空结果，**不抛异常**
        """
        raise NotImplementedError

    def parse_text(self, text: str, path: str) -> ParseResult:
        """便捷入口：字符串版本（内部转 bytes 后调 `parse`）。"""
        return self.parse(text.encode("utf-8"), path)
