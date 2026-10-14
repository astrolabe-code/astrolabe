"""Astrolabe · ② 作业层：作业执行体

★ 分层纪律（`ARCHITECTURE.md` A3）：
    本模块**可以** import 共享内核 + 解析器；
    ❌ **不得被 ① Web 层 import** —— 跨层只通过【Job 表 + 队列】通信。

★ 职责：把「一个 Job 记录」变成「一次真实的工作」。
   ⚠ 状态机（queued → running → done/failed）由 worker 负责，本模块只管**干活**。
"""

from __future__ import annotations

import logging
import os

from codeparser.scanner import scan_and_parse
from graph.writer import GraphImmutable, write_graph
from jobs.models import Job

log = logging.getLogger("astrolabe.jobs")

#: 进度回写节流 —— ⚠ 大项目逐文件回写会把 DB 打爆，按「百分比变化」才写
_PROGRESS_STEP = 5


def _progress(job: Job, percent: int, stage: str) -> None:
    job.progress = max(0, min(100, percent))
    job.stage = stage[:64]
    job.save(update_fields=["progress", "stage"])


def run_parse_job(job: Job) -> None:
    """执行一个 `parse` 作业：扫描目录 → 解析 → 写图。

    ★ payload 约定（一期）：

    ```json
    { "path": "/绝对/路径/到/项目根目录" }
    ```

    ⚠ 一期用**本地目录**；将来换成 `{ "repo_url": ..., "commit": ... }`，
      由作业层负责从 GitHub / Gitee 拉取（`B109`：源码只能服务端获取）。

    ⚠ 失败时**直接抛异常** —— 由 worker 捕获并置 `failed`（不在这里吞掉）。
    """
    payload = job.payload or {}
    # ⚠★★ 2026-10-14（`B184`）：**`path` 字段已废弃** ⚠
    #   ★ 它曾是「staff 指一个容器里的目录」的调试口子 —— ★ 现已取消 ⚠
    #   ★★ 于是这里**恒为空**（★ `core/publish.py` 不再往 payload 里放它）⚠
    #   ⇒ ★ 下面的本地目录分支**已不可达**（★ 留待清理批一并拆除）⚠
    root = payload.get("path")
    project_ref = job.project_ref

    # ---------------------------------------------------------- ⓪-0 ★★★ 定版闸门
    #   ★★ **图一旦生成就【定版】—— 此后不可再解析**（`B103` / `B155`）。
    #
    #   > 用户原话：「代码解析完成之后**应该不允许重新解析**……**解释里的"几行到几行"
    #   > 就失效了**。你要解析另一个版本的，那就**重新建一个项目**。」
    #
    #   ★★★ 放在**最前面**（连拉取都不做）—— ⚠ 定版后重新拉一遍源码是**纯浪费**，
    #     而且还可能覆盖存储空间里那份"与图对应的"源码（★ 那会让两边**对不上**）。
    #
    #   ⚠ 这是**纵深防御的第一层**；★ 第二层在 `graph.write_graph()` 里
    #     （★ 它 `select_for_update` 锁住项目行 ⇒ **并发也拦得住**）。
    project = _project_for(payload, project_ref)
    if project is not None and project.is_graph_built:
        _finish(job, payload, outcome=OUTCOME_ALREADY_BUILT)
        return

    # ---------------------------------------------------------- ⓪-0.5 ★★★ 基图（`B179`）
    #   ★★ 解析产物写进【基图】，★ 而基图的身份是【仓库 + sha】⚠
    #   ★★★ 所有者原话：「**拉去之前，看看现有的图数据里有没有同样的，
    #     有同样的，就直接返回，不拉取，不解析，还快**」
    #   ⚠★ 失败会 **`raise`**（★ 与 `_fetch_source` 同一口径 —— ★ 见 `_base_graph_for`）⚠
    base_graph = _base_graph_for(job, payload, project)

    if base_graph.built_at is not None:
        # ★★★ **已经有现成的了** —— ★ 别的项目解析过**同一个 sha** ⚠
        #   ⇒ ★★ **不拉取、不解析**：★ 绑上就完事 ✅（★ 这就是那条省算力的收益）
        from graph import binding

        binding.bind(project_ref, base_graph, requested_ref=(payload.get("ref") or ""))
        _finish(
            job, payload, outcome=OUTCOME_ALREADY_BUILT,
            extra={"reused_base_graph": base_graph.sha[:12]},
        )
        log.info(
            "复用现成基图 project_ref=%s base=%s@%s（★ 不拉取不解析）",
            project_ref, base_graph.repo_full_name, base_graph.sha[:12],
        )
        return

    # ---------------------------------------------------------- ⓪ 源码从哪来
    if not root:
        # ★★ **从这里开始，源码由【作业层】自己拉**（`B153` / `core/fetch.py`）——
        #   ✅ 因为普通用户**不可能**给我们一个"容器里已放好的目录"。
        #   ⚠ 这也是"存储空间"真正被动起来的地方（`B152`）。
        root = _fetch_source(job, payload, project)
        if not root:
            return          # ★ 失败已经写进 payload / 日志（⚠ 见 `_fetch_source`）

    # ---------------------------------------------------------- ⓪-1 ★★ 钉住 ref
    #   ★★ **两条路都要钉**（★ 拉取的、和调试直接用本地目录的）——
    #   ⚠ 原先只在 `_fetch_source()` 里钉 ⇒ ★ 走 `path` 时 `resolved_ref` 会是空的，
    #     ★ 而"这张图是哪一版代码的"就没有答案了（`B155`）。
    #
    #   ⚠★★ `B179`（2026-10-13）：这里**改成钉 sha** ⚠ ——
    #     ★★ 所有者原话：「**基图的数据一定要锚定 github 上的版本，用 sha 之类的**」
    #     ★ 以前钉的是 `commit` 字面值，★ 而实测库里 258 个作业的 `commit` **全是空字符串** ⇒
    #       ★★ 那一字段等于没钉（★ 而"HEAD"更是**会跑的名字**，⚠ 不是锚）⚠
    #     ⇒ ★★ 现在钉 `_base_graph_for` 定下来的那个 sha ✅
    #       （★ 作者再怎么提交，★ 这个 sha 指向的代码**不会变** ⚠）
    #   ★ 用 `local` 标明"这是容器里的目录，不是从远端拉的"（⚠ 别假装是某个 commit）。
    if project is not None:
        pinned = (
            (payload.get("sha") or "").strip()
            or (payload.get("commit") or "").strip()
            or ("local" if payload.get("path") else "")
        )[:128]
        if pinned and (not project.resolved_ref or project.resolved_ref in ("HEAD", "local")):
            project.resolved_ref = pinned
            project.save(update_fields=["resolved_ref", "updated_at"])

    # ---------------------------------------------------------- ① ★★ 许可核验
    #   ★★ `U3.1` 第 ④ 步：**「通过后才允许解析」** —— 所以这一步在解析【之前】。
    #   ⚠ 许可核验由【作业】做（而不是同步流程），因为
    #     ★ 它需要源码，而源码只有作业层能拿到。
    _progress(job, 2, "核验许可证")
    # ★★ `B179`：许可结论**存在基图上** ⚠ —— ★ 它是"**源码版本的性质**"（★ 同一个 sha，
    #   ★ 复用它的人不必重新核验）✅ ★ 而且 `B176` ④ 的"GPL ⇒ 只出节点"也落在那里 ⚠
    outcome = _license_gate(job, project, root, base_graph=base_graph)
    if outcome != "pass":
        _finish(job, payload, outcome=outcome, extra={"license": outcome})
        # ★★★ `B176` ②：许可没过 ⇒ **不会解析** ⇒ ★ 源码**立刻删** ——
        #   ⚠★ 这里刚拉下来的源码已经**没有任何用途**，★ 而继续留着就是"持有他人代码"。
        #   ★（★ 待审核 `awaiting_review` 也一样：★ 放行时重投的作业会**自己重新拉**
        #      —— 见 `web/views/review.py`：「B153 之后不再要求 source_path」）
        _drop_source(project, payload, root)
        return

    # ---------------------------------------------------------- ② 扫描 + 解析
    _progress(job, 5, "扫描文件")
    last_percent = 2

    def _on_file(done: int, total: int, rel: str) -> None:
        nonlocal last_percent
        # 解析阶段占 5% → 80%
        percent = 5 + int(done / max(total, 1) * 75)
        if percent - last_percent >= _PROGRESS_STEP:
            last_percent = percent
            _progress(job, percent, f"解析 {rel}")

    result, scan = scan_and_parse(root, on_file=_on_file)

    log.info(
        "解析完成 root=%s 文件=%d/%d 节点=%d 边=%d 语言=%s",
        root, scan.files_parsed, scan.files_seen,
        len(result.nodes), len(result.edges), scan.by_lang,
    )

    if scan.files_parsed == 0:
        raise ValueError(
            f"没有解析到任何文件（扫描到 {scan.files_seen} 个候选，"
            f"跳过原因：{scan.skip_reasons}）"
        )

    # ---------------------------------------------------------- ② 写图
    #   ★★★ 默认 `replace=False` ⇒ **图已存在就拒绝**（`B103` / `B155`）——
    #     ★ 见 `write_graph()` 的文档（那是**纵深防御的第二层**）。
    _progress(job, 82, f"写入图（{len(result.nodes)} 节点）")
    try:
        # ★★★ `B179`：写进【基图】（★ 不再挂项目）——
        #   ★★ 同一个 sha 的项目**共用这一份** ⚠
        stats = write_graph(base_graph, result)
    except GraphImmutable as exc:
        # ⚠ 走到这里说明**前两道都没拦住**（例如图是被并发写进去的）——
        #   ★ 不当作系统故障：★ 图已经是定版状态，**这正是我们要的结果**。
        _finish(job, payload, outcome=OUTCOME_ALREADY_BUILT, extra={"note": str(exc)[:200]})
        # ★★ `B176` ②：图已定版 ⇒ 刚拉下来的那份源码**毫无用处** ⇒ ★ 立刻删
        _drop_source(project, payload, root)
        return

    # ★★★ `B179`：把项目**绑到这份基图**上 —— ★★ 并让「已经有图了」为真 ⚠
    #   （★ 见 `graph/binding.py`：绑定时会置 `graph_built_at` + 让邻域缓存换代际）✅
    from graph import binding

    binding.bind(project_ref, base_graph, requested_ref=(payload.get("ref") or ""))

    log.info(
        "写图完成 project_ref=%s base=%s@%s 节点=%d(去重 %d) 边=%d(跳过 %d)",
        project_ref, base_graph.repo_full_name, base_graph.sha[:12],
        stats.nodes_written, stats.nodes_deduped,
        stats.edges_written, stats.edges_skipped,
    )
    if stats.unresolved_samples:
        log.info("未能解析的引用样本：%s", stats.unresolved_samples[:10])

    # ★ 把结果摘要放进 payload，便于前端 / 排查看到"这一次产出了什么"
    _finish(
        job,
        payload,
        outcome="parsed",
        extra={
            "summary": {
                "files_seen": scan.files_seen,
                "files_parsed": scan.files_parsed,
                "files_skipped": scan.files_skipped,
                "by_lang": scan.by_lang,
                "nodes": stats.nodes_written,
                "edges": stats.edges_written,
                "edges_skipped": stats.edges_skipped,
                "parse_errors": len(result.errors),
            }
        },
    )

    # ================================================ ⑤ ★★★ 源码「用完即删」
    #   ★★ **所有者原话**：「只拉下来解析，**解析之后就删掉**」
    #   ★ 此刻：★ 图已经落库、★ 回执已经写好 ⇒ ★ **这一份源码再无任何用途** ⚠
    #   ⇒ ★ **立刻删掉** —— ★ 这是「不留源码」的**主路径** ✅
    #   ⚠ 异常残留（作业被杀 / 进程重启）由 `storage.purge_stale_sources()`
    #     兜底，★ 它挂在 `heat_flush --loop` 的维护循环里（每轮顺手清一次）。
    _drop_source(project, payload, root)


#: ★ 作业的三种归宿（★ 写进 `payload.outcome`）
#:   ⚠★ 刻意**不用 `failed` 表达"许可没过"** ——
#:     ★ "许可证要人工看一下"是**业务结论**，❌ 不是**系统故障**；
#:     ⚠ 标成 `failed` 会让用户以为**平台坏了**。
OUTCOME_PARSED = "parsed"                 # ✅ 解析并出图
OUTCOME_AWAITING_REVIEW = "awaiting_review"   # ⚠ 等人工审核（★ 还没解析）
OUTCOME_REJECTED = "rejected"             # ❌ 许可核验直接拒绝
#: ★★★ **图已定版**（`B103` / `B155`）—— ★ 这个项目解析过了，**不再重新解析**
OUTCOME_ALREADY_BUILT = "already_built"


def _project_for(payload: dict, project_ref: str):
    """★ 取作业对应的项目（⚠ 拿不到返回 `None` —— 调试 / 一次性解析没有项目记录）。"""
    from core.models import Project

    pid = payload.get("project_id")
    if pid:
        got = Project.objects.filter(pk=pid).first()
        if got is not None:
            return got
    return Project.objects.filter(project_ref=project_ref).first()


def _drop_source(project, payload: dict, root: str) -> None:
    """★★ `B176` ②：本项目这一轮用完了 ⇒ ★ **立刻删掉存储空间里的源码**。

    ★★ **所有者原话**：「只拉下来解析，**解析之后就删掉**」、
      「**节点里只保存函数签名以及他所在的文件**，解析成功之后，**立刻删除**」。

    ⚠★ **只删我们自己管理的那一份**（= `storage.release()`）——
      ★ 若 `root` 来自 `payload["path"]`（★ staff 内部调试传的**容器里的目录**），
        ★★ 那是**别人的目录** ⇒ ★ **绝不能删** ⚠
      （★ 这是 `_safe_source_path` 那条纪律的延伸：**我们只碰自己接管的路径**）

    ★ 顺手把记账行也一起删 —— 因为 `release()` 本来就是「删目录 + 删记账」两件事，
      ⚠ 只删目录会留下"记账虚高"，★ 而 `storage.audit()` 自己就把那种状态判为**缺陷**。
    """
    if project is None or not root:
        return

    # ⚠★ 调试路径（payload 里显式给了 path）⇒ 不是我们的目录 ⇒ 不碰
    if (payload.get("path") or "").strip():
        return

    from core import storage

    try:
        managed = storage.project_dir(project.project_ref)
    except ValueError:
        return

    try:
        if os.path.realpath(root) != os.path.realpath(managed):
            return
    except OSError:
        return

    freed = storage.release(project.project_ref)
    log.info(
        "源码已删除 project_ref=%s 释放=%d 字节（★ B176②：不留源码）",
        project.project_ref,
        freed,
    )


def _base_graph_for(job: Job, payload: dict, project):
    """★★★ **定下这一次解析属于哪一份基图**（★ `B179`）—— ★ 顺带兜底解析 sha。

    ★★ 所有者原话（逐字）：「**基图的数据一定要锚定 github 上的版本，用 sha 之类的**」

    ## ★ sha 从哪来（两条路）

    | 路 | sha 从哪来 | 为什么这样 |
    |---|---|---|
    | ★★ **正常** | ★ 调用方（发布 / 拉取那条路）**先解析好**，塞进 `payload["sha"]` ✅ | ★★ 因为**必须先查"有没有现成的基图"**（★ 那才是省算力的地方）⚠ |
    | ⚠ **兜底** | ★ 这里**自己解析一次** ⚠ | ★ 老作业 / 调试命令（★ payload 里没带 sha）|

    ⚠★ **失败一律 `raise`**（★ 与 `_fetch_source` 同一口径）——
      ★ 由 worker 置 `failed`，★ 并把原因给用户看 ⚠
      ★★ 尤其要**如实区分**：「私有 / 不存在」★ 是**用户的事**；
        「查得太频繁」★ 是**我们的事**（★ 见 `core/fetch.py::FetchError`）⚠
    """
    from core import fetch
    from graph import binding

    provider = (
        payload.get("provider") or (project.provider if project else "") or ""
    ).strip().lower()
    repo_full = (
        payload.get("repo_full_name")
        or (fetch.repo_full_from_url(project.repo_url) if project else "")
    ).strip()
    #: ★ 调试路径（★ 源码是容器里的一个目录）—— ★ 那时**没有远端仓库**可言
    is_local = bool(str(payload.get("path") or "").strip())

    # ⚠★ `B179`：**只有"真要拉远端"时才强制要仓库地址** ⚠
    #   ★ 调试路径下项目可能根本没设 `repo_url`（★ staff 指了个目录就让解析）——
    #     ★★ 那时拿"缺仓库"当失败是**错的**（★ 它本来就不需要仓库）⚠
    if not provider or (not repo_full and not is_local):
        raise ValueError("作业 payload 里缺少 provider / repo_full_name，无法定位仓库。")

    ref = str(payload.get("ref") or "").strip()
    sha = str(payload.get("sha") or "").strip()
    default_branch = str(payload.get("default_branch") or "").strip()

    if not sha:
        # ★★ 兜底（⚠ 正常路径不会走到 —— 见函数文档）
        if str(payload.get("path") or "").strip():
            # ⚠★★ **调试路径：源码是容器里的一个目录** ⇒ ★ **没有 commit sha** ⚠
            #   ★★ 绝不去网上解析（★ 那是假仓库 / 本地目录，★ 解析必然失败 ⇒ 把作业白白搞崩）⚠
            #   ★ 用一个**一眼看得出是本地**的占位身份（★ 别假装是某个 commit）✅
            #     （★ `blob_url` 会因此返回空 —— ★ 不给假链接，见 `graph/models.py`）
            sha, default_branch = "local", ""
        else:
            _progress(job, 1, "解析版本")
            v = fetch.resolve_ref(provider, repo_full, ref)
            if not v.ok:
                raise ValueError(v.message or "解析不出这个仓库的版本。")
            sha, default_branch = v.sha, v.default_branch
        payload.update({"sha": sha, "default_branch": default_branch, "ref": ref})
        job.payload = {**payload}
        job.save(update_fields=["payload"])

    bg, created = binding.get_or_create(
        provider, repo_full, sha, ref=ref, default_branch=default_branch,
    )
    log.info(
        "基图：%s base=%s@%s（%s）",
        "新建" if created else "已存在",
        repo_full, sha[:12],
        "已建好" if bg.built_at else "待建",
    )
    return bg


def _fetch_source(job: Job, payload: dict, project) -> str:
    """★★ **从远端把源码拉进"这个项目的存储空间"**（`B153` / `core/fetch.py`）。

    ★ 这是发布链路上**最后补上的一环** —— ★ 在这之前，`source_path` 得是
      "容器里已放好的目录" ⇒ ⚠★ **只有我们自己能发布**。

    ★ 三件事一起做完：

    | # | 做什么 |
    |---|---|
    | **1** | ★ 算**这个人还剩多少空间**（`storage.remaining_for_ingest`）⇒ ★★ 当作**硬闸门**交给拉取 |
    | **2** | ★★ **边下边解边计数**（`fetch.fetch_archive`）⇒ 超了**立即中止并清理** |
    | **3** | ★ **记账**（落在 `fetch` 内部 —— ★ 让"文件已落盘"与"账已记"同一次调用完成） |

    ⚠★ **失败一律 `raise`** —— ★ 由 worker 置 `failed` 并把 `error_msg` 给用户看
      （❌ 不假装成功、也❌不静默跳过 —— ⚠ 那会让项目**永远卡在"排队中"**）。
    """
    from core import fetch, storage

    provider = (payload.get("provider") or (project.provider if project else "") or "").strip()
    repo_full = (
        payload.get("repo_full_name")
        or (fetch.repo_full_from_url(project.repo_url) if project else "")
    ).strip()

    if not provider or not repo_full:
        raise ValueError(
            "作业缺少仓库信息（provider / repo_full_name）—— "
            "★ 无法拉取源码，请由调用方补齐 payload"
        )

    owner = project.owner if (project and project.owner_id) else None
    # ★★ **硬闸门**：这个人还剩多少 ⇒ ⚠ 传 0 表示不限制（★ 只该在管理员/调试场景）
    max_bytes, max_files = storage.remaining_for_ingest(owner) if owner else (0, 0)

    _progress(job, 3, f"拉取源码（{repo_full}）")
    result = fetch.fetch_archive(
        job.project_ref,
        provider,
        repo_full,
        # ★★★ `B179`：**按 sha 下载** ⚠ —— ★ 一份基图**永远**对应同一份代码 ✅
        #   ★（⚠ 按分支名下载的话，作者一提交，同名基图的内容就变了）
        ref=(payload.get("sha") or payload.get("commit") or ""),
        max_bytes=max_bytes,
        max_files=max_files,
        owner=owner,
    )

    if not result.ok:
        # ★ 消息是**给用户看的**（★ 见 `fetch.py`：每条拒绝都说清了"还差多少"）
        raise ValueError(result.message or f"拉取源码失败（{result.reason_code}）")

    # ⚠ 钉 ref 已提到 `run_parse_job` 的 ⓪-1 —— ★ 两条来源统一在那里处理，
    #   ⚠ 免得"拉取的钉了、走本地目录的没钉"（★ 那正是踩到的 bug）。

    log.info(
        "拉取完成 project_ref=%s repo=%s 字节=%d 文件=%d 跳过=%d",
        job.project_ref, repo_full, result.bytes, result.files, result.skipped,
    )
    return storage.project_dir(job.project_ref)


def _remember_license(base_graph, verdict) -> None:
    """★★★ **把许可结论存到【基图】上**（★ `B179`）—— ★ 两处用处：

    ① ★★ **复用时不必重新核验**（★ 同一个 sha，结论不会变）✅
    ② ★★ `B176` ④：**传染性许可（GPL 等）⇒ 只出节点、不自动生成调用边** ⚠
       —— ★ 那是**建图时**的决定，★ 所以必须落在基图上 ⚠
       （★ 所有者原话：「**GPL 项目不解析，但生成节点图，不生成调用关系**」）⚠
    """
    if base_graph is None:
        return

    from core import licensing

    detections = (verdict.evidence or {}).get("detections") or []
    spdx = ""
    if detections and isinstance(detections[0], dict):
        spdx = str(detections[0].get("spdx") or "")

    base_graph.license_decision = (verdict.decision or "")[:16]
    base_graph.license_reason_code = (verdict.reason_code or "")[:32]
    base_graph.license_reason_text = (verdict.reason_text or "")[:400]
    base_graph.license_spdx = spdx[:64]
    base_graph.license_evidence = verdict.evidence or {}
    # ★★ `B176` ④：★ **只有"宽松许可"才自动生成调用关系** ⚠
    base_graph.edges_generated = (
        verdict.decision == licensing.DECISION_ALLOW and verdict.reason_code != "copyleft"
    )
    base_graph.save(
        update_fields=[
            "license_decision", "license_reason_code", "license_reason_text",
            "license_spdx", "license_evidence", "edges_generated", "updated_at",
        ]
    )


def _license_gate(job: Job, project, root: str, *, base_graph=None) -> str:
    """★★ **许可核验闸门**（`U3.1` 第 ④ 步）—— ★ 返回三种归宿之一。

    ★★ 关键动作是 `submission.resolve_license()`：★ 把那条「**待核验**」的流水
      **就地更新成真结论**（⚠ 不是再建一条 —— 那会把限额计成两次，且用户会看到两条记录）。

    ★ 判定（**放行 ⇒ 解析**）：

    | 情况 | 归宿 |
    |---|---|
    | ★ 核验结论 = 宽松（自动放行） | ✅ `pass` |
    | ★★ **人工已经放行过** | ✅ `pass`（⚠ 人的判断优先，核验只补证据） |
    | ⚠ 结论 = 进人工审核 | ⏸ `awaiting_review`（★ **不解析**） |
    | ❌ 结论 = 自动拒绝 | ❌ `rejected`（★ **不解析**） |
    """
    from core import licensing, submission
    from core.models import ProjectReview

    verdict = licensing.evaluate(root)

    # ★★ `B179`：结论存到【基图】上（★ 复用它的人不必再验；★ 且 GPL 的出图策略也在这）
    _remember_license(base_graph, verdict)

    if project is None:
        # ⚠ 没有项目记录（如调试命令 `parse_project`）⇒ ★ 只记日志，**不阻断**
        log.info("许可核验（无项目记录）：%s / %s", verdict.reason_code, verdict.decision)
        return "rejected" if verdict.decision == licensing.DECISION_REJECT else "pass"

    # ★ 这条项目最近一次提交的流水（★ 就是那条「待核验」）
    review = (
        ProjectReview.objects.filter(project_ref=project.project_ref)
        .order_by("-created_at")
        .first()
    )
    if review is not None:
        # ★★ 就地更新成真结论（★ 管理员最终看到的是真原因，❌ 不是"待核验"）
        submission.resolve_license(review, verdict, project=project)

    if review is not None and review.decision == ProjectReview.DECISION_APPROVED:
        # ★ 自动放行，**或者人工已经放行过** —— ★ 后者时 `resolve_license` 不会覆盖人工结论
        return "pass"

    if verdict.decision == licensing.DECISION_REJECT:
        return "rejected"
    return "awaiting_review"


def _finish(job: Job, payload: dict, *, outcome: str, extra: dict | None = None) -> None:
    """★ 收尾：写 `outcome` + 摘要 + 阶段文案。

    ★★ 三种归宿都走这里 —— ★ 保证「作业为什么停在这里」**永远写在 `payload` 里**
      （⚠ 否则用户只能看到一句"完成"，却不知道图为什么没出来）。
    """
    stage = {
        OUTCOME_PARSED: "完成",
        OUTCOME_AWAITING_REVIEW: "等待人工审核（源码已就绪，审核通过后自动解析）",
        OUTCOME_REJECTED: "许可证核验未通过（未解析）",
        # ★ 说清"为什么什么都没做"，⚠ 而不要含糊地写"完成"
        OUTCOME_ALREADY_BUILT: "这个项目已经解析过了，图不会重新生成",
    }.get(outcome, outcome)

    job.payload = {**payload, "outcome": outcome, **(extra or {})}
    job.progress = 100
    job.stage = stage[:64]
    job.save(update_fields=["payload", "progress", "stage"])

    # ⚠ 这几种"没解析"是**业务结论**，不是失败 —— ★ 但一定要能查得出来
    if outcome != OUTCOME_PARSED:
        log.info(
            "作业未进入解析：Job#%s project_ref=%s outcome=%s",
            job.pk, job.project_ref, outcome,
        )


def run_heat_flush_job(job: Job) -> None:
    """执行热度合并作业：把 Redis 里未合并的访问计数累加进数据库。

    ★ payload 约定（都可省略）：

    ```json
    { "project_ref": "proj_xxx", "metric": "visit" }
    ```

    ⚠ 省略 `project_ref` ⇒ **合并全部项目**（由 `graph/heat.py` 自动发现）。

    ⚠ `graph/heat.py` 内部已处理：Redis 不可用 ⇒ 跳过而不失败
      （★ 增量还在 Redis 里，Redis 一恢复下次就补上，**没有数据损失**）。
    """
    from graph import heat

    payload = job.payload or {}
    projects = [payload["project_ref"]] if payload.get("project_ref") else None
    metrics = [payload["metric"]] if payload.get("metric") else None

    _progress(job, 10, "扫描待合并增量")
    report = heat.flush_all(projects, metrics, dry_run=bool(payload.get("dry_run")))

    job.payload = {
        **payload,
        "summary": {
            "projects": report.projects,
            "batches": report.batches,
            "rows": report.rows,
            "total": report.total,
            "skipped": report.skipped[:20],
            "dry_run": report.dry_run,
        },
    }
    job.progress = 100
    job.stage = "完成"
    job.save(update_fields=["payload", "progress", "stage"])


#: ★ 作业类型 → 执行体。新增作业类型在这里加一条即可（与 Parser 注册表同思路）
HANDLERS = {
    Job.KIND_PARSE: run_parse_job,
    Job.KIND_HEAT_FLUSH: run_heat_flush_job,
}


# ===========================================================================
# ★★ 执行准入（唯一的入口）
# ===========================================================================


def claim_job(job: Job, *, worker_id: str = "") -> bool:
    """★★ **原子抢占作业执行权** —— ★ 保证 **同一个作业只被一个进程执行**。

    ⚠★★ 为什么要这一层（这是被实测逼出来的）：

    ★ worker 里的写法是「**先读 `state` 判断、再置 `running`**」——
      ⚠ 那是经典的 **check-then-use**：两个 worker（或**一个 worker + 一次手动重跑**）
      可以**同时通过检查**，于是 ★★ **同一个作业被跑两遍**。

    实测到的样子：★ 同一个 `project_ref` 下出现两条 `parse` 作业的 `outcome` 互相覆盖
      （一条 `awaiting_review`、一条 `parsed`），★ 而图**已经被写进去了** ——
      ⚠ "作业说没解析，图却有了"，**排查起来极其费劲**。

    ★★ 做法：★ 用一条 **`UPDATE ... WHERE started_at IS NULL`** 做抢占 ——
      ★ 数据库保证**只有一个**进程能把它从 `NULL` 改成时间 ⇒ **抢不到的直接退出**。
      ★ 用 `started_at` 而不是 `state` 做判据，是因为 ★ 它**只会从 NULL 变一次**
      （⚠ `state` 会被反复读写，拿它当闸门不可靠）。

    Returns: ★ `True` = 抢到了（可以往下跑）；`False` = 别人已经在跑，**直接返回**。
    """
    from django.utils import timezone

    updated = Job.objects.filter(pk=job.pk, started_at__isnull=True).update(
        state=Job.STATE_RUNNING,
        started_at=timezone.now(),
        # ⚠ 空串也要看得见来源（★ 手动重跑与 worker 必须能区分，否则排查时又要猜）
        worker_id=(worker_id or job.worker_id or "manual")[:64],
        stage="启动",
    )
    if not updated:
        log.warning("作业已被其他进程领取，跳过：Job#%s", job.pk)
        return False
    job.refresh_from_db()
    return True


#: ★ `execute()` 的三种归宿
EXEC_SKIPPED = "skipped"   # ⚠ 别人已经在跑（★ 抢不到，什么都不做）
EXEC_DONE = "done"
EXEC_FAILED = "failed"


def execute(job: Job, *, worker_id: str = "") -> str:
    """★★ **作业执行的唯一入口** —— 抢占 → 分发 → 干活 → **收尾**。

    ★ `run_worker` 与调试 / 冒烟脚本**都走这里** —— ⚠ 否则两边各写一套准入与收尾逻辑，
      ★ **早晚会漏**（`B148` 已经吃过一次这种亏）。

    ★★ 收尾（置 `done` / `failed`）也在这里 ——
      ⚠ 否则"手动跑一次"的作业会**永远停在 `running`**（★ 用户看到"执行中"，其实早跑完了）。

    ★ 一个刻意的保留：★ **`_finish()` 写下的 `stage` 不被盖成"完成"**
      —— ⚠ 因为「等待人工审核（源码已就绪…）」这种话**比"完成"有用得多**。

    Returns: `EXEC_SKIPPED` / `EXEC_DONE` / `EXEC_FAILED`
    """
    from django.db.models import F
    from django.utils import timezone

    if not claim_job(job, worker_id=worker_id):
        return EXEC_SKIPPED

    try:
        handler = HANDLERS.get(job.kind)
        if handler is None:
            raise ValueError(f"未注册的作业类型：{job.kind}")
        handler(job)
    except Exception as exc:  # noqa: BLE001 —— ★ 作业失败必须落库（❌ 不吞）
        log.exception("作业失败：Job#%s", job.pk)
        Job.objects.filter(pk=job.pk).update(
            state=Job.STATE_FAILED,
            error_msg=str(exc)[:2000],
            attempts=F("attempts") + 1,
            finished_at=timezone.now(),
        )
        return EXEC_FAILED

    job.refresh_from_db()
    stage = job.stage if job.stage and job.stage != "启动" else "完成"
    Job.objects.filter(pk=job.pk).update(
        state=Job.STATE_DONE,
        progress=100,
        stage=stage[:64],
        finished_at=timezone.now(),
    )
    return EXEC_DONE
