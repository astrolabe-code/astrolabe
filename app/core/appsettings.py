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
    # ⚠★★ 解析预算**不在档位配额里**（2026-11-01 所有者裁定）：
    #   「这些关系系统安全的设置，是**管理员的设置**优先级最高，不是默认设置，
    #     而是**底线**」⇒ 它是**站点级门禁参数**，见下方 `KEYS` 的"解析安全"一节 ⚠
    #   档位 / 用户可以更严，但⛔ 绝不允许把管理员定的底线顶高
    "parse_concurrency": 1,         # ★ 同时排队几个解析
    "queue_priority": 0,            # ★ 队列优先级
    "ugc_per_hour": 30,             # ★ UGC 写入频率
}

#: ★★★ **配额里每个字段是什么意思**（后台页面直接显示，⛔ 不要让人去翻代码）⚠
#:
#: > 所有者：「**键含义见 DEFAULT_QUOTA_FREE，写这个干啥？
#:   你直接把键的含义直接写出来，不就完了。**」
#:
#: ⇒ 这就是「直接写出来」的那一份：**后台「站点参数 → 配额」表里逐行展示** ✅
QUOTA_FIELDS: dict[str, str] = {
    "project_max": "最多能发布几个项目（总量，不是每天）",
    "project_per_day": "一天最多提交几次审核（★ 防刷）",
    "project_per_week": "一周最多提交几次审核（★ 防刷）",
    "repo_files_max": "单个仓库最多解析多少个文件（超了直接拒）",
    "repo_bytes_max": "单个仓库的源码大小上限（字节）",
    "storage_bytes_max": "所有项目加起来能占多少存储（字节）",
    "storage_files_max": "所有项目加起来最多多少个文件",
    "parse_concurrency": "同时排队几个解析任务（★ 越大出图越快）",
    "queue_priority": "队列优先级（★ 数值越大越先出图）",
    "ugc_per_hour": "每小时最多写多少条笔记 / 评论（★ 防刷）",
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
    # ---------------------------------------------------------- 解析安全（★ 硬底线）
    # ⚠★★ 所有者原话（2026-11-01）：
    #   「这些关系系统安全的设置，是**管理员的设置**优先级最高，
    #     **不是默认设置，而是底线**」
    #   ⇒ ★ 它们是**站点级、门禁类**（`gated=True`）：只有 superuser 能改，改动必留审计；
    #     ★ 档位 / 用户只能**更严**（取 min），⛔ 绝不能把这条底线顶高 ⚠
    #   ⇒ ★ 超限只让图不完整并记原因，⛔ **不是解析失败**（更不能因此禁止写笔记）
    "parse_files_max": KeySpec(
        "parse_files_max",
        int,
        5_000,
        "解析文件数底线",
        "★ 一次解析最多扫多少个文件；超过即停（图不完整，但不判失败）",
        gated=True,
    ),
    "parse_seconds_max": KeySpec(
        "parse_seconds_max",
        int,
        120,
        "解析墙钟底线（秒）",
        "★ 整次解析最多跑多久；⚠ 防「许多文件长时间解析，一直拖着服务器」",
        gated=True,
    ),
    "parse_nodes_max": KeySpec(
        "parse_nodes_max",
        int,
        300_000,
        "解析节点数底线",
        "★ 最多产出多少节点；⚠ 实测 2MB C 文件 = 8.9 万节点 / 300MB 内存，无上限会 OOM",
        gated=True,
    ),
    "parse_file_seconds": KeySpec(
        "parse_file_seconds",
        int,
        5,
        "单文件解析底线（秒）",
        "★ 单个文件最多解析多久（C 层硬超时）；⚠ 防一个病态文件卡死整次解析",
        gated=True,
    ),

    # ---------------------------------------------------------- 队列公平（★ 硬底线）
    # ⚠★★ 为什么需要：单 worker 串行 ⇒ **一个人刷满队列 = 所有人干等** ⚠
    #   · 全局上限：队列里最多躺多少条作业（超了新提交直接拒，给出明确文案）
    #   · 单用户硬顶：即使档位给了 3，也不能超过管理员这条线
    #   ⚠ 档位 `parse_concurrency` 只是"特权"，⛔ 不能突破这里的管理员底线
    "queue_max_jobs": KeySpec(
        "queue_max_jobs",
        int,
        50,
        "解析队列长度底线",
        "★ 队列里最多排多少条作业；满了 ⇒ 新提交直接拒绝（★ 防一个人把队列刷爆）",
        gated=True,
    ),
    "queue_user_max": KeySpec(
        "queue_user_max",
        int,
        3,
        "单用户排队底线",
        "★ 一个用户最多同时排几条；⚠ 档位只能更小，⛔ 不能突破这条",
        gated=True,
    ),

    # ---------------------------------------------------------- 注册 / 登录（U4.6）
    "registration_open": KeySpec(
        "registration_open",
        bool,
        False,
        "注册入口对所有人可见",
        # ★★★ `B170` **重新定义了它**：★ 它管的是【**入口可见性**】，❌ 不是"彻底关掉注册" ——
        #   ★ `True` ⇒ 入口对所有人可见 + 可注册；
        #   ★★ `False` ⇒ 入口隐藏（前端不显示注册按钮），⚠ **但持邀请码者仍可注册** ✅
        #   ⚠★ 想**彻底停掉注册**请用 `paused`（★ 那才是重锤）
        "★ 一期默认【关】—— ★ 邀请制测试期（U4.7）：★ 入口对普通访客不显示，"
        "⚠ 但**持邀请码者仍可注册**（`B170` 改的语义，旧写法会让邀请码变成废纸）；"
        "★ 要彻底停掉注册用 `paused`",
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
    # ------------------------------------------------- 登录会话（B245 / B246）
    # ★★ 2026-10-25 所有者裁定：**公网改用 Django session，弃用自研 Bearer 令牌**
    #   · · 原话：「现有的 397 个 ApiToken直接删掉……一周就差不多了，而且后台应该可调」
    #   · · ⇒ 原来的 `auth.token_ttl_days`（30）/ `auth.token_ttl_days_short`（7）**两个键作废**
    #     （* 令牌没了，它们再无对象）⚠
    "auth.session_ttl_days": KeySpec(
        "auth.session_ttl_days",
        int,
        7,
        "登录会话有效期（天）",
        "★ 所有者裁定「一周就差不多了，而且后台应该可调」（B246）⇒ 默认 7 天；"
        "★★ 未勾「记住我」时是「浏览器关闭即失效」（set_expiry(0)），不受本键影响；"
        "⚠ 下限 1 天 —— 配成 0 会让用户「登录成功但下一秒就掉线」，极难排查",
    ),
    # ---------------------------------------------------------- 界面行为
    "ui.resume_dwell_seconds": KeySpec(
        "ui.resume_dwell_seconds",
        int,
        20,
        "「继续上次」的停留阈值（秒）",
        "★ 停在一个节点上超过这么多秒，才把它记成「上次看到的位置」（`D120`）；"
        "⚠ 太短的话，随手扫一眼的节点也会被存下来，存档会漂移；"
        "★ 写了笔记 / 评论则**立刻**记，不受本阈值限制；"
        "★★ **填 0 = 关闭「继续上次」**；"
        "⚠ 建议 10~60 秒 —— 设成几百秒等于关掉了（页面会显示换算，便于自查）",
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
        "普通用户能做什么、能做多少。⚠ 下面逐行列出了每个字段的含义；"
        "★ 改大了等于放宽限制，⚠ 改小了会让已经超额的旧项目无法再更新。",
    ),
    "quota.vip": KeySpec(
        "quota.vip",
        dict,
        DEFAULT_QUOTA_VIP,
        "VIP 配额",
        "VIP 的额度。★ 只比普通用户高在「数量 / 排队 / 存储」，"
        "❌ 一处也不落在「能看到什么」上 —— 那是内容平等的红线。"
        "⚠ 下面逐行列出了每个字段的含义。",
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


#: ★★ 解析预算的四个键（**顺序**即优先级：都只允许"更严"，不允许更松）⚠
PARSE_LIMIT_KEYS = (
    "parse_files_max",
    "parse_seconds_max",
    "parse_nodes_max",
    "parse_file_seconds",
)

#: 映射到 `scan_and_parse` 的参数名（一处声明，调用方不用记）
PARSE_LIMIT_ARGS = {
    "parse_files_max": "max_files",
    "parse_seconds_max": "max_seconds",
    "parse_nodes_max": "max_nodes",
    "parse_file_seconds": "file_timeout_s",
}


def parse_limits(stricter: dict[str, Any] | None = None) -> dict[str, Any]:
    """★★ **解析安全底线**（`{max_files, max_seconds, max_nodes, file_timeout_s}`）

    ## 为什么不是"默认值"，而是"底线"

    所有者原话（2026-11-01）：

    > 「这些关系系统安全的设置，是**管理员的设置**优先级最高，
    >  **不是默认设置，而是底线**」

    ```
    取值      只认站点参数（`KEYS` 里那四个 `gated=True` 的键）
              ⛔ 不读档位配额、不读用户覆盖 —— 它们是特权，不是安全边界
    stricter  允许调用方传「更严」的值（如某个档位想更保守）⇒ **取 min**
              ⛔ 传更松的值无效：底线不会被顶高
    ```

    ⚠ 非正数（0 / 负数 / 空）一律回落到代码里的常量 —— ⛔ 不允许"设 0 就等于不限制"，
      那等于把底线变成一个空开关。
    """
    out: dict[str, Any] = {}
    stricter = stricter or {}
    for key in PARSE_LIMIT_KEYS:
        spec = KEYS[key]
        hard = int(spec.default)                    # ★ 代码里的常量 = 最后兜底
        try:
            admin = int(get(key))                   # ★ 管理员在后台设的值
        except Exception:  # noqa: BLE001
            admin = hard
        if admin <= 0:
            admin = hard                            # ⛔ 0 不是"不限"，是"没设"
        value = admin
        if key in stricter:
            try:
                want = int(stricter[key])
            except (TypeError, ValueError):
                want = value
            if want > 0:
                value = min(value, want)            # ★ 只能更严
        out[PARSE_LIMIT_ARGS[key]] = float(value) if key == "parse_file_seconds" else value
    return out


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
