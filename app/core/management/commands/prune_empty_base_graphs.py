"""Astrolabe · `manage.py prune_empty_base_graphs` —— 清掉「0 节点的基图」（`B216`）

★★ 所有者原话（逐字）：

> 「**节点为零，还要什么基图，空的还能叫基图吗？解析出节点为零的，不能做基图。**」
> 「**项目不允许绑定基图为零的，从源头上杜绝，不要事后再删除，这样牵扯范围太广。**」

## ★★ 它是什么性质（⚠ 别当日常任务）

```
★★ 源头已经挡住两处（`B216`）：
  · ★ 作业：* 解析出 0 节点 ⇒ 直接失败、* **不建基图行** ✅
  · ★★ 绑定：* `binding.bind()` 拒绝 `is_ready()` 为假的基图 ✅
⇒ ★★ 正常使用**不会**产生 0 节点的基图 ⚠

★ 本命令是**防御 + 可观测**：
  · ★ 有人（运维 / 脚本）直接动过库 ⇒ 能**发现**
  · ★★ 且能**清理**：* 先解绑项目，* 再删基图行 ✅
```

## ★ 用法

```bash
python manage.py prune_empty_base_graphs              # ★ 默认 dry-run（只列清单）
python manage.py prune_empty_base_graphs --delete     # ★ 真删（解绑 + 删行）
python manage.py prune_empty_base_graphs --limit 20   # 只看 / 只处理前 20 条
```

★ 定期跑（cron / systemd timer）：

```
30 4 * * *  cd /home/ma/astrolabe/app/deploy && docker compose exec -T web \\
              python manage.py prune_empty_base_graphs --delete
```
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Project
from graph.models import BaseGraph


class Command(BaseCommand):
    help = "列出 / 清掉 0 节点的基图（B216：空的不配叫基图）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="真的删（默认只列清单；删之前会先解绑绑在它上面的项目）",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="最多处理多少条（0 = 不限）",
        )

    def handle(self, *args, **opts):
        delete = bool(opts["delete"])
        limit = max(int(opts["limit"]), 0)

        # ★ 0 节点：* 用反向外键的 IS NULL（LEFT JOIN）判，* 不逐条 count ✅
        qs = BaseGraph.objects.filter(nodes__isnull=True).order_by("pk")
        total = qs.count()

        if total == 0:
            self.stdout.write("（没有 0 节点的基图 —— 正常）")
            return

        rows = list(qs[:limit]) if limit else list(qs)

        self.stdout.write(f"找到 {total} 张 0 节点的基图：" + ("（dry-run，未改动）" if not delete else ""))
        for bg in rows:
            bound = list(
                Project.objects.filter(base_graph=bg).values_list("name", flat=True)
            )
            built = f"{bg.built_at:%Y-%m-%d %H:%M}" if bg.built_at else "未建成"
            line = (
                f"  #{bg.pk} {bg.provider}/{bg.repo_full_name}@{(bg.sha or '')[:12]}"
                f" built_at={built} 记录节点={bg.node_count} 绑定项目={len(bound)}"
            )
            if bound:
                line += f"（{', '.join(bound)}）"
            self.stdout.write(line)

        if not delete:
            self.stdout.write(
                "（dry-run：未改动。确认无误后加 --delete 才解绑 + 删行）"
            )
            return

        # ★★ 真删：* 逐条一个事务 —— 解绑项目 + 删基图（* 半途失败不留下“解绑了但图还在”）⚠
        deleted = 0
        unbound = 0
        for bg in rows:
            with transaction.atomic():
                unbound += Project.objects.filter(base_graph=bg).update(base_graph=None)
                bg.delete()
            deleted += 1

        self.stdout.write(f"已删除 {deleted} 张基图；解绑 {unbound} 个项目（它们回到「可重新拉取」）")
