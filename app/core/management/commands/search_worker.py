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

from search import client, reconcile, sync, terms


class Command(BaseCommand):
    help = "消费索引同步队列（B238）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true", help="只处理一个待办就退出（调试用）"
        )
        parser.add_argument(
            "--timeout", type=int, default=2, help="队列阻塞秒数（默认 2）"
        )
        parser.add_argument(
            "--healthcheck",
            action="store_true",
            help="只检查心跳（* 供 docker healthcheck 用，* 超时退出码 1）⚠",
        )

    def handle(self, *args, **options):
        if options["healthcheck"]:
            # ★ 心跳超过 300 秒没更新 ⇒ 判定假死（退出码 1，* 让 compose 重启）⚠
            age = reconcile.heartbeat_age()
            if age == float("inf"):
                self.stderr.write("没有心跳记录")
                raise CommandError("no heartbeat")
            if age > 300:
                self.stderr.write(f"心跳已过期 {int(age)}s")
                raise CommandError("heartbeat stale")
            self.stdout.write(f"ok（{int(age)}s 前）")
            return

        if not client.enabled():
            raise CommandError("MEILI_MASTER_KEY 未设置（见 app/deploy/.env）")

        self.stdout.write(f"索引同步启动（{client.base_url()}）")

        # ★★★ 热词维护：**每半天一次**（* 所有者 2026-10-22 定）⚠
        #   ```
        #   ① Redis → PG 合并  ② PG 分数衰减  ③ 删低分  ④ Top2000 回灌 Redis
        #   ```
        #   ⚠ 时间戳存在 Redis 里 ⇒ 进程重启**不会**让周期重置 ✅
        last_check = 0.0

        while True:
            # ★★ 心跳：* 每轮都写（* 消费者"活着且在转"的凭证）⚠
            reconcile.beat()

            now = time.monotonic()
            # ★ 每 60 秒探一次「到点没有」（* 只是一次 Redis GET）⚠
            if now - last_check >= 60:
                last_check = now

                # ★★ 对账：* 深夜窗口内每天一次（* 所有者：这时系统卡点不影响）⚠
                try:
                    if reconcile.due():
                        rc = reconcile.reconcile(fix=True)
                        reconcile.mark()
                        self.stdout.write(
                            f"索引对账：PG {rc['pg']} · 索引 {rc['index']} "
                            f"· 缺失 {len(rc['missing'])} · 残留 {len(rc['stale'])} "
                            f"· 过期 {len(rc['outdated'])} · 已修 {rc['fixed']}"
                        )
                        if rc["summary"]:
                            self.stdout.write(f"  删除原因：{rc['summary']}")

                        # ★ 项目索引对账（* 同一套口径）⚠
                        pr = reconcile.reconcile_projects(fix=True)
                        self.stdout.write(
                            f"项目对账：PG {pr['pg']} · 索引 {pr['index']} "
                            f"· 缺失 {len(pr['missing'])} · 残留 {len(pr['stale'])} "
                            f"· 过期 {len(pr['outdated'])} "
                            f"· 计数过期 {len(pr['stale_counts'])} "
                            f"· 已修 {pr['fixed']}"
                        )
                except Exception:
                    self.stderr.write(self.style.WARNING("索引对账失败"))

                # ★ 队列积压提醒（* 消费跟不上 / 消费者卡住）⚠
                try:
                    depth = sync._redis().llen(sync.QUEUE_KEY)
                    if depth > 1000:
                        self.stderr.write(self.style.WARNING(f"索引队列积压 {depth}"))
                except Exception:
                    pass
                try:
                    if terms.due():
                        r = terms.flush_and_decay()
                        if r["merged"] or r["loaded"]:
                            self.stdout.write(
                                f"热词维护：合并 {r['merged']} · 衰减后 {r['decayed']} 条 "
                                f"· 清理 {r['pruned']} · 回灌 {r['loaded']}"
                            )
                except Exception:
                    self.stderr.write(self.style.WARNING("热词维护失败"))

                # ★★ 种子：每天一次，把最近更新的笔记标题/项目名补进热词表 ⚠
                try:
                    if terms.seed_due():
                        sr = terms.seed_from_recent()
                        if sr["created"]:
                            self.stdout.write(
                                f"热词种子：候选 {sr['candidates']} · 新增 {sr['created']} "
                                f"· 中位数 {sr['median']}"
                            )
                except Exception:
                    self.stderr.write(self.style.WARNING("热词种子失败"))


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
