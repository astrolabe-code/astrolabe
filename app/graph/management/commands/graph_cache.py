"""Astrolabe · 邻域缓存维护

★ 依据 `GRAPH-STORAGE.md` G5。

⚠ **正常运维不需要这些命令** —— 改图只要 `GraphRevision.rev + 1`（由
  `write_graph` **自动在写图事务内**完成），旧代际的缓存**立刻不可达**，
  由 TTL 自然消亡。❌ 不需要删任何 key。

★ 这些命令是给**异常排查 / 内存回收 / 人工对账**用的。

用法：
    python manage.py graph_cache proj_demo0001 --stats
    python manage.py graph_cache proj_demo0001 --show-rev
    python manage.py graph_cache proj_demo0001 --flush       # ⚠ 全项目缓存作废
    python manage.py graph_cache proj_demo0001 --rev-check   # ★ 对账：缓存代际 vs 权威 rev
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from graph import cache, revision


class Command(BaseCommand):
    help = "邻域缓存维护（查看 / 对账 / 强制作废）"

    def add_arguments(self, parser):
        parser.add_argument("project_ref")
        parser.add_argument("--stats", action="store_true")
        parser.add_argument("--show-rev", action="store_true")
        parser.add_argument("--flush", action="store_true", help="⚠ 强制作废该项目的全部邻域缓存")
        parser.add_argument("--rev-check", action="store_true", help="★ 对账缓存代际与权威 rev")

    def handle(self, *args, **opts):
        pr = opts["project_ref"]
        cfg = cache.config()

        if opts["show_rev"]:
            self.stdout.write(f"权威 rev（数据库）: {revision.current(pr)}")
            return

        if opts["flush"]:
            n = cache.invalidate(pr)
            self.stdout.write(
                self.style.WARNING(
                    f"已作废 {n} 个缓存 key（{pr}）\n"
                    f"⚠ 正常情况【不需要】这一步 —— 改图后 rev 自增即可失效"
                )
            )
            return

        if opts["rev_check"]:
            # ★ 扫一遍现有 key，看看里面写的代际号与权威 rev 是否一致
            client = cache.get_client()
            prefix = f"{cache.PREFIX}:{pr}:"
            revs: dict[str, int] = {}
            total = 0
            for key in client.scan_iter(match=f"{prefix}*", count=500):
                k = key.decode() if isinstance(key, bytes) else key
                total += 1
                part = k.split(":r", 1)[1].split(":", 1)[0] if ":r" in k else "?"
                revs[part] = revs.get(part, 0) + 1
            cur = revision.current(pr)
            self.stdout.write(f"权威 rev : {cur}")
            self.stdout.write(f"缓存 key : {total} 个，按代际分布：")
            for r, c in sorted(revs.items()):
                mark = "★ 当前代际" if r == str(cur) else "⚠ 旧代际（等待 TTL 清理）"
                self.stdout.write(f"   r{r:<4} {c:>6} 个   {mark}")
            return

        # 默认 / --stats
        self.stdout.write(f"项目      : {pr}")
        self.stdout.write(f"权威 rev  : {revision.current(pr)}")
        self.stdout.write(f"缓存开关  : {'开' if cfg['enabled'] else '关'}")
        self.stdout.write(f"热度开关  : {'开' if cfg['hot_enabled'] else '关'}")
        self.stdout.write(f"TTL       : {cfg['ttl']} 秒（{cfg['ttl'] / 86400:.1f} 天）")
        self.stdout.write(f"单值上限  : {cfg['max_bytes'] / 1024:.0f} KB（超过不缓存）")
        self.stdout.write(
            f"Redis 超时: 读 {cfg['socket_timeout']}s / 连 {cfg['socket_connect_timeout']}s "
            f"（★ 熔断阈值 {cfg['breaker_threshold']} 次，冷却 {cfg['breaker_cooldown']}s）"
        )
        self.stdout.write(f"已缓存 key: {cache.key_count(pr)} 个")
