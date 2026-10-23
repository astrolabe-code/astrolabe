# ★ 项目表补上「真实节点数 / 边数」与「平台 / 拉库地址」四列（2026-10-23）
#
# 所有者原话：
#   「项目表补上这个项目的真实节点数和边数字段，每次现算干什么？用户每次修改节点和边，
#    项目表里的边数和节点数同步修改，同时，加上是 github 或 gitee 或自建项目字段，
#    以及拉库所用网址字段。当然，这两个 github 之类的信息字段一旦创建，无法修改，
#    不要有修改接口。」
from django.db import migrations, models

HOSTS = {"github": "github.com", "gitee": "gitee.com"}


def backfill(apps, schema_editor):
    """★ 存量回填：基图计数 + 叠加层计数；平台/地址从基图取一次 ✅"""
    Project = apps.get_model("core", "Project")
    Node = apps.get_model("graph", "Node")
    Edge = apps.get_model("graph", "Edge")

    for p in Project.objects.select_related("base_graph").all():
        bg = p.base_graph

        n = (bg.node_count if bg else 0) + Node.objects.filter(
            project__project_ref=p.project_ref
        ).count()
        e = (bg.edge_count if bg else 0) + Edge.objects.filter(
            project__project_ref=p.project_ref
        ).count()

        provider = (bg.provider or "") if bg else ""
        full = (bg.repo_full_name or "").strip().strip("/") if bg else ""
        host = HOSTS.get(provider)
        url = f"https://{host}/{full}" if host and full else ""

        Project.objects.filter(pk=p.pk).update(
            node_count=n,
            edge_count=e,
            provider=provider[:16],
            repo_url=url[:512],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0046_drop_note_trgm"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="node_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="project",
            name="edge_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="project",
            name="provider",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="project",
            name="repo_url",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
