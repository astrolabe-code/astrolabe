"""★★ `python manage.py search_check` —— **索引对账**（`B238`）⚠

## ★★★ 所有者原话（逐字）

> 「先做A和B吧。A的对账时间选在深夜，没几个人用就行，这时系统卡点，不影响。」

## ★ 用法

```bash
python manage.py search_check          # 只检查，打印差异
python manage.py search_check --fix    # 检查并修复（缺的补、多的删）
```

★ 线上由 `search_worker` 在**深夜窗口（默认 03:00–05:00）每天跑一次**，
不需要 cron。
"""
from django.core.management.base import BaseCommand, CommandError

from search import client, reconcile


class Command(BaseCommand):
    help = "对比 PostgreSQL 可搜笔记与 Meilisearch 文档（B238）"

    def add_arguments(self, parser):
        parser.add_argument("--fix", action="store_true", help="发现差异就直接修")

    def handle(self, *args, **options):
        if not client.enabled():
            raise CommandError("MEILI_MASTER_KEY 未设置（见 app/deploy/.env）")

        r = reconcile.reconcile(fix=options["fix"])

        self.stdout.write(
            f"PG 可搜 {r['pg']} · 索引 {r['index']} · "
            f"缺失 {len(r['missing'])} · 残留 {len(r['stale'])} · "
            f"内容过期 {len(r['outdated'])} · 计数过期 {len(r['stale_counts'])}"
        )
        if r["missing"]:
            self.stdout.write(
                f"  缺失（数据库有、索引没有）: {r['missing'][:20]}  ← 重新投递索引任务"
            )
        if r["stale"]:
            self.stdout.write(
                f"  残留索引条目（Meilisearch 有、数据库不该有）: {r['stale'][:20]}"
                "  ← 只删索引条目，数据库不动"
            )
            # ★ 逐条给出原因：* 私有 / 隐藏 / 项目私有 / 已删 ⚠
            for nid, why in list(r["reasons"].items())[:10]:
                self.stdout.write(f"    - {nid}: {why}")
        if r["stale_counts"]:
            self.stdout.write(f"  计数过期（赞/评论 与索引不一致）: {r['stale_counts'][:20]}")
        if r["outdated"]:
            self.stdout.write(
                f"  内容过期（updated_at 对不上，索引里是旧内容）: {r['outdated'][:20]}"
            )

        if options["fix"] and r["fixed"]:
            self.stdout.write(self.style.SUCCESS(f"已修复 {r['fixed']} 条"))
        elif r["missing"] or r["stale"] or r["outdated"]:
            self.stdout.write(self.style.WARNING("加 --fix 可直接修复"))
        else:
            self.stdout.write(self.style.SUCCESS("笔记两边一致 ✅"))

        # ★★ 项目索引：同一套对账（* 2026-10-23）⚠
        pr = reconcile.reconcile_projects(fix=options["fix"])
        self.stdout.write(
            f"项目：PG {pr['pg']} · 索引 {pr['index']} · "
            f"缺失 {len(pr['missing'])} · 残留 {len(pr['stale'])} · "
            f"内容过期 {len(pr['outdated'])} · 计数过期 {len(pr['stale_counts'])}"
        )
        if pr["missing"]:
            self.stdout.write(f"  缺失项目: {pr['missing'][:10]}  ← 重新投递索引任务")
        if pr["stale"]:
            self.stdout.write(
                f"  残留索引条目: {pr['stale'][:10]}  ← 只删索引条目，数据库不动"
            )
        if pr["outdated"]:
            self.stdout.write(f"  内容过期: {pr['outdated'][:10]}")
        if pr["stale_counts"]:
            self.stdout.write(f"  计数过期: {pr['stale_counts'][:10]}")

        if options["fix"] and pr["fixed"]:
            self.stdout.write(self.style.SUCCESS(f"项目已修复 {pr['fixed']} 个"))
        elif pr["missing"] or pr["stale"] or pr["outdated"] or pr["stale_counts"]:
            self.stdout.write(self.style.WARNING("加 --fix 可直接修复"))
        else:
            self.stdout.write(self.style.SUCCESS("项目两边一致 ✅"))
