# -*- mode: python ; coding: utf-8 -*-
"""★★ PyInstaller **单文件边车**打包脚本（个人版）

## 打什么

```\ndesktop/sidecar/main.py            ← 入口（stdio 协议）\n  ├─ stores/library/notefile/...   ← 我们自己的数据层\n  ├─ codeparser/                   ← 解析器（app/ 目录，纯 Python + tree-sitter）\n  └─ graph/identity.py · kinds.py  ← vid 算法（⛔ 不含 Django）\n ```\n *
## 为什么必须显式写 `hiddenimports`

```\n * tree_sitter_* 是**二进制扩展**，且 `codeparser/registry.py` 里是 try/except 导入\n *   ⇒ PyInstaller 的静态分析看不出来，漏掉就变成\n *     "打包成功、运行时说没有解析器"（⚠ 最坑的一种失败）\n ```\n *
## 用法

```bash
pyinstaller --clean --noconfirm desktop/packaging/sidecar.spec
# 产物：dist/astrolabe-sidecar（Windows 上是 .exe）
```
"""

import os
import sys

#: 仓库根（spec 在 desktop/packaging/ 下）
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
APP_DIR = os.path.join(ROOT, "app")
SIDECAR_DIR = os.path.join(ROOT, "desktop", "sidecar")

# ★ 解析器的语法包 —— ⚠ 必须显式声明（见文件头）
HIDDEN = [
    "tree_sitter",
    "tree_sitter_python",
    "tree_sitter_c",
    "tree_sitter_cpp",
    "tree_sitter_java",
    # 文件过滤（.gitignore 语义）；⚠ 没装时边车会退化成简版匹配
    "pathspec",
    # 我们自己按目录名 import 的模块
    "library",
    "store",
    "notefile",
    "indexer",
    "autotitle",
    "parser_bridge",
    "paths",
    "filefilter",
    "projectstore",
]

a = Analysis(
    [os.path.join(SIDECAR_DIR, "main.py")],
    pathex=[SIDECAR_DIR, APP_DIR],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # ⚠ 别把 tkinter / 测试包拖进来（边车是纯 stdio 程序）
    excludes=["tkinter", "unittest", "pydoc", "test", "distutils"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="astrolabe-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # ★ 边车是控制台程序（stdio 协议），⛔ 不要 windowed
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
