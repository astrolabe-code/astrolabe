#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **问答历史**：一个节点下的一串问答，存成 JSON 文件

所有者原话（2026-11-17）：

> 「顶部这一排加第五个选项，问答，就像现在的大模型厂商的网页版一样，
>   可以让人提问，回答，记录问答历史。加一个问答历史数据的json，挂在节点上」

```
<项目数据目录>/qa/<vid>.json
{
  "vid": 123,
  "items": [
    {
      "id":   "1763350000-1",
      "q":    "这个函数为什么先检查 fd？",
      "a":    "因为……",
      "at":   "2026-11-17T10:20:30",
      "model": "deepseek-chat"
    }
  ]
}
```

## 三条边界

```
① ⛔ 只写 <data>/qa/ —— 不碰源码、不碰笔记
② 原子写：先写 .tmp 再 os.replace（断电不留半个文件）
③ 有界：单条 ≤2 万字、最多 200 条（超出丢最旧的），防止无限增长
```
"""

from __future__ import annotations

import datetime
import json
import os

#: 单条问题/回答的最大长度
MAX_TEXT = 20_000
#: 一个节点最多保留多少条问答
MAX_ITEMS = 200


class QaError(Exception):
    """可读错误（转成 400 返回）"""


def _dir(data_dir: str) -> str:
    return os.path.join(data_dir, "qa")


def _path(data_dir: str, vid: int) -> str:
    return os.path.join(_dir(data_dir), f"{int(vid)}.json")


def _read(data_dir: str, vid: int) -> dict:
    """读历史；文件不存在/损坏都当空，⛔ 不让一轮问答因为读失败而崩。"""
    p = _path(data_dir, vid)
    if not os.path.isfile(p):
        return {"vid": int(vid), "items": []}
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:  # noqa: BLE001
        return {"vid": int(vid), "items": []}
    items = raw.get("items") if isinstance(raw, dict) else None
    clean = [x for x in (items or []) if isinstance(x, dict) and str(x.get("q") or "").strip()]
    return {"vid": int(vid), "items": clean}


def _write(data_dir: str, vid: int, data: dict) -> None:
    d = _dir(data_dir)
    os.makedirs(d, exist_ok=True)
    p = _path(data_dir, vid)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def list_items(data_dir: str, vid: int) -> dict:
    """列出该节点的全部问答（按时间正序）。"""
    return _read(data_dir, vid)


def append(data_dir: str, vid: int, q: str, a: str, model: str = "") -> dict:
    """追加一条问答；返回追加后的完整列表。"""
    question = str(q or "").strip()[:MAX_TEXT]
    answer = str(a or "").strip()[:MAX_TEXT]
    if not question:
        raise QaError("问题不能为空")

    data = _read(data_dir, vid)
    now = datetime.datetime.now()
    item = {
        "id": f"{int(now.timestamp())}-{len(data['items']) + 1}",
        "q": question,
        "a": answer,
        "at": now.isoformat(timespec="seconds"),
        "model": str(model or "")[:80],
    }
    data["items"].append(item)
    if len(data["items"]) > MAX_ITEMS:
        data["items"] = data["items"][-MAX_ITEMS:]
    _write(data_dir, vid, data)
    return data


def remove_item(data_dir: str, vid: int, item_id: str) -> dict:
    """删一条（按 id）。"""
    data = _read(data_dir, vid)
    data["items"] = [x for x in data["items"] if str(x.get("id") or "") != str(item_id)]
    _write(data_dir, vid, data)
    return data


def clear(data_dir: str, vid: int) -> dict:
    """清空该节点的历史（文件保留为空数组，避免删文件）。"""
    data = {"vid": int(vid), "items": []}
    _write(data_dir, vid, data)
    return data
