"""★★★ 节点类型（`kind`）的**唯一映射表** —— `B222` · 2026-10-18

## ★★★ 所有者原话（逐字）

> 「**这个映射，我要能方便修改，毕竟现在我也不确定类型到底有多少。
> 以后改类型，加类型，都走这个映射，彻底从后端杜绝产生奇怪的类型名称。**」

## ★★ 三条铁律

```
① ★★ **唯一来源**：* 解析器 / 写路径 / API 序列化**全用这里** ——
     · · ⛔ 别处不许再写死类型名 ⚠
② ★★★ **只增不改 id**：* id 一旦分配**永不重排、* 不复用**
     · · ★ 否则存量数据**全错位**（`B222`②）
     · · ★ **加类型 = 往 `KIND_IDS` 加一行（* 零迁移）** ✅
③ ★★ **未登记 ⇒ 拒绝**：* 人工补节点时未登记 ⇒ 400（* 杜绝怪类型）
     · · ★ 解析器遇到未登记 ⇒* `OTHER_ID`（0）+ 日志告警，* 不阻断解析 ✅
```

⚠★ 数据库列是 `smallint`（* 2 字节，* 不是字符串！）——* 类型名再长也不占表空间。
"""

from __future__ import annotations

#: ★★ 类型名 → id（* **只增不改**；* 顺序即 id，* 新增只能往末尾追加）⚠
KIND_IDS: dict[str, int] = {
    "file": 1,
    "dir": 2,
    "function": 3,
    "method": 4,
    "type": 5,
    "macro": 6,
    "variable": 7,
    "constant": 8,
    "field": 9,
    "module": 10,
    "package": 11,
    "class": 12,
    # ★★ 2026-10-31 追加：把 `type` 拆细 —— 读 C/C++/Java 时
    #   struct / union / enum / typedef / interface 是完全不同的东西，
    #   混成 "type" 会让人分不清（所有者：「细一点没关系，是有限的，
    #   换来的却是更好的阅读体验」）
    #   ⚠ 规则不变：**只增不改 id**，上面 12 个的 id 一个都不动
    "struct": 13,
    "union": 14,
    "enum": 15,
    "typedef": 16,
    "interface": 17,
    "record": 18,
}

#: ★★ 未登记类型的兜底 id（* `other`）—— ⛔ 不参与写入校验的“合法类型”⚠
OTHER_ID = 0

#: ★ id → 类型名（* 反查；* 序列化用）✅
ID_KINDS: dict[int, str] = {v: k for k, v in KIND_IDS.items()}


def kind_id(name: str) -> int:
    """★★ 类型名 → id（* 未登记 ⇒ `OTHER_ID`）⚠

    ⚠★ **写入校验请用 `is_registered()`** —— 这个函数是“宽容”的，
      * 给解析器用（* 遇到新构造时降级为 other，* 不阻断解析）✅
    """
    return KIND_IDS.get((name or "").strip().lower(), OTHER_ID)


def kind_name(kid: int) -> str:
    """★ id → 类型名（* 未知 ⇒ `other`）✅"""
    return ID_KINDS.get(int(kid or 0), "other")


def is_registered(name: str) -> bool:
    """★★ 这个名字**登记过**吗（* 人工写入的校验用）⚠"""
    return (name or "").strip().lower() in KIND_IDS
