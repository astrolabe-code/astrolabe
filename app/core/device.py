"""Astrolabe · 客户端地址（原「设备令牌」模块，2026-11-04 精简）

## 这个文件现在只剩一件事：**取客户端 IP**

```
client_ip(request)  → 审计 / 封禁 / 限流都用它
```

## ★ 设备令牌为什么被删掉

所有者原话（2026-11-04）：

> 「把令牌功能先删了吧，效果没多少，判断还多，没必要。」

删除前它做两件事，两件都不划算：

```
① 分账：同一出口的多个访客分开计数
   ⚠ 但它只是个可清除的 Cookie ⇒ 攻击者清一下就换身份，分账对攻击者无效
   ⚠ 而它的"发牌配额"（每 IP 150/小时）在真实 IP 不可得时会退化成
     **全站 150/小时** —— 实测已打满（计数 222），新访客反而拿不到令牌

② 身份：给限流提供 d<token> 维度
   ⇒ 现在匿名一律按 `a<ip>` 计账（等自建隧道接入真实 IP 后才有意义）
```

⚠ 连带影响：
· `web/middleware.DeviceTokenMiddleware` 已删除（不再种 `at_device` Cookie）
· `access_audit` 的 `device_issue` 类别已删除（不再产生该审计）
· 老的 `at_device` Cookie 会自然过期，无需清理
"""

from __future__ import annotations

import logging

logger = logging.getLogger("astrolabe.device")


def client_ip(request) -> str:
    """★ 取客户端 IP（* 审计 / 封禁 / 限流用；⛔ 不用于身份认证）⚠

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
