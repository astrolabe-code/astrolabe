# `B192` / `B198` / `B197` 第二步：**改结构**
#
# ## 本迁移做四件事
#
# ```
# ① AlterField  owner    nullable → NOT NULL · SET_NULL → PROTECT   （B198）
# ② AlterField  name     200 → 120                                   （B192）
# ③ AddConstraint        UNIQUE (owner, name)                        （B192）
# ④ RemoveField          is_paid · price_note · commit · graph_built_at（B197）
# ```
#
# ## ⚠★ 为什么手写而不用 `makemigrations`
#
# ```
# ★ `makemigrations` 对「nullable → NOT NULL」会**交互式提问**：
#   「You are trying to change the nullable field 'owner' to non-nullable
#     without a default…」
#   ★★ 而 CI / docker exec 里没有 stdin ⇒ **EOFError 当场死** ⚠
#
# ★★ 而那个问题在**本项目里不该问** —— ★ 因为：
#   · ★ 数据迁移 `0013` **已经把空属主全挂上了真实用户** ✅
#   · ⇒ ★★ 改列时**不存在 NULL 行**，* 不需要任何"一次性默认值" ⚠
#   · ★ 若真按提示填一个默认 user_id ⇒ ★ 那会在迁移里**硬编码一个 id**，
#     ★★ 而它在另一个环境上**未必存在** ⚠（★ 那才是真正的坑）⚠
#
# ⇒ ★★ 所以手写 AlterField，* 并在注释里写明"数据已由 0013 修好" ✅
# ```
#
# ## ⚠★ 依赖顺序（★ 不可调换）
#
# ```
# 0013（数据）→ 0014（结构）✅
# ```
#
# ★★ 若调换：★ 0014 先改 NOT NULL ⇒ ★ 那一刻还有 NULL 行 ⇒ **当场失败** ⚠

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_b192_fix_owner_and_dup_names"),
    ]

    operations = [
        # ---- ① owner：NOT NULL + PROTECT（B198）----
        migrations.AlterField(
            model_name="project",
            name="owner",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="projects",
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # ---- ② name：200 → 120（B192）----
        #   ★★ 因为它进了联合唯一索引 ⇒ ★ 索引体积由它决定 ⚠
        #   ★ 实测现有最长 19 字 ⇒ ★ 缩了碰不到任何数据 ✅
        migrations.AlterField(
            model_name="project",
            name="name",
            field=models.CharField(max_length=120),
        ),

        # ---- ③ UNIQUE (owner, name)（B192）----
        #   ★★ 数据迁移 0013 已把 34 行重名改掉 ✅
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(
                fields=("owner", "name"), name="uniq_owner_project_name"
            ),
        ),

        # ---- ④ 删掉四个死列 / 重复事实列（B197）----
        #   · ★ `is_paid` / `price_note`：★ 实测 **0 处读写**（★ 变现那套没接线）⚠
        #   · ★ `commit`：★ 实测 **0 处读写**（★ 唯一读点已改为发空串）⚠
        #   · ★★ `graph_built_at`：★ 它与 `BaseGraph.built_at` 是**同一条事实的两份** ⚠
        #     ⇒ ★ `is_graph_built` 已改为**派生**（★ 见 `core/models.py` 的属性）✅
        migrations.RemoveField(model_name="project", name="is_paid"),
        migrations.RemoveField(model_name="project", name="price_note"),
        migrations.RemoveField(model_name="project", name="commit"),
        migrations.RemoveField(model_name="project", name="graph_built_at"),
    ]
