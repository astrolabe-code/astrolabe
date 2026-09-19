"""Astrolabe · 热度合并（Redis 热数据 → 数据库权威值）

★ 依据 `GRAPH-STORAGE.md` G5 · `B128` 的待办：
  Redis 里的计数是**热数据** —— ⚠ **Redis 重启就没了**。
  ⇒ 必须**定期把增量合并进数据库**，DB 才是**权威累计值**。

★★ 三个不能省的细节（每一个都对应一种真实的丢数据 / 算错）：

| # | 细节 | ❌ 不这么做会怎样 |
|---|---|---|
| **1** | ★ **用 `RENAME` 原子轮换**，不是「读完再清零」 | 读完之后、清零之前进来的访问会被**一起减掉** ⇒ **丢计数** |
| **2** | ★ **残留批次要捡回来** | 轮换后、合并前崩了 ⇒ 那批计数**永远躺在临时 key 里**，没人知道 ⇒ 丢一批 |
| **3** | ★ **幂等闸门 `HeatFlush`** | 写库后、删 key 前崩了 ⇒ 重跑会**重复累加** ⇒ 热度虚高，越重启越离谱 |

★ 为什么 `RENAME` 是对的：它**原子**——
  轮换那一刻之后的所有 `ZINCRBY` 都落到**新的主 key** 上，
  ❌ 不会被这一次合并碰到 ⇒ **既不丢、也不重**。

⚠ 分层（`ARCHITECTURE.md` A3）：本模块属于 graph 层，可被 ② 作业层调用；
  ⚠ 它**不在请求路径上**（由作业 / cron 触发），所以失败可以**大声报错**。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from graph import cache
from graph.models import HeatFlush, NodeHeat

log = logging.getLogger("astrolabe.graph.heat")

#: ★ 合并用到的指标（⚠ 可扩展：将来把 `notes` / `comments` 加进来）
_DEFAULT_METRICS = (cache.HOT_VISIT,)


def config() -> dict:
    cfg = {"metrics": _DEFAULT_METRICS, "lock_ttl": 120}
    cfg.update(getattr(settings, "ASTROLABE_HEAT", None) or {})
    return cfg


@dataclass
class FlushReport:
    """一次合并的结果（★ 供作业回写进度与人工核对）。"""

    projects: int = 0
    batches: int = 0
    rows: int = 0
    total: int = 0
    skipped: list[str] = field(default_factory=list)
    dry_run: bool = False

    def merge(self, other: "FlushReport") -> None:
        self.projects += other.projects
        self.batches += other.batches
        self.rows += other.rows
        self.total += other.total
        self.skipped.extend(other.skipped)


# ---------------------------------------------------------------------------
# ① 找出「哪些项目有热度」
# ---------------------------------------------------------------------------

def _parse_hot_key(key: str) -> tuple[str, str] | None:
    """`astrolabe:hot:{metric}:{project_ref}[:flush:...]` → `(project_ref, metric)`。

    ⚠ 批次 key 的尾巴（`:flush:...`）必须切掉，否则项目名会被污染成
      `proj_x:flush:1699...`，合并时找不到对应的热度。
    """
    parts = key.split(":")
    if len(parts) < 4 or parts[0] != "astrolabe" or parts[1] != "hot":
        return None
    metric, rest = parts[2], parts[3]
    # ⚠ 项目标识内部不含 ':'（`^proj_[0-9a-f]+$`）⇒ 第一个片段就是它
    return (rest, metric) if rest else None


def discover(client, metrics=None) -> list[tuple[str, str]]:
    """★ 扫出所有「有未合并热度」的 (project_ref, metric)。

    ⚠ 用 `SCAN` 而不是 `KEYS` —— 前者不阻塞 Redis 主线程。
    ★ 热度 key 的数量级是「项目数 × 指标数」，很小，扫一遍毫无压力。
    """
    allowed = set(metrics or config()["metrics"])
    found: set[tuple[str, str]] = set()
    for raw in client.scan_iter(match="astrolabe:hot:*", count=500):
        key = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        parsed = _parse_hot_key(key)
        if parsed and parsed[1] in allowed:
            found.add(parsed)
    return sorted(found)


# ---------------------------------------------------------------------------
# ② 单项目单指标合并
# ---------------------------------------------------------------------------

def _collect_batches(client, main_key: str) -> list[str]:
    """收集待合并批次：**上次的残留** + **这次刚轮换出来的**。

    ★★ 顺序很重要：
      ① 先把残留（`:flush:*`）找出来 —— 那是上一次崩在中间的批次
      ② 再 `RENAME` 主 key ⇒ 新的增量落到**新的主 key**，本次合并碰不到
    """
    batches: list[str] = []
    # ① 残留（可能是上次崩溃留下的）
    for raw in client.scan_iter(match=f"{main_key}:flush:*", count=200):
        batches.append(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)

    # ② 原子轮换
    rotated = f"{main_key}:flush:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
    try:
        client.rename(main_key, rotated)  # ⚠ 源 key 不存在时会抛 ResponseError
        batches.append(rotated)
    except Exception:  # noqa: BLE001 —— 主 key 不存在（没有增量）⇒ 正常情况
        pass

    return batches


def _apply(project_ref: str, metric: str, batches: list[str], rows_by_batch: dict) -> FlushReport:
    """把各批次累加进数据库（★ 与幂等闸门**同一个事务**）。"""
    report = FlushReport(projects=1)
    table = NodeHeat._meta.db_table

    # ★ PG 的 UPSERT：`value = 旧值 + 新值`。
    #   ⚠ 这里用原生 SQL 是有意的 —— ORM 的 `bulk_create(update_conflicts=...)`
    #     **不支持「累加」语义**（只能覆盖），逐行 `update` 又是 N 次往返。
    #     ⚠ 代价：这段是 PG 专属；将来若换库，**这里是少数几个需要移植的点之一**。
    sql = (
        f"INSERT INTO {table} (project_ref, metric, uid, value, updated_at) "
        f"VALUES (%s, %s, %s, %s, %s) "
        f"ON CONFLICT (project_ref, metric, uid) "
        f"DO UPDATE SET value = {table}.value + EXCLUDED.value, "
        f"updated_at = EXCLUDED.updated_at"
    )
    now = timezone.now()

    for batch_key in batches:
        rows = rows_by_batch.get(batch_key) or []
        if not rows:
            report.skipped.append(f"{batch_key}（空）")
            continue

        # ★★ 幂等闸门：这批已经被应用过 ⇒ 只清 key，**不重复累加**
        if HeatFlush.objects.filter(flush_key=batch_key).exists():
            report.skipped.append(f"{batch_key}（已应用过，跳过）")
            continue

        total = sum(v for _, v in rows)
        with transaction.atomic():
            # ★ 「写计数」与「记批次」在同一个事务 ⇒ 要么都成，要么都不成
            HeatFlush.objects.create(
                flush_key=batch_key,
                project_ref=project_ref,
                metric=metric,
                rows=len(rows),
                total=total,
            )
            with connection.cursor() as cur:
                cur.executemany(
                    sql, [(project_ref, metric, uid, val, now) for uid, val in rows]
                )

        report.batches += 1
        report.rows += len(rows)
        report.total += total

    return report


def flush_project(project_ref: str, metric: str, *, dry_run: bool = False) -> FlushReport:
    """合并一个项目的一个指标。★ 用 Redis 锁保证**同一批次只被一个进程处理**。"""
    cfg = config()
    client = cache.get_client()
    main_key = cache.hot_key(project_ref, metric)
    lock_key = f"astrolabe:hot:lock:{metric}:{project_ref}"

    # ★ 锁：多个 worker / cron 撞在一起时，只有一个动手
    if not client.set(lock_key, uuid.uuid4().hex, nx=True, ex=int(cfg["lock_ttl"])):
        log.info("热度合并已被其他进程持锁，跳过：%s / %s", project_ref, metric)
        return FlushReport(skipped=[f"{project_ref}/{metric}（锁被占用）"])

    try:
        batches = _collect_batches(client, main_key)
        if not batches:
            return FlushReport()

        # 读出各批次内容（★ 先读进内存，再决定怎么处理）
        rows_by_batch: dict[str, list[tuple[str, int]]] = {}
        for key in batches:
            got = client.zrange(key, 0, -1, withscores=True)
            rows_by_batch[key] = [
                (m.decode("utf-8", "replace") if isinstance(m, bytes) else m, int(s))
                for m, s in got
            ]

        if dry_run:
            rep = FlushReport(
                projects=1,
                batches=len(batches),
                rows=sum(len(v) for v in rows_by_batch.values()),
                total=sum(v for rows in rows_by_batch.values() for _, v in rows),
                dry_run=True,
            )
            log.info("[dry-run] 热度合并预览：%s", rep)
            return rep

        report = _apply(project_ref, metric, batches, rows_by_batch)

        # ★ 数据库落定之后才删临时 key（⚠ 顺序反了就会丢数据）
        for key in batches:
            client.delete(key)

        return report
    finally:
        client.delete(lock_key)


def flush_all(
    projects: list[str] | None = None,
    metrics: list[str] | None = None,
    *,
    dry_run: bool = False,
) -> FlushReport:
    """合并若干项目 / 指标。

    ⚠ **Redis 不可用时不抛异常** —— 返回空报告并记日志。
      理由：这是**维护作业**，Redis 恢复后增量还都在，**没有数据损失**，
      ❌ 没必要把一个周期性任务变成告警源。
    """
    total = FlushReport(dry_run=dry_run)
    try:
        client = cache.get_client()
        targets = (
            [(p, m) for p in projects for m in (metrics or config()["metrics"])]
            if projects
            else discover(client, metrics)
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("热度合并跳过（Redis 不可用）：%s", exc)
        return total

    for project_ref, metric in targets:
        try:
            total.merge(flush_project(project_ref, metric, dry_run=dry_run))
        except Exception as exc:  # noqa: BLE001
            # ⚠ 一个项目失败不该拖垮其余项目
            log.exception("热度合并失败：%s / %s", project_ref, metric)
            total.skipped.append(f"{project_ref}/{metric}（{exc}）")

    return total


# ---------------------------------------------------------------------------
# ③ 读路径：★ 热力图的权威数据源
# ---------------------------------------------------------------------------

def pending(project_ref: str, metric: str = cache.HOT_VISIT) -> dict[str, int]:
    """★ **尚未合并**的增量（还在 Redis 里）。用于展示 / 对账。"""
    return {uid: int(v) for uid, v in cache.top(project_ref, metric=metric, limit=100000)}


def top_nodes(
    project_ref: str,
    metric: str = cache.HOT_VISIT,
    limit: int = 20,
) -> list[tuple[str, int, int]]:
    """★ **热度读路径**：数据库权威累计值 + Redis 未合并增量。

    Returns:
        `[(uid, db_value, pending_delta), ...]`，按 `db + pending` 倒序。

    ⚠ 为什么要两边都取：合并是**周期性**的，用户刚点的那几次还没入库。
      只读 DB 会「慢半拍」——用户点了半天热度不涨，体验很怪。
    """
    fetch = max(limit * 2, limit)

    db_rows = dict(
        NodeHeat.objects.filter(project_ref=project_ref, metric=metric)
        .order_by("-value")
        .values_list("uid", "value")[:fetch]
    )
    pend = {uid: int(v) for uid, v in cache.top(project_ref, metric=metric, limit=fetch)}

    merged = [
        (uid, int(db_rows.get(uid, 0)), int(pend.get(uid, 0)))
        for uid in set(db_rows) | set(pend)
    ]
    merged.sort(key=lambda t: (t[1] + t[2], t[0]), reverse=True)
    return merged[:limit]
