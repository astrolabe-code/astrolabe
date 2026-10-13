"""★★★ `B179`：清掉改造前的图数据（★ 见函数文档）

⚠★★ **为什么它必须是一个【单独】的迁移**（★ 这是踩过一次才拆开的）：

```
★ Django 在 PostgreSQL 上会把一部分 DDL（建索引）**推迟到事务提交时**执行 ⚠
★★ 而如果同一个迁移里还有 DELETE —— ★ 那会触发外键的 trigger 事件 ⚠
⇒ ★★ 提交时就会撞上：
     psycopg.errors.ObjectInUse: cannot CREATE INDEX "graph_node"
     because it has pending trigger events
```

⇒ ★★★ **规矩**：★ **DDL 一个迁移、DML 一个迁移** ——
  ★ 别把「改结构」和「清数据」塞进同一个事务 ⚠
"""

from django.db import migrations


def _clear_old_graph(apps, schema_editor):
    """★★★ **清掉改造前的图数据** —— ★ 它们是"按项目存的解析产物" ⚠

    ★★ 在新模型里它们没有位置：

    | 新模型里的含义 | 旧数据是什么 |
    |---|---|
    | ★ `Node.base_graph` 有值 ⇒ 基图行 | ⚠ 旧行**没有** base_graph |
    | ★ `Node.project_ref` 非空 ⇒ 【用户自己新增】的行 | ★★ 旧行的含义是"某个项目**解析**出来的" ⚠ |

    ⇒ ★★★ 放到哪一边都是**错的含义** ⚠

    ⚠★ 为什么可以直接清：★ 图是**派生数据**（从公开仓库解析出来的）——

    - ★★ 重新拉一次就回来了（★ 而那一趟会写成【基图】）✅
    - ★ 改造前的实测：★ 103 个项目里 **100 个是冒烟 / 压测产物**，
      ★ 只有 2 个指向所有者自己的仓库（★ 重拉即回）⚠

    ⚠ 只清 `Node` / `Edge` —— ★ `GraphRevision` / `NodeHeat` **不动**
      （★ 前者是缓存代际、★ 后者是热度累计；★ 它们本来就按项目存，语义没变）✅
    """
    Node = apps.get_model("graph", "Node")
    Edge = apps.get_model("graph", "Edge")
    Edge.objects.all().delete()
    Node.objects.all().delete()


def _noop(apps, schema_editor):
    """★ 反向不做任何事 —— ⚠ 数据已经清掉了，回不去（★ 这是刻意的）。"""


class Migration(migrations.Migration):

    dependencies = [
        ("graph", "0005_basegraph_graphpatch_and_more"),
    ]

    operations = [
        migrations.RunPython(_clear_old_graph, _noop),
    ]
