"""Astrolabe · 共享内核：参数中心（`AppSetting` 的读写封装）

★ 依据 `USERS-AND-AUTH.md`：★ **配额与开关必须可配置，❌ 不得硬编码**（`U6` 要点 3）。

★★ 三个必须有的理由：

| # | 理由 |
|---|---|
| **1** | ★ **调一次额度不该发一次版** —— 否则运营等于开发 |
| **2** | ★★ **"可开可关"是 `PRODUCT-VERSIONS.md` F 节的硬要求** —— 将来把企业功能收回付费层时要能用开关切换 |
| **3** | ★★ **紧急时刻要能"一键收"** —— 如 `license_require_file`：★ **现在关着（便于前期测试）**，★ **以后打开就收紧**（`B143`） |

⚠★ **本模块不做进程内缓存 —— 这是有意的**：

    ⚠ `paused`（门禁）这类参数**必须"改了立刻生效"**；
    ★ 参数表只有十几行，一次全表查询 **< 1ms**，
    ★★ **不值得为它引入"缓存不一致"的风险**（`ARCHITECTURE.md` A0-3 的"Web 层无状态"也要求如此）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ===========================================================================
# 配额默认值（`U6` 配额矩阵）
# ===========================================================================

#: ★ 普通用户配额（`U6`）
DEFAULT_QUOTA_FREE: dict[str, Any] = {
    "project_max": 3,               # ★ 能发布几个项目（总量）
    # ★★ 上传频率（`U3.9` 防刷）—— 见 `core/quota.py`
    "project_per_day": 3,           # ★ 一天最多提交几次审核
    "project_per_week": 8,          # ★ 一周最多提交几次审核
    "repo_files_max": 5_000,        # ★ 单仓库文件数上限
    "repo_bytes_max": 100 * 1024 * 1024,   # ★ 单仓库源码大小上限
    # ★★ **用户存储空间总量**（`B152`）——
    #   ★ 这是"VIP 空间更大"的**落地处**：★ 单仓库上限一样，但**能放的总量不同**。
    "storage_bytes_max": 512 * 1024 * 1024,        # ★ 512 MB
    "storage_files_max": 20_000,                    # ★ 所有项目加起来最多多少个文件
    "parse_concurrency": 1,         # ★ 同时排队几个解析
    "queue_priority": 0,            # ★ 队列优先级
    "ugc_per_hour": 30,             # ★ UGC 写入频率
}

#: ★★ VIP 配额 —— ⚠★ **只比普通高在"额度 / 排队 / 加速器"上**
#: ❌ **一处也没落在"能看到什么"上**（`U1` 的核心纪律）
DEFAULT_QUOTA_VIP: dict[str, Any] = {
    "project_max": 20,
    "project_per_day": 10,          # ★★ 「真有人厉害，也得给他创造空间」（用户原话）
    "project_per_week": 40,
    "repo_files_max": 20_000,
    "repo_bytes_max": 500 * 1024 * 1024,
    # ★★ **VIP 的存储空间**（`B152`）—— ★ 这就是「VIP 空间更大」的**具体体现**；
    #   ★★ 且它符合 `U1` 铁律：★ 只是**额度**更大，❌ 不是"能看更多"
    "storage_bytes_max": 5 * 1024 * 1024 * 1024,    # ★ 5 GB
    "storage_files_max": 200_000,
    "parse_concurrency": 3,
    "queue_priority": 10,           # ★ 同样排队，★ **VIP 先出图**
    "ugc_per_hour": 120,
}


# ===========================================================================
# 键定义
# ===========================================================================

@dataclass(frozen=True)
class KeySpec:
    """★ 每个参数键必须有：**默认值 + 类型 + 说明**。

    ⚠★ **没有说明的参数是灾难** —— ★ 半年后没人知道它是干什么的、能不能改。
    """

    key: str
    type: type
    default: Any
    label: str            # ★ 人类可读的名字（★ 后台直接显示）
    note: str = ""        # ★ 为什么存在 / 改它会怎样
    gated: bool = False   # ★★ **门禁类** —— 影响全站可用性，⚠ 改动必须留审计


#: ★★ 参数注册表 —— ★ **唯一权威**（❌ 不要在别处硬编码这些键名）
KEYS: dict[str, KeySpec] = {
    # ---------------------------------------------------------- 门禁（★ 最重）
    "paused": KeySpec(
        "paused",
        bool,
        False,
        "整站停服",
        "★ 打开后【所有人】（含已登录）都被拦；⚠ 这是重锤，不要当普通开关用",
        gated=True,
    ),
    # ---------------------------------------------------------- 注册 / 登录（U4.6）
    "registration_open": KeySpec(
        "registration_open",
        bool,
        False,
        "允许新注册",
        "★ 一期默认【关】—— ★ 邀请制测试期（U4.7）；⚠ 关闭时 OAuth 新用户也一律拒绝（U4.8）",
    ),
    "login_open": KeySpec(
        "login_open",
        bool,
        True,
        "允许新登录",
        "★ 只拦【新登录】，❌ 不影响已有 token（⚠ 若影响已登录用户，那就是 paused，见 U4.6）",
    ),
    "invite_required": KeySpec(
        "invite_required",
        bool,
        True,
        "注册需要邀请码",
        "★ 邀请制总开关（U4.7）",
    ),
    "invite.default_uses": KeySpec(
        "invite.default_uses",
        int,
        1,
        "邀请默认可用次数",
        "★ 默认 1 = 「用一次即失效」（U4.7 规则 1）—— ⚠ 否则一个码泄露 = 无限注册",
    ),
    "invite.default_valid_days": KeySpec(
        "invite.default_valid_days",
        int,
        7,
        "邀请默认有效期（天）",
        "★ U4.7 规则 2 —— ⚠ 必须 > 0；★★ 填 0/负数会【直接报错】，"
        "❌ 不会静默变成「永不过期」（否则一个泄露的码就永久有效）",
    ),
    # ---------------------------------------------------------- OAuth（U4.8）
    "oauth.state_ttl_seconds": KeySpec(
        "oauth.state_ttl_seconds",
        int,
        600,
        "OAuth 授权会话有效期（秒）",
        "★ 默认 10 分钟 —— ⚠ 用户授权打不开 / 中途去改密码时不要过早失效；"
        "★★ 也不能太长：state 一次性，但过期前它是一张「可用的门票」",
    ),
    # ---------------------------------------------------------- 令牌（U4.4 / 契约 §12）
    "auth.token_ttl_days": KeySpec(
        "auth.token_ttl_days",
        int,
        30,
        "API 令牌有效期（天）",
        "★ 契约 §12 的口径是 7 / 30 天（看用户有没有勾「记住我」）—— ★ 本键是【长】的那档；"
        "⚠ 令牌存 localStorage ⇒ 有效期越长，XSS 的窗口越大（契约 §7 的 CSP 要求同源）",
    ),
    "auth.token_ttl_days_short": KeySpec(
        "auth.token_ttl_days_short",
        int,
        7,
        "API 令牌有效期（天，未勾「记住我」）",
        "★ 契约 §12：不勾「记住我」走这一档",
    ),
    # ---------------------------------------------------------- 许可核验（U3.4 / B143）
    "license_require_file": KeySpec(
        "license_require_file",
        bool,
        False,
        "无许可证一律拒绝",
        "★ 现在【关】（便于前期测试，B143）；★★ 以后打开即收紧，❌ 不用改代码",
    ),
    # ---------------------------------------------------------- 配额（U6）
    "quota.free": KeySpec(
        "quota.free",
        dict,
        DEFAULT_QUOTA_FREE,
        "普通用户配额",
        "★ 键含义见 DEFAULT_QUOTA_FREE",
    ),
    "quota.vip": KeySpec(
        "quota.vip",
        dict,
        DEFAULT_QUOTA_VIP,
        "VIP 配额",
        "⚠ 只调额度 / 排队，❌ 绝不在这里加「能看什么」—— 那是 U1 的红线",
    ),
    "quota.upload_limit": KeySpec(
        "quota.upload_limit",
        bool,
        True,
        "启用上传频率限制",
        "★★ 防刷审核（U3.9）—— ★ 关掉则任何人可无限提交；⚠ 只在被刷爆时才关",
    ),
}


# ===========================================================================
# 读
# ===========================================================================

def _coerce(spec: KeySpec, value: Any) -> Any:
    """★ 类型归一 —— ⚠ **存进去的时候是什么类型，读出来必须是什么类型**。

    ⚠ `JSONField` 会把 `True` 存成 `true`、读回来还是 `True` ✅，
    但★ **历史数据 / 手工改库可能留下字符串** ⇒ ★ 这里做一次防御性转换。
    """
    if value is None:
        return spec.default
    try:
        if spec.type is bool:
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
        if spec.type is int:
            return int(value)
        if spec.type is dict:
            return value if isinstance(value, dict) else dict(spec.default)
    except (TypeError, ValueError):
        pass
    return value


def all_settings() -> dict[str, Any]:
    """★ **一次查询取全部参数**（含默认值合并）。

    ★ 推荐用法：★ **一个请求只调一次**，然后把结果传下去 —— ❌ 不要在每个函数里各查一次。
    """
    from core.models import AppSetting

    merged = {key: spec.default for key, spec in KEYS.items()}
    rows = AppSetting.objects.filter(key__in=list(KEYS)).values_list("key", "value")
    for key, value in rows:
        spec = KEYS.get(key)
        if spec is not None:
            merged[key] = _coerce(spec, value)
    return merged


def get(key: str) -> Any:
    """取单个参数（★ 未定义的键 ⇒ `KeyError` —— ⚠ **不要用未注册的键**，那会变成隐形配置）。"""
    spec = KEYS.get(key)
    if spec is None:
        raise KeyError(f"未注册的参数键：{key}（⚠ 请先在 core/appsettings.py 的 KEYS 里声明）")

    from core.models import AppSetting

    row = AppSetting.objects.filter(key=key).values_list("value", flat=True).first()
    return _coerce(spec, row) if row is not None else spec.default


def get_bool(key: str) -> bool:
    return bool(get(key))


# ===========================================================================
# 写（★ 必须留审计）
# ===========================================================================

def set_value(key: str, value: Any, *, actor=None) -> Any:
    """改一个参数 —— ★★ **自动写审计**（`U2.5` 纪律 1）。

    ⚠★ **门禁类参数（`gated=True`）的改动尤其要记** ——
    ★ 因为它影响全站，⚠ 出事时要能回答"**谁在什么时候关的**"。
    """
    from core.models import AppSetting, AuditLog

    spec = KEYS.get(key)
    if spec is None:
        raise KeyError(f"未注册的参数键：{key}")

    if spec.gated and actor is not None and not getattr(actor, "is_superuser", False):
        raise PermissionError(f"门禁类参数 {key} 只允许 superuser 修改")

    before = get(key)
    AppSetting.objects.update_or_create(
        key=key,
        defaults={"value": value, "updated_by": actor if getattr(actor, "pk", None) else None},
    )
    after = get(key)

    AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action="setting.change",
        target_kind="AppSetting",
        target_id=key,
        detail={
            "label": spec.label,
            "gated": spec.gated,
            "before": before,
            "after": after,
        },
    )
    return after


# ===========================================================================
# 配额
# ===========================================================================

def quota_for(tier: str, profile=None) -> dict[str, Any]:
    """★ 取某档位的配额：**档位默认 → 参数覆盖 → 用户级覆盖**（`U6`）。

    ⚠ 三级是有意的：★ **档位默认是代码里的常量**（改代码）、
    ★ **参数覆盖是运营可调**（改数据库）、
    ★★ **用户级覆盖是个案**（★ 管理员给某个用户单独放宽）。
    """
    key = "quota.vip" if tier == "vip" else "quota.free"
    quota = dict(get(key) or {})
    override = getattr(profile, "quota_override", None) or {}
    quota.update(override)
    return quota
