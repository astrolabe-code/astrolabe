# `B192` / `B198` 第一步：**先修数据，再改结构**
#
# ★★ 为什么必须有这一步（★ 不改数据就加不上约束）：
#
# ```
# ① `owner` 要改成 NOT NULL（`B198`：没有平台代管项目）
#    ── ★★ 而库里**有 1 行** `owner_id IS NULL` ⚠
#       （★ `冒烟·无许可证项目` —— ★ 冒烟脚本建的）
#
# ② 要加 `UNIQUE (owner_id, name)`（`B192`：同一用户下不许重名）
#    ── ★★ 而库里**有 3 组**重名，★ 共 34 行 ⚠
#       · ★ 21 × `r`
#       · ★ 11 × `冒烟·维护者修补`
#       · ★  2 × `dbg`
#       ★★ 全是冒烟脚本造的 ✅
# ```
#
# ## ★★ 处置口径（★ 依据 `B197`）
#
# > ★★★ 所有者原话（逐字）：
# >   「**你为历史遗留问题保留的字段给我删掉，那些历史遗留数据是我测试用的，
# >     把他们丢了，完全没问题**」
#
# ⇒ ★★ 所以：★ **不删行**（★ 删会扯动外键），★ 而是**改名 + 挂属主** ⚠
#   · ★ `owner` 为空 ⇒ ★ 挂给**第一个超管**（★ 没有超管才挂第一个活跃用户）✅
#   · ★ 重名 ⇒ ★ 在原名后追加 ` #n`（★ `n` 从 2 起，★ 直到不撞）✅
#   · ★★ 保留 `project_ref` 不变 ⇒ ★ **URL / 前端缓存全不受影响** ✅
#
# ⚠★ 本迁移**只碰数据**，★ 结构改动在 `0014`（★ 由 `makemigrations` 生成）⚠

from django.db import migrations


def _fix(apps, schema_editor):
    Project = apps.get_model("core", "Project")
    User = apps.get_model("auth", "User")

    # ---- ① 给空属主挂一个真实用户 ------------------------------------
    orphans = Project.objects.filter(owner__isnull=True)
    n_orphan = orphans.count()
    if n_orphan:
        admin = (
            User.objects.filter(is_superuser=True, is_active=True).order_by("id").first()
            or User.objects.filter(is_active=True).order_by("id").first()
        )
        if admin is None:
            # ⚠★ 连一个用户都没有 ⇒ **不能**瞎挂 ⇒ 让迁移当场失败 ⚠
            #   （★ 否则改 NOT NULL 时会以一个更难懂的原因失败）⚠
            raise RuntimeError(
                f"有 {n_orphan} 个项目没有属主，而库里没有任何用户可挂 —— "
                "请先建一个管理员账号再跑本迁移"
            )
        orphans.update(owner=admin)

    # ---- ② 重名 ⇒ 追加后缀 -------------------------------------------
    #   ★★ 按 (owner, name) 分组，★ 只处理 count > 1 的组 ✅
    #   · ★ 保留每组的**第一行**不改（★ 它"占着"原名）
    #   · ★ 其余行依次改名，★ 直到不再撞 ✅
    seen: dict[tuple[int, str], int] = {}
    renamed = 0
    # ⚠★ 按 id 顺序处理 ⇒ ★ 同样的数据总是得到同样的结果（★ 可重入）✅
    for p in Project.objects.order_by("id").only("id", "owner_id", "name"):
        k = (p.owner_id, p.name)
        seen[k] = seen.get(k, 0) + 1
        n = seen[k]
        if n == 1:
            continue
        base = p.name
        while True:
            cand = f"{base} #{n}"
            n += 1
            if not Project.objects.filter(owner_id=p.owner_id, name=cand).exists():
                break
        Project.objects.filter(pk=p.pk).update(name=cand)
        renamed += 1


def _noop(apps, schema_editor):
    """⚠★ **故意不可回滚** —— ★ 改名 / 挂属主都**不该**自动还原 ⚠

    ★ 理由：★ 还原会把数据推回"违反新约束"的状态 ⚠
      ⇒ ★★ 那时连回滚这个迁移本身都会失败 ⚠
    """


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_alter_oauthstate_action"),
    ]

    operations = [
        migrations.RunPython(_fix, reverse_code=_noop),
    ]
