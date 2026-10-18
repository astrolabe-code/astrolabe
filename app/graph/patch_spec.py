"""★★★ 补丁动作与 `payload` 的**唯一规格** —— `B224` · 2026-10-18

## ★★★ 所有者原话（逐字）

> 「**还有啊，你那修补类型 action 字段是 varchar 意味着可以绕过，写一些奇怪的
> 东西进去，包括 payload 也是一样，万一网站有漏洞，那也可能被写入奇怪的东西
> 进去。除非有严格限制，就像刚才的类型映射一样。**」

## ★★ 两条纪律

```
① ★★ `action` 走 **smallint 映射**（* 只增不改）——* ⛔ 不靠 Django 的 `choices`
     （* 它只在表单校验，* `objects.create()` 能绕过）⚠
② ★★★ `payload` **按动作白名单**：
     · · ★ 只允许该动作的键 →* 未知键 **拒绝**（* ⛔ 不是“忽略”）
     · · ★ 值过**类型 / 枚举 / 长度**校验
     · · ★ 大小上限 `PAYLOAD_MAX_BYTES`（* 4 KB）
```

⚠★ **唯一写入入口是 `graph/curate.py`** ——* 别处 ⛔ 不许直接 `GraphPatch.objects.create` ⚠
"""

from __future__ import annotations

import json

from graph import kinds

#: ★★ 六个动作（* id 只增不改）⚠
ACTION_IDS: dict[str, int] = {
    "add_node": 1,
    "update_node": 2,
    "remove_node": 3,
    "add_edge": 4,
    "update_edge": 5,
    "remove_edge": 6,
}
ID_ACTIONS: dict[int, str] = {v: k for k, v in ACTION_IDS.items()}

#: ★ payload 大小上限（* 字节；* 补丁是“意见”，* 不该装大东西）⚠
PAYLOAD_MAX_BYTES = 4096

# ---- 字段规格：* ("str", 最大长度) / ("int", 下界, 上界) / ("kind",) / ("edge_type",) ----
_NODE_FIELDS = {
    "name": ("str", 512),
    "qname": ("str", 512),
    "file_path": ("str", 1024),
    "signature": ("str", 512),
    "lang": ("str", 32),
    "line": ("int", 0, 10**7),
    "line_end": ("int", -1, 10**7),
    "kind": ("kind",),
}

_EDGE_FIELDS = {
    "type": ("edge_type",),
    "line": ("int", -1, 10**7),
    "confidence": ("str", 16),
}

#: ★★ 每个动作**允许**的 payload 键（* 白名单；* 不在表里的动作 ⇒ 一律拒绝）⚠
PAYLOAD_SPEC: dict[str, dict[str, tuple]] = {
    # ⚠ add_node 的 payload 只有一段内部引用（* 内容本身在 Node 行里）
    "add_node": {"vid": ("int", 0, 10**18)},
    "update_node": _NODE_FIELDS,
    "remove_node": {},
    "add_edge": _EDGE_FIELDS,
    "update_edge": _EDGE_FIELDS,
    "remove_edge": {},
}


def _edge_types() -> tuple[str, ...]:
    """★ 边类型枚举（* 懒 import —— 避免 models ⇄ spec 成环）⚠"""
    from graph.models import EDGE_TYPE_NAMES

    return EDGE_TYPE_NAMES


def validate_payload(action: str, payload) -> tuple[dict | None, str | None]:
    """★★ **校验并规范化 payload**（* `B224`②）⚠

    Returns: `(clean, None)` 或 `(None, 错误文案)`

    ⚠★ 拒绝而不是忽略未知键 —— * 忽略会让人以为“写成功了” ⚠
    """
    if action not in PAYLOAD_SPEC:
        return None, f"未知动作：{action!r}"
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return None, "payload 必须是 JSON 对象"

    try:
        raw = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None, "payload 里有无法序列化的值"
    if len(raw.encode("utf-8")) > PAYLOAD_MAX_BYTES:
        return None, f"payload 太大（上限 {PAYLOAD_MAX_BYTES} 字节）"

    spec = PAYLOAD_SPEC[action]
    edge_types = _edge_types() if action in ("add_edge", "update_edge") else ()
    clean: dict = {}

    for key, value in payload.items():
        if key not in spec:
            return None, f"payload 不允许的字段：{key!r}"
        rule = spec[key]

        if rule[0] == "str":
            if not isinstance(value, str):
                return None, f"{key} 必须是字符串"
            if len(value) > rule[1]:
                return None, f"{key} 太长（上限 {rule[1]}）"
            clean[key] = value

        elif rule[0] == "int":
            # ⚠ bool 是 int 的子类 ⇒ 必须单独挡掉
            if isinstance(value, bool) or not isinstance(value, int):
                return None, f"{key} 必须是整数"
            if not (rule[1] <= value <= rule[2]):
                return None, f"{key} 超出范围（{rule[1]} ~ {rule[2]}）"
            clean[key] = value

        elif rule[0] == "kind":
            if not isinstance(value, str) or not kinds.is_registered(value):
                return None, f"{key} 是未登记的类型：{value!r}"
            clean[key] = value.strip().lower()

        elif rule[0] == "edge_type":
            if not isinstance(value, str) or value not in edge_types:
                return None, f"{key} 不是已知的边类型：{value!r}"
            clean[key] = value

        else:  # pragma: no cover —— 规格写错时兜底
            return None, f"{key} 的规格无效"

    return clean, None
