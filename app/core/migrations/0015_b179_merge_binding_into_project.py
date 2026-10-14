# `B179` 第二步 / `B197`：**把 `graph_projectbasegraph` 并进 `core_project`**
#
# ## 为什么可以并（★ 这是对旧理由的一次核实）
#
# ```
# ★ 旧理由（写在 ProjectBaseGraph 的 docstring 里）：
#   「依赖方向是 graph → core —— ★ 在 core 上挂 graph 的外键会绕成一个圈」
#
# ★★ 而那个理由【站不住】（★ 实测）：
#   · ★ 架构文档 `ARCHITECTURE.md` A3 管的是【层】（Web / 作业 / 计算 / 共享内核）
#     ★★ 而 `core` 与 `graph` 同属【共享内核】✅
#   · ★★ `core/models.py:217` 与 `core/publish.py:500` 早就在 `from graph import binding` ⚠
#   · ★ 外键用【字符串引用】`"graph.BaseGraph"` ⇒ ★ 连 import 都不需要 ✅
#
# ★★ 而一个项目只绑一份基图 ⇒ ★★ 一张外键就够了，* 白多一张表 ⚠
#   · ★ 少一个可能产生【孤儿行】的地方 ✅
#   · ★★ `is_graph_built` 可以【直读外键】（★ 不再每个项目查一次）✅
# ```
#
# ## 本迁移做三件事
#
# ```
# ① AddField    给 core_project 加 base_graph 外键（★ 可空）
# ② RunPython   把 ProjectBaseGraph 的行回填进新外键
# ```
#
# ⚠★ **删表在 `graph/0014`** —— ★ `DeleteModel` 必须写在**模型所属的那个 app** 里 ⚠
#   （★ 实测踩过：★ 写在 core 里会抛
#     `KeyError: ('core', 'projectbasegraph')` —— * Django 按 app_label 找模型）⚠
#
# ## ⚠★ 为什么回填要在【同一个迁移】里、且必须成功
#
# ```
# ★ 若回填失败就删表 ⇒ ★★ 所有绑定关系【永久丢失】 ⚠
#   （★ 而那会让那批项目的图【当场消失】—— ★ 数据还在，* 但项目再也找不到它）⚠
#
# ⇒ ★★ 所以顺序是：★ 先加列 ⇒ ★ 回填（★ 失败就整体回滚）✅
#   ★★ PostgreSQL 把整个迁移包在一个事务里 ⇒ ★ 任一步失败 ⇒ 全部撤销 ✅
# ```
#
# ## ⚠★ 外键的删除行为：`PROTECT`
#
# ```
# ★ 基图是【所有项目共享】的（`B179`）⚠
# · ★★ 删一份【还有人绑着】的基图 ⇒ ★ 那些项目的图会凭空消失 ⚠
# · ★ 而所有者裁定基图「一直留着，不要做定期清理」✅
# ⇒ ★★ 要删基图 ⇒ 【先显式解绑】（★ 那是明面动作）✅
# ★（★ 第 1 批删那 15 份冒烟基图时，* 正是先摘绑定再删才没出事的 ✅）
# ```

from django.db import migrations, models


def _backfill(apps, schema_editor):
    """把 `ProjectBaseGraph` 的每一行搬进 `core_project.base_graph`。"""
    Project = apps.get_model("core", "Project")
    Binding = apps.get_model("graph", "ProjectBaseGraph")

    rows = list(Binding.objects.all().values_list("project_ref", "base_graph_id"))
    if not rows:
        return

    by_ref = {ref: bg_id for ref, bg_id in rows}
    projects = list(Project.objects.filter(project_ref__in=list(by_ref)))

    # ⚠★ 逐行更新（★ 不用 bulk_update：★ 要能报出**哪一行**对不上）⚠
    moved = 0
    for p in projects:
        bg_id = by_ref.get(p.project_ref)
        if bg_id is None or p.base_graph_id == bg_id:
            continue
        p.base_graph_id = bg_id
        p.save(update_fields=["base_graph", "updated_at"])
        moved += 1

    # ⚠★★ 自检：★ 搬完之后**一行都不该剩** ⚠
    #   （★ 否则说明有绑定指向一个【已不存在的项目】—— ★ 那正是孤儿行）⚠
    orphan = [ref for ref, _ in rows if not Project.objects.filter(project_ref=ref).exists()]
    if orphan:
        raise RuntimeError(
            f"回填自检失败：有 {len(orphan)} 条绑定指向不存在的项目"
            f"（例：{orphan[:3]}）—— 这些是孤儿绑定行，请先清理再跑本迁移"
        )


def _noop(apps, schema_editor):
    """⚠★ **故意不可回滚** —— ★ 表都删了，* 没法把行搬回去 ⚠

    ★ 真要从新外键还原出那张表 ⇒ ★ 得再写一个正向迁移 ⚠
    """
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_b192_owner_name_and_drop_dead"),
        ("graph", "0013_b184_request_url_check"),
    ]

    operations = [
        # ---- ① 加外键（★ 可空：★ 没绑 = 笔记型项目 / 还没拉）----
        migrations.AddField(
            model_name="project",
            name="base_graph",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="+",
                to="graph.basegraph",
            ),
        ),

        # ---- ② 回填 ----
        migrations.RunPython(_backfill, reverse_code=_noop),

    ]
