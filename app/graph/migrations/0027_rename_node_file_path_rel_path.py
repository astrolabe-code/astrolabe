"""Node.file_path → Node.rel_path

★ 所有者原话（2026-11-18）：
  「数据库字段也改呀，跑个迁移就行」

【为什么改】图库（Code 表）与关系库（Node 表）存的是同一个东西——
  源码文件相对路径。两边一个叫 file_path、一个叫 rel_path，
  每次跨层读写都要想「这里该用哪个名字」，已经踩过 rel_path 全空的坑。

【注意】RenameField 在各数据库下的行为：
  · PostgreSQL：ALTER TABLE ... RENAME COLUMN（瞬时，不锁表）
  · SQLite    ：重建表（数据量小，可接受）
  索引 `ix_node_repo_path` 引用的是列本身，重命名后会跟着更新，无需额外操作。
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("graph", "0026_node_version_attrs"),
    ]

    operations = [
        migrations.RenameField(
            model_name="node",
            old_name="file_path",
            new_name="rel_path",
        ),
        # ⚠ 模型里的索引字段从 file_path 改成了 rel_path：
        #   索引名不变，但 Django 认为「定义变了」⇒ 必须显式删了重建，
        #   否则 makemigrations --check 会一直报有未应用的迁移。
        migrations.RemoveIndex(
            model_name="node",
            name="ix_node_repo_path",
        ),
        migrations.AddIndex(
            model_name="node",
            index=models.Index(fields=["repo", "rel_path"], name="ix_node_repo_path"),
        ),
    ]
