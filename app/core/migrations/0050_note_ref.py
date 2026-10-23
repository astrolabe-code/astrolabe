# ★ 笔记加**对外标识** `ref`（随机 16 位十六进制），URL / 接口不再暴露自增主键（2026-10-23）
#
# 所有者原话（逐字）：
#   「你这新建笔记带着笔记ID，不要是自增数字主键，不然，别人轻松就能看到，
#     推测出数据库的一些信息。」
#
# ⚠ 三步走（* 不能一步加 unique 字段：存量行 default 都是 ""，会撞唯一约束）⚠
#   ① 先加**不带 unique** 的列
#   ② 逐行回填随机值
#   ③ 再补 unique 约束
import secrets

from django.db import migrations, models


def backfill(apps, schema_editor):
    Note = apps.get_model("core", "Note")
    seen = set()
    dirty = []
    for note in Note.objects.all().only("pk", "ref"):
        ref = (note.ref or "").strip()
        if not ref or ref in seen:
            ref = secrets.token_hex(8)
            while ref in seen:
                ref = secrets.token_hex(8)
            note.ref = ref
            dirty.append(note)
        seen.add(ref)
    if dirty:
        Note.objects.bulk_update(dirty, ["ref"], batch_size=500)
        print(f"  回填笔记 ref {len(dirty)} 条")


class Migration(migrations.Migration):
    dependencies = [("core", "0049_editor_canonical")]

    operations = [
        # ① 先加列（* 不带 unique）
        migrations.AddField(
            model_name="note",
            name="ref",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        # ② 回填
        migrations.RunPython(backfill, migrations.RunPython.noop),
        # ③ 再补唯一约束 + 索引
        migrations.AlterField(
            model_name="note",
            name="ref",
            field=models.CharField(blank=True, db_index=True, default="", max_length=16, unique=True),
        ),
    ]
