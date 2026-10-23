"""★★ **设备令牌**（`B238` · 2026-10-23）⚠

## ★★★ 所有者原话（逐字）

> 「我还想到了一根更好的机制，网站链接建立时，就给设备发送一个token存起来。然后，
>   它每次访问都要带上这个token，做为身份识别。这样游客也能区分了，有token或有
>   用户名的就给正常速率。都没有的，看作一个人，走哪9倍的速率限制，这样就防刷，
>   他们用脚本清除token不管用，还能保护正常用户。」

## ★ 设计

```
首次访问（没有 cookie）⇒ 发一个**签名令牌**，写进 HttpOnly Cookie（180 天）
· 令牌 = <随机串>.<HMAC-SHA256(SECRET_KEY, 随机串)[:16]>
· 校验**不用查库**：只验签（微秒级）⇒ 伪造不了 ⚠
```

⚠★ 为什么签名而不是存 Redis：
  · · 每个 API 请求都要校验 ⇒ 存 Redis 就是每请求一次往返（~0.36ms）
  · · 签名是**无状态**的，验签只花几微秒 ✅
  · · 代价：没法"吊销单个设备" —— 对限流场景不需要 ⚠

## ★★ 为什么不做"每 IP 每小时发几个"的配额（2026-10-23 所有者裁定）

> 「不要每 IP 每小时最多发 30 个，现在收益不值得。……要是有人这么弄，我也服气了。」

```
伪造令牌：不可能（要 SECRET_KEY）
不带令牌：落进 anon 桶，全体共用 90 次/秒
要绕过  ：脚本 + 每次丢弃 Cookie 领新令牌 + 自己压速率 + 断开重连
        ⇒ 做到这个程度的人，不是刷子就是研究者，认了 ✅
```

## ★ 身份优先级

```
登录用户  u<id>      ⇒ 正常速率
有设备令牌 d<token>  ⇒ 正常速率
两者都没有 anon      ⇒ 共用一个桶，9 倍速率
```
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets

from django.conf import settings

logger = logging.getLogger("astrolabe.device")

#: Cookie 名（HttpOnly，前端读不到，也不需要读）
COOKIE_NAME = "at_device"
#: 有效期：180 天
COOKIE_MAX_AGE = 180 * 24 * 3600
#: 随机部分字节数（16 字节 ⇒ 22 字符 base64url）
TOKEN_BYTES = 16

_client = None


def _redis():
    global _client
    if _client is None:
        import redis

        _client = redis.Redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2
        )
    return _client


def _sign(raw: str) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:22]


def issue() -> str:
    """★ 生成一个新令牌（* 随机 + 签名）⚠"""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    return f"{raw}.{_sign(raw)}"


def verify(token: str) -> bool:
    """★ 验签（* 不查库、不耗时）⚠"""
    if not token or "." not in token:
        return False
    raw, sig = token.rsplit(".", 1)
    return hmac.compare_digest(sig, _sign(raw))


def set_cookie(response, token: str):
    """★ 写 Cookie（* HttpOnly：JS 读不到，* 脚本也没法"清除后保留"）⚠"""
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response
