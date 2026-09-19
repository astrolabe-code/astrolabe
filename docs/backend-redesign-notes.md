# 后端解析链路:实测经验与缺陷记录(供重设计使用)

> 记录时间:2026-09-10。背景:用户发现后端解析有严重问题、准备重新设计后端。
> 本文件是**第一手现场数据**——结论全部来自本机实测与真实跑通的作业,不是推测。
> 相关决策条目见 `frontend-decisions.md` D56–D59;本轮计划见 `frontend-plan.md`。
> **当前状态:基线采集已由用户叫停(计划暂停),但下面 3 个已修缺陷 + 5 个待查项已可信。**

---

## 一、实测环境

| 项 | 实测值 | 来源 |
|---|---|---|
| CPU | ★ 已脱敏（`B158`） | `/proc/stat` |
| 内存 | ★ 已脱敏（`B158`） | `/proc/meminfo` |
| 磁盘 | `/` = `/dev/mapper/ubuntu--vg-ubuntu--lv`,**ext4 本地盘** | `/proc/mounts` → 满足 `os.replace` 同目录 rename 原子性 |
| 负载 | loadavg 0.14,776 进程(daphne + MySQL + 1 个用户 docker 容器 `ws_1_admin`) | `/proc/loadavg` |
| MySQL | `wait_timeout=28800`、`max_connections=151`、Threads_connected=5 | 实测查询 |
| 关键设置 | `job_max_per_user=1`、`job_max_queued_global=200`、`job_child_memory_mb=1024`(本轮由 2048 校准)、`job_child_cpu_s=1800`、`job_default_timeout_s=1800`、`job_poll_interval_s=2`、`job_tick_interval_s=60`、`job_max_attempts=3`、`job_retention_days=7`、`parse_admin_only=False`、`parse_allow_user_reparse=True` | `AppSetting` |
| 部署 | `webapp.service`(daphne) / `webapp-tunnel` / `webapp-cleanup.timer` / `webapp-iptables`;**worker 此前不存在**(D56),本轮已补并常驻 | systemd |

---

## 二、当前解析链路的真实形状(两段,不是一段)

| 阶段 | 在哪执行 | 受什么约束 | 代码位置 |
|---|---|---|---|
| 上传落盘(zip) + **解压** + 探测源码根 + 重写 compile_commands + 注入 clangd | **web 进程的后台线程** (`threading.Thread`) | **无并发上限、无 RLIMIT、不受 worker 数控制** | `projects/services/upload_service.py:287`(起线程)、`:167`(`_extract_and_parse`) |
| **解析**(tree-sitter/ast → `CodeNode/CodeEdge`) | **worker 子进程** | worker 数、`RLIMIT_AS/CPU/FSIZE/NOFILE`、租约、`job_max_per_user=1` | `projects/parsing/*` + `projects/jobs/child.py` |
| 两段之间的接缝 | 解压完置 `parse_status="parsing"` → `analyze_in_background()` → 投递 parse 作业 | 投递失败 → 项目直接置 `error`("系统繁忙") | `projects/services/parser_service.py:48` |

★ **这对重设计的意义**:衡量"并发能力"时必须分开看——解压段压的是 **web**(且无上限),解析段压的是 **worker**(有上限)。集群化的硬前提是把解压段也搬进 worker(见第六节)。

---

## 三、已修复的缺陷(全部真实跑出来的)

### BUG-1 ★ fork 后 `close_all()` 打断 worker 自己的数据库连接
- **现象**:worker `systemctl` 显示 `active`,但主循环每 2 秒刷一次
  `pymysql.InterfaceError: (0, '')`(根源 `ssl.SSLError: SSLV3_ALERT_BAD_RECORD_MAC`),**永远领不到作业**。
- **根因**:`child.py` 子进程入口调 Django 的 `connections.close_all()`;该方法会让 pymysql 发送**明文 `COM_QUIT`**,而 socket 是**从父进程(worker)继承来的同一个 TLS 会话** → 明文写进 TLS 记录流,服务端同时结束该会话。
- **证据**:A/B 实验 `scripts/debug_worker_db.py`
  - 子进程 `close_all()` → 父进程立刻 `Lost connection to MySQL server during query`
  - 子进程只 `socket.detach()` + `os.close(fd)`(不发字节)→ 父进程连接完好
- **修复**:`projects/jobs/child.py::discard_inherited_connections()`;`worker.py` 主循环异常时用它自愈,并在每轮开头 `close_old_connections()`。

### BUG-2 ★ 上传端点 100% 返回 500
- **现象**:任何 `POST /api/projects/<key>/upload/` 都 500。
- **根因**:`upload_service.handle_upload` 调 `perm.check_owner(..., "无权操作该项目", builtin_status=403)`,而该参数已随"builtin 概念退役"删除
  → `TypeError: check_owner() got an unexpected keyword argument 'builtin_status'`。
- **影响**:**上传源码这条路此前完全不可用** —— 这正是"库里没有一次真实解析数据"(D48)的直接原因之一。
- **修复**:改回 `perm.check_owner(user, proj, "无权操作该项目")`。

### BUG-3 作业处理器 `_cleanup_backups` 崩溃
- **现象**:worker 首次真实运行即报 `TypeError: cannot unpack non-iterable int object`,`cleanup:backups` 作业失败。
- **根因**:`for pid, in Project.objects.values_list("pk", flat=True)` —— `flat=True` 产出 int,不能再解包。
- **修复**:`for pid in ...`;手动重投该作业后 `done / backups 完成,处理 0 项`。

> 三个缺陷的共同点:**都藏在"从来没被真实执行过"的路径里**。这验证了"先跑现场再重设计"的必要性。

---

## 四、待查 / 待定(按重要性排序)

| # | 问题 | 证据与定位入口 | 性质 |
|---|---|---|---|
| 1 | **web 仍在读写源码**(解压线程) | `upload_service.py:287` 起线程写盘 | 集群硬阻塞(见第六节) |
| 2 | **投递被拒 = 硬失败,不是排队** | py-mid(300 文件)上传后项目直接置 `error`,`parse_error="系统繁忙,请稍后在项目页重试解析"`;该文案唯一来源是 `parser_service.analyze_in_background` 里 `_submit_parse` 返回 `None`。需查清是 `Project.active_job` 未释放还是 `job_max_per_user=1` 误伤 | 设计问题(语义应为排队而非失败) |
| 3 | **SIGTERM 会打断正在跑的作业** | `worker.py::_run_one` 检测到 `_stop` 就 `_hard_stop` 当前子进程,作业落 `failed`("worker 退出");设计 §21.6 期望的是"当前 job 跑完/超时再退" | 实现与设计的偏差 |
| 4 | 死配置:`job_worker_count`、`job_shard_space` | 字段与迁移都在,但**全仓库无一处读取**;分片空间实际是 `models_job.SHARD_SPACE=64` 硬编码常量 | 配置与实现脱节 |
| 5 | 缺 `fs_backend` 启动自检 | 全仓库无该模块、无 fstype 检查;设计 §20 P2 与 §21.6 明确要求"网络 FS 拒绝启动(仅 worker)" | 缺失功能 |

**其它已知但优先级低**:诊断键 `emit_error / clamped_limits / unresolved / by_confidence` 恒为 0(`projects/diagkeys.py` 自述"补齐定稿里声明但当前未实现的键");`cron_tick` 只排了已实现 handler(`backups/deletions/note_export` 处标注"落地后再放回")。

---

## 五、实测基线(唯一完整的一组:22 文件 C 工程)

| 指标 | 实测值 |
|---|---|
| 规模 | 22 文件 / 241 函数 / zip 5.9KB |
| `t_upload` | 0.12s |
| `t_extract`(web 线程:解压+compile_commands+clangd) | 0.31s |
| 队列等待(入队 → worker 领走,≈ 轮询间隔) | 1.55s |
| `t_parse`(tree-sitter + 写库) | 1.53s |
| **t_total(用户感知)** | **3.51s** |
| 子进程峰值内存 / 父进程峰值 | **70.9MB** / 79.1MB |
| 子进程 CPU 秒 | 1.0s |
| 产出 | **267 节点 / 262 边**(dir 1、file 22、function 241、macro 2、variable 1;lang=cpp) |

**这是本系统第一次跑通「上传 → 解压 → 解析 → 落库」全链路。**
现场保留了这个项目(已置公开)供对照:
- 项目主页 `http://127.0.0.1:8000/app/p/proj__baseline_ff75f997_8adf24c5`
- 图谱页 `http://127.0.0.1:8000/app/p/proj__baseline_ff75f997_8adf24c5/graph`

**规模外推(供容量估算,未经实测验证)**:按 241 函数 ≈ 1.53s / 1.0 CPU 秒线性外推,3600 函数量级 ≈ 20–30s 解析;360MB 级源码(如 Linux 内核)需要按"节点/边数上限 + 分阶段提交"重新估算。**建议在你重设计后,用 `scripts/smoke_parse_baseline.py` 补测中等/大样本。**

---

## 六、集群硬约束(设计 §21.6 / 阶段 §3.7)

| 约束 | 现状 | 违反后果 |
|---|---|---|
| **web 无状态、不读写源码** | ❌ 违反(解压线程在 web) | 上传落在"收到 HTTP 请求的机器",而作业由"拥有该项目分片的 worker"执行 → 源码不在本地,`os.replace` 亲和性失效 |
| worker 必须与负责分片的源码同机 | ✅ 单机满足 | `os.replace` 需同目录 rename 原子性 |
| 同一分片同一时刻一个 worker | ✅ 已实现 fail-fast | 重叠会 `SystemExit(1)` |
| 源码存储为本地 FS(拒 NFS/CIFS) | ⚠ 无自检 | 集群里会**静默写坏** |
| 分片空间决定并发上界 | 64 → 最多 64 并发作业 | 上百人同时上传只能排队(除非改成 256) |

**两条路径**(阶段 §3.5):A = K8s + PVC per project(RWO,故障自动重挂);B = 裸机分片路由(该分片降级只读,需人工迁移);当前是 C 单机。

---

## 七、契约冻结清单(本轮绝对不动,动了要连带前端)

| 契约 | 为什么不能动 | 消费方 |
|---|---|---|
| `parse_status` 取值(`idle/uploading/parsing/done/error`) | SPA `ParseStatus` 组件 + 进度轮询终止条件依赖 `done/error` | SPA + 旧模板 |
| `progress` 0–100 语义 | SPA `ProgressBar` / 轮询 | SPA + 旧模板 |
| `graph/summary`、`graph/nodes`、`graph/edges`、`graph/nodes/<uid>`、`graph-rev` 响应形态 | SPA `api/types.ts` 与适配器 | SPA |
| `analysis/`、`diagnostics/` 结构 | SPA 分析页与健康度面板 | SPA |
| `jobs/` 字段(kind/state/progress/message)、`/api/jobs/<id>/cancel/` | SPA 作业表与取消 | SPA |
| `/api/projects/*`(列表/新建/编辑/删除/上传/重解析/复制) | SPA 工作区卡片 + 旧模板 `projects.html`、`analysis_page.js`、`project_home.js`、`files_page.js`、`code_page.js` | **SPA + 旧模板** |

> 改动流程(项目规矩):`docs/frontend-decisions.md` 登记 → `frontend-contract.md` 更新 → 再动代码。

---

## 八、文件速查(你设计时会用到的入口)

| 关注点 | 文件 |
|---|---|
| 上传与解压(要 Job 化) | `projects/services/upload_service.py` |
| 解析投递与策略门禁 | `projects/services/parser_service.py` |
| 解析流水线 | `projects/parsing/{quick,extract,build,incr,langs,tsutil}.py` |
| 作业系统 | `projects/jobs/{__init__,worker,child,cron,handlers,ops}.py`、`projects/models_job.py` |
| worker 入口 | `projects/management/commands/graphworker.py` |
| 设置项 | `core/models.py`(AppSetting 的 `job_*` / `parse_*` 段) |
| 诊断键 | `projects/diagkeys.py` |
| 部署单元 | `deploy/systemd/*`、`deploy/README.md` |
| 采集脚本 | `scripts/smoke_parse_baseline.py`(基线)、`scripts/debug_worker_db.py`(fork 连接 A/B)、`scripts/smoke_project_actions.py`、`scripts/smoke_avatar_compress.py`、`frontend/scripts/smoke_graph_api.py` |

---

## 九、现场残留物(确认后自行清理)

- 临时用户 `_baseline_ff75f997`(id 46)
- 项目 `proj__baseline_ff75f997_8adf24c5` —— c-small,**done,267/262,已公开**(建议保留做对照)
- 项目 `proj__baseline_ff75f997_ecc45fa4` —— py-mid,**error**(投递失败样本,建议查明再删)
- 清理命令(确认后执行):
  ```bash
  cd /home/webapp/demo && sh -c 'set -a; . ./.env; set +a; ./venv/bin/python manage.py shell -c "
  from django.contrib.auth.models import User
  User.objects.filter(username__startswith=\"_baseline\").delete()
  "'
  ```
  (删用户会级联删项目与作业;源码目录需另行 `rm -rf /home/webapp/userdata/users/46__baseline_ff75f997`)
