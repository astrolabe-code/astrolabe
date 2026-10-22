"""★★ `python manage.py search_worker` —— **索引同步消费者**（`B238`）⚠

## ★ 职责

```
BRPOP astrolabe:index:queue
  → 取最新笔记数据（⛔ 不用消息里的快照）
  → 该进索引？ upsert : delete_document
  → 失败：指数退避重试（最多 5 次）
```

## ★★ 为什么独立进程（⛔ 不塞进 web / 不塞进 run_worker）

| 选项 | 为什么不 |
|---|---|
| web 进程里同步做 | * 笔记保存会被 Meili 的延迟拖住（* 它挂了就卡写操作）⚠ |
| 塞进 `run_worker` | * 解析任务可能跑几分钟，* 索引会跟着堵 ⚠ |
| **独立常驻**（本命令） | ✅ 崩了 `restart: unless-stopped` 自动拉起 |

★ 与 `heat` 那个服务同一套路（* 一个进程只管一件事）。
"""
import time

from django.core.management.base import BaseCommand, CommandError

from search import client, sync


class Command(BaseCommand):
    help = "消费索引同步队列（B238）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true", help="只处理一个待办就退出（调试用）"
        )
        parser.add_argument(
            "--timeout", type=int, default=2, help="队列阻塞秒数（默认 2）"
        )

    def handle(self, *args, **options):
        if not client.enabled():
            raise CommandError("MEILI_MASTER_KEY 未设置（见 app/deploy/.env）")

        self.stdout.write(f"索引同步启动（{client.base_url()}）")

        while True:
            try:
                sync.drain_once(timeout=options["timeout"])
            except KeyboardInterrupt:
                break
            except Exception:
                # ⚠ 队列本身出错（Redis 断 / Meili 断）⇒ 记日志，* 别让进程死 ⚠
                self.stderr.write(self.style.WARNING("索引同步异常，1 秒后重试"))
                time.sleep(1)
                continue

            if options["once"]:
                self.stdout.write("已处理一个待办")
                break
