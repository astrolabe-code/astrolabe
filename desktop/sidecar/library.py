#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ **数据放哪**（个人版没有"库"这一层）

## 结构（所有者 2026-10-30 定）

```
<源码目录>/.astrolabe/          ← 一个源码目录 = 一本书 = 一个数据目录
├─ index.db                     SQLite 索引（可删、可重建）
├─ notes/                       0001-主角.md …
└─ trash/                       删掉的笔记（不是彻底删除）

<数据目录>/projects.json        全局清单，只记「读过哪几个目录」
<数据目录>/structures/<名字>/   空白结构（没有源码）的数据，同样的结构
```

⚠★ 为什么叫 `.astrolabe` 而不是 `data/`：
  源码目录里**本来就可能有个 data/**，占用它是毁用户的东西。

⚠★ 好处：**拷走源码目录 = 拷走笔记**，不需要"库"这个抽象。
"""


from __future__ import annotations

import json
import os
import re
import time

INDEX_DIR = ".astrolabe"
DATA_SUBDIR = INDEX_DIR  # 每个项目数据目录的名字：`.astrolabe`
DB_NAME = "index.db"
CONF_NAME = "config.json"

def data_dir() -> str:
    """程序的数据目录（`userData`，绿色版 ⇒ exe 同目录的 data/）"""
    return os.environ.get("ASTROLABE_DATA_DIR") or os.path.join(os.getcwd(), "data")

def data_subdir(project_root: str) -> str:
    """★ 一个项目的全部数据放在它自己的 `.astrolabe/` 里 ⚠

    ```\n     <源码目录>/.astrolabe/{index.db, notes/, trash/}
     ```

    ⚠ 叫 `.astrolabe` 而不是 `data` —— 源码目录里**本来就可能有个 data/**，
      占用它就是毁用户的东西（所有者明确要求避开这点）。
    """
    return os.path.join(project_root, DATA_SUBDIR)

def ensure_dir_at(data_dir: str) -> str:
    """★ 直接给数据目录（用户自己选的位置），不再拼 `.astrolabe` ⚠"""
    os.makedirs(os.path.join(data_dir, "notes"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "trash"), exist_ok=True)
    return data_dir


def ensure_data_dir(project_root: str) -> str:
    return ensure_dir_at(data_subdir(project_root))

def db_path(data_dir: str) -> str:
    return os.path.join(data_dir, DB_NAME)

def blank_root(name: str) -> str:
    """空白结构（没有源码目录）放在 `<数据目录>/structures/<名字>/`"""
    return os.path.join(data_dir(), "structures", name)

def project_dir_name(name: str) -> str:
    """项目名 → 库内子目录名

    ⚠ 只允许安全字符；中文保留（Windows 支持，且用户看得懂更亲）
    """
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", (name or "").strip())
    s = re.sub(r"\s+", "-", s).strip(".-")
    return (s or "project")[:60]
