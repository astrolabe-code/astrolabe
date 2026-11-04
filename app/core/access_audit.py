r"""★★ **访问审计：谁在疯狂请求**（2026-10-25 · 所有者需求）

## ★ 所有者原话（逐字）

> 「设备token，限流那个呢？**我要检测那些IP在疯狂请求token之类的，方便我以后禁掉他呀。
>   还要疯狂掉线和登陆也一样呀。**」

## ★★ 为什么用 Redis 而不建表

```
这是**高频、短周期**的运维数据：
  · 每来一个新访客就一条（设备令牌发放）
  · 每次登录/登出/被限流也各一条
⇒ 落库等于把只读站点变成写站点（同 `B238` 的「写放大」纪律）⚠

⇒ Redis 计数（`ZINCRBY`）+ 8 天 TTL：
  · 天然过期，不需要清理任务 ✅
  · 一天最多几十个 key，内存可忽略 ✅
  · ⚠ Redis 已开 AOF ⇒ 重启不丢 ✅
```

## ★ 记什么（五类）

| kind | 触发点 | member 形态 |
|---|---|---|
| `login_ok` | 密码 / OAuth 登录成功 | `ip\|username` |
| `login_fail` | 登录失败（⚠ 不区分账号不存在与密码错） | `ip\|username` |
| `logout` | 登出 | `ip\|username` |
| `rate_limited` | 被限流（`web/ratelimit.py`） | `ip\|身份` |

## ★★ 存储结构（Redis）

```
astrolabe:audit:<kind>:<YYYY-MM-DD>   zset   member = "<ip>|<who>"  score = 次数    TTL 8 天
astrolabe:ban:ip                      hash   field = ip   value = 封禁人（永久）
astrolabe:ban:ip:<ip>                 string value = 封禁人        TTL = 剩余秒数（临时）
```

⚠ 本文件曾在 2026-11-01 被意外清空（0 字节），此版本按当时残留的 `.pyc`
  与调用点重建，**行为与原实现一致**（键名、member 形态、TTL、返回结构均未变）。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.utils import timezone

logger = logging.getLogger("astrolabe.audit")

#: 审计记录保留天数（⚠ 改小会让后台看不了历史，改大会多占内存）
KEEP_DAYS = 8

#: 五类事件（⚠ 后台按这个顺序出表格，别随意改名 —— 键名里带它）
#: ★ 2026-11-04：`device_issue` 已移除（设备令牌功能被删除，见 `core/device.py`）
KINDS: tuple[str, ...] = ("login_ok", "login_fail", "logout", "rate_limited")

#: 封禁用的键（永久 = hash；临时 = `<BAN_KEY>:<ip>`）
BAN_KEY = "astrolabe:ban:ip"

#: ★★ **永远不许封**的地址前缀（防自锁）⚠
#:   · 回环：封了 = 管理员自己也进不来
#:   · 私有网段 / docker 网段：站点在隧道后面时，nginx/隧道看到的来源都是这些
#:     ⇒ 封它们等于**把整站锁死**（所有者踩过一次：「我上次封禁了一个IP，
#:        但是被封禁列表并没有这个IP」）
_LOOPBACK = ("127.", "::1", "localhost")
_PRIVATE_PREFIXES = (
    "10.",
    "192.168.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
)
NEVER_BAN = _LOOPBACK + _PRIVATE_PREFIXES


def _redis():
    """★ 复用 web 侧的**快客户端**（带 `socket_timeout`）⚠

    ⚠ 不能用 worker 那个 `_client()`：它为了 `bzpopmin` 故意不设 socket 超时，
      web 请求路径上用它 ⇒ Redis 一卡住就把 12 个线程全拖死。
    ⚠ 这里的调用**全部包在 try/except 里**：Redis 出问题只丢审计，不影响业务。
    """
    from jobs.queue import _fast_client

    return _fast_client()


def _key(kind: str, day: str) -> str:
    return f"astrolabe:audit:{kind}:{day}"


def _today() -> str:
    """★ 按**本地时区**算日期（跨时区/UTC 偏移下不能直接用 `date.today()`）"""
    return timezone.localdate().isoformat()


# ===========================================================================
# 记录 / 查询
# ===========================================================================


def record(kind: str, ip: str, who: str = "", n: int = 1) -> None:
    """★★ **记一次事件**（⚠ 绝不影响调用方：任何异常都吞掉）⚠

    ```
    member = f"{ip}|{who}"
      ⇒ Top 排序时能看出「哪个 IP 的哪个身份」
    ⚠ 按 member 聚合，而不是分开按 IP / 按用户 —— 那会丢关联 ⚠
    ```
    """
    try:
        if kind not in KINDS:
            return
        ip = (ip or "").strip()[:64]
        who = (who or "").strip()[:64]
        member = f"{ip}|{who}"
        conn = _redis()
        key = _key(kind, _today())
        conn.zincrby(key, n, member)
        conn.expire(key, KEEP_DAYS * 86400)
    except Exception:  # noqa: BLE001 —— ★ 审计失败不能连累业务
        logger.debug("audit record failed", exc_info=True)


def top(kind: str, day: str | None = None, limit: int = 20) -> list[dict]:
    """★ 某天的 Top N（* 次数倒序）⚠"""
    if kind not in KINDS:
        return []
    try:
        conn = _redis()
        rows = conn.zrevrange(_key(kind, day or _today()), 0, max(0, limit - 1), withscores=True)
        out = []
        for member, score in rows:
            if isinstance(member, bytes):
                member = member.decode("utf-8", "ignore")
            raw = str(member)
            ip, _sep, who = raw.partition("|")
            out.append({"ip": ip, "who": who, "count": int(score)})
        return out
    except Exception:  # noqa: BLE001
        logger.debug("audit top failed", exc_info=True)
        return []


def summary(days: int = 2, limit: int = 500) -> dict:
    """★★ **近 N 天的汇总**（* 后台页面直接用）⚠

    Returns: `{days: [date...], by_kind: {kind: [{ip, who, count}]}, totals: {kind: n}}`
    """
    today = timezone.localdate()
    day_list = [(today - timedelta(days=i)).isoformat() for i in range(max(1, days))]
    by_kind: dict[str, list[dict]] = {k: [] for k in KINDS}
    totals: dict[str, int] = {k: 0 for k in KINDS}
    try:
        for kind in KINDS:
            merged: dict[str, int] = {}
            for day in day_list:
                for row in top(kind, day, limit):
                    key = f"{row['ip']}|{row['who']}"
                    merged[key] = merged.get(key, 0) + row["count"]
            rows = []
            for k, v in merged.items():
                ip, _sep, who = k.partition("|")
                rows.append({"ip": ip, "who": who, "count": v})
            rows.sort(key=lambda r: -r["count"])
            by_kind[kind] = rows[:limit]
            totals[kind] = sum(merged.values())
    except Exception:  # noqa: BLE001
        logger.debug("audit summary failed", exc_info=True)
    return {"days": day_list, "by_kind": by_kind, "totals": totals}


def clear(kinds: tuple[str, ...] | list[str], day: str | None = None) -> int:
    """★★ **清空某几类记录**（* 所有者：「不能一直堆着，不删除吧？那岂不是越来越多」）⚠

    ```
    默认只清「今天」；day=None 且传 `all_days=True` 才能清全部
    ⇒ 刻意**不提供"一键清空所有历史"**：审计数据被一次清光是反效果 ⚠
    ```

    Returns: 删掉多少条 member
    """
    total = 0
    try:
        day = day or _today()
        conn = _redis()
        for kind in kinds:
            if kind not in KINDS:
                continue
            key = _key(kind, day)
            total += int(conn.zcard(key) or 0)
            conn.delete(key)
    except Exception:  # noqa: BLE001
        logger.debug("audit clear failed", exc_info=True)
    return total


# ===========================================================================
# 封禁
# ===========================================================================


def is_bannable(ip: str) -> bool:
    """★★ 这个 IP **能不能封**（`B249` · 2026-10-25）⚠

    ## ★ 为什么单独抽出来

    > 所有者：「**我上次封禁了一个IP，但是被封禁列表并没有这个IP**」

    根因：站点在**隧道后面**（花生壳 / SSH），nginx 看到的来源永远是
    `127.0.0.x` 或 `172.19.x` —— 封它等于把整站锁死。
    ⇒ 回环 / 私有网段 / docker 网段一律**不许封** ✅
    """
    ip = (ip or "").strip()
    if not ip:
        return False
    return not ip.startswith(NEVER_BAN)


def ban(ip: str, *, seconds: int = 0, by: str = "") -> bool:
    """★ 封禁一个 IP（`seconds=0` ⇒ 永久）。

    ⚠ 拒绝封回环 / 私有网段 —— 那会把管理员自己和 nginx 一起锁在门外 ⚠
    """
    ip = (ip or "").strip()
    if not is_bannable(ip):
        return False
    try:
        conn = _redis()
        if seconds > 0:
            # 临时封禁：用带 TTL 的键，到期自动解封（不需要清理任务）
            conn.setex(f"{BAN_KEY}:{ip}", seconds, by or "1")
        else:
            conn.hset(BAN_KEY, ip, by or "1")
        return True
    except Exception:  # noqa: BLE001
        logger.debug("audit ban failed", exc_info=True)
        return False


def unban(ip: str) -> bool:
    """★ 解封（永久与临时都清）"""
    ip = (ip or "").strip()
    if not ip:
        return False
    try:
        conn = _redis()
        n = int(conn.hdel(BAN_KEY, ip) or 0)
        n += int(conn.delete(f"{BAN_KEY}:{ip}") or 0)
        return n > 0
    except Exception:  # noqa: BLE001
        logger.debug("audit unban failed", exc_info=True)
        return False


def is_banned(ip: str) -> bool:
    """★ 这个 IP 是否被封（* 中间件每个请求调一次，必须极快）⚠"""
    ip = (ip or "").strip()
    if not ip or ip.startswith(NEVER_BAN):
        return False
    try:
        conn = _redis()
        return bool(conn.hexists(BAN_KEY, ip) or conn.exists(f"{BAN_KEY}:{ip}"))
    except Exception:  # noqa: BLE001 —— ★ Redis 挂了不能把所有人挡在门外
        logger.debug("audit is_banned failed", exc_info=True)
        return False


def banned_list() -> list[dict]:
    """★ 当前封禁名单（永久 + 临时）⚠"""
    out: list[dict] = []
    try:
        conn = _redis()
        for ip, by in (conn.hgetall(BAN_KEY) or {}).items():
            if isinstance(ip, bytes):
                ip = ip.decode("utf-8", "ignore")
            if isinstance(by, bytes):
                by = by.decode("utf-8", "ignore")
            out.append({"ip": ip, "by": by or "", "until": ""})
        for key in conn.scan_iter(f"{BAN_KEY}:*"):
            if isinstance(key, bytes):
                key = key.decode("utf-8", "ignore")
            ip = key.rsplit(":", 1)[-1]
            ttl = max(0, int(conn.ttl(key) or 0))
            if ttl >= 86400:
                left = f"{ttl // 86400} 天后"
            elif ttl >= 3600:
                left = f"{ttl // 3600} 小时后"
            elif ttl >= 60:
                left = f"{ttl // 60} 分钟后"
            else:
                left = f"{ttl} 秒后"
            who = conn.get(key)
            if isinstance(who, bytes):
                who = who.decode("utf-8", "ignore")
            out.append({"ip": ip, "by": who or "", "until": left, "temp": True})
    except Exception:  # noqa: BLE001
        logger.debug("audit banned_list failed", exc_info=True)
    return out
