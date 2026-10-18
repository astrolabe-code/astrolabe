"""★★★ 补丁动作与 `payload` 的**唯一规格** —— `B224` / `B229` · 2026-10-18

## ★★★ 所有者原话（逐字）

> 「**payload 写入的键值一定要是复合要求的，也就是，我之前在节点表里定好的，
> 为此，在提交时，把 payload 拆开，逐个检查也没关系。反正修补是不常有的事，
> 慢一点没关系。主要就是不能有奇怪的键值对写进数据库。**」

> 「**前端也做同样限制，浓选择列表，天然不允许非法键值对出现。
> 形成前端防君子，后端防小人。**」

## ★★ `B229`：**校验以模型为准**（反射，⛔ 不手写白名单）

```
★★ 键必须是模型里**真有的字段**，* 值必须合该字段的**类型与长度** ⚠
  · · ★ 手写清单迟早和模型漂移（* B224 的 PAYLOAD_SPEC 已作废）⚠
  · · ★★ 好处：* 模型加一列 ⇒* 自动可改，* 校验代码不用动 ✅
```

## ★★ 不许改的字段（排除项）

| 排除 | 为什么 |
|---|---|
| 主键（`node_id` / `id`） | 身份 |
| 外键（`repo` / `project` / `node` / `from_node` / `to_node`） | 归属走专门动作 |
| `stable_vid` | **派生列** —— 按内容算的，手改 = 伪造身份 |
| `versions` | 版本归属，系统维护 |
| `created_at` / `updated_at` | 时间戳 |

## ★★ 前端同源（`B230`）

`graph_meta()` 输出可改字段 + 控件类型 + 上限 + 枚举 —— **同一个推导函数**，
后端校验与前端表单不漂移。端点见 `web/views/graph.py::meta`。
"""

from __future__ import annotations

from functools import lru_cache

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

#: ★ payload 大小上限（* 字节；* 补丁是「意见」，* 不该装大东西）⚠
PAYLOAD_MAX_BYTES = 4096

#: ★★ **排除**的字段（* 不许手改；* 见模块文档）⚠
_EXCLUDE_FIELDS = frozenset(
    {"stable_vid", "versions", "created_at", "updated_at", "id", "node_id"}
)

#: ★★ 走枚举下拉的字段（* 值来自 `graph/kinds.py` / 边类型）⚠
_ENUM_FIELDS = {
    "kind": "kinds",
    "type": "edge_types",
}

#: ★ 每个动作校验哪个模型（* `add_node` 的 payload 只有内部 vid，* 单独处理）⚠
_ACTION_MODEL = {
    "update_node": "graph.Node",
    "add_edge": "graph.Edge",
    "update_edge": "graph.Edge",
}


# ---------------------------------------------------------------- 反射
def _model(path: str):
    from django.apps import apps

    return apps.get_model(path)


@lru_cache(maxsize=8)
def _field_specs(path: str) -> dict[str, tuple]:
    """★★★ **从模型反射出「可改字段 + 值规格」**（`B229`）⚠

    Returns:
        `{字段名: ("str", max_length) | ("int", 下界, 上界) | ("bool",) | ("json",)}`
    """
    from django.db import models as dj

    out: dict[str, tuple] = {}
    for f in _model(path)._meta.get_fields():
        # ⚠ 只要**具体的、非关系**字段（* 外键 / 反查 / M2M 都不算）⚠
        if not getattr(f, "concrete", False):
            continue
        if f.primary_key or f.many_to_one or f.one_to_one or f.many_to_many:
            continue
        if f.name in _EXCLUDE_FIELDS:
            continue

        if isinstance(f, dj.TextField):
            out[f.name] = ("str", None)
        elif isinstance(f, dj.CharField):
            out[f.name] = ("str", f.max_length)
        elif isinstance(f, dj.BooleanField):
            out[f.name] = ("bool", None)
        elif isinstance(f, dj.PositiveSmallIntegerField):
            out[f.name] = ("int", 0, 32767)
        elif isinstance(f, dj.PositiveIntegerField):
            out[f.name] = ("int", 0, 2147483647)
        elif isinstance(f, dj.SmallIntegerField):
            out[f.name] = ("int", -32768, 32767)
        elif isinstance(f, (dj.IntegerField,)):
            out[f.name] = ("int", -2147483648, 2147483647)
        elif isinstance(f, dj.BigIntegerField):
            out[f.name] = ("int", -(2**63), 2**63 - 1)
        elif isinstance(f, dj.JSONField):
            out[f.name] = ("json", None)
        # 其它类型（* 文件 / 二进制 …）一律**不接受** ⚠
    return out


@lru_cache(maxsize=8)
def _allowed_keys(path: str) -> tuple[str, ...]:
    """★ 该模型的**可改键**（* 报错时列给用户看）⚠"""
    return tuple(sorted(_field_specs(path)))


# ---------------------------------------------------------------- 枚举值
def _kinds() -> list[str]:
    from graph import kinds

    return sorted(kinds.KIND_IDS)


def _edge_types() -> list[str]:
    from graph.models import EDGE_TYPE_NAMES

    return list(EDGE_TYPE_NAMES)


def _enums(name: str) -> list[str] | None:
    which = _ENUM_FIELDS.get(name)
    if which == "kinds":
        return _kinds()
    if which == "edge_types":
        return _edge_types()
    return None


# ---------------------------------------------------------------- 校验
def validate_payload(action: str, payload) -> tuple[dict | None, str | None]:
    """★★★ **校验并规范化 payload**（* `B224`② / `B229`）⚠

    Returns:
        `(clean, None)` 或 `(None, 错误文案)`

    ⚠★ 未知键 ⇒ **拒绝**（⛔ 不是「忽略」—— 忽略会让人以为写成功了）⚠
    """
    if action not in ACTION_IDS:
        return None, f"未知动作：{action!r}"
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return None, "payload 必须是 JSON 对象"

    import json

    try:
        raw = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None, "payload 里有无法序列化的值"
    if len(raw.encode("utf-8")) > PAYLOAD_MAX_BYTES:
        return None, f"payload 太大（上限 {PAYLOAD_MAX_BYTES} 字节）"

    # ⓐ 不带模型的动作：payload 只能是空（* 删除就是删除）
    path = _ACTION_MODEL.get(action)
    if path is None:
        if payload:
            return None, f"{action} 不接受 payload（应为空对象）"
        return {}, None

    specs = _field_specs(path)
    clean: dict = {}

    # ⓑ 逐个键、逐个值查（* 所有者：* 「拆开逐个检查也没关系」✅）
    for key, value in payload.items():
        if key not in specs:
            return None, (
                f"payload 不允许的字段：{key!r}（可改字段见 GET /api/graph/meta/）"
            )
        rule = specs[key]

        # 枚举字段（kind / 边 type）
        enum = _enums(key)
        if enum is not None:
            if not isinstance(value, str) or value not in enum:
                return None, f"{key} 不是合法取值：{value!r}（可选：{enum}）"
            clean[key] = value
            continue

        if rule[0] == "str":
            if not isinstance(value, str):
                return None, f"{key} 必须是字符串"
            if rule[1] is not None and len(value) > rule[1]:
                return None, f"{key} 太长（上限 {rule[1]}）"
            clean[key] = value

        elif rule[0] == "int":
            # ⚠ bool 是 int 的子类 ⇒ 必须单独挡掉
            if isinstance(value, bool) or not isinstance(value, int):
                return None, f"{key} 必须是整数"
            if not (rule[1] <= value <= rule[2]):
                return None, f"{key} 超出范围（{rule[1]} ~ {rule[2]}）"
            clean[key] = value

        elif rule[0] == "bool":
            if not isinstance(value, bool):
                return None, f"{key} 必须是 true / false"
            clean[key] = value

        elif rule[0] == "json":
            if not isinstance(value, dict):
                return None, f"{key} 必须是 JSON 对象"
            clean[key] = value

        else:  # pragma: no cover —— 规格推导漏了类型时兜底
            return None, f"{key} 的规格无效"

    return clean, None


# ---------------------------------------------------------------- 前端元数据
def graph_meta() -> dict:
    """★★★ **图修补元数据**（`B230`）—— ★ 前端表单的**唯一来源** ⚠

    ```
    ★★ 与 `validate_payload` 用同一个反射函数 ⇒* 后端校验与前端表单**同源**，
      * ⛔ 不会漂移 ✅
    ```

    Returns:
        `{node_fields:[…], edge_fields:[…], kinds:[…], edge_types:[…]}`
    """
    def describe(path: str) -> list[dict]:
        rows = []
        for name, rule in sorted(_field_specs(path).items()):
            enum = _enums(name)
            if enum is not None:
                control, extra = "select", {"enum": enum}
            elif rule[0] == "str":
                control, extra = "text", {"max_length": rule[1]}
            elif rule[0] == "int":
                control, extra = "number", {"min": rule[1], "max": rule[2]}
            elif rule[0] == "bool":
                control, extra = "switch", {}
            else:
                control, extra = "json", {}
            rows.append({"name": name, "control": control, **extra})
        return rows

    return {
        "node_fields": describe("graph.Node"),
        "edge_fields": describe("graph.Edge"),
        "kinds": _kinds(),
        "edge_types": _edge_types(),
    }
