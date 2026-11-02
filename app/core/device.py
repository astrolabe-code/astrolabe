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

## ★★ 发牌速率：每 IP 每小时 150 个（2026-10-23 所有者定）

> 「嗯，还加一个令牌发放速率就行，一个小时150个就行。」

```
正常用户：一个设备一辈子只要一个令牌
   150/小时 ⇒ 相当于"一小时 150 台新设备"，家庭/公司出口都够 ✅
超出    ：⛔ 不再发牌，* 该客户端落进 anon 桶（共用 90 次/秒）⚠

伪造令牌：不可能（要 SECRET_KEY）
不带令牌：落进 anon 桶
要绕过  ：脚本 + 丢 Cookie 领新牌 + 自己压速率 + 断开重连
        ⇒ 做到这个程度的人，认了 ✅
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
import time

from django.conf import settings

logger = logging.getLogger("astrolabe.device")

#: Cookie 名（HttpOnly，前端读不到，也不需要读）
COOKIE_NAME = "at_device"
#: 有效期：180 天
COOKIE_MAX_AGE = 180 * 24 * 3600
#: 随机部分字节数（16 字节 ⇒ 22 字符 base64url）
TOKEN_BYTES = 16

#: ★★ **令牌发放速率**（* 所有者 2026-10-23：「一个小时150个就行」）⚠
#:   · · 正常用户一个设备只要一次 ⇒ 150 相当于"一小时 150 个新设备"
#:   · · 超出 ⇒ ⛔ 不再发牌，* 该客户端落进 anon 桶（共用 90 次/秒）✅
ISSUE_MAX = 150
ISSUE_WINDOW = 3600

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


def _issue_allowed(ip: str) -> bool:
    """★★ **每 IP 每小时最多发 150 个令牌**（* 固定小时窗口）⚠

    ⚠★ 只在"要不要发牌"时用 IP；**限流身份**永远不用 IP（* 那是误伤的根源）⚠
    """
    if not ip:
        return True
    # ★ 审计：谁在疯狂要令牌（2026-10-25 所有者：「我要检测那些IP在疯狂请求token」）⚠
    from core import access_audit

    access_audit.record("device_issue", ip)
    try:
        key = f"astrolabe:dev:issue:{ip}:{int(time.time()) // ISSUE_WINDOW}"
        n = _redis().incr(key)
        if n == 1:
            _redis().expire(key, ISSUE_WINDOW + 60)
        return n <= ISSUE_MAX
    except Exception:
        # ★ Redis 挂了 ⇒ 放行（* 令牌只是限流手段，* 不能因此不让访问）⚠
        return True


def client_ip(request) -> str:
    """★ 取客户端 IP（* 仅用于"发牌"配额与审计，* 不用于限流身份）⚠

    ## ⚠★★ 2026-11-02 改动：**不再相信客户端自带的 `X-Forwarded-For`**

    ```
    旧写法：取 XFF 的**第一段**（最左边那个）
      · nginx 用 $proxy_add_x_forwarded_for ⇒ 它把客户端带来的值原样保留在前面
      · 于是 client_ip() 返回的完全由**客户端决定**
        —— 实测：加一个 `X-Forwarded-For: 1.2.3.4` 就真的返回 1.2.3.4 ⚠
      · 后果：封禁一改头就绕过；还能伪造别人的 IP 让人被误封；审计数据不可信
    ```

    ## 现在的取值顺序

    ```
    ① X-Real-IP      ← nginx **覆盖写**的（`$remote_addr`），客户端改不了 ✅
    ② REMOTE_ADDR    ← 直连时的对端
    ⛔ 不读 XFF —— 那是客户端可以随便写的
    ```

    ⚠ 一旦接入自有隧道并要求它**覆盖**写 XFF，再在 nginx 启用 `realip` 模块，
      这里读到的就会是**真实客户端 IP**（届时把 ① 换成 nginx 覆盖后的值即可）。
    """
    return (
        (request.META.get("HTTP_X_REAL_IP") or "").strip()
        or request.META.get("REMOTE_ADDR")
        or ""
    )


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
