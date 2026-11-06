#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **代码展示**的数据层：列文件树 / 读一个文件的源码

## 为什么单独一个模块

```
个人版没有版权顾虑 ⇒ 可以直接显示自己磁盘上的源码。
但"能看见"不等于"什么都能读"，所以把边界集中在这里：
  · 路径必须落在项目根内（⛔ 不允许 .. 逃出去、不允许绝对路径 / 盘符）
  · 只认 UTF-8 文本（⛔ 二进制、超大文件直接拒绝，不把界面卡死）
  · 文件树**不按 .gitignore 过滤**（所有者明确要求：全部显示）
    ⚠ 但解析代码仍由 codeparser/ignore.py 过滤，那是另一回事
```

## 与 main.py 的关系

```
R_TREE   /api/projects/<ref>/tree/      → tree(root)
R_SOURCE /api/projects/<ref>/source/?path= → read(root, rel)
```

⚠ 这里不 import Django、不碰数据库 —— 纯文件系统操作，打包进边车零负担。
"""

from __future__ import annotations

import os

#: 单个文件最大读取字节数（超过就直接拒绝，不截断，避免"看半截代码"误导）
MAX_FILE_BYTES = 512 * 1024
#: 文件树最多列多少个节点（防御性：几万文件的仓库不至于把 UI 拖死）
MAX_TREE_NODES = 20000
#: 最大递归深度
MAX_TREE_DEPTH = 12

#: 后缀 → 语言标识（前端据此动态加载 CodeMirror 语言包）
LANG_BY_EXT = {
    ".py": "python", ".pyi": "python", ".pyw": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".java": "java", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".go": "go", ".rs": "rust", ".php": "php", ".rb": "ruby",
    ".cs": "csharp", ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
    ".sql": "sql", ".json": "json", ".jsonc": "json",
    ".md": "markdown", ".markdown": "markdown",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini",
    ".html": "html", ".htm": "html", ".vue": "html", ".xml": "xml",
    ".css": "css", ".scss": "css", ".less": "css",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ps1": "shell",
    ".bat": "shell", ".cmd": "shell",
    ".gradle": "groovy", ".groovy": "groovy", ".lua": "lua",
    ".proto": "protobuf", ".graphql": "graphql", ".r": "r", ".R": "r",
    ".txt": "", ".log": "", ".cfg": "", ".conf": "", ".env": "", ".gitignore": "",
}


class SourceError(Exception):
    """可读的错误（会转成 400 返回给界面）"""

    def __init__(self, message: str, code: str = "source_unreadable"):
        super().__init__(message)
        self.message = message
        self.code = code


def safe_path(root: str, rel: str) -> str:
    """★ 把相对路径解析成**项目根内**的绝对路径；越界就抛错

    ⚠ Windows 上前端传的是 `/` 分隔，用户也可能粘 `\\` ⇒ 两种都当分隔符
    ⚠ 拒绝：绝对路径、盘符（C:）、`..`、符号链接指向根外
    """
    if not rel or not rel.strip():
        raise SourceError("没有指定文件路径", "need_path")

    rel = rel.replace("\\", "/").strip()
    if os.path.isabs(rel) or (len(rel) >= 2 and rel[1] == ":"):
        raise SourceError("只能用项目内的相对路径", "bad_path")

    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts:
        raise SourceError("没有指定文件路径", "need_path")
    if any(p == ".." for p in parts):
        raise SourceError("路径不能包含 ..", "bad_path")

    root_abs = os.path.abspath(root)
    full = os.path.abspath(os.path.join(root_abs, *parts))
    try:
        if os.path.commonpath([root_abs, full]) != root_abs:
            raise SourceError("这个文件不在项目目录里", "outside_root")
    except ValueError:
        raise SourceError("这个文件不在项目目录里", "outside_root") from None
    return full


def lang_of(rel: str) -> str:
    """按后缀猜语言（猜不出就空字符串 ⇒ 前端用纯文本）"""
    name = rel.replace("\\", "/").rsplit("/", 1)[-1]
    if name.startswith(".") and "." not in name[1:]:
        ext = name  # .gitignore 这类点文件
    else:
        ext = os.path.splitext(name)[1]
    return LANG_BY_EXT.get(ext, "")


def tree(root: str) -> dict:
    """★ 列出项目根下**全部**文件与目录（⛔ 不做 .gitignore 过滤）

    ```
    返回 {"items": [...], "truncated": bool}
    节点 {"name", "path", "type": "dir"|"file", "children": [...]}
    ```

    ⚠ 目录在前、同类按名称排序；不跟随符号链接（防循环、防跳出项目）
    ⚠ 深度/节点数到上限就停，并在该层标 truncated —— 不让界面假死
    """
    root_abs = os.path.abspath(root)
    if not os.path.isdir(root_abs):
        raise SourceError("项目目录不存在", "no_root")

    counter = {"n": 0, "truncated": False}

    def walk(abs_dir: str, rel_dir: str, depth: int) -> list[dict]:
        if depth > MAX_TREE_DEPTH or counter["n"] >= MAX_TREE_NODES:
            counter["truncated"] = True
            return []
        out: list[dict] = []
        try:
            entries = list(os.scandir(abs_dir))
        except (OSError, PermissionError):
            return []
        # ★ 目录在前，再按名字（忽略大小写）
        entries.sort(key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        for e in entries:
            if counter["n"] >= MAX_TREE_NODES:
                counter["truncated"] = True
                break
            if e.is_symlink():
                # ⚠ 不跟随：既避免循环，也避免链接指向项目外
                continue
            rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
            counter["n"] += 1
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            node = {"name": e.name, "path": rel, "type": "dir" if is_dir else "file"}
            if is_dir:
                node["children"] = walk(e.path, rel, depth + 1)
            out.append(node)
        return out

    items = walk(root_abs, "", 0)
    return {"items": items, "truncated": counter["truncated"]}


def read(root: str, rel: str) -> dict:
    """★ 读一个文件的文本（UTF-8，≤512KB）

    ```
    返回 {"path", "text", "lines", "lang", "size", "encoding"}
    ⚠ 二进制 / 非 UTF-8 / 超大 / 越界 ⇒ 抛 SourceError（界面显示原因）
    """
    full = safe_path(root, rel)
    if not os.path.isfile(full):
        raise SourceError("这不是一个文件（或已被删除）", "not_a_file")

    try:
        size = os.path.getsize(full)
    except OSError:
        raise SourceError("读不到这个文件", "stat_failed") from None
    if size > MAX_FILE_BYTES:
        raise SourceError(
            f"文件 {size // 1024} KB，超过 {MAX_FILE_BYTES // 1024} KB 上限（怕把界面卡住）",
            "too_large",
        )

    try:
        with open(full, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise SourceError("没有权限读这个文件", "open_failed") from None

    if b"\x00" in raw:
        raise SourceError("这是二进制文件，不是文本", "binary")

    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        raise SourceError("不是 UTF-8 文本文件", "not_utf8") from None

    return {
        "path": rel.replace("\\", "/"),
        "text": text,
        "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        "lang": lang_of(rel),
        "size": size,
        "encoding": encoding,
    }
