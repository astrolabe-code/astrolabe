"""Astrolabe · **登录失败计数与硬锁**（P1a · 2026-11-04）

## 所有者原话（逐字）

> 「用户名被锁后，只能硬等到时间到，除非我（管理员）手动给他打开。
>  也就是说，admin 账号不能被反复登陆锁死，可以整个脚本解锁。
>  而且，我说了，密码登陆只是我的几个朋友可以，其他人都是 oauth 认证登陆，
>  我朋友密码被锁了，能找到我，他们也宽容许多。」

## 规则

```
计数键   rl:login:user:<strip().lower(用户名)>      ← ⚠ 规范化**只用于计数键**
阈值     失败满 5 次 ⇒ 之后（第 6 次起）**直接拒绝**
时长     锁定 15 分钟（从第 5 次失败起算，TTL 自动过期）
解除     ① 等满 15 分钟   ② 管理员解锁（后台按钮 / deploy/unlock-login.sh）
```

## 三条不能写错的（见 RATE-LIMIT.md 5.3 / 10.3）

```
① 用户名规范化只用于**计数键**；`authenticate()` 必须用用户原始输入
   （数据库里的用户名可能大小写敏感，顺手 lower 会让合法用户登不进来）
② **不存在的用户名也照常计数、照常锁定**
   否则"被锁了 vs 密码错"就是免费的用户名枚举 Oracle
③ 锁定文案必须与"密码错误"**不可区分**（⛔ 不写"该用户已锁定"）
```

## Redis 故障时

按 RATE-LIMIT.md 5.5：**fail-closed** —— 调用方捕获异常后返回 503
「服务暂时不可用」，⛔ 不降级成"放行"（那等于无限试密码）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("astrolabe.login_guard")

#: 失败多少次后开始锁定
MAX_FAILS = 5
#: 计数窗口（秒）—— 15 分钟
WINDOW = 15 * 60
#: 锁定时间（秒）—— 15 分钟
LOCK = 15 * 60
#: 键前缀（后台「登录锁定」页与 CLI 都靠它扫）
KEY_PREFIX = "rl:login:user:"


def normalize(username: str) -> str:
    """★ **仅用于计数键** 的规范化（⛔ 不要拿它去做认证）"""
    return (username or "").strip().lower()


def key_for(username: str) -> str:
    return KEY_PREFIX + normalize(username)


def _redis():
    """★ 复用作业层的"快客户端"（带 1 秒超时，Redis 卡住时快速失败）"""
    from jobs.queue import _fast_client

    return _fast_client()


def is_locked(username: str) -> tuple[bool, int]:
    """★★ 是否已被锁（* 必须在 `authenticate()` **之前**调用）⚠

    Returns:
        `(locked, retry_after_seconds)`

    Raises:
        Exception: Redis 不可用 —— 调用方应按 fail-closed 处理（返回 503）
    """
    key = key_for(username)
    client = _redis()
    raw = client.get(key)
    try:
        n = int(raw or 0)
    except (TypeError, ValueError):
        n = 0
    if n < MAX_FAILS:
        return False, 0
    ttl = client.ttl(key)
    return True, max(int(ttl or 1), 1)


def record_failure(username: str) -> int:
    """★ 记一次失败（* 返回累计次数）

    ⚠ 满 `MAX_FAILS` 次时把 TTL 改成 `LOCK` ⇒ 锁定从"第 5 次失败"起算
    """
    key = key_for(username)
    client = _redis()
    n = client.incr(key)
    if n == 1:
        client.expire(key, WINDOW)
    elif n >= MAX_FAILS:
        client.expire(key, LOCK)
    return int(n)


def clear(username: str) -> bool:
    """★ 清掉某个用户名的失败计数（成功登录 / 管理员解锁都走这里）

    Returns:
        True = 原本确实有计数（被清掉了）；False = 本来就没有
    """
    return bool(_redis().delete(key_for(username)))


def fail_count(username: str) -> int:
    """★ 当前失败次数（0 = 没有记录）"""
    try:
        return int(_redis().get(key_for(username)) or 0)
    except (TypeError, ValueError):
        return 0


def locked_list(limit: int = 100) -> list[dict]:
    """★ 当前被锁的用户名列表（后台「登录锁定」页 / CLI `--list` 用）

    ⚠ 用 **SCAN**（⛔ 不用 KEYS）；单次最多 `limit` 条（小站够用）
    """
    client = _redis()
    out: list[dict] = []
    for key in client.scan_iter(match=KEY_PREFIX + "*", count=200):
        try:
            n = int(client.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if n < MAX_FAILS:
            continue
        ttl = int(client.ttl(key) or 0)
        out.append(
            {
                "username": key[len(KEY_PREFIX) :],
                "count": n,
                "ttl": max(ttl, 0),
            }
        )
        if len(out) >= limit:
            break
    out.sort(key=lambda x: -x["count"])
    return out


def human_ttl(seconds: int) -> str:
    """★ 秒数 → 人话（"12 分 30 秒"）"""
    seconds = max(int(seconds or 0), 0)
    if seconds <= 0:
        return "已过期"
    m, s = divmod(seconds, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h} 小时 {m} 分"
    return f"{m} 分 {s} 秒" if m else f"{s} 秒"
