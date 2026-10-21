# ★ 搜索加速：pg_trgm 三元组索引（* 2026-10-21）
#
# 所有者原话：
#   「CREATE EXTENSION pg_trgm; ... 把这些加上，提高一下搜索效率，
#     不要每次都用搜索关键字。」
#
# ⚠★ 为什么是 pg_trgm 而不是全文检索（tsvector）：
#   · · ★ 中文需要分词器（zhparser 等）才能用 tsvector，* 而 PG 默认不带 ⇒ 成本高
#   · · ★ pg_trgm 把字符串切成三元组，* 对「子串匹配」（LIKE '%kw%'）天然友好，
#     中文不用分词，* 且 `icontains` 的语法一行都不用改 ✅
#
# ⚠★ `CONCURRENTLY`：★ 建索引不锁表（* 生产环境数据在写也不怕）
#   · · ⚠ 但 `CONCURRENTLY` **不能在事务里跑** ⇒ 这里必须
#     `atomic = False`，* 否则迁移会报「CREATE INDEX CONCURRENTLY cannot run
#     inside a transaction block」⚠
from django.db import migrations

TRGM_EXTENSION = "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

IDX_NOTE_TITLE = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_note_title_trgm "
    "ON core_note USING gin (upper(title) gin_trgm_ops);"
)
IDX_NOTE_BODY = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_note_body_trgm "
    "ON core_note USING gin (upper(body) gin_trgm_ops);"
)
IDX_PROJ_NAME = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_project_name_trgm "
    "ON core_project USING gin (upper(name) gin_trgm_ops);"
)
IDX_PROJ_DESC = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_project_desc_trgm "
    'ON core_project USING gin (upper("desc") gin_trgm_ops);'
)
IDX_USER_NAME = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_username_trgm "
    "ON auth_user USING gin (upper(username) gin_trgm_ops);"
)


class Migration(migrations.Migration):
    # ⚠ CONCURRENTLY 不能在事务内 ⇒ 整条迁移非事务化
    atomic = False

    dependencies = [
        ("core", "0038_comment_parent"),
    ]

    operations = [
        migrations.RunSQL(TRGM_EXTENSION, migrations.RunSQL.noop),
        migrations.RunSQL(IDX_NOTE_TITLE, "DROP INDEX IF EXISTS idx_note_title_trgm;"),
        migrations.RunSQL(IDX_NOTE_BODY, "DROP INDEX IF EXISTS idx_note_body_trgm;"),
        migrations.RunSQL(IDX_PROJ_NAME, "DROP INDEX IF EXISTS idx_project_name_trgm;"),
        migrations.RunSQL(IDX_PROJ_DESC, "DROP INDEX IF EXISTS idx_project_desc_trgm;"),
        migrations.RunSQL(IDX_USER_NAME, "DROP INDEX IF EXISTS idx_user_username_trgm;"),
    ]
