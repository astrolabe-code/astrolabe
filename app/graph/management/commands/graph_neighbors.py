"""Astrolabe · 调试命令：打印一个节点的 N 跳邻域

★ 用途：
   · **评估遍历成本** —— 几跳会开始爆、在哪一层被预算截断（`GRAPH-STORAGE.md` G10-1）
   · 验证四道刹车（深度 / 节点 / 边 / statement_timeout）是否真的生效

⚠ 只读命令 —— 不写任何数据。

用法：
    python manage.py graph_neighbors 42       --project-ref proj_demo0001 --depth 3
    python manage.py graph_neighbors run_parse_job --project-ref proj_demo0001 --depth 4
    python manage.py graph_neighbors 42 --project-ref proj_xxx --depth 6 --direction in
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from graph.traversal import (
    DIRECTION_BOTH,
    DIRECTION_IN,
    DIRECTION_OUT,
    get_reader,
    resolve_limits,
)


class Command(BaseCommand):
    help = "打印一个节点的 N 跳邻域（★ 评估遍历成本 / 验证刹车是否生效）"

    def add_arguments(self, parser):
        parser.add_argument("node", help="vid（整数）或 uid（字符串）")
        parser.add_argument("--project-ref", required=True)
        parser.add_argument("--depth", type=int, default=1)
        parser.add_argument(
            "--direction",
            choices=(DIRECTION_OUT, DIRECTION_IN, DIRECTION_BOTH),
            default=DIRECTION_OUT,
        )
        parser.add_argument("--edge-types", default="", help="逗号分隔，如 calls,imports")
        parser.add_argument("--max-nodes", type=int, default=None)
        parser.add_argument("--max-edges", type=int, default=None)
        parser.add_argument("--show", type=int, default=8, help="每层最多打印多少个节点")

    def handle(self, *args, **opts):
        raw = str(opts["node"])
        node: int | str = int(raw) if raw.isdigit() else raw

        edge_types = [t.strip() for t in (opts["edge_types"] or "").split(",") if t.strip()]
        overrides: dict = {}
        if opts["max_nodes"] is not None:
            overrides["max_nodes"] = opts["max_nodes"]
        if opts["max_edges"] is not None:
            overrides["max_edges"] = opts["max_edges"]

        # ★ 走 `get_reader()` 而不是 `neighborhood()` ——
        #   ⚠ 后者会记访问热度，**调试命令不该污染热度统计**
        sg = get_reader().neighborhood(
            opts["project_ref"],
            node,
            depth=opts["depth"],
            direction=opts["direction"],
            edge_types=edge_types or None,
            limits=overrides or None,
        )

        if sg.root is None:
            raise CommandError(f"节点不存在：{node}（项目 {opts['project_ref']}）")

        st = sg.stats
        cfg = resolve_limits(overrides)
        self.stdout.write(f"项目      : {sg.project_ref}")
        self.stdout.write(f"起点      : vid={sg.root}  节点={node}")
        self.stdout.write(
            f"方向      : {st['direction']}    "
            f"请求跳数 {st['requested_depth']} → 实际 {st['depth']}（到第 {st['levels_reached']} 层）"
        )
        self.stdout.write(
            f"结果      : {st['nodes']} 节点 / {st['edges']} 边    "
            f"用时 {st['elapsed_ms']} ms"
        )
        self.stdout.write(
            f"各层节点数: "
            + " / ".join(str(st["per_level"].get(d, 0)) for d in range(st["depth"] + 1))
        )

        if st["ambiguous_uid"]:
            self.stdout.write(self.style.WARNING("⚠ uid 存在重复，已取最小 vid"))
        if sg.truncated:
            self.stdout.write(self.style.WARNING(f"⚠ 已截断：{sg.truncated_reason}"))
        else:
            self.stdout.write(self.style.SUCCESS("✅ 未截断（预算足够）"))

        self.stdout.write(
            f"预算      : 深度≤{cfg['max_depth']} · 节点≤{st['budget']['max_nodes']} · "
            f"边≤{st['budget']['max_edges']} · 时间≤{cfg['max_seconds']:g}s · "
            f"statement_timeout={st['budget']['statement_timeout_ms']}ms"
        )

        by_depth: dict[int, list] = {}
        for n in sg.nodes:
            by_depth.setdefault(n.depth, []).append(n)

        out_deg: dict[int, int] = {}
        for e in sg.edges:
            out_deg[e.src] = out_deg.get(e.src, 0) + 1

        for d in sorted(by_depth):
            label = "起点" if d == 0 else f"第 {d} 跳"
            self.stdout.write("")
            self.stdout.write(f"── {label}（{len(by_depth[d])} 个）──")
            for n in by_depth[d][: opts["show"]]:
                deg = out_deg.get(n.vid, 0)
                self.stdout.write(
                    f"   [vid {n.vid:>5}] {n.kind:<9} {n.name:<26} "
                    f"{n.file_path}:{n.line}   出边 {deg}"
                )
            if len(by_depth[d]) > opts["show"]:
                self.stdout.write(f"   … 还有 {len(by_depth[d]) - opts['show']} 个")
