"""Astrolabe · 冒烟：**维护者手工修补**（`§2.3.12` 通道 ②）

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_curate.py"

> **用户原话（`B157`）**：「**修补节点是项目创建者自己修补，不是我这个管理员帮他修补。**
> 所以，**必须在网页上能操作**。」

★★★ 本轮重点（★ 都是上一批**完全没有**的东西）：

1. ★★★ **权限** —— **owner 自己** ✅ / **外人** ❌ / **staff 代改** ⚠（审计里要看得出来）
2. ★★★ **HTTP 层真的能改** —— 401 / 404（越权**与不存在同形**）/ 400 / 409 / 200
3. ★★★ **批量 = 一个事务 + 一条审计 + bump 一次**（★ 不是 N 条审计、不是跳 N 次）
4. ★★ **批量里任一条失败 ⇒ 整批回滚**（⚠ 不留"半个修补"）
5. ★★ **`base_graph_rev` 不匹配 ⇒ `stale_rev`**（★ 且带上当前 rev 供前端重放）
6. ★★★ **修补是【局部】的**（★ 与"重新解析"的本质区别）—— 原有，保留
"""

from django.contrib.auth import get_user_model
from django.test import Client
from django.test.utils import override_settings

from core.models import AuditLog, Project
from core.refs import new_project_ref
from graph import curate
from graph.models import ORIGIN_MANUAL, Edge, Node
from graph.revision import current as graph_rev
from graph.writer import GraphImmutable, write_graph

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


def section(title):
    print()
    print("=" * 84)
    print(title)
    print("=" * 84)


U = get_user_model()


def mkuser(name, *, staff=False):
    u, _ = U.objects.get_or_create(username=name)
    u.set_unusable_password()
    u.is_staff = staff
    u.save()
    return u


Owner = mkuser("smoke_k_owner")          # ★★ **项目创建者**（主路径）
Outsider = mkuser("smoke_k_outsider")    # ⚠ 无关的人（应被拒）
Admin = mkuser("smoke_k_admin", staff=True)   # ⚠ 站点管理员（代改）

REF = new_project_ref()
Project.objects.filter(project_ref=REF).delete()
p = Project.objects.create(project_ref=REF, name="冒烟·维护者修补", owner=Owner)

# ===========================================================================
section("① 先用【解析作业】建一张图（3 个节点）")
from codeparser.base import ParsedNode, ParseResult  # noqa: E402

result = ParseResult()
for nm, ln in (("parse", 10), ("render", 30), ("main", 50)):
    # ⚠ `uid` 是【派生属性】（kind#path#name）—— ★ 不能当参数传
    result.nodes.append(
        ParsedNode(kind="function", name=nm, file_path="app.py",
                   line=ln, line_end=ln + 5, lang="python")
    )
write_graph(REF, result)

nodes = list(Node.objects.filter(project_ref=REF).order_by("line"))
check("★ 解析建出 3 个节点", len(nodes), 3)
check("★★ 全部是解析产物", set(n.origin for n in nodes), {"parsed"})
rev0 = graph_rev(REF)
print(f"     graph_rev = {rev0}   行号 = {[n.line for n in nodes]}")

# ===========================================================================
section("② ★★★ 权限：★ **项目创建者自己**能改，❌ 外人不能，⚠ 管理员代改要留痕")
v_owner = curate.can_curate(REF, Owner)
check("★★★ 项目创建者 ⇒ **允许**（★ 这是主路径）", v_owner.allowed, True)
check("★ 且标为 is_owner", v_owner.is_owner, True)
check("★ 且**不是**管理员代改", v_owner.via_admin, False)

v_out = curate.can_curate(REF, Outsider)
check("★★★ 无关的人 ⇒ **拒绝**（★ 上一批完全没有这道检查）", v_out.allowed, False)
check("★★ 且**不区分「不存在」与「无权」**（§19.3）", v_out.code, "not_found")

v_admin = curate.can_curate(REF, Admin)
check("⚠ 站点管理员 ⇒ 也允许（§2.3.11「可修任何项目」）", v_admin.allowed, True)
check("★★★ **但标为「管理员代改」**（⚠ 与'他自己改的'分得开）", v_admin.via_admin, True)

v_none = curate.can_curate(REF, None)
check("★ 未登录 ⇒ 拒绝", v_none.allowed, False)

# ★ 权限拒绝是**业务失败**（⇒ `ok=False`），⚠ 不是"编程错误"（那才 `raise`）
r_out = curate.add_node(REF, by=Outsider, reason="我是外人", uid="u",
                        kind="function", name="n", file_path="f.py", line=1)
check("★★★ 外人调用 add_node ⇒ **被拒**（★ 上一批完全没有这道检查）", r_out.ok, False)
check("★ 对外只说'不存在或无权'（不泄露项目是否存在）", r_out.message, "项目不存在或无权访问")
check("★★ 且**没有真的写进去**",
      Node.objects.filter(project_ref=REF, name="n").exists(), False)

r_out2 = curate.apply_changes(REF, by=Outsider, reason="我是外人",
                              changes=[{"action": "add_node", "name": "x",
                                        "file_path": "f.py", "line": 1}])
check("★★★ 外人走 apply_changes ⇒ **被拒**", r_out2.ok, False)
check("★ 且原因不可读（不泄露项目是否存在）", r_out2.message, "项目不存在或无权访问")

# ===========================================================================
section("③ ★★★ 修补是【局部】的 —— 补一个，其余节点一个字段都不动")
before = {n.node_id: (n.line, n.line_end, n.name, n.file_path) for n in nodes}
r = curate.add_node(REF, by=Owner, reason="解析漏了模板里定义的函数",
                    uid="function#app.py#helper", kind="function", name="helper",
                    file_path="app.py", line=20, line_end=25, lang="python")
check("★ 补上了（★ 由 owner 自己操作）", r.ok, True)
check("★★ 新节点标成 origin=manual", r.node.origin, ORIGIN_MANUAL)

after = {n.node_id: (n.line, n.line_end, n.name, n.file_path)
         for n in Node.objects.filter(project_ref=REF).exclude(node_id=r.node.node_id)}
check("★★★ **其余节点【一个字段都没变】**（★ 「局部」的实证）", after, before)
check("★★ graph_rev 已 +1", graph_rev(REF), rev0 + 1)
rev1 = graph_rev(REF)

# ===========================================================================
section("④ ★★★ 批量：一次事务 + **一条审计** + **bump 一次**")
audit_before = AuditLog.objects.filter(target_id=REF).count()
batch = curate.apply_changes(
    REF, by=Owner, reason="一次性补 3 处（模板 + 宏展开漏掉的）",
    changes=[
        {"action": "add_node", "uid": "function#app.py#a1", "name": "a1",
         "file_path": "app.py", "line": 60, "lang": "python"},
        {"action": "add_node", "uid": "function#app.py#a2", "name": "a2",
         "file_path": "app.py", "line": 70, "lang": "python"},
        {"action": "add_node", "uid": "function#app.py#a3", "name": "a3",
         "file_path": "app.py", "line": 80, "lang": "python"},
        {"action": "add_edge", "from_vid": nodes[0].node_id,
         "to_vid": nodes[1].node_id, "type": "calls"},
    ],
)
check("★ 一批 4 条全部成功", batch.ok, True)
check("★ applied 逐条返回（★ 前端据此逐条确认）", batch.applied_count, 4)
# ★★★ 每个动作都必须**回带自己的 id** —— ⚠ 原先 `add_node` 漏了 `vid`，
#   单条包装取它时直接 `KeyError`（★ 就是冒烟抓出来的）
check("★★★ 每条 applied 都带 id（vid / edge_id）—— ★ 防将来再漏",
      all(("vid" in a) or ("edge_id" in a) for a in batch.applied), True)
check("★★★ **graph_rev 只 +1**（⚠ 不是 +4 —— 否则缓存反复失效）",
      batch.graph_rev, rev1 + 1)
# ⚠★ 注意：单条操作（`add_node` 等）现在**也走 `apply_changes`** ⇒ 也写这条审计。
#   所以基准是 `audit_before`，⚠ 而不是"整个项目只有 1 条"。
check("★★★ **这一批只多了一条审计**（⚠ 否则看不出'他一次干了什么'）",
      AuditLog.objects.filter(target_id=REF, action="graph.curate.apply").count(),
      audit_before + 1)
# ★★ 取**最新**那条 —— ⚠ `.first()` 默认按主键**升序**，会取到最早的那条（★ 我踩过）
log = AuditLog.objects.filter(target_id=REF, action="graph.curate.apply").order_by("-id").first()
check("★★ 审计里含**全部** changes", (log.detail or {}).get("count"), 4)
check("★ 审计里 actor = **owner 本人**（★ 不是管理员）", log.actor_id, Owner.pk)
check("★ 且标明**不是**管理员代改", (log.detail or {}).get("via_admin"), False)
rev2 = graph_rev(REF)

# ===========================================================================
section("⑤ ★★ 批量里任一条失败 ⇒ **整批回滚**（⚠ 不留'半个修补'）")
n_before = Node.objects.filter(project_ref=REF).count()
bad = curate.apply_changes(
    REF, by=Owner, reason="故意让第 2 条失败",
    changes=[
        {"action": "add_node", "uid": "function#app.py#good", "name": "good",
         "file_path": "app.py", "line": 90, "lang": "python"},
        {"action": "remove_node", "vid": 999999999},      # ← ★ 不存在
    ],
)
check("★ 整批失败", bad.ok, False)
check("★ 且指出是第几条", (bad.detail or {}).get("failed_index"), 1)
check("★★★ **第 1 条也【没生效】**（★ 这才是'要么全成、要么全不成'）",
      Node.objects.filter(project_ref=REF, name="good").exists(), False)
check("★★ 节点总数没变", Node.objects.filter(project_ref=REF).count(), n_before)
check("★★ **graph_rev 也没动**", graph_rev(REF), rev2)

# ===========================================================================
section("⑥ ★ `base_graph_rev`：不匹配 ⇒ stale（★ 不是 CAS，是善意提示）")
st = curate.apply_changes(
    REF, by=Owner, reason="基于过期的版本",
    changes=[{"action": "add_node", "uid": "function#app.py#z", "name": "z",
              "file_path": "app.py", "line": 100}],
    base_graph_rev=rev2 - 5,
)
check("★★ 不匹配 ⇒ 被拒", st.ok, False)
check("★★★ 且标为 `stale`（★ 前端据此提示'图变了，请重读'）", st.stale, True)
check("★★ 并带上**当前** rev（★ 前端靠它重放）", st.current_rev, rev2)

okc = curate.apply_changes(
    REF, by=Owner, reason="基于当前版本",
    changes=[{"action": "add_node", "uid": "function#app.py#z", "name": "z",
              "file_path": "app.py", "line": 100}],
    base_graph_rev=rev2,
)
check("★ 匹配 ⇒ 成功（★ 这就是乐观并发的正常路径）", okc.ok, True)

# ===========================================================================
section("⑦ ★ 删节点：连带删边要报告；删除的审计是它【唯一的墓碑】")
a, b = (Node.objects.filter(project_ref=REF, name="a1").first(),
        Node.objects.filter(project_ref=REF, name="a2").first())
e = curate.add_edge(REF, by=Owner, reason="补一条边", from_vid=a.node_id,
                    to_vid=b.node_id, type="calls")
check("★ 补边成功", e.ok, True)
r_del = curate.delete_node(REF, a.node_id, by=Owner, reason="这个是解析误报")
check("★ 删节点成功", r_del.ok, True)
check("★★★ **报告了连带删掉几条边**", r_del.detail.get("cascaded_edge_count"), 1)
check("★★ 边真的没了（不留悬空边）",
      Edge.objects.filter(project_ref=REF, id=e.edge.pk).exists(), False)

log_del = (AuditLog.objects.filter(target_id=REF, action="graph.curate.apply")
           .order_by("-id").first())
blob = str((log_del.detail or {}).get("applied"))
check("★★★ 删除的**完整快照**在审计里（★ 别处再也查不到了）", "a1" in blob, True)

# ===========================================================================
section("⑧ ★★★ HTTP 层：**网页上真的能改**（★ 这才是用户要的那条路）")
from django.urls import reverse  # noqa: E402

# ⚠★ 为了让"游客可读来源标注"这条断言成立，项目必须是**公开**的
#   （★ 私有项目游客读不了 —— ⚠ 那是**正确**行为，不是 bug；★ 我原先的断言搞错了前提）
p.is_public = True
p.save(update_fields=["is_public"])
url = reverse("web:graph-edit", kwargs={"project_ref": REF})
manual_url = reverse("web:graph-manual", kwargs={"project_ref": REF})
print(f"     端点: {url}")
client = Client()
OK_BODY = {"reason": "网页上补一个漏掉的函数",
           "changes": [{"action": "add_node", "uid": "function#app.py#viaweb",
                        "name": "viaweb", "file_path": "app.py", "line": 110}]}

with override_settings(ALLOWED_HOSTS=["testserver"]):
    # ---- 未登录 ⇒ 401 ----
    resp = client.post(url, data=OK_BODY, content_type="application/json")
    check("★ 未登录 ⇒ **401**（★ 前端据此弹登录，⚠ 不是越权）", resp.status_code, 401)
    check("★ 且 code = unauthenticated", resp.json()["error"]["code"], "unauthenticated")

    # ---- 外人 ⇒ 404（★ 与"不存在"同形）----
    client.force_login(Outsider)
    resp = client.post(url, data=OK_BODY, content_type="application/json")
    check("★★★ 无关的人 ⇒ **404**（★ 与'项目不存在'**不可区分**）", resp.status_code, 404)

    # ---- 不存在的项目 ⇒ 也是 404（★ 两者必须一模一样）----
    ghost = reverse("web:graph-edit", kwargs={"project_ref": new_project_ref()})
    resp_ghost = client.post(ghost, data=OK_BODY, content_type="application/json")
    check("★★★ 不存在的项目 ⇒ 也是 **404**（★ 两者**同形**，❌ 不可区分）",
          resp_ghost.status_code, 404)

    client.force_login(Owner)
    # ---- 空 body ⇒ 400 bad_json ----
    resp = client.post(url, data="", content_type="application/json")
    check("★ 空请求体 ⇒ 400 bad_json", resp.json()["error"]["code"], "bad_json")

    # ---- 没填理由 ⇒ 400（★ 这是「用户全权负责」的技术前提）----
    resp = client.post(url, data={"changes": OK_BODY["changes"]},
                       content_type="application/json")
    check("★★ 没填理由 ⇒ **400**（★ 理由必填）", resp.status_code, 400)
    check("★ 且文案说清了为什么", "审计" in resp.json()["error"]["message"], True)

    # ---- stale_rev ⇒ 409 + 当前 rev ----
    resp = client.post(url, data={"reason": "旧版本", "base_graph_rev": 1,
                                  "changes": OK_BODY["changes"]},
                       content_type="application/json")
    check("★★★ rev 不匹配 ⇒ **409**", resp.status_code, 409)
    check("★★ 且 code = stale_rev", resp.json()["error"]["code"], "stale_rev")
    check("★★ 且带上**当前** graph_rev（★ 前端靠它重放）",
          isinstance(resp.json()["data"]["graph_rev"], int), True)

    # ---- ★★★ 正常路径 ----
    before_n = Node.objects.filter(project_ref=REF).count()
    resp = client.post(url, data=OK_BODY, content_type="application/json")
    check("★★★ **owner 在网页上补节点 ⇒ 200**", resp.status_code, 200)
    body = resp.json()
    check("★ 返回契约约定的 `{graph_rev, applied}`",
          sorted(body["data"].keys()), ["applied", "graph_rev"])
    check("★★ 节点真的进了库", Node.objects.filter(project_ref=REF).count(), before_n + 1)
    check("★ 回来的是 ① 型 `{ok:true,data}`", body["ok"], True)

    # ---- 只读的 manual 接口：游客也能看（★ §19.4 来源标注）----
    client.logout()
    resp = client.get(manual_url)
    check("★ 游客可读 `graph/manual/`（★ 来源标注是读者有权知道的）",
          resp.status_code, 200)
    check("★ 且报出「人补了几项」", resp.json()["data"]["has_manual"], True)

# ===========================================================================
section("⑨ ★★ 参数校验仍然【抛】（★ 编程错误 ≠ 业务失败）")
for label, kwargs in (("不给 by", dict(by=None, reason="x")),
                      ("不给 reason", dict(by=Owner, reason="   "))):
    try:
        curate.apply_changes(REF, changes=[{"action": "add_node", "name": "n",
                                            "file_path": "f.py", "line": 1}], **kwargs)
        check(f"★★ {label} ⇒ 应抛异常", "没抛", "ValueError")
    except ValueError:
        check(f"★★ {label} ⇒ 抛异常（★ 无法省略）", "ValueError", "ValueError")

r_bl = curate.apply_changes(REF, by=Owner, reason="试改主键",
                            changes=[{"action": "update_node", "vid": nodes[0].node_id,
                                      "fields": {"node_id": 99999}}])
check("★★ 白名单：改 node_id ⇒ 被拒", r_bl.ok, False)

# ===========================================================================
section("⑩ ★ 与「图不可变」【不冲突】—— 两条纪律同时成立")
p.refresh_from_db()
check("★ 修补**不会**清掉「已定版」标记", p.is_graph_built, True)
try:
    write_graph(REF, result)
    check("★★★ 系统重新解析 ⇒ 仍被拒", "没抛", "GraphImmutable")
except GraphImmutable:
    check("★★★ 系统重新解析 ⇒ 仍被拒（★ 图不可变没被修补破坏）",
          "GraphImmutable", "GraphImmutable")

s = curate.manual_summary(REF)
print(f"     节点 {s['total_nodes']}（★ 人补 {s['manual_nodes']}）"
      f"  边 {s['total_edges']}（★ 人补 {s['manual_edges']}）  rev={s['graph_rev']}")
check("★ 能数出人补的节点", s["manual_nodes"] >= 1, True)

# ===========================================================================
# 清理
Edge.objects.filter(project_ref=REF).delete()
Node.objects.filter(project_ref=REF).delete()
Project.objects.filter(project_ref=REF).delete()

print()
print("=" * 84)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   - {f}")
else:
    print("✅ 全部通过")
print("=" * 84)
