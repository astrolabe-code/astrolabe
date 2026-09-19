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


@dataclass(slots=True)
class ScanStats:
    """扫描与解析的统计（★ 用于进度显示与诊断，不进图）。"""

    files_seen: int = 0
    files_parsed: int = 0
    files_skipped: int = 0
    by_lang: dict[str, int] = field(default_factory=dict)
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.files_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


def scan_and_parse(
    root: str | Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    extra_excludes: set[str] | None = None,
    on_file: Callable[[int, int, str], None] | None = None,
) -> tuple[ParseResult, ScanStats]:
    """扫描目录并逐文件解析。

    Args:
        root: 项目根目录（★ 调用方负责确认它存在且可读）
        max_files: 文件数上限（超出即停止，并把原因记进 `errors`）
        extra_excludes: 追加的排除目录名
        on_file: 每解析一个文件后的回调 `(已完成, 总数, 相对路径)` —— 供作业回写进度

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

    # ---------------------------------------------------------------- ① 收集候选
    candidates: list[tuple[Path, str]] = []  # (绝对路径, 相对路径)
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root_path):
        # ★ 原地修改 dirnames ⇒ os.walk 不会进入这些目录（比事后过滤高效得多）
        dirnames[:] = [d for d in dirnames if d not in excludes]
        for filename in sorted(filenames):
            abs_path = Path(dirpath, filename)
            rel = str(abs_path.relative_to(root_path)).replace("\\", "/")
            if detect_lang(rel) is None:
                continue
            candidates.append((abs_path, rel))
            if len(candidates) >= max_files:
                truncated = True
                break
        if truncated:
            break

    if truncated:
        merged.errors.append(f"文件数达到上限 {max_files}，其余已跳过")
    stats.files_seen = len(candidates)

    # ---------------------------------------------------------------- ② 逐文件解析
    parsers = build_parsers()
    total = len(candidates)

    for idx, (abs_path, rel) in enumerate(candidates, start=1):
        lang = detect_lang(rel)
        parser = parsers.get(lang) if lang else None
        if parser is None:
            stats.skip(f"无解析器:{lang}")
            continue

        try:
            if abs_path.stat().st_size > MAX_FILE_BYTES:
                stats.skip("文件过大")
                continue
            source = abs_path.read_bytes()
        except OSError as exc:
            merged.errors.append(f"读取失败 {rel}：{exc}")
            stats.skip("读取失败")
            continue

        one = parser.parse(source, rel)
        merged.nodes.extend(one.nodes)
        merged.edges.extend(one.edges)
        # ⚠ 只保留前若干条错误，避免一个坏项目把 errors 撑爆
        if len(merged.errors) < 200:
            merged.errors.extend(one.errors)

        stats.files_parsed += 1
        stats.by_lang[lang] = stats.by_lang.get(lang, 0) + 1

        if on_file is not None:
            on_file(idx, total, rel)

    return merged, stats
