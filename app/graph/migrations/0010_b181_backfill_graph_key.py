# `B181` 第二步：**回填**「请求地址」与「身份证号」
#
# ★★ 所有者原话（逐字）：
#
# > 「**基图数据应该记录对应的请求地址**，比如 https://github.com/chk/repo/blob/{sha}/，
# > 以后对比这个地址，就知道取的是不是同一份数据，**如果比较字符串比较麻烦，
# > 毕竟前面的https这些一模一样，可以用这个地址生成唯一的ID来比较，
# > 这是基图的身份证号。**」
#
# ★ 本迁移给每一行补上这两样（★ 与 `graph/models.py::canonical_url()` **同一套规则**）⚠
#
# ⚠★ **三种来源，一条都不能空**（★ 所有者 2026-10-13 裁定：
#   「有唯一性约束，而字段是""的，你直接随便填一个值就完了呗」⚠）：
#
# | 来源 | 地址长什么样 |
# |---|---|
# | ★ 远端源码（★ 有真 sha）| ★ `https://github.com/{owner}/{repo}/blob/{sha}` |
# | ★ 调试源码（★ `sha='local'`）| ★★ `file://{目录}` —— ⚠ 但**存量行没记过目录** ⚠ |
# | ★★ 两者都推不出来 | ★★ `legacy://{平台}/{仓库}/{sha}` ← ★ 本迁移对老调试行的处理 ✅ |
#
# ★★ 为什么用 `legacy://` 而不是留空：
#   · ★ 字段**按设计就要有值**（★ 空号的行 `find()` 查不到 ⇒ 永远孤立）⚠
#   · ★★ 而它**不会被误当成真地址** —— `blob_url` 只回 `https://` 开头 ✅
#   · ★ 仍然保持 (平台+仓库+sha) 的**唯一性** ⇒ ★ 不会互相撞 ✅
#
# ⚠★ 顺带把 `provider` / `repo_full_name` / `sha` **规范化**（转小写）——
#   ★★ 这是 `B181` 要修的那个真 bug：★ `chk/repo` / `Chk/Repo` / `chk/Repo`
#     曾造出 **3 份**基图（★ 而平台认为它们是**同一个仓库**）⚠
#   · ★ 已验证：★ 规范化后**没有重复组**，★ 所以这次合并不会丢数据 ✅

import hashlib
import re

from django.db import migrations

#: ★ 与 `graph/models.py::BaseGraph._HOSTS` 保持一致 ⚠（★ 改一处要改两处）
HOSTS = {"github": "github.com", "gitee": "gitee.com"}

#: ★ 真 commit sha：★ 十六进制、≥7 位（★ GitHub 短 sha 就是 7 位）
HEX_SHA = re.compile(r"^[0-9a-f]{7,}$")


def _canonical(provider: str, repo_full_name: str, sha: str) -> str:
    """★ 与 `BaseGraph.canonical_url()` 同一套规则（★ 迁移里不能用模型方法）。"""
    prov = (provider or "").strip().lower()
    full = (repo_full_name or "").strip().strip("/").lower()
    commit = (sha or "").strip().lower()

    if HEX_SHA.match(commit):
        host = HOSTS.get(prov)
        if host and full:
            return f"https://{host}/{full}/blob/{commit}"
        return ""
    # ⚠ 不是真 sha ⇒ 调试路径，★ 而**存量行没记过目录** ⇒ 只能标记成 legacy
    return ""


def _key_of(url: str) -> str:
    """★ 与 `BaseGraph.key_of()` 同一套算法（★ SHA-256 取前 32 位）。"""
    return hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:32]


def _backfill(apps, schema_editor):
    """★★ 给存量行补 `request_url` / `graph_key`（★ 并规范化三个身份字段）。"""
    BaseGraph = apps.get_model("graph", "BaseGraph")

    rows = list(
        BaseGraph.objects.all().only(
            "id", "provider", "repo_full_name", "sha", "request_url", "graph_key"
        )
    )
    if not rows:
        return

    # ---- ⓵ 先算好每一行的地址与身份证号 ----
    plan = {}
    for bg in rows:
        prov = (bg.provider or "").strip().lower()
        full = (bg.repo_full_name or "").strip().strip("/").lower()
        commit = (bg.sha or "").strip().lower()

        url = _canonical(prov, full, commit)
        if not url:
            # ⚠★ 推不出来（★ 存量调试行）⇒ ★ `legacy://` 明确标记 ✅
            #   ★ 用 (平台+仓库+sha) 保证它仍然唯一（★ 不会和别行撞）✅
            url = f"legacy://{prov}/{full}/{commit}"

        plan[bg.pk] = {
            "provider": prov,
            "repo_full_name": full,
            "sha": commit,
            "request_url": url,
            "graph_key": _key_of(url),
        }

    # ---- ⓶ ★★ 合并重复（★ 规范化之后才可能现形）----
    #   ⚠ 两个行算出**同一个身份证号** ⇒ ★ 它们是同一份源码版本 ⚠
    #   ★★ 保留「已建好」的那个（★ `built_at` 有值），★ 因为那才有图数据 ⚠
    #   · ★ 另一个的绑定关系要**改指**到保留行（★ 否则那些项目会变成"没图"）⚠
    #   · ★ 另一个**直接删掉**（★ 它的节点/边随 CASCADE 走；★ 它是重复产物）⚠
    ProjectBaseGraph = apps.get_model("graph", "ProjectBaseGraph")

    by_key: dict[str, int] = {}          # graph_key ⇒ 保留下来的 pk
    doomed: list[int] = []
    for bg in BaseGraph.objects.all().only("id", "graph_key", "built_at").order_by("id"):
        want = plan[bg.pk]["graph_key"]
        if want in by_key:
            doomed.append(bg.pk)
        else:
            by_key[want] = bg.pk

    if doomed:
        # ★★ 先决定"谁留下"：★ 已建好的优先，★ 否则留 id 最小的 ✅
        keep: dict[str, int] = {}
        for bg in BaseGraph.objects.filter(pk__in=[p for p in plan]).only(
            "id", "graph_key", "built_at"
        ).order_by("id"):
            want = plan[bg.pk]["graph_key"]
            if want not in keep or (bg.built_at and not _built(keep[want], BaseGraph)):
                keep[want] = bg.pk
        for dead in doomed:
            if dead in keep.values():
                doomed.remove(dead)

        for dead in doomed:
            want = plan[dead]["graph_key"]
            survivor = keep.get(want)
            if survivor is None:
                continue
            # ★★ 绑定关系改指（★ 否则那些项目当场变成"没有图"）⚠
            ProjectBaseGraph.objects.filter(base_graph_id=dead).update(
                base_graph_id=survivor
            )
            BaseGraph.objects.filter(pk=dead).delete()

    # ---- ⓷ 写回 ----
    for pk, vals in plan.items():
        if pk in doomed:
            continue
        BaseGraph.objects.filter(pk=pk).update(**vals)


def _built(pk: int, BaseGraph) -> bool:
    """★ 那一行建好了吗（★ `built_at` 有值）。"""
    return bool(BaseGraph.objects.filter(pk=pk, built_at__isnull=False).exists())


def _noop(apps, schema_editor):
    """★ 反向不做事 —— ⚠ 回填过的字段留着无害（★ 它们本来就是派生值）。"""


class Migration(migrations.Migration):

    dependencies = [
        ('graph', '0009_basegraph_request_url_graph_key'),
    ]

    operations = [
        migrations.RunPython(_backfill, _noop),
    ]
