# `B184` 第一步：**基图身份收敛到「只许远端」**
#
# ★★ 所有者原话（逐字）：
#   「**canonical_url要改，只能有远端形式也就是从github之类的上拉取，不能有上传文件，
#     这留下了一个攻击缺口。还有可以为空，为空的时候表示不用源码，就是写节点，
#     这就不用记录到基图里，在其他地方识别一下。所以，基图里这个字段只有唯一合法的样式，且不能为空**」
#
# ## 本迁移做三件事
#
# ```
# ① DML  删掉 15 份非远端基图（★ file:// 9 · legacy:// 6）
#         ── ★★ 它们全是冒烟 / 调试残留（★ smoke_owner/* · dbg/x）
#         ── ★ 删之前已实测：★ 无任何补丁指着它们（★ 否则会被 CASCADE 静默抹掉）⚠
# ② DDL  给 request_url 加 CHECK 正则（★ 挡住 file:// / 空串 / 任何别的写法）
# ③ DDL  删掉 graph_basegraph 上两棵多余的 graph_key 索引
#         ── ★★ 唯一索引 uniq_base_graph_key 已经覆盖等值查询 ⚠
# ```
#
# ⚠★ 为什么 ①② 不能合成一个迁移（★ 这是被 PostgreSQL 逼的，★ 项目里踩过两次）：
#
# ```
# ★ PostgreSQL 把建索引 / 加约束**推迟到事务提交时**校验 ⚠
#   ⇒ ★ 若先删数据、再在【同一个迁移】里加 CHECK：
#     · 删掉的那 15 行在事务内已经不存在 ⇒ ★ 其实不会撞 ⚠
#     · ★★ 但 `AddConstraint` 在 PG 上会走 "pending trigger events" 路径
#       （★ `0005`/`0006` 与 `0009`–`0011` 都踩过同一个坑）⚠
#   ⇒ ★★ 拆成两个迁移最稳：★ 本迁移只删数据 + 删索引，
#     ★ 下一个迁移（0013）单独加 CHECK ⚠
# ```
#
# ⚠★ 而 ③（删索引）放在这里**是安全的** —— ★ 删索引不校验数据 ✅

from django.db import migrations, models

# ★★ 只认这两种形态（★ 与 `BaseGraph.canonical_url()` 的实现一致）⚠
_REMOTE_PREFIX = "https://"


def _drop_non_remote_basegraphs(apps, schema_editor):
    """★ 删掉所有**非远端**的基图（★ 连同它们的节点 / 边 / 绑定）。

    ⚠★ 删之前必须确认（★ 已实测）：
      · ★ 无任何 `GraphPatch` 指着它们的节点 / 边
        ── ★ 否则会被 `on_delete=CASCADE` **静默抹掉**（★ 那条补丁属于别的项目）⚠
      · ★ 它们全是冒烟 / 调试残留，★ 重新解析即可重建 ✅
    """
    BaseGraph = apps.get_model("graph", "BaseGraph")
    Node = apps.get_model("graph", "Node")
    Edge = apps.get_model("graph", "Edge")
    ProjectBaseGraph = apps.get_model("graph", "ProjectBaseGraph")

    bad = list(
        BaseGraph.objects.exclude(request_url__startswith=_REMOTE_PREFIX)
        .values_list("id", flat=True)
    )
    if not bad:
        return

    # ★★ 先摘绑定（★ 它是另一个方向的引用，★ 不摘会挡住删除）⚠
    ProjectBaseGraph.objects.filter(base_graph_id__in=bad).delete()
    # ★★ 节点 / 边由 `base_graph` 的 CASCADE 一并处理 ✅
    Node.objects.filter(base_graph_id__in=bad).delete()
    Edge.objects.filter(base_graph_id__in=bad).delete()
    BaseGraph.objects.filter(id__in=bad).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('graph', '0011_b181_unique_graph_key'),
    ]

    operations = [
        # ---- ① 删掉非远端基图（★ DML）----
        migrations.RunPython(
            _drop_non_remote_basegraphs,
            # ⚠★ **故意不可回滚** —— ★ 那些是调试残留，★ 而且回滚也重建不出
            #   ★★ `file://` 那种"本地目录身份"（★ B184 起它已经非法）⚠
            reverse_code=migrations.RunPython.noop,
        ),

        # ---- ③ 删掉两棵多余的 graph_key 索引（★ DDL）----
        #   ★★ `uniq_base_graph_key`（唯一索引）已经覆盖等值查询 ⚠
        #   · `graph_basegraph_graph_key_dd2c89eb`      btree(graph_key)
        #   · `graph_basegraph_graph_key_dd2c89eb_like` btree(graph_key varchar_pattern_ops)
        #
        # ⚠★ 为什么用 `RunSQL` 而不是 `RemoveIndex`（★ 踩过一次，记下来）：
        #   ★★ `RemoveIndex` 要求那棵索引**在 Django 的 migration state 里** ⚠
        #     —— ★ 而这两棵是**历史遗留**（★ `db_index=True` 时代自动建的，
        #       ★ 后来 `Meta.indexes` 改过，* state 里已经没有它们了）⚠
        #   ⇒ ★ 用 `RemoveIndex` 会当场抛
        #     `ValueError: No index named graph_basegraph_graph_key_dd2c89eb on model BaseGraph`
        #     （★ 实测踩过，* 而且它发生在 RunPython **之后**）⚠
        #   ⇒ ★★ 所以直接用 SQL 删，* 并配 `state_operations` 让 state 保持一致 ✅
        #   ★ `IF EXISTS` 是必须的 —— ★ 免得某个环境上它们本来就不在 ⚠
        migrations.RunSQL(
            sql=[
                "DROP INDEX IF EXISTS graph_basegraph_graph_key_dd2c89eb",
                "DROP INDEX IF EXISTS graph_basegraph_graph_key_dd2c89eb_like",
            ],
            # ⚠★ 回滚时**不重建**它们 —— ★ 它们本来就是多余的 ⚠
            reverse_sql=migrations.RunSQL.noop,
            # ★★ 告诉 Django「state 里也没有它们了」⇒ ★ 以后 makemigrations 不会再来吵 ⚠
            state_operations=[
                migrations.RemoveIndex(
                    model_name="basegraph",
                    name="graph_basegraph_graph_key_dd2c89eb",
                ),
                migrations.RemoveIndex(
                    model_name="basegraph",
                    name="graph_basegraph_graph_key_dd2c89eb_like",
                ),
            ],
        ),
    ]
