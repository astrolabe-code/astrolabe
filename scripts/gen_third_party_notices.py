#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 THIRD-PARTY-NOTICES.txt（第三方组件与许可证声明）⚠

## 为什么必须生成，不是可选

MIT / ISC / BSD 三类许可证都有同一条要求：**分发时必须保留版权声明**。
我们要分发个人版的安装包，所以必须随包附带这份文件 —— 否则就是违约，
而不是"最好写一下"。

## 生成方式

```bash
# ① 前端依赖（本机 node_modules 全在，直接遍历）
python3 scripts/gen_third_party_notices.py

# ② 后端依赖（Django 等只装在容器里）—— 先在容器里导一份 JSON：
docker compose -f app/deploy/docker-compose.yml exec -T web python - <<'PY'
import json, importlib.metadata as m
out = []
for d in m.distributions():
    name = d.metadata["Name"] if d.metadata else None
    if not name:
        continue
    out.append({
        "name": name,
        "version": d.version,
        "license": (d.metadata.get("License-Expression")
                    or d.metadata.get("License")
                    or ""),
        "classifier": [c for c in (d.metadata.get_all("Classifier") or [])
                       if c.startswith("License")],
    })
print(json.dumps(out, ensure_ascii=False))
PY
# 把输出存到 /tmp/pydeps.json，再：
python3 scripts/gen_third_party_notices.py --python-json /tmp/pydeps.json
```

⚠ 依赖变了就重跑一次 —— 过时的声明等于错的声明。
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
OUT = os.path.join(ROOT, "THIRD-PARTY-NOTICES.txt")

# ⚠ 这些是**运行时/打包链**上的固定项，不来自 package.json
FIXED = [
    (
        "Electron",
        "MIT（内含 Chromium / Node.js / 各 BSD 组件）",
        "分发包内必须保留 LICENSES.chromium.html —— ⛔ 不要删，删了违反 Chromium 的 BSD 许可",
    ),
    ("Node.js", "MIT", "Electron 内嵌的运行时"),
    ("Python", "PSF-2.0", "解释器随包分发"),
    (
        "PyInstaller",
        "GPL-2.0-or-later WITH bootloader-exception",
        "仅用于打包。例外条款明确允许分发**专有程序**，不传染应用代码",
    ),
    ("NSIS", "zlib/libpng", "Windows 安装器生成器"),
    ("7-Zip", "LGPL-2.1（仅构建时使用，不随包分发）", ""),
]

LICENSE_FILE_RE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)", re.I)

# ★★ 个人版**实际随包分发**的 Python 包（解析器 sidecar 只需要这些）
#   ⚠ 其余（Django / DRF / gunicorn / psycopg / redis-py …）只在社区版跑，
#     不随个人版安装包分发 —— 声明里必须区分，否则读者会以为我们打进了 LGPL 的 psycopg ⚠
PYTHON_SHIPPED = {
    "tree-sitter",
    "tree-sitter-python",
    "tree-sitter-c",
    "tree-sitter-cpp",
    "tree-sitter-java",
}

# ★ 前端 319 个里绝大多数进构建产物；devDependencies 已在遍历时排除


def _read_license_text(pkg_dir: str) -> tuple[str, str]:
    """返回 (许可证名候选, 版权行)"""
    if not os.path.isdir(pkg_dir):
        return "", ""
    for fn in sorted(os.listdir(pkg_dir)):
        if not LICENSE_FILE_RE.match(fn):
            continue
        p = os.path.join(pkg_dir, fn)
        if not os.path.isfile(p):
            continue
        try:
            text = open(p, encoding="utf-8", errors="ignore").read(4000)
        except OSError:
            continue
        m = re.search(r"^.*copyright.*$", text, re.I | re.M)
        line = re.sub(r"\s+", " ", m.group(0)).strip() if m else ""
        return fn, line[:160]
    return "", ""


def _resolve(name: str, base: str) -> str | None:
    """在 base 往上找 node_modules/<name>（处理嵌套依赖）"""
    cur = base
    while True:
        cand = os.path.join(cur, "node_modules", name)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def collect_node() -> list[tuple[str, str, str, str]]:
    """(name, version, license, copyright) —— 只走 dependencies，不走 devDependencies"""
    pkgs: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    queue: list[tuple[str, str]] = []

    root_pkg = json.load(open(os.path.join(FRONTEND, "package.json"), encoding="utf-8"))
    for dep in root_pkg.get("dependencies", {}):
        queue.append((dep, FRONTEND))

    seen_paths: set[str] = set()
    while queue:
        name, base = queue.pop()
        pkg_dir = _resolve(name, base)
        if not pkg_dir or pkg_dir in seen_paths:
            continue
        seen_paths.add(pkg_dir)
        try:
            j = json.load(open(os.path.join(pkg_dir, "package.json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lic = j.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type", "")
        lic = str(lic or "")
        fn, cr = _read_license_text(pkg_dir)
        if not lic and fn:
            lic = fn
        key = (str(j.get("name") or name), str(j.get("version") or "?"))
        pkgs[key] = (key[0], key[1], lic or "（package.json 未声明）", cr)
        for sub in (j.get("dependencies") or {}):
            queue.append((sub, pkg_dir))

    return sorted(pkgs.values(), key=lambda x: x[0].lower())


def collect_python(path: str | None) -> list[tuple[str, str, str]]:
    if not path or not os.path.exists(path):
        return []
    raw = json.load(open(path, encoding="utf-8"))
    out = []
    for d in raw:
        lic = (d.get("license") or "").strip()
        lic = re.sub(r"\s+", " ", lic)[:80]
        if not lic:
            cls = [c.split("::")[-1].strip() for c in (d.get("classifier") or [])]
            lic = "; ".join(cls) if cls else "（元数据未声明）"
        out.append((d["name"], str(d.get("version") or "?"), lic))
    return sorted(out, key=lambda x: x[0].lower())


def main() -> None:
    argv = sys.argv[1:]
    py_json = None
    if "--python-json" in argv:
        py_json = argv[argv.index("--python-json") + 1]

    node = collect_node()
    py = collect_python(py_json)

    L: list[str] = []
    L.append("Astrolabe · 第三方组件与许可证声明")
    L.append("=" * 62)
    L.append("")
    L.append(f"生成日期：{date.today().isoformat()}")
    L.append("")
    L.append("本产品包含以下第三方组件，其版权归各自作者所有。")
    L.append("MIT / ISC / BSD 类许可证要求**分发时保留版权声明**，本文件即为此用。")
    L.append("")

    L.append("-" * 62)
    L.append(f"一、前端依赖（构建产物随包分发）　共 {len(node)} 个")
    L.append("-" * 62)
    for name, ver, lic, cr in node:
        L.append(f"{name} {ver}  —  {lic}")
        if cr:
            L.append(f"    {cr}")
    L.append("")

    L.append("-" * 62)
    if py:
        L.append(f"二、后端依赖（解析器随包分发）　共 {len(py)} 个")
    else:
        L.append("二、后端依赖（解析器随包分发）")
        L.append("    ⚠ 未提供 --python-json；请按脚本头部说明在容器里导一份后重跑")
    L.append("-" * 62)
    for name, ver, lic in py:
        shipped = name.lower() in PYTHON_SHIPPED
        tag = "" if shipped else "   ← 仅社区版，不随个人版分发"
        L.append(f"{name} {ver}  —  {lic}{tag}")
    L.append("")
    L.append("⚠ 个人版安装包只内含 tree-sitter 系（解析器），其余后端组件不随包分发。")
    L.append("")

    L.append("-" * 62)
    L.append("三、运行时与打包工具")
    L.append("-" * 62)
    for name, lic, note in FIXED:
        L.append(f"{name}  —  {lic}")
        if note:
            L.append(f"    ⚠ {note}")
    L.append("")

    L.append("-" * 62)
    L.append("四、合规要点（别踩）")
    L.append("-" * 62)
    L.append("· Electron 包内 LICENSES.chromium.html **不可删除**（Chromium 的 BSD 许可要求）。")
    L.append("· 本文件须随安装包分发；应用内「关于」里也应能打开。")
    L.append("· 依赖变更后必须重新生成本文件（过时的声明等于错的声明）。")
    L.append("· 本产品暂不含 GPL / AGPL 代码；若将来引入，须重新评估对闭源分发的影响。")
    L.append("")

    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print(f"已生成 {OUT}")
    print(f"  前端 {len(node)} 个 · 后端 {len(py)} 个 · 固定项 {len(FIXED)} 个")


if __name__ == "__main__":
    main()
