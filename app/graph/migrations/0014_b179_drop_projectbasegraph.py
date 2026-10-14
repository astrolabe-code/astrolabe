# `B179` 第二步：**删掉 `graph_projectbasegraph`**
#
# ★★ 绑定已并入 `core_project.base_graph`（★ 见 `core/0015`）⚠
#   · ★ 一个项目只绑一份基图 ⇒ ★ 一张外键就够了 ⚠
#   · ★★ 而"依赖会成圈"那个旧理由**站不住**（★ 实测 `core` 早已 import `graph`）⚠
#
# ⚠★ 为什么删表单独一个迁移、且**排在 core/0015 之后**：
#   · ★ `DeleteModel` 必须写在**模型所属的 app**（★ `graph`）里 ⚠
#     （★ 写在 core 里会抛 `KeyError: ('core', 'projectbasegraph')`）⚠
#   · ★★ 而它必须**等回填跑完**再删 —— ★ 否则绑定关系还没搬就没了 ⚠
#
# ⚠★ `core/0015` 里有一段**自检**：★ 搬完之后若还有绑定指向不存在的项目
#   ⇒ ★ 它**抛异常** ⇒ ★ 整个迁移回滚 ⇒ ★ 表不会被删 ✅
#   （★ 那正是"孤儿绑定行"的守护位 ✅）

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_b179_merge_binding_into_project"),
        ("graph", "0013_b184_request_url_check"),
    ]

    operations = [
        migrations.DeleteModel(name="ProjectBaseGraph"),
    ]
