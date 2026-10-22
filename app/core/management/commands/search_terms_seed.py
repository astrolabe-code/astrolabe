"""★★ `python manage.py search_terms_seed` —— **给热词表播种子** ⚠

## ★★★ 所有者原话（逐字）

> 「补上种子命令，改为一天自动执行一次。具体步骤是，取今天更新日期最新的前 2000 条
>   笔记和项目名称，给他们赋值 postgresql 里热词表分数的中位数。再逐条添加，注意
>   不要产生重复的词，在 redis 和 redis 回灌过程也一样。redis 缓存和 postgresql 里的
>   热词表不能有重复词。」

## ★ 做法

```
① 笔记标题 + 项目名，只取**公开可见**的，按 updated_at 倒序合并取前 N 条
② 分值 = 热词表当前分数的**中位数**（表空 ⇒ 1.0）
③ 已存在的词**跳过**（不覆盖已有分数，免得把热词拉低）
④ 重建 Redis（两侧词集合完全一致）
```

★ 线上由 `search_worker` 每天自动跑一次（* 时间戳存 Redis，重启不重置）。
"""
from django.core.management.base import BaseCommand

from search import terms


class Command(BaseCommand):
    help = "把最近更新的笔记标题/项目名灌进热词表（B238 / D109）"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=terms.SEED_LIMIT, help="最多取多少条")

    def handle(self, *args, **options):
        r = terms.seed_from_recent(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                f"候选 {r['candidates']} · 新增 {r['created']} · 已存在跳过 {r['skipped']} · "
                f"中位数 {r['median']} · 回灌 Redis {r['loaded']}"
            )
        )
