#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ **思考白板布局持久化**（个人版边车，文件式 JSON，跟仿写 / links 同款）

· 存 `<项目数据目录>/boards/<vid>.json`（vid = 节点 vid）
· 内容就是前端传来的布局对象 { pos, board, sizes, canvas }，边车**不解读**其结构
· 原子写（tempfile + os.replace），避免写入中途进程退出留下半截文件
"""

from __future__ import annotations

import json
import os
import tempfile


def _path(data_dir: str, vid: int) -> str:
    d = os.path.join(data_dir, "boards")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{int(vid)}.json")


def load(data_dir: str, vid: int) -> dict | None:
    try:
        with open(_path(data_dir, vid), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        # 坏数据当没有：下次保存会覆盖
        return None


def save(data_dir: str, vid: int, layout: dict) -> dict:
    p = _path(data_dir, vid)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return {"ok": True}
