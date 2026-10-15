# `B199`：**删掉扫过 0 次的 `_like` 索引**
#
# ## 它们是什么
#
# ```
# ★ Django 给 `varchar` 的索引**自动配一个 `varchar_pattern_ops` 的双胞胎**（★ 供 `LIKE` 用）⚠
# ★ 全库共 **29 个**，★ 累计扫描 2993 次 —— ★ 但**分布极不均** ⚠
# ```
#
# ## ⚠★ 为什么用 `RunSQL` 而不是 `RemoveIndex`
#
# ```
# ★★ `RemoveIndex` 要求那棵索引**在 Django 的 migration state 里** ⚠
#   · ★ 而这些是**历史遗留**（* `db_index=True` 时代自动建的，
#     * 后来 `Meta.indexes` 改过，* state 里已经没有它们了）⚠
#   · ★ 用 `RemoveIndex` 会当场抛
#     `ValueError: No index named … on model …`
#     （★ 同一个坑，`graph/0012` 已经踩过一次）⚠
# ```
#
# ## ★ 删哪些（* 实测扫过 0 次的 9 个）
#
# ```
# · core_apitoken_prefix_e3ffe00b_like
# · core_auditlog_action_978477aa_like
# · core_oauthidentity_provider_6b92c14d_like
# · core_project_review_state_86e65995_like
# · core_project_state_266cc10b_like
# · core_projectreview_reason_code_011d2f17_like
# · graph_edge_project_ref_adcc99d9_like
# · graph_graphpatch_project_ref_07941032_like
# · graph_node_project_ref_63d83487_like
# ```
#
# ⚠★ **其余 20 个不动** —— ★ 它们有扫描记录 ⇒ ★ 说明代码里真有 `LIKE` 查询 ⚠
#   · ★ 其中 `graph_node_uid_like` 只扫过 2 次 ⇒ ★ 边界数据不足，* **先留** ⚠
#
# ⚠★ 每个都带 `IF EXISTS` —— ★ 免得某个环境上它本来就不在 ⚠

from django.db import migrations

_DEAD_LIKE = [
    "core_apitoken_prefix_e3ffe00b_like",
    "core_auditlog_action_978477aa_like",
    "core_oauthidentity_provider_6b92c14d_like",
    "core_project_review_state_86e65995_like",
    "core_project_state_266cc10b_like",
    "core_projectreview_reason_code_011d2f17_like",
    "graph_edge_project_ref_adcc99d9_like",
    "graph_graphpatch_project_ref_07941032_like",
    "graph_node_project_ref_63d83487_like",
]


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_remove_notecomment_ix_comment_chapter_and_more"),
        ("graph", "0023_remove_edge_graph_edge_project_f2c813_idx_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[f"DROP INDEX IF EXISTS {n}" for n in _DEAD_LIKE],
            # ⚠★ 回滚时**不重建** —— ★ 它们本来就是多余的 ⚠
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
