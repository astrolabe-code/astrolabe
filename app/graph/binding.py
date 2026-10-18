"""Astrolabe · 图：**项目 ↔ 基图的绑定**（★ `B179` · 2026-10-13）

★★★ 所有者原话（逐字）：

> 「**用户拉一个图就解析一次，太浪费算力，应该是，拉去之前，看看现有的图数据里
> 有没有同样的，有同样的，就直接返回，不拉取，不解析，还快。**」

★ 本模块就是那句里的两个动作：

| 动作 | 函数 |
|---|---|
| ★★ 「**看看现有的图数据里有没有同样的**」 | `find()` / `get_or_create()` |
| ★★ 「**（有同样的，就）直接返回**」 | `bind()` —— ★ 把项目绑上去，★ **不投作业** ✅ |

---

# ⚠★★ 2026-10-14（`B179` 第二步）：**这一节整个作废** ⚠
#
# ★★ 原文写的是"为什么绑定关系单独一张表"：
#   「依赖方向是 graph → core —— ★ 在 core.Project 上挂 graph 外键会绕成圈」
#
# ★★ 而那个理由**站不住**（★ 实测）：
#   · ★ 架构文档 `ARCHITECTURE.md` A3 管的是【**层**】（Web / 作业 / 计算 / 共享内核）
#     ★★ 而 `core` 与 `graph` **同属共享内核** ✅
#   · ★★ 而 `core/models.py` 与 `core/publish.py` **早就在 `from graph import binding`** ⚠
#   · ★ 外键用**字符串引用** `"graph.BaseGraph"` ⇒ ★ 连 import 都不需要 ✅
#
# ⇒ ★★ 所以绑定**并入了 `core_project.base_graph`**（★ 一个项目只绑一份基图 ⇒ 一张外键就够）⚠
#   · ★ 少一张表、* 少一个可能产生**孤儿行**的地方 ✅
#   · ★★ `is_graph_built` 可以**直读外键**（★ 不再每个项目查一次）✅

# ★ 一个刻意的选择：绑定时**顺手做两件事**

| 做的事 | 为什么 |
|---|---|
| ★★ `Project.graph_built_at` | ★ 那表示「**这个项目已经有可显示的图了**」—— ★★ 复用时**立刻**就该为真 ⚠<br>（★ 否则页面上会一直转圈等一个**根本不会来**的作业）⚠ |
| ★ `GraphRevision.bump()` | ★ 缓存命名空间是**按项目**的 ⇒ ★★ 图"出现"了这个时刻必须换代际 ⚠ |
"""

from __future__ import annotations

import redis
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from graph import revision
from graph.models import BaseGraph

# ===========================================================================
# ★★★ `B181`：**基图位置的 Redis 映射**（★ 所有者 2026-10-13 裁定）
# ===========================================================================
#
# ★★ 所有者原话（逐字）：
#
# > 「**还有要用 redis 缓存最常用的哪些地址对应的图数据的位置，
# > 以后直接取，不要频繁搜索数据库比较。**」
#
# ★★ 而**取出之后必须校验**（★ 所有者第 4 点，逐字）：
#
# > 「**最后，拿出数据比较地址也是为这个设计的，过期就消掉原有错误数据映射，
# > 用新的数据映射替代**」
#
# ⇒ ★★ 所以本模块的查询顺序是（★ 见 `find()`）：
#
# ```
# ① 算身份证号（★ 由规范化地址算 —— ★★ 不查库）
# ② 试 Redis 映射 ⇒ 直接拿到基图位置
# ③ ★★ 拿到后【必须比地址】
#       · 对得上 ⇒ ✅ 返回
#       · 对不上 ⇒ ★★ 消掉这条错误映射，★ 继续往下
# ④ 回落数据库（★ 按 graph_key 唯一索引）
# ⑤ 数据库命中了 ⇒ 顺手把映射补回 Redis
# ```

#: ★ 映射的键前缀（★ 与 `jobs/queue.py` 的 `astrolabe:jobs` 同一风格）
CACHE_PREFIX = "astrolabe:basegraph"

#: ★ 映射存活时间（秒）—— ★ 7 天
#   ⚠ 有 TTL **不等于**靠它保正确：★ 真正的保障是第 ③ 步「比地址」⚠
#   ★ 它只是兜底 —— ★ 万一第 ③ 步漏了，★ 映射最多错 7 天 ✅
CACHE_TTL = 7 * 24 * 3600


class BindingImmutable(Exception):
    """★★★ **项目已绑定基图，不可更换**（`B227` · 2026-10-18）⚠

    ★★★ 所有者原话（逐字）：

    > 「**项目不允许换绑，建项目时绑定什么版本，以后永远是。**」

    ```
    ★★ `project.base_graph` 一旦有值 ⇒* **只能还是那一份**
      · · ★ 同值重复绑定 ⇒ 幂等放行（* 作业重跑 / 并发重入）✅
      · · ★★ 想换版本 ⇒* **建新项目** ⚠
    ```
    """


def _redis() -> "redis.Redis":
    """★ Redis 客户端（★ 与 `jobs/queue.py` 同一口径）。

    ⚠★★ **缓存故障绝不能让业务失败** —— ★ 所有调用点都包 try ⚠
      ★ 缓存是**加速**，❌ **不是依赖**：★ Redis 挂了照样能查库 ✅
      （★ 否则一个缓存的故障会变成整个网站不能建项目 —— ★ 那是因小失大）⚠
    """
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _cache_key(graph_key: str) -> str:
    return f"{CACHE_PREFIX}:{graph_key}"


def _cache_get(graph_key: str) -> int | None:
    """★ 从映射里取基图主键（★ 没有 / 故障 ⇒ `None`）。"""
    if not graph_key:
        return None
    try:
        raw = _redis().get(_cache_key(graph_key))
    except Exception:  # noqa: BLE001 —— ★ 缓存故障不影响业务（见 `_redis` 文档）
        return None
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        # ⚠ 映射里存了看不懂的东西 ⇒ ★ 当它不存在（★ 下一步会查库并覆盖它）✅
        return None


def _cache_put(graph_key: str, pk: int) -> None:
    """★ 写入 / 刷新映射（★ `setex` = 带 TTL 的 set）。"""
    if not graph_key:
        return
    try:
        _redis().setex(_cache_key(graph_key), CACHE_TTL, str(pk))
    except Exception:  # noqa: BLE001
        pass


def _cache_drop(graph_key: str) -> None:
    """★★ **消掉一条映射**（★ 所有者第 4 点：「过期就消掉原有错误数据映射」）。"""
    if not graph_key:
        return
    try:
        _redis().delete(_cache_key(graph_key))
    except Exception:  # noqa: BLE001
        pass


def find(provider: str, repo_full_name: str, sha: str) -> BaseGraph | None:
    """★★ **按【请求地址】找现成的基图** —— ★ 这就是"有没有同样的"那句。

    ## ★★ `B181` 之后这里变了（★ 所有者定的查询顺序）

    | 步骤 | 做什么 | 为什么 |
    |---|---|---|
    | ① | ★ 算**身份证号**（★ 规范化地址 ⇒ SHA-256 前 32 位）| ★★ **不查库**就知道"该是哪一份" ✅ |
    | ② | ★ 试 **Redis 映射** ⇒ 直接拿到位置 | ★★ 所有者：「不要频繁搜索数据库比较」⚠ |
    | ③ | ★★ **比地址** | ★★ 所有者：「拿出数据比较地址也是为这个设计的」⚠ |
    | ④ | ★ 回落**数据库**（★ `graph_key` 唯一索引）| ★ 映射没命中时的正路 ✅ |
    | ⑤ | ★ 命中了 ⇒ **补回映射** | ★ 下次就快了 ✅ |

    ⚠★★ 第 ③ 步为什么**不能省**：
      ★★ 映射可能**过期 / 过期前就被改写**（★ 基图删了又建、★ 或者缓存被清过）⚠
      ⇒ ★★ 不校验就会把一个**错的基图**当成对的返回 ⚠
        ★★ 而那是**静默的错**（★ 用户看到的是另一份代码的图，却没有任何提示）⚠
      ⇒ ★ 所有者为此专门定了：「**过期就消掉原有错误数据映射，用新的数据映射替代**」✅

    ## ⚠★★ 2026-10-14（`B184`）：**不再有 `legacy://` 兜底** ⚠

    ★★ 以前 `canonical_url()` 返回空串时，★ 这里会拼一个 `legacy://{prov}/{full}/{commit}` ⚠
      ★ 而现在 `canonical_url()` 对非法身份**直接抛 `ValueError`** ⚠
      ★★ 于是「存得进、查不到」那种静默不一致**从根上消失** ✅
    """
    canonical = BaseGraph.canonical_url(provider, repo_full_name, sha)
    key = BaseGraph.key_of(canonical)

    # ---- ②③ Redis 快路 + ★ 取出后校验地址 ----
    pk = _cache_get(key)
    if pk is not None:
        bg = (
            BaseGraph.objects.filter(pk=pk)
            .only("id", "provider", "repo_full_name", "sha", "request_url",
                  "graph_key", "built_at")
            .first()
        )
        if bg is not None and bg.canonical == canonical:
            return bg                                    # ✅ 对得上
        # ★★ 对不上 ⇒ 消掉这条错误映射（★ 所有者第 4 点），★ 然后照常查库
        _cache_drop(key)

    # ---- ④ 回落数据库（★ graph_key 上有唯一索引）----
    bg = BaseGraph.objects.filter(graph_key=key).first()
    if bg is not None:
        _cache_put(key, bg.pk)                           # ⑤ 补回映射
    return bg


def is_ready(bg: BaseGraph | None) -> bool:
    """★★ 这份基图**真的建好了**吗（★ 只有建好的才能"直接返回"）⚠

    ## ★★★ 判据：`built_at` 有值 **且真的有节点**

    ```
    ★★ 所有者裁定（2026-10-17）：「**节点为零，还要什么基图，空的还能叫基图吗？
      解析出节点为零的，不能做基图。**」
    ⇒ ★★ 基图 ⇔ 至少一个节点 ——* 0 节点的行**根本不该存在**：
      · · ★ 正常解析出 0 节点 ⇒* `write_graph` 抛 `EmptyGraph`、* 作业失败、
        * 基图行删除（* 见 `graph/writer.py` / `jobs/tasks.py`）✅
      · · ★★ 而这里仍做一次防御：* 万一有人直接动库留下空行，
        * **不复用**（* 不绑空图）* ✅
    ```
    """
    if bg is None or bg.built_at is None:
        return False
    from graph.models import Node

    # ★★ `B220`：* 节点跨版本共用 ⇒* 按 `versions` 数组判「这个版本有没有节点」⚠
    return Node.objects.filter(versions__contains=[bg.pk]).exists()


def get_or_create(
    provider: str,
    repo_full_name: str,
    sha: str,
    *,
    ref: str = "",
    default_branch: str = "",
) -> tuple[BaseGraph, bool]:
    """★★ **取或建**那一条基图记录（★ 只是记录 —— ★ 图数据由作业写 ⚠）。

    ⚠★ 为什么要"先建记录、后写图"：★ 因为**解析作业**要用它当落点 ⚠
      ★★ 而"建好了没有"由 `built_at` 说了算（★ 不是"有没有这一行"）✅

    ## ⚠★ `B181`：身份判据换成「身份证号」

    ★★ 以前按 `(provider, repo_full_name, sha)` 三个字段各自相等 ——
      ★★ 而那只在**大小写完全一致**时才对得上 ⚠
      （★ 实测：`chk/repo` / `Chk/Repo` / `chk/Repo` 会造出 **3 份**基图）⚠
    ⇒ ★★ 现在按 `graph_key`（★ 由**规范化地址**算出）—— ★ 大小写 / 末尾斜杠
      都被抹平了 ⇒ ★ 同一个仓库**只会有一份** ✅
    """
    prov = (provider or "").strip().lower()
    full = (repo_full_name or "").strip().strip("/").lower()   # ★★ `B181`：转小写！
    commit = (sha or "").strip().lower()                       # ★★ hex 一律小写
    # ⚠★★ 2026-10-14（`B184`）：**没有 `legacy://` 兜底了** ⚠
    #   ★★ 非法身份（★ 没有可锚定的 sha）会在这里**直接抛 `ValueError`** ⚠
    #     ⇒ ★ 「存得进、查不到」那种静默不一致**从根上消失** ✅
    canonical = BaseGraph.canonical_url(prov, full, commit)
    key = BaseGraph.key_of(canonical)

    # ★★ `B181`：身份判据是**身份证号**（★ 不再是三个字段各自相等）——
    #   ★★ 大小写 / 末尾斜杠都在算地址时抹平了 ⇒ ★ 同一个仓库只会有一份 ✅
    bg, created = BaseGraph.objects.get_or_create(
        graph_key=key,
        defaults={
            "provider": prov,
            "repo_full_name": full,
            "sha": commit,
            # ★★ 所有者要求「**记录**请求地址」⇒ ★ 存下来 ✅
            "request_url": canonical,
            "ref": (ref or "")[:128],
            "default_branch": (default_branch or "")[:128],
        },
    )

    _cache_put(key, bg.pk)          # ★ 建好就写映射（★ 下次直接拿）
    return bg, created


def of(project_ref: str) -> BaseGraph | None:
    """★ 这个项目绑的是哪份基图（★ 没绑 ⇒ `None`）。

    ⚠★★ 2026-10-14（`B179` 第二步）：**绑定已并入 `core_project.base_graph`** ⚠

    ★★ 原先这里查独立的 `ProjectBaseGraph` 表 —— ★ 而那一张**已删** ⚠
      · ★ 一个项目只绑一份基图 ⇒ ★ 一张外键就够了 ⚠
      · ★★ 而"依赖会成圈"那个旧理由**站不住**（★ 实测 `core` 早已 import `graph`）⚠

    ★ 口径：★ `select_related` 一次 join 取回基图 ✅
    """
    from core.models import Project

    project = (
        Project.objects.select_related("base_graph")
        .filter(project_ref=project_ref)
        .first()
    )
    return project.base_graph if project is not None else None


def bind(
    project_ref: str, base_graph: BaseGraph, *, requested_ref: str = ""
) -> None:
    """★★ **把这个项目绑到那份基图上**（★ 并顺手把"已经有图"这件事设为真）⚠

    ★★ 关键：★ 如果这份基图**已经建好了** ⇒ ★ 绑定之后**不需要再投任何作业** ✅
      ★ 这正是「**不拉取、不解析，还快**」的落点 ⚠

    ⚠ 幂等：★ 同一个项目重复绑定**只是把关系指向最新的那份**（★ 不会报错）——
      ★ 因为"换一个分支再拉"就是**又绑一次**（★ 那时会指向另一份基图）✅
    """
    from core.models import Project

    with transaction.atomic():
        # ⚠★★ 2026-10-14（`B179` 第二步）：**直写项目外键** —— ★ 不再建绑定行 ⚠
        #   ★★ `update_or_create` 换成一个 `update`：* 项目**必然已存在**（* 绑定发生在建项目之后）⚠
        #   · ★ `requested_ref`（* 用户当时指定的分支）* **不再存** ——
        #     ★ 基图的 `ref` / `default_branch` 已经是权威（* `B197`：* 一个概念一处）⚠
        # ★★★ `B227`：**绑定不可更换**（* 锁住项目行，* 防并发换绑）⚠
        project = (
            Project.objects.select_for_update()
            .filter(project_ref=project_ref)
            .only("pk", "base_graph_id")
            .first()
        )
        if project is None:
            raise ValueError(
                f"绑定失败：项目不存在（project_ref={project_ref!r}）—— "
                "绑定只能发生在项目建好之后"
            )
        if project.base_graph_id is not None and project.base_graph_id != base_graph.pk:
            raise BindingImmutable(
                f"项目已绑定另一个版本（base_graph={project.base_graph_id}），不可更换 —— "
                "要看别的版本，请新建一个项目"
            )
        if project.base_graph_id is None:
            Project.objects.filter(pk=project.pk).update(base_graph=base_graph)

        # ⚠★★ 2026-10-13：**必须重新读一次 `built_at`**（★ 别信传进来那个对象的属性）⚠
        #
        # ★★ 为什么：`writer.write_graph()` 是**另取一个实例**去更新它的 ⚠
        #   ```
        #   bg = BaseGraph.objects.select_for_update().filter(pk=base_graph.pk).first()  ← ★ 新实例
        #   bg.built_at = timezone.now()   ← ★ 更新的是【它】
        #   bg.save(...)
        #   ```
        #   ⇒ ★★ 调用方手上那个 `base_graph` 的 `built_at` **还是旧的 `None`** ⚠
        #
        # ★★★ 后果是**静默的**（★ 最难查的一类）：
        #   ★ 图**明明建好了**（★ 节点 / 边都在库里），
        #   ★★ 而 `is_ready()` 判成 False ⇒ **不肯置 `graph_built_at`** ⚠
        #   ⇒ ★ 项目页显示「**未解析**」⇒ ★ 用户以为没跑成功 ⚠
        #
        # ★ 实测证据：`records` 那个项目 **90 节点 / 226 边**，
        #   ★★ 而 `is_graph_built = False` ⚠
        #
        # ⇒ ★★ 所以在**这里**重读 —— ★ 这样无论谁调用 `bind()` 都不会再踩 ✅
        base_graph.refresh_from_db(fields=["built_at", "node_count", "edge_count"])

        # ★★★ 2026-10-17（所有者裁定）：**0 节点的基图【不许绑到项目】** ⚠
        #   · ★ 原话：「**项目不允许绑定基图为零的，从源头上杜绝，不要事后再删除，
        #     这样牵扯范围太广。**」
        #   · ★★ 绑定是项目拿到图的**唯一入口** ⇒ 在这里挡，* 波及面最小 ✅
        #   · ★ 判据 = `is_ready()`（* `built_at` 有值 ∧ 真有节点）——
        #     * 放在 `refresh_from_db` **之后**：* 刚写完图的 `built_at` 才是新的 ⚠
        if not is_ready(base_graph):
            from graph.writer import EmptyGraph

            raise EmptyGraph(
                f"拒绝绑定：基图 #{base_graph.pk} 没有任何节点 —— "
                "空的不能当基图用（请重新拉取解析）"
            )

        # ★★ 「这个项目已经有图了」—— ★ 复用时**立刻**为真（❌ 不靠一个不会来的作业）⚠
        #
        # ⚠★★ 2026-10-14（`B197`）：**这里不再写任何东西** ⚠
        #
        # ★★ 原先这里要置 `Project.graph_built_at` —— ★ 而那一列**已删** ⚠
        #   · ★ 它与 `BaseGraph.built_at` 是**同一条事实的两份** ⇒ ★ 迟早不一致 ⚠
        #   · ★★ 而 `is_graph_built` 现在**直接读基图**（★ 见 `core/models.py` 的属性）✅
        #   ⇒ ★★ 于是本项目**从"写两处、担保一致"变成"只写一处"** ✅
        #
        # ★★ 上面那次 `refresh_from_db()` **仍然必须留** ⚠
        #   （★ 它保证 `is_ready()` 读到的是**刚写进去的** `built_at`，
        #     ★★ 而不是调用方手上那个过期的 `None` —— ★ 那个坑实测踩过）⚠
        #
        # ⚠★ 而"置 `graph_built_at`"那一段**已整段删除** ⚠
        #   · ★ 那一列已删（`B197`：它与 `BaseGraph.built_at` 是同一条事实的两份）⚠
        #   · ★★ 现在 `is_graph_built` **直读外键 + 基图的 `built_at`** ⇒ ★ 无需落库 ✅
        #   · ⇒ ★★ 于是本项目从"写两处、担保一致"变成"**只写一处**" ✅

        # ★ 图"出现"了 ⇒ 这个项目的邻域缓存换代际（★ 见模块文档）
        revision.bump(project_ref)

        return None
