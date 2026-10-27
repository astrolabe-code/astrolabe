# ★★ Note.seq —— 「该作者的第几篇」（`D113` · 2026-10-26）⚠
#
# 所有者原话（逐字）：
#   「笔记盒学习法，不就是这样吗？不过，他是在编号，可以借鉴一下。」
#   「用时间戳的话，信息行最后不就是时间吗？都写了，还写一次吗？」
#
# ⚠ 本迁移除了加列，还要**回填存量笔记的编号** ——
#   否则老笔记全是 0，下一次新建会从 1 开始，和已有编号撞车 ⚠
#
# ⚠ 回填口径：**按 created_at 升序**，每人从 1 开始；
#   包含软删的（`deleted_at` 非空）—— 它们将来恢复时还得用原来的号 ✅

from django.db import migrations, models


def backfill_seq(apps, schema_editor):
    Note = apps.get_model("core", "Note")
    # ★ 一次取出所有 (作者, id, created_at)，内存里分组排序 ⇒ 避免 N 次查询 ⚠
    rows = list(
        Note.objects.order_by("created_by_id", "created_at", "id").values_list(
            "id", "created_by_id", "created_at"
        )
    )
    counters: dict[int, int] = {}
    updates = []
    for note_id, author_id, _created in rows:
        key = author_id or 0
        counters[key] = counters.get(key, 0) + 1
        updates.append(Note(id=note_id, seq=counters[key]))

    # ★ bulk_update 只写 seq 一列，⛔ 不碰其他字段 ✅
    if updates:
        Note.objects.bulk_update(updates, ["seq"], batch_size=500)


def unbackfill(apps, schema_editor):
    """回滚 ⇒ 全部归零（列本身由 RemoveField 删）"""
    Note = apps.get_model("core", "Note")
    Note.objects.update(seq=0)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0053_alter_appsetting_options_alter_auditlog_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="note",
            name="seq",
            field=models.PositiveIntegerField(db_index=True, default=0),
        ),
        migrations.RunPython(backfill_seq, unbackfill),
    ]
