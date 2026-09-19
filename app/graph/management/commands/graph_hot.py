"""Astrolabe · 节点访问热度（★ 热力图的数据源）

★ 依据 `GRAPH-STORAGE.md` G5 —— 邻域缓存的副产品：
  用户**反复查看的就是那几个难懂的函数**（幂律分布），
  把这个事实**记下来**，就能反过来告诉所有人「**哪里最难懂**」。

★★ 指标的扩展通道（`graph/cache.py`）：

| 指标 | 状态 |
|---|---|
| `visit`（被查看次数） | ✅ 已实现 |
| `notes`（被写了多少条解释） | ⚠ 将来 —— 来自 UGC，**与 visit 加权合成最终热度** |
| `comments`（被评论多少条） | ⚠ 将来 |

⚠ **计数在 Redis（热数据）** ⇒ Redis 重启会丢。
  正式上线前需要一个**定期合并进数据库**的作业（待办，见 B128）。

用法：
    python manage.py graph_hot proj_demo0001
    python manage.py graph_hot proj_demo0001 --limit 30
    python manage.py graph_hot proj_demo0001 --reset
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from graph import cache, heat
from graph.models import Node


class Command(BaseCommand):
    help = "打印节点的访问热度 TOP N（★ 热力图的数据源）"

    def add_arguments(self, parser):
        parser.add_argument("project_ref")
        parser.add_argument("--metric", default=cache.HOT_VISIT)
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--reset", action="store_true", help="⚠ 清空该项目的热度统计")

    def handle(self, *args, **opts):
        pr = opts["project_ref"]
        metric = opts["metric"]

        if opts["reset"]:
            n = cache.hot_reset(pr)
            self.stdout.write(self.style.WARNING(f"已清空 {n} 个热度 key（{pr}）"))
            return

        # ★★ 读路径 = 数据库权威累计值 + Redis 未合并增量（见 graph/heat.py）
        #    ⚠ 只读 DB 会"慢半拍"（刚点的还没落库）；只读 Redis 会"丢历史"（重启就没了）
        rows = heat.top_nodes(pr, metric=metric, limit=opts["limit"])
        if not rows:
            self.stdout.write("（暂无热度数据 —— 跑几次 neighborhood 查询就会有了）")
            return

        # ★ 一次查出所有 uid 对应的节点（❌ 不要 N 次查询）
        uids = [uid for uid, _, _ in rows]
        nodes: dict[str, Node] = {}
        for n in Node.objects.filter(project_ref=pr, uid__in=uids).order_by("node_id"):
            nodes.setdefault(n.uid, n)  # ⚠ uid 可能重复 ⇒ 取最小 vid

        total = sum(db_val + pend for _, db_val, pend in rows)
        self.stdout.write(f"项目: {pr}   指标: {metric}   TOP {len(rows)}")
        self.stdout.write(
            "说明: ★ 计数按 **uid**（跨重新解析稳定）；⚠ uid 可重复 ⇒ 同名节点合并计数"
        )
        self.stdout.write(
            "来源: **数据库权威值** + **Redis 未合并增量**（后者由 `heat_flush` 定期落库）"
        )
        self.stdout.write("")
        self.stdout.write(
            f"{'#':>3}  {'总次数':>7}  {'已落库':>7}  {'未合并':>6}  {'占比':>6}  "
            f"{'类型':<9} {'名字':<26} 位置"
        )
        self.stdout.write("-" * 118)
        for i, (uid, db_val, pend) in enumerate(rows, start=1):
            tot = db_val + pend
            n = nodes.get(uid)
            if n is None:
                self.stdout.write(
                    f"{i:>3}  {tot:>7}  {db_val:>7}  {pend:>6}  {tot / total:>5.1%}  "
                    f"{'?':<9} {uid[:58]}"
                )
                continue
            self.stdout.write(
                f"{i:>3}  {tot:>7}  {db_val:>7}  {pend:>6}  {tot / total:>5.1%}  "
                f"{n.kind:<9} {n.name:<26} {n.file_path}:{n.line}  (vid {n.node_id})"
            )

        self.stdout.write("")
        self.stdout.write(
            "★ 这就是「**哪几个函数最难懂**」的直接证据 —— "
            "用户反复来看，通常不是因为好玩，是因为**看不懂**。"
        )
