"""Astrolabe · 解析器：目录扫描与批量解析

★ 归属：**公开版**源码。

★ 职责：走目录 → 过滤 → 逐文件解析 → 汇总成一个 `ParseResult`。

⚠ 分层纪律（ARCHITECTURE.md A3）—— 本模块**只做解析**：
   · ❌ 不落库（那是「图写入方」的事，见 `graph/writer.py`）
   · ❌ 不判权限 / 不判项目归属（那是 ① Web 层的事）
   · ❌ 不拉远程仓库（一期用本地目录；将来由 ② 作业层负责拉取，B109）
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .base import ParseResult
from .registry import build_parsers, detect_lang

#: ★ 排除目录（沿用旧设计 `backend-parse-flow-current.md` §3.2 的清单）
EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn",
        "node_modules", "venv", ".venv", "env", "site-packages",
        "__pycache__", "dist", "build", ".cache", ".idea", ".vscode",
        ".mypy_cache", ".pytest_cache", ".tox", ".eggs",
        # ⚠ 第三方代码：一期跳过（将来可开成选项）
        "vendor", "third_party", "thirdparty",
    }
)

#: 单文件上限 —— ⚠ 防止一个巨型生成文件拖垮整个项目解析
MAX_FILE_BYTES = 2 * 1024 * 1024

#: 单项目文件数上限 —— ⚠ 防止误指到一个巨型仓库
DEFAULT_MAX_FILES = 5000
#: ★★ 硬性预算（防恶意仓库 / 防极端输入，网页版尤其需要）⚠
#: 任何一个超了都**停下来并记原因**，⛔ 不能无限期耗着
DEFAULT_MAX_SECONDS = 120.0            # 墙钟时间
DEFAULT_MAX_TOTAL_BYTES = 256 << 20    # 累计读取 256MB
DEFAULT_MAX_DEPTH = 64                 # 目录嵌套深度（防病态结构）


def _human_bytes(n: int) -> str:
    """把字节数说成人话（100000 → 98KB）"""
    if n >= 1 << 20:
        return f"{n / (1 << 20):.0f}MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f}KB"
    return f"{n}B"


@dataclass(slots=True)
class ScanStats:
    """扫描与解析的统计（★ 用于进度显示与诊断，不进图）。"""

    files_seen: int = 0
    files_parsed: int = 0
    files_skipped: int = 0
    by_lang: dict[str, int] = field(default_factory=dict)
    skip_reasons: dict[str, int] = field(default_factory=dict)
    #: ★ 达到预算（时间/文件数/累计字节）而提前停止的原因；空串 = 正常跑完
    #: ⚠ 它**不是错误**：截断说明图可能不完整，但不代表解析失败，
    #:   更不能因此禁止用户写笔记（两者语义完全不同）
    stop_reason: str = ""

    def skip(self, reason: str) -> None:
        self.files_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


def scan_and_parse(
    root: str | Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    extra_excludes: set[str] | None = None,
    on_file: Callable[[int, int, str], None] | None = None,
    accept_dir: Callable[[str], bool] | None = None,
    accept_file: Callable[[str], bool] | None = None,
    max_seconds: float | None = DEFAULT_MAX_SECONDS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> tuple[ParseResult, ScanStats]:
    """扫描目录并逐文件解析。

    Args:
        root: 项目根目录（★ 调用方负责确认它存在且可读）
        max_files: 文件数上限（超出即停止，并把原因记进 `errors`）
        extra_excludes: 追加的排除目录名
        on_file: 每解析一个文件后的回调 `(已完成, 总数, 相对路径)` —— 供作业回写进度
        accept_dir: 可选，`(相对路径) -> bool`；返回 False 的目录整棵跳过
        accept_file: 可选，`(相对路径) -> bool`；返回 False 的文件跳过
        max_seconds: 墙钟预算；超时即停（`None` = 不限，⚠ 只在测试里这么用）
        max_total_bytes: 累计读取上限（防"很多个中等文件"式的耗尽）
        max_depth: 目录嵌套深度上限（防病态深目录）

    ⚠★ 三个预算都是**硬约束**：恶意仓库可以构造几十万文件、GB 级单文件、
      深层嵌套或慢速挂载点，让解析一直耗着。任何一项超限都立刻停并写进
      `errors`（同时出现在 `ScanStats` 的截断原因里），⛔ 不允许无限期运行。

    Returns:
        `(汇总的 ParseResult, ScanStats)`

    ⚠ **本函数不抛异常** —— 单个文件失败只记进 `result.errors`，
      因为「一个文件坏了」不该让整个项目解析失败。
    """
    root_path = Path(root).resolve()
    merged = ParseResult()
    stats = ScanStats()

    if not root_path.is_dir():
        merged.errors.append(f"不是目录：{root}")
        return merged, stats

    excludes = EXCLUDE_DIRS | (extra_excludes or set())
    t_end = (time.monotonic() + max_seconds) if max_seconds else None
    stop_reason = ""

    # ---------------------------------------------------------------- ① 收集候选
    candidates: list[tuple[Path, str]] = []  # (绝对路径, 相对路径)
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root_path):
        # ★ 原地修改 dirnames ⇒ os.walk 不会进入这些目录（比事后过滤高效得多）
        dirnames[:] = [d for d in dirnames if d not in excludes]

        # ★ 深度上限：超过就直接不再往下走（`os.walk` 是自顶向下，剪掉即可）
        depth = len(Path(dirpath).relative_to(root_path).parts)
        if depth >= max_depth:
            dirnames[:] = []

        # ★★ 外部可插拔的目录判定（个人版用它接 `.gitignore` / 硬链接 / 扩展名白名单）⚠
        if accept_dir is not None:
            kept = []
            for d in dirnames:
                rel_d = str(Path(dirpath, d).relative_to(root_path)).replace("\\", "/")
                if accept_dir(rel_d):
                    kept.append(d)
            dirnames[:] = kept
        for filename in sorted(filenames):
            # ★ 每处理一个文件就查一次时间（⛔ 不能每 1000 个才查：单目录几万文件时查不到）
            if t_end is not None and time.monotonic() > t_end:
                stop_reason = f"超过时间预算 {max_seconds:g}s"
                break
            abs_path = Path(dirpath, filename)
            rel = str(abs_path.relative_to(root_path)).replace("\\", "/")
            if accept_file is not None and not accept_file(rel):
                continue
            if detect_lang(rel) is None:
                continue
            candidates.append((abs_path, rel))
            if len(candidates) >= max_files:
                truncated = True
                break
        if truncated or stop_reason:
            break

    if truncated:
        stats.stop_reason = f"文件数达到上限 {max_files}，其余已跳过"
    if stop_reason:
        stats.stop_reason = f"{stop_reason}，其余已跳过"
    stats.files_seen = len(candidates)

    # ---------------------------------------------------------------- ② 逐文件解析
    parsers = build_parsers()
    total = len(candidates)

    read_bytes = 0
    for idx, (abs_path, rel) in enumerate(candidates, start=1):
        # ★ 解析阶段同样要随时能停：单个文件也可能极慢
        if t_end is not None and time.monotonic() > t_end:
            stats.stop_reason = f"解析超过时间预算 {max_seconds:g}s，剩余 {total - idx + 1} 个文件未处理"
            break
        lang = detect_lang(rel)
        parser = parsers.get(lang) if lang else None
        if parser is None:
            stats.skip(f"无解析器:{lang}")
            continue

        try:
            if abs_path.stat().st_size > MAX_FILE_BYTES:
                stats.skip("文件过大")
                continue
            read_bytes += abs_path.stat().st_size
            if read_bytes > max_total_bytes:
                stats.stop_reason = (
                    f"累计读取超过 {_human_bytes(max_total_bytes)} 上限，剩余 {total - idx + 1} 个文件未处理"
                )
                break
            source = abs_path.read_bytes()
        except OSError as exc:
            merged.errors.append(f"读取失败 {rel}：{exc}")
            stats.skip("读取失败")
            continue

        one = parser.parse(source, rel)
        merged.nodes.extend(one.nodes)
        merged.edges.extend(one.edges)
        # ★★ 字段也要合并 —— 漏了这一行，结构体成员在整项目解析里会**全部消失**
        #   （单文件测试看不出来，只在"扫目录"时丢，踩过）
        merged.fields.extend(getattr(one, "fields", []) or [])
        # ⚠ 只保留前若干条错误，避免一个坏项目把 errors 撑爆
        if len(merged.errors) < 200:
            merged.errors.extend(one.errors)

        stats.files_parsed += 1
        stats.by_lang[lang] = stats.by_lang.get(lang, 0) + 1

        if on_file is not None:
            on_file(idx, total, rel)

    return merged, stats
