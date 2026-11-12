#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★★ **思考白板持久化**（个人版边车，文件式 JSON）

· ★ 一个节点可以挂**多块白板**（跟笔记一样：新建 → 列表 → 点开）
· 存 `<项目数据目录>/boards/<board_id>.json`
  - 新建白板 id = `<vid>_<毫秒时间戳>`（例如 `12_1762920000000`）
  - 历史格式 id = `<vid>`（早期「一个节点一块画布」留下的文件，继续可读写）
· 文件内容 = 布局对象 { pos, board, sizes, canvas } + `name`（白板名字）
  - 名字在点「保存布局」弹窗里让用户确认 / 修改；没写就用默认名 `白板 N`
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


def _fill_names(items: list[dict]) -> list[dict]:
    """★ 没写名字的白板 ⇒ 同一节点内按修改时间老→新补默认名 `白板 N`"""
    by_vid: dict[int, list[dict]] = {}
    for it in items:
        by_vid.setdefault(it["vid"], []).append(it)
    for group in by_vid.values():
        group.sort(key=lambda x: x["mtime"])
        for i, it in enumerate(group):
            if not str(it.get("name") or "").strip():
                it["name"] = f"白板 {i + 1}"
    return items


def list_boards(data_dir: str) -> list[dict]:
    """★★ 列出项目里所有白板（按修改时间**新→旧**）⚠

    · 每项 { id, vid, mtime, name }；节点名由 main.py 再查索引补上
    """
    d = _dir(data_dir)
    items: list[dict] = []
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        stem = fn[:-5]
        if not _ID.match(stem):
            continue
        p = os.path.join(d, fn)
        try:
            mtime = int(os.path.getmtime(p))
        except OSError:
            mtime = 0
        name = ""
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                name = str(data.get("name") or "")
        except Exception:
            pass
        items.append({
            "id": stem,
            "vid": int(stem.split("_")[0]),
            "mtime": mtime,
            "name": name,
        })
    _fill_names(items)
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _default_name(data_dir: str, board_id: str) -> str:
    for it in list_boards(data_dir):
        if it["id"] == str(board_id):
            return it["name"]
    return "白板 1"


def load(data_dir: str, board_id: str) -> dict | None:
    try:
        with open(_path(data_dir, board_id), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        # 文件不存在 / 坏数据 / 非法 id 都当没有：下次保存会覆盖
        return None
    if not isinstance(data, dict):
        return None
    # ★ 老数据 / 没写名字：补默认名，保证前端「保存白板」弹窗永远有预填值
    if not str(data.get("name") or "").strip():
        data = {**data, "name": _default_name(data_dir, board_id)}
    return data


def save(data_dir: str, board_id: str, layout: dict) -> dict:
    if not isinstance(layout, dict):
        layout = {}
    name = str(layout.get("name") or "").strip()
    if not name:
        # ★ 自动保存不带名字时：保留旧名字，实在没有就用默认名（别把名字弄丢）
        old = load(data_dir, board_id) or {}
        name = str(old.get("name") or "").strip() or _default_name(data_dir, board_id)
    layout = {**layout, "name": name}
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
    """★★ 在当前节点下**新建一块空白白板**（默认名 `白板 N`，保存弹窗里可改）"""
    vid = int(vid)
    board_id = f"{vid}_{int(time.time() * 1000)}"
    n = sum(1 for x in list_boards(data_dir) if x["vid"] == vid)
    name = f"白板 {n + 1}"
    save(data_dir, board_id, {"name": name})
    return {"id": board_id, "vid": vid, "mtime": int(time.time()), "name": name}
