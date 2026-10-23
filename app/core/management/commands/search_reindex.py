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
from django.db.models import Count
from django.utils import timezone
from django.db.models import Q

from core.models import Note, Project
from search import client, documents


#: ★ 全量重建用的临时索引名（* 建完再与主索引原子交换）⚠
TMP_INDEX = "notes_tmp"


class Command(BaseCommand):
    help = "把符合条件的笔记全量导入 Meilisearch（B238）"

    def _fill(self, uid: str, qs, size: int, total: int) -> int:
        """★ 分批写入指定索引，返回写了几篇 ⚠"""
        batch: list[dict] = []
        written = 0
        for note in qs.iterator(chunk_size=size):
            batch.append(documents.build_document(note, like_count=note.like_count))
            if len(batch) >= size:
                client.add_documents(uid, batch)
                written += len(batch)
                self.stdout.write(f"  已写入 {written}/{total}")
                batch = []
        if batch:
            client.add_documents(uid, batch)
            written += len(batch)
        return written

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
            # ★ 赞数用聚合一次算出来（* 否则每篇一次 COUNT）⚠
            .annotate(like_count=Count("likes"))
            .order_by("pk")
        )
        total = qs.count()
        size = max(1, options["batch"])

        if options["keep"]:
            # ---- 增量补写：直接写主索引（* 不清空、不切换）⚠
            client.ensure_index(client.NOTES_INDEX)
            client.update_settings(client.NOTES_INDEX, documents.INDEX_SETTINGS)
            written = self._fill(client.NOTES_INDEX, qs, size, total)
            self.stdout.write(
                self.style.SUCCESS(f"完成：应索引 {total} 篇，已补写 {written} 篇")
            )
            return

        # ---- 全量重建：**临时索引 + 原子交换**（* 零空窗）⚠
        started = timezone.now()
        tmp = TMP_INDEX

        client.delete_index(tmp)                      # 清理上次残留
        client.ensure_index(tmp)
        client.update_settings(tmp, documents.INDEX_SETTINGS)
        self.stdout.write(f"临时索引 {tmp} 已就绪（* 线上仍在服务旧索引）")

        written = self._fill(tmp, qs, size, total)

        # ★ 主索引必须存在才能交换（首次部署时可能还没有）
        client.ensure_index(client.NOTES_INDEX)
        client.swap_indexes(tmp, client.NOTES_INDEX)  # ★ 原子切换
        client.delete_index(tmp)                      # 此时 tmp 名下是旧数据
        self.stdout.write("已原子切换到新索引，旧索引已删除")

        # ★ 构建期间被改动的笔记：重新投递（* 否则这几篇的内容会停在快照时点）⚠
        try:
            from search import sync

            recent = list(
                Note.objects.filter(updated_at__gte=started).values_list("pk", flat=True)
            )
            for nid in recent:
                sync.enqueue_note(nid)
            if recent:
                self.stdout.write(f"补投递构建期间更新的笔记 {len(recent)} 篇")
        except Exception:
            self.stdout.write(self.style.WARNING("补投递失败（可跑 change 对账修复）"))

        stats = client.index_stats(client.NOTES_INDEX)
        self.stdout.write(
            self.style.SUCCESS(
                f"完成：应索引 {total} 篇，已写入 {written} 篇，"
                f"索引内文档数 {stats.get('numberOfDocuments')}"
            )
        )
