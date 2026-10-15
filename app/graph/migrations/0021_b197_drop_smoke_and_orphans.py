# `B197` 第五步：**删掉冒烟残留与孤儿行，* 把 CHECK 改回简单**
#
# ## ★★ 为什么要这一步（★ 所有者质问之下自查出来的）
#
# ```
# ★ 所有者原话（2026-10-15）：
#   「**我说了，现在数据库里的数据都是可以删的，你没有为了迎合这些数据，
#     做了其他操作，致使代码变复杂吧？**」
#
# ★★ 自查结果：★ **有，* 两处** ⚠
# ```
#
# ### ① CHECK 里那一支"过渡态"
#
# ```
# ★ 判据本应是「`base_graph_id` 与（`project_id` 或 `project_ref`）二选一」⚠
#   · ★ 我却加了第三支「两者都有」——
#     ★★ 而它只为 **115 行**而加 ⚠
#   · ★ 而那 115 行**全是冒烟数据**（`冒烟·维护者修补 #10` / `#11`）⚠
#   ⇒ ★★ 为了不改测试数据，* 我给约束加了**一整支 + 一大段注释** ⚠
#     ★★ 而那正是被质问的那个毛病 ⚠
# ```
#
# ### ② 546 行孤儿"留着待决"
#
# ```
# ★ 回填时抓到 546 行 `project_ref` 指着**已不存在的项目** ⚠
#   · ★ 我写了套"数出来、写日志、不删"的代码 ⚠
#   · ★★ 而那套代码**纯粹是为了伺候它们而存在的** ⚠
#   · ★ 所有者早就说过「**数据都可以删**」⚠
# ```
#
# ## ★★ 本迁移做三件事
#
# ```
# ① DML  删掉 546 行孤儿（* project_ref 指着不存在的项目）
# ② DML  删掉 115 行"两者都有"的冒烟残留
# ③ DDL  把两条 CHECK 的"过渡态"那一支【删掉】⇒ ★ 判据回到两分支 ✅
# ```
#
# ## ⚠★★ 为什么拆成两个迁移（* 这个坑本项目已踩过三次）
#
# ```
# ★ PostgreSQL 把「加/改约束」的校验**推迟到事务提交时**执行 ⚠
#   · ★ 而**同一个事务里先做 DML**（* 删行 / update）⇒ ★ 提交时撞上
#     「**cannot ALTER TABLE ... because it has pending trigger events**」⚠
#   · ★ 实测踩到（* `graph/0005`、`0006`、`0009`–`0011` 都踩过同一个）⚠
#   ⇒ ★★ 拆开最稳：* 本迁移只清数据，* `0022` 单独改约束 ✅
# ```
#
# ## ⚠★ 删的都是什么（* 如实列出来）
#
# ```
# ★ ① 孤儿行 546：* jobs_job 335 · graphrevision 167 · node 16 ·
#                patch 16 · nodeheat 6 · heatflush 6
#     ⇒ ★★ 它们的项目**早就不在了** —— * 留着只是死数据 ⚠
#
# ★ ② "两者都有" 115：* 全部属于 `冒烟·维护者修补 #10` / `#11`
#     ⇒ ★★ 冒烟脚本造的（* 按纪律：* 旧冒烟脚本不改不删，* 但它造的**数据**可删）✅
#     · ★ 项目本身**不删**（* 那是所有者建的项目）⚠
#     · ★★ 只删这些行上**冗余的 `project_ref`** —— * 外键照旧保留 ✅
#       （* 这样读路径切过去之后，* 它们照样读得到 ✅）
# ```
#
# ⚠★ 注意：* 第 ② 步**不是删行**，* 而是**把 `project_ref` 清成空串** ⚠
#   · ★ 因为那些节点 / 边 / 补丁**本身是有用的**（* 冒烟项目的图数据）⚠
#   · ★ 冗余的只是那个**字符串副本** ✅
#   · ★★ 于是：* 数据一条不丢，* 而 CHECK 可以回到两分支 ✅

from django.db import migrations, models


def _clean(apps, schema_editor):
    Project = apps.get_model("core", "Project")
    Node = apps.get_model("graph", "Node")
    Edge = apps.get_model("graph", "Edge")
    GraphPatch = apps.get_model("graph", "GraphPatch")
    GraphRevision = apps.get_model("graph", "GraphRevision")
    NodeHeat = apps.get_model("graph", "NodeHeat")
    HeatFlush = apps.get_model("graph", "HeatFlush")
    Job = apps.get_model("jobs", "Job")

    alive = set(Project.objects.values_list("project_ref", flat=True))

    # ---- ① 删孤儿行（* project_ref 指着不存在的项目）----
    orphan_specs = [
        (Node, "project_ref"),
        (Edge, "project_ref"),
        (GraphPatch, "project_ref"),
        (GraphRevision, "project_ref"),
        (NodeHeat, "project_ref"),
        (HeatFlush, "project_ref"),
        (Job, "project_ref"),
    ]
    total = 0
    for M, field in orphan_specs:
        qs = M.objects.exclude(**{field: ""}).exclude(**{f"{field}__in": alive})
        n = qs._raw_delete(qs.db) if hasattr(qs, "_raw_delete") else qs.delete()[0]
        total += n
        print(f"  [B197] 删孤儿 {M.__name__:14} {n} 行")

    # ---- ② 清掉"两者都有"那批的 project_ref（* 保留行本身）----
    #   ⚠★ 用 `.update()` 而不是逐行 save ⇒ ★ 不触发信号、* 也更快 ✅
    #
    # ⚠★★ 但【不是所有表都能清】—— ★ `project_ref` 在下面两张表里是**键的一部分** ⚠
    #   · ★ `graph_graphrevision`：★ **主键就是 `project_ref`** ⚠
    #   · ★ `graph_nodeheat`：★ `UNIQUE (project_ref, metric, uid)` ⚠
    #   ⇒ ★★ 清成空串 ⇒ ★ 多行撞同一个键 ⇒ **IntegrityError** ⚠
    #     （* 实测踩到：* `duplicate key ... graph_graphrevision_pkey (project_ref)=()`）⚠
    #   ⇒ ★★ 所以这两张表只能【删行】⚠
    #     · ★ 而它们的内容（* 修订号 / 热度）**本来就是缓存性质的** ⚠
    #       （* `GRAPH-STORAGE.md` G5：* 修订号是邻域缓存的命名空间代际）✅
    #     · ★★ 删了会**自动重建** ⇒ ★ 没有损失 ✅
    cleared = 0
    for M in (Node, Edge, GraphPatch, Job, HeatFlush):
        cleared += M.objects.exclude(project_ref="").exclude(project=None).update(
            project_ref=""
        )

    # ★★ project_ref 是键的一部分 ⇒ ★ 只能删行（* 内容是缓存，* 会重建）✅
    dropped = 0
    for M in (GraphRevision, NodeHeat):
        dropped += M.objects.exclude(project_ref="").exclude(project=None).delete()[0]

    print(f"  [B197] 合计：删孤儿 {total} 行 · 清冗余 {cleared} 行 · 删缓存行 {dropped} 行")


def _noop(apps, schema_editor):
    """⚠★ **故意不可回滚** —— ★ 删掉的行**不该**回来（* 它们是死数据）⚠"""
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("graph", "0020_remove_edge_edge_belongs_to_exactly_one_and_more"),
        ("jobs", "0004_b197_backfill_job"),
        ("core", "0018_b197_backfill_projectstorage"),
    ]

    operations = [
        # ---- ①② 清数据（* 只 DML，* ❌ 不碰 DDL）----
        migrations.RunPython(_clean, reverse_code=_noop),
    ]
