# `B197` 第五步（* 下）：**把两条 CHECK 改回两分支**
#
# ⚠★ 为什么单独一个迁移：★ 与 `0021`（* 清数据）拆开 ⚠
#   · ★ 同一个事务里先 DML 再 DDL ⇒ ★ PostgreSQL 报
#     「cannot ALTER TABLE ... pending trigger events」⚠
#   · ★★ 本项目已踩过三次（* `0005` / `0006` / `0009`–`0011`）✅
#
# ★★ 而它必须排在 `0021` **之后**：
#   · ★ 旧约束允许"两者都有"，* 新约束**不允许** ⚠
#   · ★★ 不清完那 115 行就改约束 ⇒ ★ 校验存量行时 **IntegrityError** ⚠

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("graph", "0021_b197_drop_smoke_and_orphans"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="node", name="node_belongs_to_exactly_one"),
        migrations.RemoveConstraint(model_name="edge", name="edge_belongs_to_exactly_one"),
        migrations.AddConstraint(
            model_name="node",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(base_graph__isnull=False, project__isnull=True, project_ref="")
                    | (
                        models.Q(base_graph__isnull=True)
                        & (
                            models.Q(project__isnull=False, project_ref="")
                            | models.Q(project__isnull=True, project_ref__gt="")
                        )
                    )
                ),
                name="node_belongs_to_exactly_one",
            ),
        ),
        migrations.AddConstraint(
            model_name="edge",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(base_graph__isnull=False, project__isnull=True, project_ref="")
                    | (
                        models.Q(base_graph__isnull=True)
                        & (
                            models.Q(project__isnull=False, project_ref="")
                            | models.Q(project__isnull=True, project_ref__gt="")
                        )
                    )
                ),
                name="edge_belongs_to_exactly_one",
            ),
        ),
    ]
