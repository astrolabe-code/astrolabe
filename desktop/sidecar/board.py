#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ **思考白板持久化**（个人版边车，文件式 JSON）

· ★ 一个节点可以挂**多块白板**（跟笔记一样：新建 → 列表 → 点开）⚠
· 存 `<项目数据目录>/boards/<board_id>.json`
  - 新建白板 id = `<vid>_<毫秒时间戳>`（例如 `12_1762920000000`）
  - 历史格式 id = `<vid>`（早期「一个节点一块画布」留下的文件，继续可读写）
· 内容就是前端传来的布局对象 { pos, board, sizes, canvas }，边车**不解读**其结构
· 原子写（tempfile + os.replace），避免写入中途进程退出留下半截文件
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time

# ★ 白板 id 只认「数字」或「数字_数字」，防止路径穿越
_ID = re.compile(r"^\d+(?:_\d+)?$")


def _dir(data_dir: str) -> str:
    d = os.path.join(data_dir, "boards")
    os.makedirs(d, exist_ok=True)
    return d


def _path(data_dir: str, board_id: str) -> str:
    if not _ID.match(str(board_id)):
        raise ValueError("非法白板 id")
    return os.path.join(_dir(data_dir), f"{board_id}.json")


def load(data_dir: str, board_id: str) -> dict | None:
    try:
        with open(_path(data_dir, board_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # 文件不存在 / 坏数据 / 非法 id 都当没有：下次保存会覆盖
        return None


def save(data_dir: str, board_id: str, layout: dict) -> dict:
    p = _path(data_dir, board_id)
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


def new_board(data_dir: str, vid: int) -> dict:
    """★★ 在当前节点下**新建一块空白白板**（跟「新建笔记」一样的动作）"""
    board_id = f"{int(vid)}_{int(time.time() * 1000)}"
    save(data_dir, board_id, {})
    return {"id": board_id, "vid": int(vid), "mtime": int(time.time())}


def list_boards(data_dir: str) -> list[dict]:
    """★★ 列出项目里所有白板（按修改时间**新→旧**）⚠

    · 每项 { id, vid, mtime }；节点名由 main.py 再查索引补上
    """
    d = _dir(data_dir)
    items: list[dict] = []
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        stem = fn[:-5]
        if not _ID.match(stem):
            continue
        try:
            mtime = int(os.path.getmtime(os.path.join(d, fn)))
        except OSError:
            mtime = 0
        items.append({"id": stem, "vid": int(stem.split("_")[0]), "mtime": mtime})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items
