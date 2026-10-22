"""★★ `python manage.py search_terms_flush` —— **把 Redis 热词合并进 PostgreSQL** ⚠

## ★ 为什么需要它

```
Redis ZSET = 在线读写（快，但断电/重启会丢）
SearchTerm = 持久副本（慢，但不会丢）
```

⚠★ 合并取**最大值**（`max(redis, db)`）⇒ 反复跑不会把计数算重，也不会因为
  Redis 被淘汰过而把数据库的计数**改小** ✅

## ★ 用法

```bash
python manage.py search_terms_flush          # 合并一次
python manage.py search_terms_flush --stats  # 只看条数
```

★ 线上由 `search_worker` 每 5 分钟自动调用一次（* 不需要 cron）。
"""
from django.core.management.base import BaseCommand

from search import terms


class Command(BaseCommand):
    help = "把 Redis 热搜词合并进 core_searchterm（B238）"

    def add_arguments(self, parser):
        parser.add_argument("--stats", action="store_true", help="只打印条数，不写入")

    def handle(self, *args, **options):
        if options["stats"]:
            s = terms.stats()
            self.stdout.write(f"Redis {s['redis']} 条 · PostgreSQL {s['db']} 条")
            return

        n = terms.flush()
        s = terms.stats()
        self.stdout.write(
            self.style.SUCCESS(
                f"合并 {n} 条；Redis {s['redis']} 条 · PostgreSQL {s['db']} 条"
            )
        )
