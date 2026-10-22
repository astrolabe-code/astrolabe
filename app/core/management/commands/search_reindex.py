"""★★ `python manage.py search_reindex` —— **全量重建搜索索引**（`B238`）⚠

## ★★ 用法

```bash
# 全量重建（先清空再灌，* 搜索会短暂为空 —— 现在搜索还没切过来，无感）
docker compose exec -T web python manage.py search_reindex

# 只补写（不清空；适合修数据后补漏，* 已删除的旧文档不会自动消失 ⚠）
docker compose exec -T web python manage.py search_reindex --keep
```

## ★★ 为什么要「全量重建」

- 索引**不是真相**（PostgreSQL 才是）⇒ 任何怀疑索引坏了，就重建 ✅
- Meilisearch 没有 TTL、不会自动过期 ⇒ **对账/重建是唯一兜底** ⚠
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from core.models import Note, Project
from search import client, documents


class Command(BaseCommand):
    help = "把符合条件的笔记全量导入 Meilisearch（B238）"

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=500, help="每批文档数（默认 500）")
        parser.add_argument(
            "--keep",
            action="store_true",
            help="不清空索引，只增量补写（⚠ 已失效的旧文档不会自动删除）",
        )

    def handle(self, *args, **options):
        if not client.enabled():
            raise CommandError("MEILI_MASTER_KEY 未设置（见 app/deploy/.env）")

        try:
            client.health()
        except client.MeiliError as exc:
            raise CommandError(f"连不上 Meilisearch（{client.base_url()}）：{exc}") from None

        client.ensure_index(client.NOTES_INDEX)
        client.update_settings(client.NOTES_INDEX, documents.INDEX_SETTINGS)
        self.stdout.write("索引与设置就绪")

        if not options["keep"]:
            client.delete_all_documents(client.NOTES_INDEX)
            self.stdout.write("已清空旧文档")

        # ★★ 口径与 PG 检索一致：* 只导公开内容（见 search/documents.py）⚠
        qs = (
            Note.objects.filter(
                deleted_at__isnull=True,
                state=Note.STATE_ACTIVE,
                is_public=True,
            )
            .filter(
                Q(project__isnull=True)
                | (Q(project__is_public=True) & Q(project__state=Project.STATE_ACTIVE))
            )
            .select_related("project", "created_by")
            .order_by("pk")
        )

        total = qs.count()
        batch: list[dict] = []
        written = 0
        size = max(1, options["batch"])

        for note in qs.iterator(chunk_size=size):
            batch.append(documents.build_document(note))
            if len(batch) >= size:
                client.add_documents(client.NOTES_INDEX, batch)
                written += len(batch)
                self.stdout.write(f"  已写入 {written}/{total}")
                batch = []

        if batch:
            client.add_documents(client.NOTES_INDEX, batch)
            written += len(batch)

        stats = client.index_stats(client.NOTES_INDEX)
        self.stdout.write(
            self.style.SUCCESS(
                f"完成：应索引 {total} 篇，已写入 {written} 篇，"
                f"索引内文档数 {stats.get('numberOfDocuments')}"
            )
        )
