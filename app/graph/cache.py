"""Astrolabe · 邻域缓存 + 节点访问热度（Redis）

★ 依据 `GRAPH-STORAGE.md` G5：**图不可变 + 维护者修补**（`B103`）⇒
  邻域查询结果**可以缓存很久**，而且 **key 必须带图版本号**。

★★ 三件事，一件都不能少：

| # | 事 | 为什么 |
|---|---|---|
| **1** | **缓存带 `rev`** | ⚠ 图**不是永远不变** —— 维护者会手工修补（G1）⇒ 靠 `graph/revision.py` 换命名空间失效 |
| **2** | ★ **热度按 `uid` 记**（❌ 不按 `vid`） | ⚠ `vid` **不保证跨次解析相同**（`B117` 发号）⇒ 按 vid 记，重新解析一次热度就全归零 |
| **3** | ★★ **尽力而为 + 熔断** | ⚠ Redis 慢/挂**绝不能拖住读路径** —— 否则"缓存"反而成了故障源 |

★ 分层（`ARCHITECTURE.md` A3）：
  本模块属于 **graph 层的读路径**（`graph` = 图模型与查询，① ② 共用）；
  ⚠ `graph/revision.py` **不 import Redis**（保持只依赖 ORM），本模块才用 Redis。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import zlib
from typing import Any, Iterable, Sequence

import redis
from django.conf import settings

from graph import revision
from graph.traversal import (
    DIRECTION_OUT,
    GraphEdge,
    GraphNode,
    GraphReader,
    SubGraph,
    resolve_limits,
    resolve_node,
)

log = logging.getLogger("astrolabe.graph.cache")

#: 缓存 key 前缀（★ 全部带这个前缀，方便管理和排查）
PREFIX = "astrolabe:neigh"

#: 序列化格式版本 —— ⚠ 改了结构就 +1，旧值会被当作**未命中**
_PAYLOAD_VERSION = 1

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "hot_enabled": True,
    # ⚠ TTL ≠ 失效手段。★ **真正的失效是 `rev + 1`**；
    #   TTL 只负责「把旧代际的 key 清理掉，别无限占内存」。
    "ttl": 30 * 86400,
    # ★ 超过这个大小就不缓存 —— 常被查的是「**难懂的那几个函数**」（结果很小），
    #   大结果属于长尾，缓存它只会挤占内存而命中率极低。
    "max_bytes": 256 * 1024,
    # ★★ 「不卡死系统」：Redis 慢/挂时，**读路径必须在毫秒级失败**，而不是挂着
    "socket_timeout": 1.0,
    "socket_connect_timeout": 0.5,
    # ★ 熔断：连续失败 N 次后，冷却 M 秒内**直接跳过 Redis**（连尝试都不做）
    "breaker_threshold": 3,
    "breaker_cooldown": 10.0,
}


def config() -> dict[str, Any]:
    """合并配置：★ 内置默认 → `settings.ASTROLABE_NEIGHBORHOOD_CACHE`。"""
    cfg = dict(_DEFAULT_CONFIG)
    cfg.update(getattr(settings, "ASTROLABE_NEIGHBORHOOD_CACHE", None) or {})
    return cfg


def cache_enabled() -> bool:
    return bool(config()["enabled"])


# ---------------------------------------------------------------------------
# Redis 客户端（★ 单例 + 短超时 + 熔断）
# ---------------------------------------------------------------------------

_client: redis.Redis | None = None
_client_lock = threading.Lock()


def get_client() -> redis.Redis:
    """★ 单例客户端。

    ⚠ 为什么不用 `redis.Redis.from_url(...)` **每次新建**：
      那会每次新建连接池 ⇒ 读路径上每请求都建连接。
      但 ⚠ **必须配 `socket_timeout`** —— 单例的长连接一旦对端卡住，
      不设超时就会**永久挂住**（这正是"缓存把系统拖死"的典型成因）。
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                cfg = config()
                _client = redis.Redis.from_url(
                    settings.REDIS_URL,
                    # ⚠ 存的是压缩后的二进制 ⇒ 不自动解码
                    decode_responses=False,
                    socket_timeout=cfg["socket_timeout"],
                    socket_connect_timeout=cfg["socket_connect_timeout"],
                    health_check_interval=30,
                )
    return _client


class _Breaker:
    """★ 极简熔断器 —— Redis 连续失败后**短期直接放弃**。

    ⚠ 没有它，Redis 挂掉时**每个请求**都要等 `socket_connect_timeout` 才失败
      ⇒ 读路径整体被拖慢。有了它，失败几次之后就是 **零成本跳过**。
    """

    def __init__(self) -> None:
        self._fails = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return time.monotonic() >= self._open_until

    def ok(self) -> None:
        with self._lock:
            self._fails = 0
            self._open_until = 0.0

    def fail(self) -> None:
        cfg = config()
        with self._lock:
            self._fails += 1
            if self._fails >= int(cfg["breaker_threshold"]):
                self._open_until = time.monotonic() + float(cfg["breaker_cooldown"])
                self._fails = 0


_breaker = _Breaker()


def _guard(fn, default=None):
    """★ 尽力而为地执行一次 Redis 操作 —— ⚠ **绝不向上抛异常**。

    ★ 读路径的原则：**缓存是"快一点"，不是"必须有"**。
      Redis 出任何问题 ⇒ 降级为"没有缓存"，❌ 不让用户看到错误。
    """
    if not _breaker.allow():
        return default
    try:
        result = fn()
        _breaker.ok()
        return result
    except Exception as exc:  # noqa: BLE001 —— ★ 故意的：任何 Redis 异常都不该冒泡
        _breaker.fail()
        log.warning("Redis 操作失败，已降级（%s）：%s", type(exc).__name__, exc)
        return default


# ---------------------------------------------------------------------------
# 序列化（★ 紧凑 + 压缩）
# ---------------------------------------------------------------------------

def _encode(sg: SubGraph) -> bytes:
    """★ 用「数组」而不是「字典列表」—— 同样的数据小 40% 以上（字段名不重复存）。

    ⚠ `ensure_ascii=False`：代码路径里有中文注释/标识符时能省一大截。
    """
    payload = [
        _PAYLOAD_VERSION,
        sg.root,
        1 if sg.truncated else 0,
        sg.truncated_reason,
        sg.stats,
        [
            [n.vid, n.uid, n.kind, n.name, n.file_path, n.line, n.line_end, n.lang, n.depth]
            for n in sg.nodes
        ],
        [[e.src, e.dst, e.type, e.line] for e in sg.edges],
    ]
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return zlib.compress(raw, 1)  # ★ level=1：只求快，不求最小


def _decode(project_ref: str, raw: bytes) -> SubGraph | None:
    """⚠ 任何解不开的情况 ⇒ 返回 `None`（当作**未命中**），❌ **绝不猜**。"""
    try:
        data = json.loads(zlib.decompress(raw).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, list) or not data or data[0] != _PAYLOAD_VERSION:
        return None  # ★ 格式版本不符 —— 旧值直接作废

    _, root, truncated, reason, stats, nodes, edges = data
    return SubGraph(
        project_ref=project_ref,
        root=root,
        nodes=[
            GraphNode(
                vid=n[0], uid=n[1], kind=n[2], name=n[3], file_path=n[4],
                line=n[5], line_end=n[6], lang=n[7], depth=n[8],
            )
            for n in nodes
        ],
        edges=[GraphEdge(src=e[0], dst=e[1], type=e[2], line=e[3]) for e in edges],
        truncated=bool(truncated),
        truncated_reason=reason,
        # ⚠ `elapsed_ms` 是上一次【真算】的耗时 —— 缓存命中的耗时由调用方覆盖
        stats=dict(stats or {}),
    )


# ---------------------------------------------------------------------------
# ★ 缓存 key：**版本号写进 key**，靠换命名空间来失效（G5）
# ---------------------------------------------------------------------------

def neighborhood_key(
    project_ref: str,
    rev: int,
    vid: int,
    depth: int,
    direction: str,
    edge_types: Sequence[str] | None = None,
) -> str:
    """拼缓存 key（★ 图语义参数 → 稳定字符串，⚠ 不含任何 SQL / 表名）。"""
    if edge_types:
        etag = "h" + str(abs(hash(tuple(sorted(edge_types)))) % 10**8)
    else:
        etag = "all"
    return f"{PREFIX}:{project_ref}:r{rev}:{vid}:d{depth}:{direction}:{etag}"


def load(key: str, project_ref: str) -> tuple[SubGraph | None, int]:
    """读缓存。Returns: `(SubGraph | None, Redis 往返耗时 ms)`"""
    t0 = time.monotonic()
    raw = _guard(lambda: get_client().get(key))
    ms = int((time.monotonic() - t0) * 1000)
    if not raw:
        return None, ms
    return _decode(project_ref, raw), ms


def store(key: str, sg: SubGraph) -> bool:
    """写缓存。★ 超过 `max_bytes` ⇒ **不缓存**并返回 `False`（长尾结果不值得占内存）。"""
    cfg = config()
    try:
        raw = _encode(sg)
    except Exception as exc:  # noqa: BLE001
        log.warning("缓存序列化失败，跳过：%s", exc)
        return False

    if len(raw) > int(cfg["max_bytes"]):
        log.debug("结果过大（%d B > %d B），不缓存：%s", len(raw), cfg["max_bytes"], key)
        return False

    return bool(_guard(lambda: get_client().set(key, raw, ex=int(cfg["ttl"]))))


# ---------------------------------------------------------------------------
# ★★ 节点访问热度（热力图的数据源）
# ---------------------------------------------------------------------------

#: 指标名 —— ★ 先留好通道，将来 UGC（解释数 / 评论数）直接加一条即可
HOT_VISIT = "visit"        # ✅ 已实现：被查看次数（邻域查询的**起点**）
HOT_NOTES = "notes"        # ⚠ 将来：被写了多少条解释（来自 UGC）
HOT_COMMENTS = "comments"  # ⚠ 将来：被评论了多少条


def hot_key(project_ref: str, metric: str) -> str:
    return f"astrolabe:hot:{metric}:{project_ref}"


def record(project_ref: str, uid: str, metric: str = HOT_VISIT, amount: int = 1) -> None:
    """记一次访问（★ **按 `uid`，不按 `vid`**）。

    ⚠ **为什么必须按 `uid`**：`vid` 是**服务器发号**（`B117`），
      ⚠ **不保证跨次解析相同** ⇒ 若按 vid 记，**重新解析一次热度就全归零**。
      `uid` 由「路径 + 名字」派生 ⇒ ★ **跨解析稳定**，热度才攒得住。

    ⚠ 代价（诚实记录）：`uid` **允许重复**（`B117`）⇒ 同名节点会**合并计数**。
      对「热度」这个用途来说这可以接受（甚至更合理：**同一个名字的函数就是同一个关注点**）。

    ★ 用 `ZINCRBY`：一次 O(log N) 的原子自增，**每请求开销可忽略**。
    """
    if not config()["hot_enabled"] or not uid:
        return
    _guard(lambda: get_client().zincrby(hot_key(project_ref, metric), amount, uid))


def top(project_ref: str, metric: str = HOT_VISIT, limit: int = 20) -> list[tuple[str, float]]:
    """取热度 TOP N —— ★ **这就是热力图的数据源**。Returns: `[(uid, 次数), ...]`"""
    rows = _guard(
        lambda: get_client().zrevrange(hot_key(project_ref, metric), 0, max(limit, 1) - 1, withscores=True)
    )
    if not rows:
        return []
    return [(m.decode("utf-8", "replace") if isinstance(m, bytes) else m, float(s)) for m, s in rows]


def score(project_ref: str, uid: str, metric: str = HOT_VISIT) -> float:
    val = _guard(lambda: get_client().zscore(hot_key(project_ref, metric), uid))
    return float(val or 0.0)


def hot_reset(project_ref: str, metrics: Iterable[str] | None = None) -> int:
    """清空热度统计（⚠ 危险操作，仅供调试 / 重建）。"""
    keys = [hot_key(project_ref, m) for m in (metrics or (HOT_VISIT, HOT_NOTES, HOT_COMMENTS))]
    return int(_guard(lambda: get_client().delete(*keys)) or 0)


# ---------------------------------------------------------------------------
# 维护工具（⚠ 只在人工排查 / 收尾时用，❌ 不在请求路径上）
# ---------------------------------------------------------------------------

def invalidate(project_ref: str, batch: int = 500) -> int:
    """⚠ **强制清掉某项目的全部邻域缓存** —— 用 `SCAN` 分批删。

    ★ 正常情况下**不需要它**：改图只要 `revision.bump()`，旧代际自然失效。
      它适用于「**rev 与缓存被怀疑不同步**」这类异常排查，或彻底回收内存。
    ⚠ 用 `SCAN` 而不是 `KEYS` —— `KEYS` 会**阻塞 Redis 主线程**。
    """
    pattern = f"{PREFIX}:{project_ref}:*"
    deleted = 0

    def _run() -> int:
        nonlocal deleted
        client = get_client()
        for key in client.scan_iter(match=pattern, count=batch):
            deleted += client.delete(key)
        return deleted

    return int(_guard(_run) or 0)


def key_count(project_ref: str) -> int:
    """数一下某项目缓存了多少个 key（供人工判断内存占用）。"""

    def _run() -> int:
        return sum(1 for _ in get_client().scan_iter(match=f"{PREFIX}:{project_ref}:*", count=500))

    return int(_guard(_run) or 0)


# ---------------------------------------------------------------------------
# ★ 缓存装饰器：给任意 `GraphReader` 套上一层缓存
# ---------------------------------------------------------------------------

class CachedGraphReader:
    """★ 把缓存**装饰**在任意 `GraphReader` 外面。

    ⚠ **为什么是装饰器，而不是写进 `PostgresAdjacencyReader`**：
      缓存是**读路径策略**，不是**存储实现**的特性。
      ★ 将来换成 Neo4j 读取器时，**这层缓存照样能套上去** —— 换图库不用重做缓存。
      ✅ 同时它**不改变 `G6` 接口**：调用方看到的仍然只是一个 `neighborhood(...)`。

    ★★ 两条正确性纪律：

    | # | 纪律 | 原因 |
    |---|---|---|
    | **1** | **`limits` 非空 ⇒ 绕过缓存** | ⚠ 自定义预算会得到**不同结果**，混进同一条缓存会串味 |
    | **2** | **key 里必须用"生效后"的 `depth`** | ⚠ `depth=None` 与 `depth=1` 结果相同但请求不同 ⇒ 不归一化就会重复缓存 |
    """

    def __init__(self, inner: GraphReader) -> None:
        self._inner = inner

    #: 便于排查：看看被装饰的是谁
    @property
    def inner_name(self) -> str:
        return type(self._inner).__name__

    def neighborhood(
        self,
        project_ref: str,
        node: int | str,
        *,
        depth: int | None = None,
        direction: str = DIRECTION_OUT,
        edge_types: Sequence[str] | None = None,
        limits=None,
    ) -> SubGraph:
        cfg = config()

        # ★ 纪律 1：自定义预算 ⇒ 不缓存（结果不同）
        if limits or not cfg["enabled"]:
            return self._inner.neighborhood(
                project_ref, node, depth=depth, direction=direction,
                edge_types=edge_types, limits=limits,
            )

        # ★ 把 uid 先解析成 vid —— 否则「同一个节点的 uid 写法」和「vid 写法」
        #   会各自缓存一份（重复占内存，且两份额度不同步）
        vid, ambiguous = resolve_node(project_ref, node)
        if vid is None:
            return self._inner.neighborhood(
                project_ref, node, depth=depth, direction=direction,
                edge_types=edge_types, limits=None,
            )

        # ★ 纪律 2：用"生效后"的跳数做 key（与真实计算保持一致）
        eff_depth = max(0, min(int(cfg_depth_floor(depth)), int(resolve_limits()["max_depth"])))
        rev = revision.current(project_ref)
        key = neighborhood_key(project_ref, rev, vid, eff_depth, direction, edge_types)

        t0 = time.monotonic()
        cached, redis_ms = load(key, project_ref)
        if cached is not None:
            # ⚠ 覆盖为"这一次"的真实观感：命中耗时 + 命中标记
            cached.stats["cache"] = "hit"
            cached.stats["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
            cached.stats["redis_ms"] = redis_ms
            cached.stats["rev"] = rev
            if ambiguous:
                cached.stats["ambiguous_uid"] = True
            return cached

        sg = self._inner.neighborhood(
            project_ref, vid, depth=eff_depth, direction=direction,
            edge_types=edge_types, limits=None,
        )
        stored = store(key, sg)
        sg.stats["cache"] = "miss"
        sg.stats["cached"] = stored
        sg.stats["rev"] = rev
        sg.stats["key"] = key
        return sg


def cfg_depth_floor(depth: int | None) -> int:
    """`depth=None` ⇒ 取配置里的默认跳数（★ 保证 key 与真实计算一致）。"""
    if depth is None:
        return int(resolve_limits()["default_depth"])
    return int(depth)
