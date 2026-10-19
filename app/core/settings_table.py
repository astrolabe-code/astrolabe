"""Astrolabe · **用户档 / 项目档设置**（★ `B190` · 2026-10-15）

★★★ **本模块把"设置"从一档扩成三档**：

```
① 全局档   core_appsetting   （★ 已有，* 本模块不动它）✅
② 用户档   core_usersetting  （★ 新增）
③ 项目档   core_projectsetting（★ 新增）
```

## ★★ 所有者原话（逐字）

> 「**我差点忘了，你要有张属性或设置表，用来设置一下用户或项目的可能我还没想到的设置，
> 就像IDE的设置一样。**」

> 「**三级继承很好，不过，这个属性设置是一些按钮之类的，不是用户想加什么属性，
> 就能加什么属性的。属性种类是我指定了的**」

## ★★ 由此定下六条（* 少一条就会退化成杂物袋）

| # | 规矩 | 为什么 |
|---|---|---|
| ① | ★★ **键在代码注册表里声明** | ★ 前端**按注册表渲染控件**；* 用户**不能**自己造字段 ⚠ |
| ② | ★★ **未设置 = 不存行** | ★ 以后**改默认值会自动生效**（* 否则老行永远钉着旧默认）⚠ |
| ③ | ★★ **三级继承** | ★ 全局默认 → 用户覆盖 → 项目覆盖 ✅ |
| ④ | ★ **值存 jsonb** | ★ 与 `core_appsetting` **一致**（* 不为类型约束放弃一致性）⚠ |
| ⑤ | ★★ **读走缓存、写失效缓存** | ★ 设置是**高频读** ⇒ ★ 不缓存会变热查询 ⚠ |
| ⑥ | ★★ **改动留审计** | ★ "谁在什么时候关的"必须查得到 ⚠ |

## ⚠★ 与 `core/appsettings.py` 的分工

```
★★ `core/appsettings.py` ⇒ ★ **全局档**（* 已有，* 继续用它）✅
★★ 本模块             ⇒ ★ **用户档 + 项目档** + ★ 三级继承的读取口径 ✅
```

⚠★ **为什么不为每档写三套 get/set**：
  ★★ 三档的差别只在"属主是谁"—— ★ 那是**一个维度**，❌ 不是三个概念 ⚠
  ⇒ ★ 所以本模块用**同一对函数** + 一个 `scope` 参数 ✅
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ===========================================================================
# 键注册表（★ 与 appsettings.KeySpec 同一形状，* 只多一个 scopes）
# ===========================================================================


@dataclass(frozen=True)
class ScopedKeySpec:
    """★ 一个可分档的键：**默认值 + 类型 + 说明 + 适用哪几档**。

    ⚠★ **没有说明的参数是灾难** —— ★ 半年后没人知道它是干什么的、能不能改。
    """

    key: str
    type: type
    default: Any
    label: str
    note: str = ""
    #: ★★ **适用哪几档**（* `global` / `user` / `project`）——
    #: ★★ 它决定"这个键在哪些表里可能出现" ⚠
    #: ★ 例：* `("project",)` ⇒ ★ 只有 `core_projectsetting` 能有它 ✅
    scopes: tuple[str, ...] = ("global",)
    #: ★★ **门禁类** —— ★ 用户自己改不了，* 只有管理员能改 ⚠
    #: ★（★ 所有者 2026-10-14 定：* 「历史版本数是**网站管理员可以给每个用户单独指定**」）⚠
    gated: bool = False


#: ★★ **用户档 / 项目档的键注册表** —— ★ **唯一权威**
#: ⚠★ 全局档的键仍在 `core/appsettings.py::KEYS`（* 那里不动，* 避免两处定义同一个键）⚠
SCOPED_KEYS: dict[str, ScopedKeySpec] = {
    # ---------------------------------------------------------- 笔记 · 段评（B189）
    "note.orphan_comment_policy": ScopedKeySpec(
        "note.orphan_comment_policy",
        str,
        "hide",
        "段落被修改后，原段评如何处理",
        # ★★★ 所有者原话（2026-10-14，逐字）：
        #   「**修改段落了，评论默认不再显示，但要给作者三个选项，
        #     挂在新写的段落上，放底部评论区里，默认的不显示。
        #     嗯，这个不要每次修改都跳，记录到项目设置里**」
        # ★★ 三个取值：
        #   · ★ `attach_to_new`  ⇒ ★ 挂到新写的那一段上（★ 唯一会"猜"的策略 ⇒ ⚠ 猜错就挂错）⚠
        #   · ★ `move_to_chapter` ⇒ ★ 放底部评论区（★ 章评区），* 标注"原段落已变更" ✅
        #   · ★★ `hide`           ⇒ ★ 默认的"不显示"（* 数据仍在，* 不猜）✅
        # ★★ 默认取 `hide` 的理由：* **不猜** ⚠
        #   （* `attach_to_new` 是三条里唯一会主动猜的，* 猜错就把评论挂到别处）⚠
        "★ 段落被改后，挂在它上面的段评怎么办；"
        "★ 这是【项目级策略】—— 作者一次定好，以后自动照办（不要每次改都弹提示）；"
        "★ 三个取值：attach_to_new（挂到新段，会猜）/ move_to_chapter（移到章评区）"
        "/ hide（不显示，数据仍在）；★ 默认 hide，因为它是唯一不猜的",
        scopes=("project",),
    ),
    # ---------------------------------------------------------- 图谱 · 流星（D104）
    "graph.meteor.enabled": ScopedKeySpec(
        "graph.meteor.enabled",
        bool,
        True,
        "图谱页显示流星轨迹",
        # ★★★ 所有者原话（2026-10-19，逐字）：
        #   「**微调的设置，你直接集成到用户设置，不就行了，让用户自己调。
        #     我记得我设计了全局，用户，项目三级设置继承的。**」
        # ★★ 用户档：* 每个人自己决定要不要看（* 默认开）✅
        "★ 关掉后图谱页不再画流星层（* 性能敏感 / 嫌吵时用）；★ 用户档设置",
        scopes=("user",),
    ),
    "graph.meteor.speed": ScopedKeySpec(
        "graph.meteor.speed",
        int,
        5,
        "流星速度（每帧相位增量 ×1000，越小越慢）",
        # ★ 用整数存：* `5` = 0.005（* `_coerce` 只认 bool/int/str，* 浮点会原样透传）⚠
        "★ 值是「每帧相位增量 × 1000」：5 = 0.005（默认，慢速）；10 = 0.01（原速）；"
        "20 = 0.02（快）；★ 越小越慢",
        scopes=("user",),
    ),
    "graph.meteor.size_pct": ScopedKeySpec(
        "graph.meteor.size_pct",
        int,
        25,
        "流星大小（占发出节点直径的百分比）",
        # ★ 25 ⇒ * 节点 14px ⇒ 流星 3.5px（* 所有者定的 1/4）✅
        "★ 100 = 和节点一样大；25 = 节点的 1/4（默认）；10 = 节点的 1/10（很小）",
        scopes=("user",),
    ),
    # ---------------------------------------------------------- 笔记 · 历史版本（B191）
    "note.revision_limit": ScopedKeySpec(
        "note.revision_limit",
        int,
        10,
        "每篇笔记最多保留几个历史版本",
        # ★★★ 所有者原话（2026-10-14，逐字）：
        #   「**笔记要有历史版本，不过不用太多，最多追溯10个版本就行**」
        #   「**嗯，这才对嘛，保存十个是保持最近十个，你别到了十个就不保存了**」
        # ★★ 环形缓冲：* **一直存、永不停止**，* 每存一份新的就挤掉最老的 ⚠
        #   （* ❌ 不是"满 10 个就停"—— * 那是最容易实现错的一处）⚠
        # ★★ 而"当前正文"【不占】这 10 个位置 ✅
        "★ 环形缓冲：一直存、永不停止，每存一份新的就删掉最老的那一份；"
        "★ 当前正文不占这 N 个位置；★ 超出上限即永久删（界面须说明）",
        scopes=("user",),
        gated=True,  # ★★ 只有管理员能改（所有者 2026-10-14 定）
    ),
    "note.revision_interval": ScopedKeySpec(
        "note.revision_interval",
        int,
        180,
        "历史版本自动存档间隔（秒）",
        # ★★ 业界先例：* 口袋写作「**每三分钟自动存一次档**」⚠
        # ★★ 实现上**不需要后台定时器**：
        #   · ★ 用户保存正文时，* 顺手判断"距上次快照是否超过间隔" ⇒ 超了就存一份 ✅
        #   · ★★ 没人写的时候本来就没有新内容可存 ⇒ ★ 定时器纯属浪费 ⚠
        "★ 秒；业界先例（口袋写作）是 180；"
        "★ 实现不需要后台定时器——保存正文时顺手判断是否超过间隔即可",
        scopes=("user",),
        gated=True,
    ),
}


def spec_of(key: str) -> ScopedKeySpec:
    """取一个键的定义（★ 未注册 ⇒ `KeyError`，* ❌ 不让未注册的键流过去）。

    ⚠★ 这是"**属性种类由所有者指定**"的**硬执行点** ⚠
      （* 所有者 2026-10-14：*「**不是用户想加什么属性，就能加什么属性的**」）⚠
    """
    try:
        return SCOPED_KEYS[key]
    except KeyError:
        raise KeyError(
            f"未注册的设置键：{key!r} —— 请先在 core/settings_table.py::SCOPED_KEYS 里声明"
        ) from None


def keys_for(scope: str) -> list[ScopedKeySpec]:
    """某一档**可用**的键（★ 按 `scopes` 筛）。

    ★ 前端**按这个列表渲染控件**（* 开关 / 下拉 / 输入框）✅
    """
    return [s for s in SCOPED_KEYS.values() if scope in s.scopes]


# ===========================================================================
# 读（★ 三级继承）
# ===========================================================================

def _cache():
    """★ 设置的缓存容器（★ 走 Django 的 cache 抽象；❌ 不可用时退回无缓存）。

    ⚠★ 键名带 `ss:` 前缀 —— ★ 免得和别的东西撞 ⚠
    """
    try:
        from django.core.cache import cache

        return cache
    except Exception:  # noqa: BLE001
        return None


def _ck(scope: str, owner_pk, key: str) -> str:
    return f"ss:{scope}:{owner_pk}:{key}"


def _coerce(spec: "ScopedKeySpec", raw) -> object:
    """把存下来的 jsonb 值**按注册表的类型**转回去。

    ⚠★ jsonb 不保类型（* `int` 可能存成 `float`、* `bool` 可能存成 `0/1`）⚠
      ⇒ ★★ 所以读出来**必须按注册表转一次** ✅
    """
    if raw is None:
        return spec.default
    try:
        if spec.type is bool:
            return bool(raw)
        if spec.type is int:
            return int(raw)
        if spec.type is str:
            return str(raw)
    except (TypeError, ValueError):
        return spec.default
    return raw


def resolve(key: str, *, project=None, user=None):
    """★★ **按三级继承取一个设置的值**。

    ```
    项目档 → 用户档 → 全局档 → ★★ 代码里的默认值
    ```

    ⚠★ **未设置 = 不存行** ⇒ ★ 所以"取不到"**不是错误**，* 是**正常回落** ✅
      （* 这也正是"以后改默认值会自动生效"的原因）⚠

    ⚠★ `project` / `user` 都传 ⇒ ★ **项目档优先**
      （* 同 IDE 的"工作区设置覆盖用户设置"）✅

    ★ 返回 `(值, 来源)` —— ★ 来源用于**后台显示"这一项为什么是这个值"** ⚠
    """
    spec = spec_of(key)
    cache = _cache()

    for scope, owner in (("project", project), ("user", user), ("global", None)):
        # ★★ 这一档不适用这个键 ⇒ ★ 跳过（* 例：* `("user",)` 的键没有项目档）⚠
        if scope not in spec.scopes:
            continue
        if scope != "global" and owner is None:
            continue

        ck = _ck(scope, getattr(owner, "pk", None), key)
        if cache is not None:
            hit = cache.get(ck)
            if hit is not None:
                return hit, scope

        from core.models import AppSetting, ProjectSetting, UserSetting

        if scope == "project":
            row = ProjectSetting.objects.filter(project=owner, key=key).first()
        elif scope == "user":
            row = UserSetting.objects.filter(user=owner, key=key).first()
        else:
            row = AppSetting.objects.filter(key=key).first()

        if row is not None:
            val = _coerce(spec, row.value)
            if cache is not None:
                cache.set(ck, val, timeout=300)
            return val, scope

    return spec.default, "default"


def get(key: str, *, project=None, user=None):
    """只取值（★ 不给来源）—— ★ 给业务代码用 ✅"""
    return resolve(key, project=project, user=user)[0]


def all_for(*, project=None, user=None) -> dict:
    """★★ **某一档下全部设置的值**（★ 后台设置页 / 前端一次拉全）。

    ⚠★ 只返回**该档可用**的键 —— ★ 例：* 项目设置页不该出现 `note.revision_limit` ⚠
    """
    scopes = []
    if project is not None:
        scopes.append("project")
    if user is not None:
        scopes.append("user")
    if not scopes:
        scopes = ["global"]
    out: dict = {}
    for s in SCOPED_KEYS.values():
        if any(sc in s.scopes for sc in scopes):
            out[s.key] = resolve(s.key, project=project, user=user)[0]
    return out


# ===========================================================================
# 写（★ 必须留审计）
# ===========================================================================

def set_value(key: str, value, *, project=None, user=None, actor=None):
    """★★ **改一个设置** —— ★★ 自动写审计 + 失效缓存。

    ## ⚠★ 三条硬规矩

    ```
    ① ★★ 键必须已注册          ⇒ ★ 否则 KeyError（* 未注册的键流不过去）⚠
    ② ★★ 门禁类只允许管理员改  ⇒ ★ 否则 PermissionError ⚠
    ③ ★★ 落哪一档由 scope 决定 ⇒ ★ 例：* ("user",) 的键【不能】写到项目档 ⚠
    ```

    ⚠★ **为什么不支持更花的操作**：
      ★★ 一次只改一个键、* 一个档 ⇒ ★ 语义最直白，* 也最好记审计 ⚠
      · ★ 想回到默认 ⇒ ★ 调 `clear()` ✅
    """
    from core.models import AppSetting, AuditLog, ProjectSetting, UserSetting

    spec = spec_of(key)

    # ---- ② 门禁类：* 只有管理员能改 ----
    if spec.gated:
        who = actor
        is_admin = bool(
            getattr(who, "is_superuser", False) or getattr(who, "is_staff", False)
        )
        if who is None or not is_admin:
            raise PermissionError(
                f"门禁类设置 {key} 只允许管理员修改"
                "（gated=True；所有者 2026-10-14 定：用户自己改不了）"
            )

    # ---- ③ 定档位 ----
    if project is not None and "project" in spec.scopes:
        scope, owner, Model = "project", project, ProjectSetting
    elif user is not None and "user" in spec.scopes:
        scope, owner, Model = "user", user, UserSetting
    elif "global" in spec.scopes:
        scope, owner, Model = "global", None, AppSetting
    else:
        raise ValueError(
            f"设置 {key} 不适用于传入的档位"
            f"（它的 scopes={spec.scopes}；project={project!r}, user={user!r}）"
        )

    before, _ = resolve(key, project=project, user=user)
    row, _ = Model.objects.update_or_create(
        key=key,
        **({"project": owner} if scope == "project" else {}),
        **({"user": owner} if scope == "user" else {}),
        defaults={
            "value": value,
            "updated_by": actor if getattr(actor, "pk", None) else None,
        },
    )
    after, _ = resolve(key, project=project, user=user)

    # ---- 失效缓存（* 含下游档：* 改了用户档，* 项目档的解析结果可能变）----
    cache = _cache()
    if cache is not None:
        for sc, ow in (("project", project), ("user", user), ("global", None)):
            if sc in spec.scopes and (sc == "global" or ow is not None):
                cache.delete(_ck(sc, getattr(ow, "pk", None), key))

    AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action="setting.change",
        target_kind=Model.__name__,
        target_id=key,
        detail={
            "label": spec.label,
            "scope": scope,
            "owner": getattr(owner, "pk", None),
            "gated": spec.gated,
            "before": before,
            "after": after,
        },
    )
    return after


def clear(key: str, *, project=None, user=None) -> None:
    """★★ **删掉这一行 ⇒ 回到默认**。

    ⚠★ 这正是"**未设置 = 不存行**"的另一半：
      · ★ 存一行 ⇒ ★ 覆盖默认 ✅
      · ★★ 删一行 ⇒ ★ **自动回到代码里的默认值** ⚠
      · ★（★ 若一设置就存一个默认值 ⇒ ★ 以后改默认值**对老行不生效** ⚠）
    """
    from core.models import ProjectSetting, UserSetting

    spec = spec_of(key)
    if project is not None and "project" in spec.scopes:
        ProjectSetting.objects.filter(project=project, key=key).delete()
        cache = _cache()
        if cache is not None:
            cache.delete(_ck("project", project.pk, key))
    elif user is not None and "user" in spec.scopes:
        UserSetting.objects.filter(user=user, key=key).delete()
        cache = _cache()
        if cache is not None:
            cache.delete(_ck("user", user.pk, key))
    else:
        raise ValueError(f"设置 {key} 没有可清除的档位（scopes={spec.scopes}）")
