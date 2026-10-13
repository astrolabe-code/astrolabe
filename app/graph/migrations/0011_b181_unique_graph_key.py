# `B181` 第三步：**加唯一约束**（★ 回填之后才能加）
#
# ★★ 为什么拆成三步（★ 这是被 PostgreSQL 逼的，★ 已经踩过一次）：
#
# ```
# 0009  纯 DDL：加字段 + 去旧约束        ← 此刻所有行 graph_key 都是 ""
# 0010  纯 DML：回填地址与身份证号        ← 空号变成真号
# 0011  纯 DDL：加唯一约束               ← ★★ 必须在这之后 ⚠
# ```
#
# ⚠★ 若把 ①③ 合成一个迁移：★ PostgreSQL 把建索引**推迟到事务提交时**执行 ⚠
#   ⇒ ★ 0010 的 UPDATE 先跑 ⇒ ★ 提交时撞上 "pending trigger events" ⚠
#   ★★（同一个坑，`0005`/`0006` 已经踩过一次 —— ★ 见 `0006` 的文档）⚠
#
# ⚠★ 若在 0009 就加约束：★ 7 个空号互相撞 ⇒ ★ **当场失败** ⚠

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('graph', '0010_b181_backfill_graph_key'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='basegraph',
            constraint=models.UniqueConstraint(fields=('graph_key',), name='uniq_base_graph_key'),
        ),
    ]
