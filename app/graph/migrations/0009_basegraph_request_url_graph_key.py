# `B181` 第一步：**只做 DDL** —— ★ 加两个字段 + 去掉旧的三字段唯一约束
#
# ⚠★ 新的唯一约束【故意不在这里加】⚠ ——
#   ★★ 存量行的 `graph_key` 此刻还是空的（★ 字段刚加，默认 `""`）⚠
#   · ★ 无条件唯一约束 + 7 个空号 ⇒ ★ **迁移当场失败** ⚠
#   · ★ 所以必须【先回填】（`0010`）⇒ ★【后加约束】（`0011`）✅
#
# ⚠★ 这也再次印证那条教训：★ **改结构**与**动数据**不要放在同一个迁移里 ——
#   ★ PostgreSQL 把建索引推迟到事务提交时执行，★ DML 先跑会撞上
#     "pending trigger events"（★ `0005`/`0006` 已经踩过一次）⚠

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('graph', '0008_projectbasegraph'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='basegraph',
            name='uniq_base_graph',
        ),
        migrations.AddField(
            model_name='basegraph',
            name='request_url',
            field=models.CharField(blank=True, default='', max_length=1024),
        ),
        migrations.AddField(
            model_name='basegraph',
            name='graph_key',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32),
        ),
    ]
