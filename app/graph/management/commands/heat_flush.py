"""Astrolabe · 热度合并命令（Redis → 数据库）

★ 依据 `GRAPH-STORAGE.md` G5 · `B128`：Redis 是**热数据，重启会丢**，必须定期落库。

★ 三种跑法：

| 方式 | 命令 |
|---|---|
| **手动 / 排查** | `python manage.py heat_flush` |
| **cron / systemd timer** | `heat_flush`（一次性跑完退出） |
| ★ **常驻调度**（部署用的就是这个） | `heat_flush --loop --interval 900` |

⚠ **为什么部署用「常驻服务」而不是 cron**：
  · 部署是 Docker Compose，**没有 host cron 可用**（见 `deploy/docker-compose.yml` 的 `heat` 服务）
  · ★ 常驻 + `restart: unless-stopped` ⇒ 崩了自动拉起，**不需要额外的调度器**
  · ★ 独立于 `worker` ⇒ worker 卡在一个长解析上时，**热度仍能正常落库**

用法：
    python manage.py heat_flush                       # ★ 合并全部项目，跑完退出
    python manage.py heat_flush --loop --interval 900 # ★ 常驻：每 15 分钟合并一次
    python manage.py heat_flush --project-ref proj_x  # 只合并一个项目
    python manage.py heat_flush --dry-run             # ⚠ 只看会合并多少，不写库
    python manage.py heat_flush --status              # 看「未合并增量」还有多少
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from graph import cache, heat


class Command(BaseCommand):
    help = "把 Redis 里未合并的节点热度累加进数据库（★ 权威累计值）"

    def add_arguments(self, parser):
        parser.add_argument("--project-ref", default="", help="只合并该项目；不给则全部")
        parser.add_argument("--metric", default="", help=f"默认 {cache.HOT_VISIT}")
        parser.add_argument("--dry-run", action="store_true", help="⚠ 只统计，不写库、不删 key")
        parser.add_argument("--status", action="store_true", help="查看未合并增量")
        parser.add_argument("--loop", action="store_true", help="★ 常驻：周期性合并（部署用）")
        parser.add_argument(
            "--interval", type=int, default=900, help="常驻模式的间隔秒数（默认 900 = 15 分钟）"
        )

    def handle(self, *args, **opts):
        metrics = [opts["metric"]] if opts["metric"] else None
        projects = [opts["project_ref"]] if opts["project_ref"] else None

        if opts["loop"]:
            self._loop(max(int(opts["interval"]), 5), projects, metrics)
            return

        if opts["status"]:
            self._status(projects, metrics)
            return

        rep = heat.flush_all(projects, metrics, dry_run=opts["dry_run"])

        prefix = "[dry-run] " if rep.dry_run else ""
        self.stdout.write(
            f"{prefix}合并完成：{rep.projects} 个项目 · {rep.batches} 个批次 · "
            f"{rep.rows} 个节点 · 累计 {rep.total} 次"
        )
        if rep.skipped:
            self.stdout.write(self.style.WARNING(f"跳过 {len(rep.skipped)} 项："))
            for s in rep.skipped[:10]:
                self.stdout.write(f"   - {s}")
        if rep.batches == 0 and not rep.skipped:
            self.stdout.write("（没有待合并的增量 —— 正常）")

    def _loop(self, interval: int, projects, metrics) -> None:
        """★ 常驻模式 —— 部署时由 `deploy/docker-compose.yml` 的 `heat` 服务运行。

        ⚠ 单次失败**不退出**（继续下一轮）—— 周期性维护任务不该被一次异常干掉；
          但把错误写进 stderr，`docker compose logs heat` 能看到。
        """
        self.stdout.write(
            f"★ 热度合并调度启动：每 {interval}s 一次（Ctrl+C 或 docker compose stop 退出）"
        )
        while True:
            try:
                rep = heat.flush_all(projects, metrics)
                stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
                if rep.batches:
                    self.stdout.write(
                        f"[{stamp}] {rep.projects} 项目 · {rep.batches} 批次 · "
                        f"{rep.rows} 节点 · 累计 {rep.total} 次"
                    )
                else:
                    self.stdout.write(f"[{stamp}] 无待合并增量")
            except Exception as exc:  # noqa: BLE001 —— ★ 一轮失败不能终止整个调度
                self.stderr.write(self.style.ERROR(f"热度合并失败（将在下一轮重试）：{exc}"))
            time.sleep(interval)

    def _status(self, projects, metrics):
        """★ 看「还躺在 Redis 里、没落库」的增量。"""
        client = cache.get_client()
        targets = (
            [(p, m) for p in (projects or []) for m in (metrics or heat.config()["metrics"])]
            if projects
            else heat.discover(client, metrics)
        )
        if not targets:
            self.stdout.write("（没有待合并的热度 key）")
            return

        self.stdout.write(f"{'项目':<28} {'指标':<10} {'未合并节点':>10} {'未合并次数':>10}")
        self.stdout.write("-" * 64)
        for project_ref, metric in targets:
            rows = heat.pending(project_ref, metric)
            self.stdout.write(
                f"{project_ref:<28} {metric:<10} {len(rows):>10} {sum(rows.values()):>10}"
            )
        self.stdout.write("")
        self.stdout.write("★ 未合并 = Redis 里已记但还没落库的增量（正常会有，等下次 heat_flush）")
