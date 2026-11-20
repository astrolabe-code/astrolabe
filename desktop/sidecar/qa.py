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
      "model": "deepseek-chat",
      "tokens_in": 862,
      "tokens_out": 164,
      "ms": 2400,
      "usage": {
        "total": 1026,
        "hit": 820, "miss": 42, "write": 0,
        "think": 0, "response": 164
      }
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
#: 思考过程最多存多少字（DeepSeek 的 reasoning_content，可能很长）
MAX_THINK = 6_000
#: 一个节点最多保留多少条问答
MAX_ITEMS = 200


class QaError(Exception):
    """可读错误（转成 400 返回）"""


def _clean_text(text: str) -> str:
    """清洗将要写进 JSON 的文本。

    ★ 所有者原话（2026-11-17）：「不要把ai返回的内容直接写进json，防止弄坏，
      系统要检查一下」
    ⚠ 模型输出可能带控制字符（\x00–\x1f）、孤立代理项（0xD800–0xDFFF）、
      或离谱的长度 —— 这些进了 JSON 虽然能被转义，但会让文件变得难处理。
      ⇒ 保留换行/制表，其余控制字符一律丢弃，再按 MAX_TEXT 截断。
    """
    out: list[str] = []
    for ch in str(text or ""):
        if ch in ("\n", "\t"):
            out.append(ch)
            continue
        o = ord(ch)
        if o < 0x20 or 0xD800 <= o <= 0xDFFF:
            continue
        out.append(ch)
    return "".join(out)[:MAX_TEXT]


def _dir(data_dir: str) -> str:
    return os.path.join(data_dir, "qa")


def _path(data_dir: str, vid: int, scope: str = "main") -> str:
    """main → <vid>.json；challenge → <vid>-challenge.json。"""
    safe = str(scope or "main").strip()
    # ⛔ 只允许两种 scope，别让外部字符串拼进文件名
    suffix = "" if safe == "main" else "-challenge" if safe == "challenge" else ""
    if not suffix:
        safe = "main"
    name = f"{int(vid)}{suffix}.json"
    return os.path.join(_dir(data_dir), name)


def _read(data_dir: str, vid: int, scope: str = "main") -> dict:
    """读历史；文件不存在/损坏都当空，⛔ 不让一轮问答因为读失败而崩。"""
    p = _path(data_dir, vid, scope)
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


def _write(data_dir: str, vid: int, data: dict, scope: str = "main") -> None:
    d = _dir(data_dir)
    os.makedirs(d, exist_ok=True)
    p = _path(data_dir, vid, scope)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def list_items(data_dir: str, vid: int, scope: str = "main") -> dict:
    """列出该节点的问答（按时间正序）。"""
    return _read(data_dir, vid, scope)


def append(
    data_dir: str,
    vid: int,
    q: str,
    a: str,
    model: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    ms: int = 0,
    usage: dict | None = None,
    think: str = "",
    trace: list | None = None,
    steps: list | None = None,
    scope: str = "main",
    item_id: str = "",
) -> dict:
    """追加一条问答；返回追加后的完整列表。

    ★ `tokens_in/out/ms` 用于界面上的「速率统计」（OpenWebUI 那排按钮里的信息）。
      ⚠ 显式保存而不是每次重算：历史是**当时**的消耗，不该随后来的计价变。
    """
    question = _clean_text(str(q or "")).strip()
    answer = _clean_text(str(a or "")).strip()
    if not question:
        raise QaError("问题不能为空")

    data = _read(data_dir, vid, scope)
    now = datetime.datetime.now()
    # ★★ 前端生成 id（OpenWebUI 风格）：流式期间它就已在消息列表里，
    #   后端入库时照用 ⇒ 不需要「临时 id → 真 id 替换」那一步。
    #   没传（老调用方）才用原来的时间戳 + 序号。
    new_id = str(item_id or "").strip()[:120] or f"{int(now.timestamp())}-{len(data['items']) + 1}"
    item = {
        "id": new_id,
        "q": question,
        "a": answer,
        "at": now.isoformat(timespec="seconds"),
        "model": str(model or "")[:80],
        "tokens_in": max(0, int(tokens_in or 0)),
        "tokens_out": max(0, int(tokens_out or 0)),
        "ms": max(0, int(ms or 0)),
        # ★ 完整用量明细（输入/输出/缓存命中/思考），用于「详情」面板
        # ★★ 有序步骤：思考与工具调用**按发生顺序**交错，
        #   前端照这个顺序渲染（「想了什么 → 查了什么 → 又想到什么」）。
        #   think / trace 保留为兼容字段（老数据、以及只关心纯文本的场景）。
        "steps": [
            (
                {
                    "kind": "think",
                    "text": _clean_text(str(x.get("text") or ""))[:MAX_THINK],
                }
                if str(x.get("kind") or "") == "think"
                else {
                    "kind": "tool",
                    "name": str(x.get("name") or "")[:40],
                    "chars": max(0, int(x.get("chars") or 0)),
                    "lines": max(0, int(x.get("lines") or 0)),
                }
            )
            for x in (steps or [])[:80]
            if isinstance(x, dict)
        ],
        # ★ 思考过程与工具调用轨迹一起存：事后回看时能判断 AI 怎么走的
        "think": _clean_text(str(think or ""))[:MAX_THINK],
        "trace": [
            {
                "name": str(x.get("name") or "")[:40],
                "chars": max(0, int(x.get("chars") or 0)),
                "lines": max(0, int(x.get("lines") or 0)),
            }
            for x in (trace or [])[:40]
            if isinstance(x, dict)
        ],
        "usage": {
            "total": max(0, int((usage or {}).get("total") or 0)),
            "hit": max(0, int((usage or {}).get("hit") or 0)),
            "miss": max(0, int((usage or {}).get("miss") or 0)),
            "write": max(0, int((usage or {}).get("write") or 0)),
            "think": max(0, int((usage or {}).get("think") or 0)),
            "response": max(0, int((usage or {}).get("response") or 0)),
        },
    }
    data["items"].append(item)
    if len(data["items"]) > MAX_ITEMS:
        data["items"] = data["items"][-MAX_ITEMS:]
    _write(data_dir, vid, data, scope)
    return data


def remove_item(data_dir: str, vid: int, item_id: str, scope: str = "main") -> dict:
    """删一条（按 id）。"""
    data = _read(data_dir, vid, scope)
    data["items"] = [x for x in data["items"] if str(x.get("id") or "") != str(item_id)]
    _write(data_dir, vid, data, scope)
    return data


def clear(data_dir: str, vid: int, scope: str = "main") -> dict:
    """清空该节点的历史（文件保留为空数组，避免删文件）。"""
    data = {"vid": int(vid), "items": []}
    _write(data_dir, vid, data, scope)
    return data
