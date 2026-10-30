#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **文件过滤**（移植自所有者自己写的 `/home/ma/codeparser/ignore.py` + `code_scanner.py`）

## 为什么需要

```\n * 现在的解析器只按目录名跳过（node_modules / .git / dist …）\n * ⇒ 用户 `.gitignore` 里排除的东西照样被扫、被解析\n * ⇒ 大仓库里自动生成的目录会被当成代码读进去 ⚠\n ```\n *
所有者的做法：**默认忽略 + 项目 .gitignore + 扩展名白名单 + 几条硬规则**。

## 照搬的规则（逐条对应他那份代码）

```\n 1. 默认忽略       node_modules/ __pycache__/ /dist/ /build/ /target/ /vendor/\n 2. .gitignore     读仓库根的 .gitignore（gitignore 语义）\n 3. 隐藏项          名字以 . 开头一律跳过\n 4. 符号链接        跳过（避免环、避免重复）\n 5. 硬链接          st_nlink > 1 跳过（内核那种 arch/*/include/asm 的重复链接）\n 6. 大文件          > 300KB 跳过（解析器内部另有 2MB 硬上限）\n 7. 扩展名白名单     CODE_EXTS\n ```\n *
⚠ `pathspec` 没装时退化成内置简版匹配（默认忽略 + 通配），够用但语义不如 gitignore 全。
"""

from __future__ import annotations

import fnmatch
import os

#: 默认忽略（与所有者那份一致）
DEFAULT_IGNORE_PATTERNS = [
    "node_modules/",
    "__pycache__/",
    "/dist/",
    "/build/",
    "/target/",
    "/vendor/",
]

#: 代码扩展名白名单（照搬；解析器只认其中 .py/.c/.h/.cpp/.java，其余仅用于扫描统计）
CODE_EXTS = {
    ".py", ".pyi", ".pyw",
    ".js", ".mjs", ".cjs", ".jsx",
    ".ts", ".mts", ".cts", ".tsx",
    ".java", ".go", ".rs",
    ".c", ".h",
    ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h++",
    ".cs", ".csx", ".php", ".phtml", ".rb", ".rake", ".swift",
    ".kt", ".kts", ".scala", ".sc", ".clj", ".cljs", ".cljc",
    ".ex", ".exs", ".erl", ".hrl", ".hs", ".lhs", ".ml", ".mli", ".fs", ".fsi", ".fsx",
    ".lua", ".pl", ".pm", ".r", ".jl", ".dart", ".m", ".mm", ".groovy", ".vb",
    ".tcl", ".awk", ".zig", ".nim", ".cr", ".d",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1", ".bat", ".cmd",
    ".asm", ".s", ".v", ".vhd", ".vhdl", ".sol",
    ".f", ".f90", ".f95", ".f03", ".pas", ".adb", ".ads",
    ".lisp", ".lsp", ".scm", ".ss", ".pro", ".cob", ".cbl",
}

DEFAULT_MAX_BYTES = 300_000  # 与所有者那份一致


class _FallbackSpec:
    """`pathspec` 不在时的简版匹配（⚠ 不支持 `!` 取反）"""

    def __init__(self, patterns: list[str]) -> None:
        self.patterns = [p.strip() for p in patterns if p.strip() and not p.strip().startswith("#")]

    def match_file(self, rel: str) -> bool:
        rel = rel.replace(os.sep, "/")
        for p in self.patterns:
            if p.endswith("/"):
                if rel.startswith(p) or f"/{p}" in f"/{rel}/":
                    return True
                continue
            if p.startswith("/"):
                if fnmatch.fnmatch(rel, p[1:]) or fnmatch.fnmatch(rel, p[1:] + "/*"):
                    return True
                continue
            if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(os.path.basename(rel), p):
                return True
            if f"/{p}/" in f"/{rel}/":
                return True
        return False


def _build_spec(root: str):
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    gi = os.path.join(root, ".gitignore")
    if os.path.isfile(gi):
        try:
            with open(gi, "r", encoding="utf-8", errors="ignore") as f:
                patterns.extend(f.readlines())
        except OSError:
            pass
    try:
        from pathspec import PathSpec  # type: ignore

        return PathSpec.from_lines("gitignore", patterns)
    except Exception:  # noqa: BLE001 —— 没装就用简版，⛔ 不能让缺一个包导致整体不可用
        return _FallbackSpec(patterns)


class Filter:
    """★ 一次扫描用一份（内部持有 ignore spec 与根目录）"""

    def __init__(self, root: str, max_file_size: int = DEFAULT_MAX_BYTES) -> None:
        self.root = os.path.abspath(root)
        self.spec = _build_spec(self.root)
        self.max_file_size = max_file_size

    def skip_dir(self, name: str, rel: str) -> bool:
        if name.startswith("."):
            return True
        try:
            return bool(self.spec.match_file(rel + "/"))
        except Exception:  # noqa: BLE001
            return False

    def skip_file(self, name: str, rel: str) -> bool:
        if name.startswith("."):
            return True
        if os.path.splitext(name)[1].lower() not in CODE_EXTS:
            return True
        try:
            return bool(self.spec.match_file(rel))
        except Exception:  # noqa: BLE001
            return False

    def stat_ok(self, abs_path: str) -> bool:
        """软链 / 硬链接 / 超大文件 —— 所有者那份里的三条硬规则"""
        try:
            st = os.lstat(abs_path)
        except OSError:
            return False
        if os.path.islink(abs_path):
            return False
        if st.st_nlink > 1:  # 硬链接：同一份内容在多处出现
            return False
        if st.st_size > self.max_file_size:
            return False
        return True


def iter_code_files(root: str, max_file_size: int = DEFAULT_MAX_BYTES):
    """照搬所有者那版：`yield (rel_path, size)`

    ⚠ 它只回答"哪些文件算代码"；能不能解析由解析器判断（只认 4 种语言）。
    """
    root = os.path.abspath(root)
    flt = Filter(root, max_file_size)
    stack: list[tuple[str, str]] = [(root, "")]
    while stack:
        cur, rel_dir = stack.pop()
        try:
            with os.scandir(cur) as entries:
                for e in entries:
                    rel = (f"{rel_dir}/{e.name}" if rel_dir else e.name).replace(os.sep, "/")
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if flt.skip_dir(e.name, rel):
                            continue
                        stack.append((e.path, rel))
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    if flt.skip_file(e.name, rel):
                        continue
                    if not flt.stat_ok(e.path):
                        continue
                    try:
                        size = os.lstat(e.path).st_size
                    except OSError:
                        continue
                    yield rel, size
        except OSError:
            continue


def make_acceptors(root: str):
    """给解析器用的两个判定函数：`(rel, is_dir) -> bool`（True = 接受）"""
    flt = Filter(root)
    return (
        lambda rel: not flt.skip_dir(os.path.basename(rel), rel),
        lambda rel: not flt.skip_file(os.path.basename(rel), rel),
    )
