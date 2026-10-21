# ★ 0039 的修正：三元组索引必须是**表达式索引**（* 2026-10-21）
#
# ⚠ 0039 把索引建在了裸列上（title / body / name / "desc"）——
#   * 而 Django 的 `icontains` 生成 `UPPER(col::text) LIKE UPPER('%kw%')`
#   * ⇒ 表达式与索引对不上，* PG 仍然全表扫描（* 实测 `enable_seqscan=off`
#     都逼不出索引）⚠
#
# ★ 本迁移：* 旧的删掉，* 按 `UPPER(col)` 重建；* 另加 auth_user.username
from django.db import migrations

DROP_OLD = [
    "DROP INDEX IF EXISTS idx_note_title_trgm;",
    "DROP INDEX IF EXISTS idx_note_body_trgm;",
    "DROP INDEX IF EXISTS idx_project_name_trgm;",
    "DROP INDEX IF EXISTS idx_project_desc_trgm;",
]

CREATE_NEW = [
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_note_title_trgm "
    "ON core_note USING gin (upper(title) gin_trgm_ops);",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_note_body_trgm "
    "ON core_note USING gin (upper(body) gin_trgm_ops);",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_project_name_trgm "
    "ON core_project USING gin (upper(name) gin_trgm_ops);",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_project_desc_trgm "
    'ON core_project USING gin (upper("desc") gin_trgm_ops);',
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_username_trgm "
    "ON auth_user USING gin (upper(username) gin_trgm_ops);",
]


class Migration(migrations.Migration):
    # ⚠ CONCURRENTLY 不能在事务内 ⇒ 非事务化
    atomic = False

    dependencies = [
        ("core", "0039_search_trgm_indexes"),
    ]

    operations = [
        *[migrations.RunSQL(sql, migrations.RunSQL.noop) for sql in DROP_OLD],
        *[migrations.RunSQL(sql, migrations.RunSQL.noop) for sql in CREATE_NEW],
    ]
