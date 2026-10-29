#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ Astrolabe 个人版 · Python 边车（stdio 协议）

## 它是什么

```\n壳（Electron）── 换行分隔 JSON ──▶ 本进程\n           ◀──────────────────────\n```\n
**不监听任何端口**。这是"端口被占 / localhost 被安全策略封"这两类问题的根治办法。

## 协议

```json
→ {"id": 1, "method": "GET", "path": "/api/me", "body": null}
← {"id": 1, "status": 200, "body": {"ok": true, "data": {...}}}
```

⚠ 一行一条，⛔ 不要格式化输出（`json.dumps` 不能带缩进）。
⚠ 任何异常都要**转成一行错误响应**，⛔ 不能抛到 stdout 里 —— 壳会解析失败。
"""

from __future__ import annotations

import json
import os
import sys

VERSION = "0.1.0"


def _data_dir() -> str:
    return os.environ.get("ASTROLABE_DATA_DIR") or os.path.join(os.getcwd(), "data")


# ---------------------------------------------------------------- 路由


def handle(method: str, path: str, body: dict | None) -> tuple[int, dict]:
    """⚠ 目前是骨架：只证明"壳 ↔ 边车"这条通道活着。
    真正的数据层（sqlite + 解析器）接进来时，在这里分派。"""

    if path == "/api/site-config/":
        return 200, {
            "ok": True,
            "data": {"siteMode": "personal", "theme": "plain", "resumeDwellSeconds": 20},
        }

    if path == "/api/me/":
        # ★ 个人版没有登录：永远是「本机用户」
        return 200, {
            "ok": True,
            "data": {"authenticated": True, "username": "我", "display": "我", "is_staff": True},
        }

    if path == "/api/projects/":
        return 200, {"ok": True, "data": {"items": [], "total": 0}}

    if path == "/api/ping":
        return 200, {"ok": True, "data": {"pong": True, "version": VERSION, "dataDir": _data_dir()}}

    return 404, {"ok": False, "error": f"未实现：{method} {path}"}


# ---------------------------------------------------------------- 主循环


def main() -> None:
    # ★ 强制 utf-8：Windows 控制台默认 cp936，中文会乱码
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            # ⚠ 解析不了就没法回 id ⇒ 只能记到 stderr（壳会打印出来）
            print("[sidecar] 坏 JSON：%r" % line[:200], file=sys.stderr, flush=True)
            continue

        rid = req.get("id")
        try:
            status, payload = handle(
                str(req.get("method") or "GET"),
                str(req.get("path") or "/"),
                req.get("body"),
            )
        except Exception as exc:  # noqa: BLE001 —— 边车不能因为一个请求死掉
            status, payload = 500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        sys.stdout.write(json.dumps({"id": rid, "status": status, "body": payload}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
