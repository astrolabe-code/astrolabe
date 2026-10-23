# ★ 下线笔记搜索的 PostgreSQL 路径（`B238` 第四阶段 · 2026-10-23）
#
# ⚠ 背景：笔记搜索已全部改走 Meilisearch，`icontains` + 三元组索引那条路不再使用。
#   · 留着只是白占写入开销（* 每次存笔记都要维护 2 个 GIN 索引）⚠
#   · ★ 项目搜索仍用 `icontains` ⇒ 项目的两个索引（name / desc）**保留** ✅
#   · ★ 用户名索引也保留（* 项目按作者搜会用到）
from django.db import migrations

DROP_NOTE_INDEXES = [
    "DROP INDEX CONCURRENTLY IF EXISTS idx_note_title_trgm;",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_note_body_trgm;",
]


class Migration(migrations.Migration):
    # ⚠ CONCURRENTLY 不能跑在事务里 ⇒ 非事务化
    atomic = False

    dependencies = [
        ("core", "0045_search_term_float"),
    ]

    operations = [
        migrations.RunSQL(
            sql=sql,
            reverse_sql=migrations.RunSQL.noop,  # * 回滚不重建（* 真要回滚跑 0040）
        )
        for sql in DROP_NOTE_INDEXES
    ]
