# `B183` / `B197`：**把新加的 `project` 外键从 `project_ref` 回填**
#
# ## 为什么必须回填
#
# ```
# ★ 外键是【后来加的】⇒ ★ 存量行的 `project_id` 全是 NULL ⚠
#   · ★ 而 NULL ⇒ ★ 外键**一个都挡不住**（* 它只挡"指向不存在的东西"）⚠
#   · ★★ 那这一步不做 ⇒ ★ 等于白加 ⚠
# ```
#
# ## ⚠★ 自检：**对不上的 project_ref 要报出来**
#
# ```
# ★ 若某个 `project_ref` 在 `core_project` 里找不到 ⇒ ★ 那是【孤儿行】⚠
#   · ★ 它正是"项目删了、这些行还在"的活证据 ⚠
#   · ★★ 而本项目**已经因此出过事**（* "判重只看流水 ⇒ 删了项目照样拦死人"）⚠
# ```
#
# ⇒ ★ 所以：★ 孤儿行**不静默跳过**，* 而是**数出来、写进日志** ⚠
#   · ★ 若数量是 0 ⇒ ★ 皆大欢喜 ✅
#   · ★ 若不是 0 ⇒ ★ 那些行的 `project_id` 留 NULL（* 由人决定怎么处置）⚠
#   ★★ 而不该由迁移**自作主张**删掉它们 ✅

from django.db import migrations


def _backfill(apps, schema_editor):
    Project = apps.get_model("core", "Project")
    Job = apps.get_model("jobs", "Job")

    refs = list(
        Job.objects.exclude(project_ref="")
        .values_list("project_ref", flat=True)
        .distinct()
    )
    if not refs:
        return

    by_ref = dict(
        Project.objects.filter(project_ref__in=refs).values_list("project_ref", "id")
    )
    orphan = sorted(set(refs) - set(by_ref))

    moved = 0
    for ref in refs:
        if ref not in by_ref:
            continue
        moved += Job.objects.filter(project_ref=ref, project=None).update(
            project_id=by_ref[ref]
        )

    # ⚠★ 孤儿行：数出来，* 不删、* 不静默 ✅
    if orphan:
        print(
            f"  ⚠ [B197] {len(orphan)} 个 project_ref 在 core_project 里找不到"
            f"（孤儿行，project_id 留 NULL 由人处置）：{orphan[:5]}"
        )


def _noop(apps, schema_editor):
    """⚠★ **故意不可回滚** —— ★ 把外键清成 NULL 只会让它重新失去约束力 ⚠"""
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0003_job_project"),
    ]

    operations = [
        migrations.RunPython(_backfill, reverse_code=_noop),
    ]
