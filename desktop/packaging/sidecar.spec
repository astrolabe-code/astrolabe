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

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

#: 仓库根（spec 在 desktop/packaging/ 下）
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
APP_DIR = os.path.join(ROOT, "app")
SIDECAR_DIR = os.path.join(ROOT, "desktop", "sidecar")

# ★★ LadybugDB 是 C++ 扩展（_lbug*.pyd + 依赖 dll），静态分析看不到
#   collect_all 会把二进制、数据文件和隐藏 import 一起收进来；
#   打包机上必须已经 pip install ladybug（见 requirements.txt）
# ⚠ 不要用 collect_all：它会把 ladybug 里的 torch_geometric_* 子模块
#   一并塞进 hiddenimports，那条 import 链会再把 distutils 拖回模块图，
#   与 excludes 里的 distutils 撞成
#   ValueError: Target module "distutils" already imported as ExcludedModule(...)
try:
    import ladybug as _lb  # noqa: F401  —— 没装时下面几条会抛，退化成"图库不可用"
    LB_DATAS = collect_data_files("ladybug")
    LB_BINARIES = collect_dynamic_libs("ladybug")
    # ★★★ ladybug 的 Windows wheel 是 delvewheel 布局：
    #   site-packages/ladybug/_lbug.cp312-win_amd64.pyd
    #   site-packages/ladybug.libs/msvcp140-xxxx.dll   ← 与包目录**同级**
    #   collect_dynamic_libs 只扫包内文件 ⇒ 漏掉这个 dll，
    #   产物里 _lbug.pyd 加载失败 ⇒ 图库打不开 ⇒ 图谱页没有数据。
    try:
        from PyInstaller.utils.hooks import collect_delvewheel_libs_directory

        _libs_datas, _libs_bins = collect_delvewheel_libs_directory("ladybug")
        LB_DATAS = LB_DATAS + _libs_datas
        LB_BINARIES = LB_BINARIES + _libs_bins
    except Exception:  # 老版 PyInstaller 没有这个工具，退回原样
        pass
    # ★ _lbug 是 import_module("._lbug") 动态加载的 ⇒ 静态分析看不到，
    #   必须显式声明，否则打包成功、运行时 ImportError
    LB_HIDDEN = ["ladybug", "ladybug._lbug", "ladybug._lbug_capi"]
except Exception:  # pragma: no cover
    LB_DATAS, LB_BINARIES, LB_HIDDEN = [], [], []

# ★ 解析器的语法包 —— ⚠ 必须显式声明（见文件头）
HIDDEN = [
    "tree_sitter",
    "tree_sitter_python",
    "tree_sitter_c",
    "tree_sitter_cpp",
    "tree_sitter_java",
    # 文件过滤（.gitignore 语义）；⚠ 没装时边车会退化成简版匹配
    "pathspec",
    # ★ 每种语言的处理模块是 importlib 动态导入的，静态分析看不到
    "codeparser.langs",
    "codeparser.langs.base",
    "codeparser.langs.c",
    "codeparser.langs.cpp",
    "codeparser.langs.python",
    "codeparser.langs.java",
    "codeparser.queryparser",
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
    # code viewer: file tree / source read
    "source",
    # 仿写：一个节点下多份代码卡
    "imitation",
    # 卡片盒的链（深入 / 参见）
    "links",
    # ★ 图库：拓扑真相（LadybugDB 的二进制由 collect_all 收集）
    "graphdb",
]

a = Analysis(
    [os.path.join(SIDECAR_DIR, "main.py")],
    pathex=[SIDECAR_DIR, APP_DIR],
    binaries=LB_BINARIES,
    # ★★ 查询文件必须打进去 —— 运行时按 `codeparser/queries/*.scm` 相对路径读
    #   ⚠ 漏了它：打包"成功"，运行时所有语言都退回遍历式解析器（无错但慢）
    datas=[
        (os.path.join(APP_DIR, "codeparser", "queries", "*.scm"), "codeparser/queries"),
    ] + LB_DATAS,
    hiddenimports=HIDDEN + LB_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # ⚠ 别把 tkinter / 测试包拖进来（边车是纯 stdio 程序）
    # ⚠ 别把 distutils 列进来：Python 3.12 已移除它，而某些 hook 的
    #   import 链仍会引用 ⇒ 与 ExcludedModule 冲突（见上面 ladybug 的注释）
    #
    # ★ Anaconda 里装着一堆重型科学计算包，PyInstaller 会顺着 ladybug 的
    #   可选依赖（query_result.py 里的 try: import pandas / torch_geometric）
    #   一路分析过去，最后走到 skimage；而 skimage 的 hook 要在隔离子进程里
    #   import 它自己，DLL 不匹配就直接把子进程搞崩：
    #   SubprocessDiedError ... exit code 3228369022 (= 0xC06D007E, DLL 找不到)
    #   边车一个都用不到这些包（ladybug 的引用全在 try/except 里），排除掉。
    excludes=[
        "tkinter", "unittest", "pydoc", "test",
        "skimage", "matplotlib", "IPython",
        "torch", "torch_geometric",
        "pandas", "scipy", "numba", "dask",
    ],
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
    # ⚠ 关掉 UPX：LadybugDB 的 .pyd 是 C++ 扩展，被 UPX 压缩后
    #   在部分 Windows 机器上加载会失败（LoadLibrary 报错），不值得为体积冒险
    upx=False,
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
