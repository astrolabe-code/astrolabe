"""★★ **运维概览的数据来源**（2026-10-24）⚠

## ★ 为什么有这个模块

所有者：「Astrolabe 后台可以看到 kuma 的信息吗？还是我每次都要打开这两个页面」

⇒ 后台加一页把三件事汇在一起：

```
① 依赖探活   DB / Redis / Meili（* 与 /readyz 同一套判断）✅
② Kuma 监控  **只读** sqlite（挂载卷 ro）—— ⛔ 不走 iframe（Kuma 有 X-Frame-Options: SAMEORIGIN）
③ 索引状态   队列积压 / 同步进程心跳 / 上次对账日期
```

⚠ 读 Kuma 的库是**只读**（`mode=ro`）：Kuma 自己在写，⛔ 我们绝不能写它 ⚠
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime

from django.conf import settings

#: ★ compose 把 Kuma 的数据卷只读挂到这里（见 deploy/docker-compose.yml）⚠
KUMA_DB = "/kuma-data/kuma.db"


# ---------------------------------------------------------------- 依赖探活


def _timed(fn) -> dict:
    started = time.monotonic()
    try:
        fn()
        return {"ok": True, "ms": round((time.monotonic() - started) * 1000, 1)}
    except Exception as exc:  # ⚠ 任何异常都算失败，不往外抛 ⚠
        return {
            "ok": False,
            "ms": round((time.monotonic() - started) * 1000, 1),
            "error": f"{type(exc).__name__}: {str(exc)[:100]}",
        }


def stack_checks() -> dict:
    """★ DB / Redis / Meili 三项探活（* `/readyz` 与后台概览共用）⚠"""
    import urllib.request

    from django.db import connection

    def check_db() -> None:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()

    def check_redis() -> None:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
        )
        try:
            if not client.ping():
                raise RuntimeError("PING 无响应")
        finally:
            client.close()

    def check_meili() -> None:
        from search import client as meili

        headers = {}
        key = meili.master_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(f"{meili.base_url()}/health", headers=headers)
        with urllib.request.urlopen(request, timeout=2) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")

    return {
        "db": _timed(check_db),
        "redis": _timed(check_redis),
        "meili": _timed(check_meili),
    }


# ---------------------------------------------------------------- Kuma


def kuma_monitors() -> dict:
    """★★ **只读** Kuma 的监控与最近一次心跳 ⚠

    Returns: `{"ok": bool, "items": [...], "error": str}` —— 出错也只是显示红字，
    ⛔ 绝不让后台页面 500 ⚠
    """
    import os

    if not os.path.exists(KUMA_DB):
        return {"ok": False, "items": [], "error": "Kuma 数据卷未挂载（/kuma-data）"}

    try:
        # ⚠ `mode=ro`：只读打开 —— Kuma 正在写，我们绝不能写它 ⚠
        conn = sqlite3.connect(f"file:{KUMA_DB}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT m.id, m.name, m.type, m.active, m.interval, m.url,
                   h.status AS h_status, h.msg AS h_msg, h.ping AS h_ping, h.time AS h_time
            FROM monitor m
            LEFT JOIN heartbeat h
              ON h.id = (SELECT id FROM heartbeat WHERE monitor_id = m.id ORDER BY time DESC LIMIT 1)
            WHERE m.type != 'group'
            ORDER BY m.id
            """
        ).fetchall()
        conn.close()
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "items": [], "error": f"{type(exc).__name__}: {exc}"}

    items = []
    for row in rows:
        items.append(
            {
                "name": row["name"],
                "type": row["type"],
                "url": row["url"],
                "active": bool(row["active"]),
                # ⚠ 1=up 0=down，None = 还没收到过心跳 ⚠
                "status": row["h_status"],
                "msg": row["h_msg"] or "",
                "ping": row["h_ping"],
                "time": row["h_time"] or "",
                "interval": row["interval"],
            }
        )
    return {"ok": True, "items": items, "error": ""}


# ---------------------------------------------------------------- 索引


def index_stats() -> dict:
    """★ 索引队列与同步进程心跳（* 全是 Redis 里现成的 key）⚠"""
    from search import reconcile, sync

    data: dict = {}
    try:
        import redis as redis_lib

        conn = redis_lib.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
        )
        try:
            data["queue"] = int(conn.llen(sync.QUEUE_KEY))
            data["pending"] = int(conn.scard(sync.PENDING_KEY))
            data["retry"] = int(conn.zcard(sync.RETRY_KEY))
            day = conn.get(reconcile.DAY_KEY)
            data["reconcile_day"] = day.decode() if isinstance(day, bytes) else day
        finally:
            conn.close()
        data["ok"] = True
    except Exception as exc:  # pragma: no cover
        data = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        age = reconcile.heartbeat_age()
        data["heartbeat_age"] = round(age, 1) if age is not None else None
    except Exception:
        data["heartbeat_age"] = None

    return data


def backup_status() -> dict:
    """★ 最近一次备份的产出（* 备份目录只读挂载）⚠

    ```\n    看的是**文件**：最新 db-*.sql.gz 的时间与大小\n    超过 36 小时没新文件 ⇒ 标红（* 说明 cron 没跑或脚本失败）\n    ```\n
    """
    import glob
    import os
    from datetime import datetime as _dt

    data: dict = {"ok": True, "items": [], "stale": False, "error": ""}
    try:
        db_files = sorted(glob.glob("/backup/db-*.sql.gz"))
        if not db_files:
            data["ok"] = False
            data["error"] = "还没有任何数据库备份"
            return data
        latest = db_files[-1]
        mtime = os.path.getmtime(latest)
        age_hours = (time.time() - mtime) / 3600
        data["latest"] = {
            "name": os.path.basename(latest),
            "size": os.path.getsize(latest),
            "time": _dt.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
            "age_hours": round(age_hours, 1),
        }
        data["stale"] = age_hours > 36  # ⚠ 超过 36h 说明昨天的没跑成 ⚠
        data["count"] = len(db_files)
        kuma = sorted(glob.glob("/backup/uptime-kuma-2*.tar.gz"))
        data["kuma_latest"] = os.path.basename(kuma[-1]) if kuma else ""
    except Exception as exc:  # pragma: no cover
        data["ok"] = False
        data["error"] = f"{type(exc).__name__}: {exc}"
    return data


def collected_at() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
