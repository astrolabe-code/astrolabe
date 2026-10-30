#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **文件过滤**（思路来自所有者写的 `ignore.py` + `code_scanner.py`，实现重写过）

## 做了什么

```\n 1. 默认忽略       node_modules/ __pycache__/ 以及 /dist/ /build/ /target/ /vendor/\n 2. .gitignore     **根目录 + 每个子目录**各读一份（git 的真实语义）\n 3. 隐藏项          名字以 . 开头一律跳过\n 4. 符号链接        跳过（避免环、避免重复）\n 5. 大文件          > 300KB 跳过（解析器内部另有 2MB 硬上限）\n 6. 扩展名白名单     CODE_EXTS\n 7. 迭代顺序        排序后输出（⛔ 不依赖文件系统顺序）\n 8. 文件数上限      默认 20 万，防止超大仓库一直扫\n ```\n *
## 与原实现的三处不同（原实现里有问题的地方）

```\n ✗ 原版读 .gitignore 不 strip、注释行原样塞给 pathspec   ⇒ 这里 strip + 过滤空行注释\n ✗ 原版只读根目录的 .gitignore                        ⇒ 这里逐目录读（git 语义）\n ✗ 原版 st_nlink > 1 就跳过文件                        ⇒ 这里去掉（会误杀正常硬链接）\n ```\n *
⚠ 前导 `/` 的语义按 gitignore：`/dist/` **只匹配仓库根**，`node_modules/` 匹配任意层级。
  这是有意的 —— 深处可能真有叫 `build` 的源码目录，不能无差别排掉。
"""

from __future__ import annotations

import fnmatch
import os

#: 默认忽略。带前导 `/` 的只匹配根，其余匹配任意层级
DEFAULT_IGNORE_PATTERNS = [
    "node_modules/",
    "__pycache__/",
    "/dist/",
    "/build/",
    "/target/",
    "/vendor/",
]

#: 代码扩展名白名单（照搬所有者那份；解析器只认其中 .py/.c/.h/.cpp/.java）
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

#: **这一版解析器真正能解析的**扩展名（对应 codeparser/registry.py 的 EXT_TO_LANG）
#: ⚠ 用途：选目录时告诉用户"xx 个能读、yy 个这版还不支持"，
#:   而不是把 334 个代码文件都报成"可读"、最后只解析 233 个（数字对不上）
PARSABLE_EXTS = {
    ".c", ".h",
    ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx",
    ".py",
    ".java",
    ".s", ".asm",   # 汇编走的是内置解析器，不是 tree-sitter
}

DEFAULT_MAX_BYTES = 300_000
DEFAULT_MAX_FILES = 200_000


class _FallbackSpec:
    """`pathspec` 不在时的简版匹配（⚠ 不支持 `!` 取反）"""

    def __init__(self, patterns: list[str]) -> None:
        self.patterns = list(patterns)

    def match_file(self, rel: str) -> bool:
        rel = rel.replace(os.sep, "/")
        is_dir = rel.endswith("/")
        rel = rel.rstrip("/")
        parts = rel.split("/")

        for p in self.patterns:
            anchored = p.startswith("/")
            core = p[1:] if anchored else p
            dir_only = core.endswith("/")
            if dir_only:
                core = core.rstrip("/")
            if not core:
                continue

            if dir_only:
                if anchored:
                    # `/dist/` ⇒ 只匹配仓库根的 dist
                    if rel == core or rel.startswith(core + "/"):
                        return True
                else:
                    # `node_modules/` ⇒ 任意层级
                    if core in parts[:-1] or rel.startswith(core + "/") or (
                        is_dir and rel.endswith("/" + core)
                    ):
                        return True
                continue

            if anchored:
                if fnmatch.fnmatch(rel, core) or (is_dir and fnmatch.fnmatch(rel + "/", core + "/")):
                    return True
            else:
                if (
                    fnmatch.fnmatch(rel, core)
                    or fnmatch.fnmatch(os.path.basename(rel), core)
                    or f"/{core}/" in f"/{rel}/"
                ):
                    return True
        return False


def _read_patterns(root: str, dir_rel: str) -> list[str]:
    """读 `<root>/<dir_rel>/.gitignore`**（去空行、去注释、strip）**

    ⚠ 原实现把 `readlines()` 的结果直接 append 进去（带换行），
      并注释掉了注释行过滤 —— 依赖 pathspec 内部宽容，属于"能跑"而非"正确"。
    """
    path = os.path.join(root, dir_rel.replace("/", os.sep), ".gitignore") if dir_rel else os.path.join(root, ".gitignore")
    out: list[str] = []
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                out.append(line)
    except OSError:
        return []
    return out


def _make_spec(patterns: list[str]):
    if not patterns:
        return None
    try:
        from pathspec import PathSpec  # type: ignore

        return PathSpec.from_lines("gitignore", patterns)
    except Exception:  # noqa: BLE001 —— 没装 pathspec 就退化，⛔ 不能让缺包导致不可用
        return _FallbackSpec(patterns)


class Filter:
    """★ 一次扫描用一份（按目录缓存 ignore spec）"""

    def __init__(self, root: str, max_file_size: int = DEFAULT_MAX_BYTES) -> None:
        self.root = os.path.abspath(root)
        self.max_file_size = max_file_size
        self._cache: dict[str, object | None] = {}

    # ---- ignore spec（逐目录，git 语义）--------------------------------
    def spec_of(self, dir_rel: str):
        if dir_rel in self._cache:
            return self._cache[dir_rel]
        pats = list(DEFAULT_IGNORE_PATTERNS) if not dir_rel else []
        pats.extend(_read_patterns(self.root, dir_rel))
        spec = _make_spec(pats)
        self._cache[dir_rel] = spec
        return spec

    @staticmethod
    def _ancestors(rel: str) -> list[str]:
        """`a/b/c.py` ⇒ ['', 'a', 'a/b']（含根，不含自己）"""
        parts = rel.split("/")[:-1]
        out = [""]
        acc: list[str] = []
        for p in parts:
            acc.append(p)
            out.append("/".join(acc))
        return out

    def ignored(self, rel: str) -> bool:
        """★ 逐个祖先目录用自己的 .gitignore 匹配（子目录规则相对它自己的目录）"""
        rel = rel.replace(os.sep, "/")
        for d in self._ancestors(rel):
            spec = self.spec_of(d)
            if spec is None:
                continue
            sub = rel[len(d) + 1:] if d else rel
            try:
                if spec.match_file(sub):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    # ---- 判定 ----------------------------------------------------------
    def skip_dir(self, name: str, rel: str) -> bool:
        """目录能不能进：隐藏项、以及**父目录**的 ignore 规则"""
        if name.startswith("."):
            return True
        return self.ignored(rel + "/")

    def skip_file(self, name: str, rel: str) -> bool:
        if name.startswith("."):
            return True
        if os.path.splitext(name)[1].lower() not in CODE_EXTS:
            return True
        return self.ignored(rel)

    def stat_ok(self, abs_path: str) -> bool:
        """软链 / 超大文件

        ⚠★ 原实现的 `st_nlink > 1` 那条**没有照搬**：
          它想躲开内核那种 arch/*/include/asm 的重复链接，但那是**符号链接**，
          上一行已经挡掉了；硬链接更多是"同一文件的正经别名"，
          跳掉会静默少解析 ⇒ 收益小、误伤大。
        """
        try:
            st = os.lstat(abs_path)
        except OSError:
            return False
        if os.path.islink(abs_path):
            return False
        if st.st_size > self.max_file_size:
            return False
        return True


def iter_code_files(
    root: str,
    max_file_size: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
):
    """`yield (rel_path, size)` —— 哪些文件算代码

    ⚠ 迭代顺序**排序过**：`os.scandir` 的顺序取决于文件系统，
      不排序会让两次扫描的节点顺序不同，图上看得出跳动。
    """
    root = os.path.abspath(root)
    flt = Filter(root, max_file_size)
    stack: list[tuple[str, str]] = [(root, "")]
    count = 0
    while stack:
        cur, rel_dir = stack.pop()
        try:
            with os.scandir(cur) as entries:
                for e in sorted(entries, key=lambda x: x.name):
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
                    count += 1
                    if count > max_files:
                        return
                    yield rel, size
        except OSError:
            continue


def make_acceptors(root: str):
    """给解析器用的两个判定函数：`accept_dir(rel)` / `accept_file(rel)`"""
    flt = Filter(root)
    return (
        lambda rel: not flt.skip_dir(os.path.basename(rel), rel),
        lambda rel: not flt.skip_file(os.path.basename(rel), rel),
    )
