# 现状:「上传源码 → 图谱数据」完整流程与存储结构(重设计前的事实基线)

> 记录时间:2026-09-10,**全部结论来自代码实读**(每条附 `文件:行号`)。
> 用途:给后端重设计提供"现在到底是怎么跑的"的准确底稿。
> 配套:`backend-design.md`(你的新设计)、`backend-decisions.md`(决策 B<n>)、
> `backend-redesign-notes.md`(实测环境与缺陷)。

---

## 0. 一句话时序

```
① 上传 POST      web 进程:校验 → zip 落 /tmp → 起后台线程 → 立即返回
② 解压(web 线程) safe_extract → 探测源码根 → 提取 compile_commands 到 .lspdb
                 → 写 .clangd → 置 parse_status=parsing
③ 投递作业       analyze_in_background → _set_parsing → jobs.submit(parse)
④ worker 领取    每 2s 轮询 → _claim_next(分片+SKIP LOCKED) → try_start(租约)
⑤ 子进程解析     fork → 静默丢连接 → RLIMIT → PDEATHSIG → execute_parse
⑥ 流水线         build.run:增量判定 → discover_files → 逐文件 scrape
                 → 重载 uid → upsert 节点 → 解析边 → upsert 边 → 语言画像
⑦ finalize       delete_stale(epoch) → 转正/drift → 诊断标准化
                 → 写 CodeAnalysis → 更新 Project(done/epoch/graph_rev+1)
⑧ P7 分析        analyze_project:度量/入口/死代码/聚类/环/执行流 + 重建搜索索引
⑨ 作业终态       finish:dedup_key=NULL、清 active_job、同步项目状态
```

**关键点:①–② 在 web 进程(其中 ② 是后台线程),④–⑧ 在 worker 子进程。** 这两段的性能与故障模型完全不同。

---

## 1. 阶段详解

### ① 上传请求(web 进程)
- 入口 `projects/views/projects.py:110` `project_upload` → `us.handle_upload(user, proj, request.FILES, ...)`
- 校验顺序(保持旧顺序):登录 → 归属 → `file` 存在 → 扩展名(`.zip/.tar.gz/.tgz`)
  (`upload_service.py:212-223`)
- 大小:生效值 = `min(前端 max_mb, AppSetting.upload_max_size_mb, 200MB)`(`:225-237`)
- 配额:`UserProfile.used_bytes + f.size > storage_quota_mb*1MB` → 400(`:239-248`)
- 源码目录:优先沿用 `Project.source_path`(必须是当前用户目录下的路径),否则新建
  `用户目录/项目目录名` 并回写(`:250-269`)
- 清理旧解压目录后,**请求内先把 zip 落盘** 到 `/tmp/webapp_upload_tmp/<uuid>_<name>`(`:271-281`)
- 置 `parse_status="uploading"`,然后 `threading.Thread(target=_extract_and_parse).start()`,**请求立即返回**(`:283-291`)

### ② 解压与准备(web 进程的后台线程)
`_extract_and_parse`(`upload_service.py:167-205`):
1. 解压:`zipfile` → `safe_extract_zip`(防 `../`、绝对路径、符号链接;限制条目数与解压后总大小
   `extract_max_mb`,上限 1024MB)(`:17`)
2. `_probe_src_dir(proj_dir)`:探测真正的源码根(处理"包了一层目录"的情况)
3. `_rewrite_compile_commands(proj, src_dir)`(`:103-164`):
   递归(限深 3)找包内的 `compile_commands.json` → 按当前位置重写 `file/command/directory`
   → **提取到外部** `.lspdb/<uid>_<username>/<key>/compile_commands.json`(`core.common._lspdb_dir_for`)
   → 删除项目目录内的原文件(保持项目目录干净)
4. `_inject_clangd_config(src_dir)`(`:88-100`):若有 C/C++ 文件,在项目根写 `.clangd`
   (`-Wno-implicit-function-declaration -fno-builtin`)
5. 置 `parse_status="parsing"`、`parse_progress=0`(`:187-190`)
6. `analyze_in_background(project.key, src_dir)`(`:191-192`)

### ③ 投递 parse 作业(仍在 web 线程)
`parser_service.py:48-64`:
- `job_progress(proj)` 已有活动作业 → 直接 return(静默)
- `_set_parsing(proj)`:置 `parsing` / `progress=0` / 清 `parse_error`(`:34-38`)
- `_submit_parse` → `submit(Job.KIND_PARSE, "proj:<key>", project=proj, user=owner,
  payload={"src_dir":..., "full": True})`(`:41-45`)
- `submit()`(`jobs/__init__.py:75-121`)做四件事:
  1. 全局队列上限 `job_max_queued_global`(200)
  2. 单用户并发上限 `job_max_per_user`(1)
  3. `shard = shard_of("proj:<key>") % SHARD_SPACE`(64)
  4. 事务内 `Job.objects.create(dedup_key=dedup_key(kind,key), fence=next_fence())`
     + `Project.objects.filter(pk, active_job__isnull=True).update(active_job=job, active_fence=fence)`
     → 占位失败抛 `JobBusy` → **返回 None**
- **返回 None 时项目被置 `error`**:`parse_error="系统繁忙,请后在项目页重试解析"`
  (`:62-64`;这就是 `backend-decisions.md` B7 待查项的现场)

### ④ worker 领取
- 主循环每 `job_poll_interval_s`(2s)`_claim_next()`(`jobs/worker.py:57,131`)
- `_claim_next`:`select_for_update(skip_locked=True).filter(state=queued, shard__in=本 worker 分片)`
  → `try_start(job)`(`jobs/__init__.py:126-147`):更新 `state=running`、`lease_until=now+120s`、
  `attempts+1`;校验 `active_job` 一致性,不一致抛 `JobBusy`
- leader(最小 id 的在线 worker)额外领 `shard=-1` 全局任务,并每 60s 跑一次 `cron_tick`

### ⑤ 子进程执行
- `_run_one`(`worker.py:159+`)fork `multiprocessing.Process(target=child_main)`
- `child_main`(`jobs/child.py:153+`):
  1. `discard_inherited_connections()` ← **B3 修复点**(原 `close_all()` 会污染父进程 TLS 连接)
  2. `apply_child_limits()`:`RLIMIT_AS=job_child_memory_mb`(现 1024MB)、`RLIMIT_CPU=1800s`、
     `RLIMIT_FSIZE=1024MB`、`RLIMIT_NOFILE=1024`
  3. `set_pdeath_sig()`(`prctl(PDEATHSIG)`)
  4. 写 `child_pid`,然后 `HANDLERS["parse"](job_id)`
- `handlers.job_parse` → `projects.parsing.execute_parse(job_id)`(`handlers.py:51-60`)

### ⑥ 解析流水线
`parsing/__init__.py:51-191` `execute_parse`:
1. `select_for_update` 取 Project → `epoch = project.parse_epoch + 1`(`:84-86`)
2. `_limits(project, s)`(`__init__.py:23-48`):**生效限制 = min(用户自选, 管理员上限)**,
   含 `max_files / max_file_kb / max_sym_file / max_sig / max_sites / max_nodes / max_edges`;
   并参与增量指纹 `meta_fp`(改限制 → 指纹变 → 自动全量)
3. `build.run(project, src_dir, limits, epoch, tick, fence)`(`build.py:195`)
   - **增量派发**(`:204`):`incr.plan(files, disc_counts, project, limits, cache)`
     基于 `Project.parse_hash_cache` 的基线 + `meta_fp`;有效则走 `_run_incremental`(`:628`),
     否则全量
   - `discover_files(src_dir, limits)`(`:86`):按 `langs.LANG_SPECS` 判语言,排除
     `IGNORE_DIRS`/`HARD_EXCLUDE_NAMES`(.git/.graphbak/.lspdb)/用户 `parse_exclude_*`,
     超限跳过并记 `skipped_files`
   - **逐文件 scrape**:`extract.scrape(lang, rel_path, raw, max_sym)`(`extract.py:782`)
     → Python 走 `extract_python`(:127,ast),C/C++ 走 `extract_c_cpp`(:252,tree-sitter via
     `tsutil.get_parser/parse_bytes`),其他走 `_extract_generic`(:543)
   - **目录容器**:`_dir_chain` 生成 dir/file 节点(`:170,234`)
   - **重载 uid**:`upsert.assign_overload_uids(project, nodes, lang)`(`:311-313`,`upsert.py:102`)
   - **节点写库**:`upsert.bulk_upsert_nodes(project, nodes, batch=500)`(`:359,387`)
   - **边解析**:`_add_edge(from_uid, to_uid, etype, res, conf, level, rel, line, col)`(`:408`)
     - `CALLS`(:522)按候选池解析,`resolution` ∈ `exact/qualified/name/heuristic`,
       对应 `confidence` 1.0/0.9/0.5/0.3,并记录 `sites`(调用点 file/line/col)
     - `IMPORTS`(:549,文件级)、`EXTENDS/IMPLEMENTS`(:466,472)、`OVERRIDES`(:486)
   - **边写库**:`upsert.bulk_upsert_edges(project, edges, batch=500)`(`:567,573`)
   - **语言画像**:`lang_breakdown` + `parse_langs` + `main_lang`(`:584-602`)
   - 进度写回:`tick(progress=int(10 + 80*i/total))`(`_tick` :252-255,经 `child.tick` 续租+写
     `Job.progress`)
   - **增量路径** `_run_incremental`(`:628-1043`):①只 scrape changed 文件 ②目录链 upsert +
     清孤儿 ③范围 stale ④候选池 = 变化文件内存符号 ∪ DB 存量符号
4. 全过程中 `fence()`(`child.assert_fence`)在每批写前校验,失效即自杀,防"失去租约还写库"

### ⑦ finalize(解析收尾)
`parsing/__init__.py:92-180`:
1. **stale 删除**(全量轮):`delete_stale(CodeNode/CodeEdge.objects.filter(project, origin="source",
   parse_epoch__lt=epoch))`(`:104-107`,`upsert.py:168`)—— **epoch 精确删除,绝不删 planned**
2. 隐藏 source 行本轮消失 → 记 uid → 删后归档孤儿笔记(`:101-117`)
3. `import_orphans(project)`:节点重现时孤儿笔记一键导入(`:118`)
4. `promotion.promote_and_detect(project, epoch, diags)`:转正 / drift / **unknown** 判定;
   `reconcile_planned_edges(project)`(`:129-135`)
5. `diagkeys.standardize_diagnostics(diags, planned_count, dead_count)`(`:139-148`):
   补别名与标准键;`emit_error / clamped_limits / unresolved / by_confidence` 目前是**补的默认值(恒 0)**
6. 写 `CodeAnalysis`(`:152-170`):`stats`(files/functions/methods/types/edges/sites/
   skipped_files/truncated_edges/epoch/graph_rev)、`lang_breakdown`、`diagnostics`
7. 更新 Project(`:171-180`):`parse_status=done`、`parse_progress=100`、`parse_epoch=epoch`、
   `parse_lang`、`parse_langs`、`parse_langs_v+1`、`parse_hash_cache=baseline`、**`graph_rev+1`**

### ⑧ P7 分析(异常不阻断解析)
`analysis.py:216-261` `analyze_project`:
- 度量 `_metrics_lines`(:40,圈复杂度/行数)、邻接 `_adjacency`(:70)
- 环检测 `_scc_cycles`(:82,SCC)→ `diagnostics["cycles"]`
- 入口/死代码 `_entry_dead`(:121)→ 写 `CodeNode.is_entry / is_dead`
- 聚类 `cluster`(目录/包名,≤64 字符)→ `CodeNode.cluster`,聚类清单 → `CodeAnalysis.clusters`
- 执行流 `_build_processes`(:264)→ `CodeAnalysis.processes`;入口清单 → `entry_points`
- **重建搜索索引**:`search.rebuild_index(project)`(`analysis.py:225-226`,`search.py:117`)
  → 写 `SearchIndex`(term / postings / doc_freq / parse_epoch)

### ⑨ 作业终态
`jobs.finish(job, ok=True)`(`jobs/__init__.py:152-174`):`state=done`、`dedup_key=NULL`(释放幂等)、
清 `lease_until/child_pid/worker_pid`;若 `active_job==job.pk` 则清 `active_job/active_fence`;
再 `_finalize_project_status`(:177-190):`done`→项目 `done`,`failed/canceled`→项目 `error`
**并清空 `parse_hash_cache`(下次必定全量)**。

---

## 2. 状态机

**`Project.parse_status`**(前端契约,冻结中):
`idle`(未上传) → `uploading`(解压中) → `parsing`(解析中) → `done` / `error`

**`Job.state`**:`queued → running → done|failed|canceled`
(租约过期回 `queued` 重试,不是终态;`attempts ≥ 3` 才落 `failed`)

---

## 3. 存储结构

### 3.1 数据库

| 表 | 关键字段 | 说明 |
|---|---|---|
| **Project** | `source_path`、`parse_status/progress/error`、`parse_epoch`(本轮轮次,upsert-first 依据)、`parse_hash_cache`(增量基线;失败清空→全量)、`parse_lang/parse_langs/parse_langs_v`、`parse_limits/parse_exclude_names/parse_exclude_suffix`(用户偏好,≤ 管理员上限)、`parse_parameters`、`sig_strict_defaults`、`min_retained_rev`(增量同步最早 rev)、`graph_rev`(全局发号器)、`active_job`(OneToOne,单一写者占位)、`active_fence`(fencing token) | `models.py:12-45` |
| **CodeNode** | `uid`(项目内唯一)、`base_uid`(重载族)、`kind`(12 种)、`subtype`、`name/qname`、`file_path/dir_path`、`line/col/end_line/end_col`、`parent_uid`、`lang`、`signature`、`return_type`、`params`、`modifiers/annotations/flags`、`visibility`、`origin`(source/planned)、`lifecycle`、`spec/planned_sig/baseline_sig/actual_sig/sig_match`、`metrics`、`cluster`、`is_entry`、`is_dead`、`hidden`、`rev`、`extra`(重载信息)、**`parse_epoch`** | `models_graph.py:46-132`;索引含 `(project,kind)`、`(project,file_path)`、`(project,origin,parse_epoch)`、`(project,base_uid)`、`(project,cluster)`、`(project,is_entry)` |
| **CodeEdge** | `from_uid/to_uid`、`type`(12 种)、`level`(file/symbol)、`confidence`、`resolution`(exact 1.0 / qualified 0.9 / scope 0.8 / name 0.5 / heuristic 0.3)、`sites`(≤50)+`site_count`、`origin`、`dangling`、`rev`、**`parse_epoch`** | `models_graph.py:160-212`;唯一约束 `(project, from_uid, to_uid, type, origin)` |
| **CodeAnalysis** | `clusters`、`processes`、`entry_points`、`diagnostics`、`stats`、`lang_breakdown`、`include_planned` | `models_graph.py:215-236`(每项目一行,`execute_parse` 与 `analyze_project` 都写) |
| **SearchIndex** | `term`、`postings`(`[{u,t,d}]`,≤64 词元/行、词频上限 1024)、`doc_freq`、`parse_epoch` | `models_graph.py:239-261`;`search.rebuild_index` 整树重建 |
| **Job** | `kind/state`、`dedup_key`(可空唯一)、`fence/worker_pid/child_pid/lease_until/worker`、`cancel_requested`、`progress/message/error`、`attempts`、`timeout_s`、`shard`、`payload` | `models_job.py:19-82` |
| **WorkerNode** | `name/host/pid`、`shards`、`status`(online/draining/offline)、`load`、`heartbeat_at` | `models_job.py:85-106` |
| **GraphBackup** | `ts`、`files/files_count/files_overflow`、`node_uids`、`reason`、`size_bytes`、`status`(pending/files_written/committed/rolled_back/stalled)、`protected` | 迁移备份与意图日志,`models_job.py:109-148` |
| **GraphDeletion** | `kind`(node/edge)、`key`、`rev`、`deleted_at` | 删除墓碑,供增量同步 `?since=`,`models_job.py:151-171` |
| **UserProfile** | `storage_quota_mb`、`used_bytes`(源码字节账本)、`used_db_bytes`(图数据 DB 配额) | 配额预检与结算(`build.py:_reserve_db/_settle_db`) |

### 3.2 磁盘

| 路径 | 内容 | 谁写 |
|---|---|---|
| `UPLOAD_ROOT/users/<uid>_<username>/<项目目录名>` | 解压后的项目源码根(`Project.source_path`) | `handle_upload` / `create_project` |
| `/tmp/webapp_upload_tmp/<uuid>_<name>` | 上传的 zip 临时落盘(请求内必须落盘,`request.FILES` 会关闭) | `handle_upload:271-281`;解压后删除 |
| `.lspdb/<uid>_<username>/<key>/compile_commands.json` | 从包内提取并重写的编译数据库(项目目录保持干净) | `_rewrite_compile_commands:103-164` |
| `<项目根>/.clangd` | clangd 配置(老式 C 兼容) | `_inject_clangd_config:88-100` |
| `<项目根>/.graphbak/<ts>/` | 迁移前的图数据备份 | 迁移流程(`ops.py` 清理) |
| 排除项 | `.git`、`node_modules`、`venv/.venv`、`__pycache__`、`dist`、`.cache`、`.idea`、`.graphbak`、`.lspdb` | `langs.py:36-44` |

### 3.3 uid 规则(`projects/uidutil.py`)
- 分隔符 `UID_SEP = "#"`(:26);容器 kind = `{dir, file}`(:30);`QNAME_KINDS = {method, field, enum_member, parameter}`(:31)
- `make_uid(kind, file_path, name, qname, ...)`(:89)生成 uid;`base_uid_of`(:217)、
  `same_family`(:225)判断重载族
- `overload_key(sig, lang)`(:164)归一化重载键;`make_overload_uid`(:191)
- 校验:`validate_uid_path`(:47)、`validate_path`(:65)、`validate_name`(:77)、`normalize_path`(:81)

---

## 4. 与重设计直接相关的观察(结论已登记到 backend-decisions.md)

| 观察 | 位置 | 已登记 |
|---|---|---|
| 上传/解压在 web 进程,无并发上限与资源限制 | `upload_service.py:287` 起线程 | B8 |
| 投递失败 = 项目直接 `error`,而不是排队 | `parser_service.py:62-64` | B7 |
| `dedup_key` 按项目(`proj:<key>`),同项目重复投递会被拒 | `parser_service.py:43` | B7 |
| 分片空间硬编码 64,`AppSetting.job_shard_space` 无人读取 | `models_job.py:15` | B10 |
| 缺 `fs_backend` 启动自检(网络 FS 不拒绝) | 无该模块 | B9 |
| SIGTERM 打断作业而非"跑完再退" | `worker.py::_run_one` | B11 |
| 诊断键 `emit_error/clamped_limits/unresolved/by_confidence` 恒 0 | `diagkeys.py:26-29` | 待登记 |
| 子进程 `close_all()` 曾污染父进程连接(已修) | `jobs/child.py` | B3 |
| 上传端点曾 100% 500(已修) | `upload_service.py:215` | B4 |
| `cleanup:backups` 解包崩溃(已修) | `jobs/ops.py:171` | B5 |
