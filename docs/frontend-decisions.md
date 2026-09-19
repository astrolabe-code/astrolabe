# 前端重构决策记录(权威副本)

> ★ 本文件是「决策与改进」的唯一权威副本。
> 计划工件 `plan.md/plan.json` 由 IDE 计划管理器托管,**直接编辑会被回滚**;
> 对话内容在上下文压缩后会丢失。因此所有决策/改进一律先登记到本文件,
> 再通过 `plan_create` 重新生成计划把结论并入正文。
>
> 登记格式:`D<n> · YYYY-MM-DD · 决策/改进 · 结论 · 落实位置`
> 规则:先写本文件 → 再更新 `frontend-plan.md` / `frontend-contract.md` → 最后重新生成计划 → 才动代码。

---

## 已确认决策

### D1 · 2026-09-09 · 重构范围
- **结论**:本阶段只做「图谱工作区主链」= 登录 → 项目工作区(列表/新建上传) → 项目主页 → 图谱浏览 → 节点详情 → 搜索 → 分析面板。
- 管理后台、容器终端、留言消息、LSP 管理等仍是 Django 模板,后续按模块迁入。
- 落实:`frontend-plan.md` 边界章节。

### D2 · 2026-09-09 · 前后端托管形态
- **结论**:**独立 SPA + token 认证**(前后端分离),不是 Django 同源壳页。
- 落实:后端新增 `authapi` + Bearer/CORS 中间件。

### D3 · 2026-09-09 · 技术栈
- **结论**:**TypeScript** 必选;React 18 + Vite 5 + react-router-dom 6 + @tanstack/react-query 5 + zustand 4。
- 落实:`frontend-plan.md` 技术栈。

### D4 · 2026-09-09 · 图渲染库
- **结论**:**vis-network**;用 **npm 包**,不拷贝旧静态资产 `assets/static/js/vis-network.min.js`(旧 `data_json/custom` 图 UI 已下线,旧 `graph_page.js` 不可用作数据源)。
- 落实:`src/graph/adapter.ts`。

### D5 · 2026-09-09 · UI 方案
- **结论**:**Tailwind CSS**(mobile-first)+ 少量自绘组件,**不用 MUI**;图标 lucide-react / react-icons。
- 版本固定:tailwindcss 3.4.17、tailwind-merge 2.5.5、tailwindcss-animate 1.0.7、postcss 8.5、autoprefixer 10.4.20。
- 落实:`tailwind.config.js`、`src/styles/index.css`。

### D6 · 2026-09-09 · 小屏图谱形态
- **结论**:**列表模式 + 详情**。`<lg(1024px)` 图谱画布默认收起,展示节点列表 + 搜索,点选弹出底部全屏详情抽屉;保留「进入画布」全屏缩放入口。
- 落实:`VisGraphMobile` / `NodeDetailDrawer`。

### D7 · 2026-09-09 · 图数据源(D1 议题)
- **背景**:后端没有任何接口返回「全项目边集合」(`graph/nodes` 只有点、`node_detail` 只有 ego 邻居、`changes` 只有 rev 元数据)。
- **结论**:**方案 A+ 分层端点**。新增只读 `GET /api/projects/<key>/graph/edges/`;前端默认取 `level=file` 文件级边做全局总览,点开文件/符号再按需取 `level=symbol` 边展开。
- 落实:`projects/views/graphdata.py` + `projects/urls.py`;前端 `src/graph/adapter.ts`。

### D8 · 2026-09-09 · token 有效期
- **结论**:默认 **7 天**,勾选「记住我」 **30 天**;env `API_TOKEN_TTL_HOURS=168` / `API_TOKEN_TTL_HOURS_REMEMBER=720`。
- **不做自动续期**,过期返回 401 `unauthenticated` 后重新登录。
- 落实:`authapi` 签发逻辑 + `mysite/settings.py`。

### D9 · 2026-09-09 · planned 规划节点编辑器深度
- **结论**:**完整动态表单(spec-schema 驱动)**。按 `GET …/spec-schema/?lang=` 的 `capabilities`(receiver / multi_return / decorators / async / macro / overload / visibility / param_type)生成每语言字段(名称、qname、签名、参数、返回类型、修饰符、注解、doc)与可见性选择;kind/subtype/visibility 选项取自 schema 的 `kinds`/`subtypes`/`visibility`/`params_kind`;新建前可用 `POST …/planned/derive/` 建议头文件路径与 guard;保存走 `POST/PUT/DELETE …/planned/nodes/`。
- 落实:`components/SpecForm.tsx`。

### D10 · 2026-09-09 · 文档与落盘纪律
- **结论**:计划、改进、接口契约一律写入 `/home/webapp/demo/docs/`(git 可追溯),**不再依赖对话记忆,也不再落 /tmp**。
- 计划工件 `plan.md/plan.json` 仅作镜像,改动必须通过 `plan_create` 重新生成。
- 落实:本目录三份文档。

---

---

## 2026-09-09 用户评审(7 条)登记

### D11 · 2026-09-09 · CSRF 与 Bearer 中间件的交互边界
- **问题**:若 `/api/` 无 Authorization 但有 session cookie 的 POST,CsrfViewMiddleware 仍校验 → 担心旧模板页 403。
- **核实**:`assets/static/js/base.js` 已为同源非 GET 的 fetch 自动补 `X-CSRFToken`(含无 cookie 时自愈重试),旧模板调用 `/api/` 不会 403。
- **结论(三态精确策略)**:
  1. `Authorization: Bearer` 合法 → 挂 `request.user` + 置 `request._dont_enforce_csrf_checks=True`(免 CSRF);
  2. **无 Authorization 头 → 原样放行**,走既有 session + CSRF(旧模板与游客路径零变化);
  3. **有 Authorization 但无效/过期/撤销 → 401 `unauthenticated`,不回退 session**(避免双认证混淆)。
- `/api/auth/login`、`/api/auth/logout` 显式 `csrf_exempt`(登录时尚无 token)。
- 新增 env `API_STRICT_BEARER`(默认 `0`):置 `1` 时 `/api/` 无 Authorization 直接 401(仅 Bearer)。该开关只在旧模板全部迁移后才启用,本阶段不动。
- 落实:`mysite/bearer.py`、`mysite/settings.py`;`frontend-contract.md` §7。

### D12 · 2026-09-09 · token 存储与 XSS 防护
- **结论**:维持 **localStorage**(独立 SPA 跨域场景下 httpOnly cookie 需 `SameSite=None; Secure` + `credentials` + 重新引入 CSRF,代价与风险更大),但强制配套:
  1. 后端加 **CSP**(`default-src 'self'`,脚本仅同源 + 构建产物,禁 inline/eval);
  2. 笔记/markdown 等富文本渲染一律 **DOMPurify** 净化,禁止 `dangerouslySetInnerHTML` 直出;
  3. TTL **7 天**("记住我" 30 天)+ 服务端可撤销 + 登出立即撤销;
  4. 后续若改为同源部署,再评估迁移到 httpOnly cookie。
- 落实:`frontend-plan.md` 风险章节、`frontend-contract.md` §7。

### D13 · 2026-09-09 · `/edit/` 已存在,无需新增后端任务
- **核实**:`projects/views/edit.py::graph_edit` 已实现并注册(`api/projects/<key>/edit/`),语义满足统一写接口:
  - body `{base_graph_rev, changes:[…]}`;顶层 CAS 失败 → `409 stale_rev`(带 `data.graph_rev`);
  - **每个 change 项**还可带 `rev`,与行 rev 不一致 → `409 code="stale"`(带 `data.expected_rev`);
  - 门禁:`graph_not_ready`(解析未完成)、`project_busy`(有活跃作业)、`too_many_changes`(单次超限)。
  - `op` 支持:`create`、`update`(patch 白名单见下)、`hide`、`delete`、`rename`、`edge_create`、`edge_update`(patch 仅 `note`)、`edge_delete`。
  - `update` patch 白名单:`spec, signature, annotations, flags, doc, hidden, params, return_type, visibility, modifiers, subtype`;仅 `origin="planned"` 节点可 update/rename。
- **结论**:不新增后端任务;契约补全,前端按此实现并在超限时自动分批。
- 落实:`frontend-contract.md` §8。

### D14 · 2026-09-09 · 分析面板数据来源(不新增端点)
- **核实**:现有接口已全覆盖,**本阶段不新增分析端点**:
  - 入口点/执行流/聚类/环/统计 → `GET …/analysis/`(`entry_points`、`processes`、`clusters`、`cycles`、`metrics_stats`、`counts{entries,dead,clustered}`);
  - 诊断健康度 → `GET …/diagnostics/`(`diagnostics` 原始键 + `counts{nodes,edges,entries,dead,clustered,cycles}`);
  - 死代码/入口点清单(可翻页) → `GET …/graph/nodes/?is_dead=1` / `?is_entry=1`。
- 落实:`frontend-contract.md` §9(面板区块 → 接口映射)。

### D15 · 2026-09-09 · 上传需独立 client 方法
- **结论**:`client.ts` 增加 `upload(url, file, {onProgress})`,用 **XMLHttpRequest**(fetch 无上传进度事件);`multipart/form-data`,**不手动设 Content-Type**(交给浏览器生成 boundary);不走 JSON 归一,直接返回后端响应。
- 落实:`src/api/client.ts`;`frontend-contract.md` §10。

### D16 · 2026-09-09 · 图谱性能默认收紧
- **结论**:
  1. 默认节点上限 **500**(而非 1000),可在 UI 调整到上限 2000 并提示;
  2. 进入页面即按 `kind` / `type` / `origin` **前置过滤**,不先全量再裁;
  3. `physics` 在 `stabilizationIterationsDone` 后关闭,或首屏直接用静态/层级布局;
  4. 超阈值时按 `dir_path` 或 `cluster` **聚合展示**,点开再展开子图;
  5. symbol 级边仅在点开文件/符号时按需拉取(D7 分层)。
- 落实:`frontend-plan.md` 性能章节、§4 前端分层。

### D17 · 2026-09-09 · envelope 长期治理
- **结论**:
  1. `frontend-contract.md` 为每个端点登记**原始形态**(①/②/③/④)与归一规则,逐接口可查;
  2. **所有新增后端接口**(`/api/auth/*`、新增 `graph/edges/`)统一采用 `{ok:true,data}` / `{ok:false,error:{code,message}}`;
  3. 既有接口保持不动(避免破坏旧模板),后续新接口一律遵循统一 envelope,逐步收敛。
- 落实:`frontend-contract.md` §11。

### D18 · 2026-09-09 · 视觉基线以现站点为准(撤销生成器配色)
- **问题**:计划与设计文档里的 `#0F1419/#161D26` 石墨黑 + 冷青 `#12B8A6` 是计划生成器产物,**不是站点真实样式**,会与"样式不要改"直接冲突。
- **核实**:真实样式是「晨光控制台」——浅色默认 + `[data-theme="dark"]` 夜穹深色变体:
  - 浅色(`assets/static/css/base.css:7-72`):`--bg #eef3f9`、`--card #ffffff`、`--text-main #101d33`、`--accent #0891b2`、`--accent-strong #0e7490`、`--accent-dim rgba(8,145,178,.10)`、`--ok #059669`、`--warn #d97706`、`--err #dc2626`。
  - 深色(`base.css:78-136`):`--bg #16213e`、`--card #252536`、`--accent #4db8d6`;`.btn.primary` 深色用 `#23768f`。
- **结论**:§2 设计系统整节以本文档为准,**生成器配色作废**;一切颜色/尺寸/动效沿用现站点 token。

### D19 · 2026-09-09 · 旧 HTML/CSS/JS 不逐行移植,仅作规格参考
- **用户原话**:"我以前写时很多没考虑好,一直想删掉,重构一版新的,语言更清晰、更简洁高效"。
- **结论**:旧代码**不复制、不兼容式引入**;它只提供两样东西:① 视觉规格(尺寸/配色/动效/断点);② 交互与文案事实(如登录失败文案、解析状态流转)。逻辑全部用 React + TS 重写,结构更清晰、无历史包袱。
- 例外:纯静态资源(字体、`lucide` 图标集)可直接沿用,不算"旧逻辑"。

### D20 · 2026-09-09 · 样式落地方式:新写干净样式层 + Tailwind 映射 token
- **结论**:不把旧 `base.css` 引入 SPA(它带着历史冗余)。改为:
  1. `src/styles/tokens.css` 新写一份**同名同值**的 CSS 变量(浅色默认 + `[data-theme="dark"]` 变体),值来自 D18;
  2. `tailwind.config.js` 把这些变量映射为语义色(`accent: 'var(--accent)'`、`card: 'var(--card)'` …),组件用 Tailwind 类 + 语义类名,外观与现站一致;
  3. 通用外观语义类(按钮/卡片/输入框/表格/标签/弹窗/进场)在 `src/styles/components.css` 里重写一份精简版(去掉历史 hack 与重复规则)。
- 收益:视觉 1:1,代码干净,单一变量源,深色模式天然支持。

### D21 · 2026-09-09 · 旧资产处置:迁移一个删一个
- **结论**:主链页面在 React 里实现并通过联调后,才删除对应旧资产;未迁移页面(管理后台/终端/消息/LSP 等)保持不动。
- 删除清单登记在 `frontend-design.md` §13,每删一项勾选并注明日期;删除前确认对应 Django 视图无其它引用。

### D22 · 2026-09-09 · 首页先行(本阶段第一个落地页)
- **用户决定**:"先改首页,首页样式比较简单基础;首页做好了,再去改其他页面"。
- **结论**:把 **React 首页**提为本阶段第一个前端交付物,排在登录/工作区/图谱之前;通过后删除旧首页资产。
- **顺序调整**:后端认证 + CORS(仍最先,SPA 跨域调 API 必需)→ **前端骨架(含样式层 tokens/components)** → **首页 1:1 复刻** → 登录页 → 工作区 → 项目主页 → 图谱 → 详情/搜索 → 分析。`graph/edges/` 端点可后置到图谱页之前。
- **完成后删除**:`core/templates/core/index.html`、`assets/static/js/index_page.js`(及其 `vis_flow_fx.js` 若仅首页使用);删除前确认 `core/views` 不再 render 该模板。
- 落实:`frontend-design.md` §13、`frontend-plan.md` 里程碑表。

### D23 · 2026-09-09 · 首页数据与登录态方案
- **核实**:`GET /api/projects/` 走 `ps.list_visible_projects(request.user)`,**不支持 `q` 参数**;旧首页 `/projects/?q=` 也是把 q 交给页面后在 `/api/projects/` 结果里**前端过滤**(`projects.html` 同款做法)。
- **结论**:首页 hero 搜索沿用同样语义 —— 拉 `GET /api/projects/`(游客可见公开项目)后在前端按 `name/desc/owner` 过滤;Enter 跳工作区并带 `q`。**不新增后端搜索端点**。
- **导航登录态**:SPA 有 token → `GET /api/auth/me`;无 token → 游客态(显示登录/注册)。首页阶段登录/注册按钮**临时指向旧站 `/login/`、`/register/`**,待 React 登录页完成后切回 SPA 路由。
- 落实:`frontend-design.md` §13。

### D24 · 2026-09-09 · 旧样式文件先归档再改(可回溯)
- **用户要求**:"以前写的样式文件要有备份,万一你写错样式了,还有可以参考改进的"。
- **结论**:任何旧样式/模板被修改或删除**之前**,先做只读归档;归档未完成时**禁止**删除或改写旧文件。
- **归档位置**:`/home/webapp/demo/docs/legacy-style/`(docs 目录内,不参与构建、不被 Django static 收集,纯参考)。
- **命名**:`<原文件名>.legacy-YYYY-MM-DD`(如 `base.css.legacy-2026-09-09`)。
- **首批归档清单**(执行第一步完成):
  - `assets/static/css/base.css`(浅/深变量 + 全部组件样式 + 背景特效 + 断点)
  - `assets/static/css/base.css.bak-theme`(若仍存在)
  - `core/templates/core/index.html`(含首页 `extra_css` 全量样式)
  - `core/templates/core/nav.html`(顶栏结构与内联样式)
  - `core/templates/core/base.html`、`_skyfx.html`(外壳与背景层结构)
  - `core/templates/accounts/login.html`(登录页结构与样式)
- **用法**:新 `tokens.css`/`components.css` 出视觉偏差时,与归档逐条 diff 变量与规则;归档只读,永不修改。
- **与 git 的关系**:git 历史已有版本,但归档提供"随时可打开对照"的即时参考,二者并存。
- 落实:`frontend-design.md` §13(旧资产处置前置步骤)、`frontend-plan.md` 里程碑 0。

### D25 · 2026-09-10 · 部署拓扑事实(纠正"nginx 发静态"的误判)
- **核实**(只读:systemctl / nginx -T / .env):
  - systemd 服务 `webapp`:`User=webapp`、`WorkingDirectory=/home/webapp/demo`、`EnvironmentFile=/home/webapp/demo/.env`、`ExecStart=venv/bin/daphne -b 127.0.0.1 -p 8000 mysite.asgi:application`(**daphne/ASGI**,非 gunicorn)。
  - nginx:`listen 80; server_name 192.168.3.91`;`/static/`、`/`、`/ws/` 三条 location **全部 `proxy_pass` 到 127.0.0.1:8000**,**没有 try_files / alias / root**。
  - `.env`:`DJANGO_DEBUG=0`;`DJANGO_ALLOWED_HOSTS=192.168.3.91,127.0.0.1,localhost,128wqkv667751.vicp.fun`。
  - 仓库内**无 nginx 配置**(配置在 `/etc/nginx`,仓库外),也无 gunicorn/uwsgi/docker/whitenoise。
- **静态真实链路(实测 `curl` 80/8000 均 `200 text/css 23081B`)**:`mysite/asgi.py` 用 `ASGIStaticFilesHandler(django_asgi_app)` 包装 —— 等价于 `runserver --insecure`,因此 `DJANGO_DEBUG=0` 时仍由 **Django staticfiles 直接读 `assets/static/`** 提供静态;响应特征 `Content-Disposition: inline` + `Cache-Control: no-cache`。settings 无 `STATIC_ROOT`/`STATICFILES_DIRS`;media 另走 `urls.py` 的 `django.views.static.serve`。另有 `mysite/csp.py`(CSP `script-src 'self'`)。
- **结论**:线上 = 「nginx 纯反向代理 → daphne → Django(ASGIStaticFilesHandler 发静态)」;**不能假设 nginx 直接发静态**,也不需要 `collectstatic`。
- **对 SPA 的影响**:构建产物放 Django 静态目录即可被提供,D26 方案 A(Django 托管 `/app/` + catch-all 视图)与现状完全一致,零 nginx/settings 改动。
- 落实:`frontend-plan.md` 部署章节。

### D26 · 2026-09-10 · 部署决策推迟到首页完成后(用户选择)
- **用户决定**:"我先看方案再定(先不动部署,等前端首页做完在 /app/ 下联调时再定)"。
- **首页阶段(里程碑 2–3)联调方式**:
  1. Vite dev server(`host 0.0.0.0`、`allowedHosts:true`、端口 5173),前端 `VITE_API_BASE` 指向 Django;
  2. `DJANGO_CORS_ORIGINS` 增加 `http://192.168.3.91:5173` 等 dev 源,CORS 中间件**仅 dev/此阶段启用**;
  3. **不动 nginx、不动线上、不改 `/`**。
- **首页验收通过后再定托管**(默认推荐 A):
  - **A(推荐)Django 托管 `/app/`**:构建产物进静态目录,`mysite/urls.py` 加 `re_path(r'^app/.*$')` 返回 SPA `index.html`;零 nginx 改动,与现状(静态走 Django)一致。
  - **B nginx 托管**:`/app/` 用 `alias` + `try_files` 指向构建目录(省 Django 资源),需改仓库外 nginx 配置并留档到 docs。
  - **C 降级**:若托管层无法做 history fallback,前端改用 hash 路由(`createHashRouter`)。
- **通用约束**:SPA 迁移期一律挂 **`/app/` 前缀**,不占用 `/`;旧路由(/login/、/projects/、/graph/ 等)零影响;fallback 只匹配 `^app/`。
- 落实:`frontend-plan.md` 里程碑(首页之后新增"部署与托管决策"步骤)。

### D27 · 2026-09-10 · 路由隔离与 fallback 边界
- SPA 一律挂 `/app/` 前缀;history fallback **只匹配 `^app/`**(Django 侧 `re_path` 或 nginx `try_files` 仅限该前缀)。
- 旧路由(`/login/`、`/register/`、`/projects/`、`/project/<key>/`、`/graph/<key>/`、`/tools/`、`/manuals/`、`/admin/`、`/api/`、`/static/`、`/media/`)显式精确/前缀匹配,**不做 fallback**,杜绝"SPA 吞掉旧路由"。

### D28 · 2026-09-10 · 节点 uid 用查询参数,不用路径
- SPA 路由:`/p/:key/node?uid=<encodeURIComponent(uid)>`(`#`/`/`/`?` 在 pathname 有歧义,splat 解码不可靠)。
- 调后端 `/api/projects/<key>/graph/nodes/<path:uid>/`:`#` → `%23`,`/` 保持字面(Django `<path:>` 原生支持斜杠);里程碑 8 用真实 uid(如 `file#src/main.py`)做一条联调断言。

### D29 · 2026-09-10 · 图资源上限同时约束节点与边(不改后端)
- `graph/summary` 已返回 `counts.edges` / `counts.by_type` / `counts.nodes`,进入前即可决策。
- 规则:`nodes ≤ 500 且 edges ≤ 2000` 正常渲染;`edges > 2000` → 简化模式(仅 CALLS/IMPORTS + `confidence ≥ 0.8` + 按 `dir_path` 聚合);`nodes > 500` → 按 kind 前置过滤;两者都超 → 聚合视图 + 提示展开目录。边同样 `limit/offset` 分页 + DataSet 增量并入。

### D30 · 2026-09-10 · token 安全的分层缓解(v1)+ v2 迁移路径
- v1 维持 localStorage,补:`package-lock.json` 入库;CI `npm audit --audit-level=high` 失败即阻断;服务端"登出全部设备"(撤销该用户全部 token,改密/登出时调用);可视化依赖动态 import 缩小攻击面。
- **v2(同域部署后)**:迁移 `HttpOnly + SameSite=Strict + Secure` 会话 cookie,前端仅存非敏感登录态标记;因同域无需 CORS credentials。与 D26 方案 A 绑定。

### D31 · 2026-09-10 · envelope 归一改为显式声明
- 新增 `src/api/endpoints.ts`:每个端点显式登记 `kind`(`data` / `spread` / `legacy-error` / `coded-error`),client **不做结构猜测**。
- 边界规则:`ok === false` 优先判失败;仅当 `ok === true && 'data' in body` 才走 `data` 形态(避免字段名恰为 `ok` 误判)。
- Vitest 覆盖 4 形态 × 边界用例。

### D32 · 2026-09-10 · 归档扩展 JS + SHA-256 校验
- 归档范围从"CSS + 模板"扩展到 **JS**:`index_page.js`、`login_page.js`、`nav.js`、`base.js`、`project_home.js`、`graph_page*.js`、`vis_flow_fx.js` 等。
- 生成 `docs/legacy-style/MANIFEST.sha256`;删除旧文件前用仓库内脚本 `frontend/scripts/verify-archive.mjs` 逐项比对 hash,不一致即中止。

### D33 · 2026-09-10 · 迁移期降级跳转(避免导航断裂)
- 维护 `LEGACY_FALLBACK` 映射,未完成路由自动跳旧站(带 `?from=spa`):`/workspace → /projects/`、`/login → /login/`、`/p/:key → /project/:key/`、`/p/:key/graph → /graph/:key/?project=:key`。
- 首页 CTA(开始使用/浏览手册/三张入口卡)在对应页完成前一律指旧站,完成后逐条摘除。

### D34 · 2026-09-10 · 移动列表分页(已支持,无需改后端)
- `graph/nodes` 提供 `limit`(≤500)/ `offset` / `total` → 用 React Query `useInfiniteQuery`;首屏 100 条滚动加载,行内显示签名与 `file:line`。

### D35 · 2026-09-10 · 图谱刷新保留视口与选中
- 重取前保存 `network.getScale()`、`getViewPosition()` 与选中 uid 到 store;增量更新后 `moveTo` + `setScale` **静默恢复**;仅当选中节点消失时才提示"图谱已更新"。

### D36 · 2026-09-10 · 主题状态契约(已核实 `theme-init.js` + `base.js`)
- `localStorage["theme"]`,取值 `"light" | "dark"`,写到 `document.documentElement`(`<html data-theme>`);与旧站**同 key 同值同元素**。
- **完整行为(以 base.js `initTheme` 为准)**:有存储值 → 用它;无存储值 → **跟随系统 `prefers-color-scheme`**;未手动选择过时**持续跟随系统变化**。`theme-init.js` 只负责"有存储值时提前应用"以防闪变,SPA 侧已按同规则实现(`useTheme`)。

### D37 · 2026-09-10 · SpecForm 拆子任务 + 轻量渲染器
- 拆三块独立验收:① schema→表单描述映射(字段类型仅 text/code/params/tags/markdown/select 六类,**自研轻量渲染器**,不引 RJSF);② params 编辑器(pos/kw/var_positional/var_keyword);③ 校验与错误展示。
- 若后续 schema 出现嵌套/数组,再评估 RJSF 适配层。里程碑 8 内单列子任务并预留额外工时。

### D38 · 2026-09-10 · 可访问性补强
- `Modal`/`Drawer` 统一:焦点陷阱、打开聚焦首元素、关闭焦点归还触发元素、Esc 关闭、`aria-modal`/`role="dialog"`。
- 图谱页**桌面也提供"列表视图"切换**(键盘可达的节点列表),Canvas 之外始终有语义化替代;验收加键盘导航测试。

### D39 · 2026-09-10 · 测试策略(P0)
- **Vitest**:client 归一(4 形态 + 边界)、authStore/workspaceStore、graph adapter 映射。
- **Playwright E2E**:登录、首页渲染与搜索、工作区建项目、图谱打开与选中、节点详情、搜索、分析。
- **视觉回归**:旧首页 vs 新首页,浅/深 × 1440/1024/640/420 截图对比(容差 0.5%)。
- 全部落在 `frontend/tests/`,**不落 /tmp**。

### D40 · 2026-09-10 · 性能预算与代码分割
- 主 bundle **gzip ≤ 200KB**;`manualChunks` 分离 `react` / `vis-network` / `recharts`。
- 首页 demo 图用 `IntersectionObserver` 触发 `React.lazy(() => import('./DemoGraph'))`。
- `npm run build` 后脚本校验体积,超预算报警。

### D41 · 2026-09-10 · share 与登录态优先级(已核实后端)
- `permission_service.can_view` 是**并集**(public / owner / staff / share 任一通过即放行),share **不会降权**。
- 前端把 `share` 当**补充参数全程透传**,不覆盖登录态;仅当"项目非公开 + 未登录 + 靠 share 才可见"时,顶部提示"正在以分享身份查看(只读)"。

### D42 · 2026-09-10 · 静态文件「不缓存」是有意设计,禁止后续加缓存
- **用户原话**:"当初我就是不要缓存,因为在频繁更改静态文件,缓存了,还要清缓存,才能看到效果"。
- **现状**:`ASGIStaticFilesHandler` 返回 `Cache-Control: no-cache`(带 `Last-Modified`/`ETag`,可 304 协商),改完文件刷新即生效 —— **这是刻意的,不是缺陷**。
- **规则(写死,不得随意更改)**:
  1. **禁止**为 `/static/` 添加长 `max-age` / `immutable`;禁止在 nginx 加静态强缓存(方案 B 若实施,也必须保留 `no-cache` 或等价的协商缓存)。
  2. 模板里 `{% static ... %}?v=2026xxxx` 的版本号习惯**保留**(与 no-cache 并存,无害)。
  3. **SPA 的 `index.html` 必须不缓存**(`Cache-Control: no-store` 或 `no-cache`),否则发新版后浏览器仍用旧 HTML 引用旧资源。
  4. Vite 产物带内容哈希(`assets/index-xxxx.js`)理论上可长缓存,但**本阶段与现状保持一致:一律不缓存**;确需优化时再单独决策并登记。
- 落实:`frontend-plan.md` §8.1(缓存策略)。

### D43 · 2026-09-10 · 【待办提醒】稳定后切换为生产级静态部署
- **用户要求**:"把稳定以后,改用生产级别的静态文件部署登记进 doc,以免我以后忘了"。
- **当前状态**:⏳ **待办**(本阶段**不执行**,D26 已决定部署推迟到首页完成后再定)。
- **触发条件(全部满足才做)**:① 主链页面(首页/登录/工作区/项目主页/图谱/详情/搜索/分析)迁移完成并验收;② 静态文件不再频繁手改(或已改为"改完走构建");③ 你明确说"稳定了,可以切生产部署了"。
- **目标**:静态资源由 **nginx 直接发**(Django 不再承担静态),SPA 走 nginx `alias` + `try_files`。
- **执行清单(到时按序做,每步留档)**:
  1. `settings.py` 增加 `STATIC_ROOT`(如 `/home/webapp/demo/staticfiles`),保留 `STATIC_URL='/static/'`;
  2. 发布流程加入 `python manage.py collectstatic --noinput`;
  3. **备份**现网 nginx 配置(`cp /etc/nginx/... → docs/deploy/nginx-<日期>.conf`);
  4. nginx 改:`location /static/ { alias <STATIC_ROOT>; }`(去掉 `proxy_pass`);`location /app/ { alias <SPA dist>; try_files $uri $uri/ /app/index.html; }`;
  5. `mysite/asgi.py` 的 `ASGIStaticFilesHandler` 改为**仅开发环境启用**(生产直接用 `django_asgi_app`),确认 Channels/WebSocket 不受影响;
  6. `media` 仍走 Django `serve`(或一并交给 nginx,二选一并登记);
  7. `systemctl restart webapp` + `nginx -t && systemctl reload nginx`,验证 `/static/css/base.css`、`/app/`、旧路由三者都正常;
  8. 回退方案:nginx 改回 `proxy_pass` + asgi 恢复包装(5 分钟内可回滚)。
- **缓存策略(与 D42 冲突,届时必须你确认)**:默认**继续保持不缓存**;若确实要加速,只允许对**带内容哈希的 Vite 产物**加 `max-age=31536000, immutable`,`index.html` 与旧站 `/static/` 仍保持 `no-cache`。**未经你确认不得加任何强缓存**。
- 落实:`frontend-plan.md` §8.1「后续演进」。

### D44 · 2026-09-10 · dev 联调链路与资源路径约定(首页实施中确认)
- **dev 免 CORS**:Vite dev server(`0.0.0.0:5173`、`allowedHosts:true`)把 `/api`、`/media`、`/static` **proxy 到 Django**(`VITE_DJANGO_ORIGIN`,默认 `http://127.0.0.1:8000`)。浏览器视角同源 → **首页阶段无需 CORS 中间件**;`credentials:'same-origin'` 让旧站 session cookie 在同主机下依然生效(导航能显示真实登录态)。
- **base 与路由**:`vite.config.ts` 设 `base:'/app/'`,React Router `basename='/app'`;`index.html` 加 `<base href="/app/" />`,使 `favicon.svg`/`theme-init.js` 等**相对路径**在任意子路由下都解析为 `/app/...`(避免 Vite dev 把绝对路径二次拼接成 `/app/app/...`)。
- **静态资源**:`theme-init.js`、`favicon.svg` 放 `public/`,以相对路径引用(生产构建产物验证为 `/app/theme-init.js`)。
- **性能实测(首屏)**:主包 gzip ≈ 73KB(react 51 + index 10 + query 12),`vis-network` 走 `MiniGraph` 动态 import 独立分包(663KB / gzip 161KB),仅在图谱 Tab/卡片进入视口时加载 —— 满足 D40 预算。
- 落实:`frontend-plan.md` §10 执行进度。

### D45 · 2026-09-10 · 流星(流光)效果实现与层序(边 → 流星 → 节点)
- **背景**:旧站 `vis_flow_fx.js` 依赖**打过补丁的** vis-network(vendored 版内含 `window.__visFlowLayer` 钩子),绘制层序为 `drawEdges → 流星 → drawNodes`;npm 版 **vis-network v10 没有该钩子**。
- **首次实现失误**:退化为 `afterDrawing` 事件绘制 → 流星画在**节点之上**,节点被盖住(用户指出)。
- **v10 渲染序列(源码核对)**:`beforeDrawing`(2989) → `_drawEdges`(3000) → `_drawNodes`(3008) → `afterDrawing`(3034)。
- **结论**:**运行时包装** `renderer._drawNodes` —— 先画流星、再调用原方法,得到与旧站一致的「边 → 流星 → 节点」层序;**不修改 node_modules**;`stop()` 时原样还原,避免影响其它图谱实例;若未来内部结构变化导致包装失败,自动退回 `afterDrawing`(最上层)保证可见。
- **参数保持 1:1**:尾迹 `TRAIL=0.2`、`SEGS=6`、头部光晕 r=6(alpha 0.7)+ 白核 r=2.8、拖拽暂停、缩放暂停 120ms、每 2 帧推进、边数 >150 抽样、页面切后台暂停。
- **颜色**:读 `--fx-dot`,旧站未定义该变量 → 回退 `#38bdf8`,浅/深主题一致(与旧站相同)。
- 落实:`src/lib/meteorFx.ts`;`MiniGraph` 的 `meteor` prop(演示窗口 `phase 0 / speed 0.008`,卡片预览 `phase 0.5 / speed 0.012`)。

## 后续改进登记(新增条目追加到本表)

| 编号 | 日期 | 改进/问题(用户原话摘要) | 结论 | 落实位置 | 状态 |
|---|---|---|---|---|---|
| D11 | 2026-09-09 | CSRF 与 Bearer 边界存在矛盾风险 | 三态策略:合法 Bearer 免 CSRF;无头放行 session+CSRF;Bearer 无效即 401 不回退;加 `API_STRICT_BEARER` 开关(默认关) | `mysite/bearer.py`、contract §7 | 已登记 |
| D12 | 2026-09-09 | localStorage 的 XSS 风险 | 维持 localStorage + 强制 CSP、DOMPurify、7 天 TTL、可撤销;同源部署后再评估 httpOnly | plan 风险章节、contract §7 | 已登记 |
| D13 | 2026-09-09 | `/edit/` 是否已存在且满足语义? | 已存在且满足;补 op 清单、patch 白名单与双层 rev 校验契约 | contract §8 | 已核实 |
| D14 | 2026-09-09 | 分析面板数据来源不明 | 现有 `analysis`/`diagnostics`/`graph/nodes?is_dead\|is_entry` 已覆盖,不新增端点 | contract §9 | 已核实 |
| D15 | 2026-09-09 | 上传需 multipart 与进度 | 新增 `client.upload()`(XHR + onProgress) | `client.ts`、contract §10 | 已登记 |
| D16 | 2026-09-09 | 1000 节点 vis-network 仍会卡 | 默认上限 500、前置过滤、稳定后关物理引擎、超阈值按 dir/cluster 聚合 | plan 性能章节 | 已登记 |
| D17 | 2026-09-09 | 4 种 envelope 长期维护成本 | contract 逐接口登记原始形态;新接口统一 `{ok,data,error}`;旧接口不动 | contract §11 | 已登记 |
| D18 | 2026-09-09 | 计划配色与站点真实样式不符 | 以现站「晨光控制台」为准(浅色默认 + dark 变体),生成器石墨黑作废 | design §2 | 已登记 |
| D19 | 2026-09-09 | 旧 HTML/CSS/JS 太乱想删掉重写 | 不移植旧代码,仅作视觉与交互规格参考,逻辑 React 重写 | design §13 | 已登记 |
| D20 | 2026-09-09 | 样式如何落地 | 新写 tokens.css + components.css,Tailwind 映射变量;不引旧 base.css | plan §2 | 已登记 |
| D21 | 2026-09-09 | 旧资产何时删 | 迁移一个删一个,清单见 design §13,删除前做引用检查 | design §13 | 已登记 |
| D22 | 2026-09-09 | 先做首页 | 首页提为第一个前端交付物;通过后删 index.html 与 index_page.js | design §12 / plan 里程碑 | 已登记 |
| D23 | 2026-09-09 | 首页搜索与登录态数据来源 | `/api/projects/` 前端过滤(无 q 端点);导航用 `/api/auth/me`,游客态链接临时指旧站 | design §12 | 已登记 |
| D24 | 2026-09-09 | 旧样式要有备份,写错可对照 | 先归档到 `docs/legacy-style/`(只读)再改;归档未完成禁止删改旧文件 | design §13 / plan 里程碑 0 | 已登记 |
| D25 | 2026-09-10 | 部署拓扑误判(以为 nginx 发静态) | 实测:nginx 纯反代 → daphne:8000 → Django,静态也走 Django;仓库外才有 nginx 配置 | plan 部署章节 | 已核实 |
| D26 | 2026-09-10 | 部署先不定,首页做完再定 | 首页阶段 Vite dev + CORS 联调,不动 nginx/线上;托管三方案 A(推荐)/B/C,一律挂 /app/ 前缀 | plan 里程碑 | 已登记 |
| D27 | 2026-09-10 | fallback 可能吞掉旧路由 | SPA 挂 /app/ 前缀,fallback 只匹配 ^app/;旧路由显式匹配不做 fallback | plan §8.1 | 已登记 |
| D28 | 2026-09-10 | uid 含 # / / 走路径不可靠 | SPA 用 `?uid=`;API 侧 # 编 %23、/ 保字面,实施时做真实 uid 断言 | plan 里程碑 8 | 已登记 |
| D29 | 2026-09-10 | 只限节点未限边,画布会卡 | 节点 ≤500 且边 ≤2000,超边进简化模式(用 summary 已有 counts) | plan 里程碑 7 | 已登记 |
| D30 | 2026-09-10 | localStorage token 被 XSS 窃取 | v1 依赖锁定+npm audit CI+登出全部设备;v2 同域后迁 HttpOnly cookie | plan 风险章节 | 已登记 |
| D31 | 2026-09-10 | envelope 归一靠猜易误判 | `endpoints.ts` 每端点显式声明 kind + 边界规则 + 单测 | plan 里程碑 2 | 已登记 |
| D32 | 2026-09-10 | 归档漏 JS、无校验 | 归档扩展到 JS + SHA-256 MANIFEST + 校验脚本 | design §13 / 里程碑 0 | 已登记 |
| D33 | 2026-09-10 | 迁移期导航断裂 | `LEGACY_FALLBACK` 映射,未完成路由跳旧站;首页 CTA 暂指旧站 | plan 里程碑 3 | 已登记 |
| D34 | 2026-09-10 | 移动无限滚动需分页 | `graph/nodes` 已支持 limit/offset/total → useInfiniteQuery | plan 里程碑 7 | 已核实 |
| D35 | 2026-09-10 | 刷新丢失视口与选中 | 重取前存 scale/position/选中,更新后静默恢复 | plan 里程碑 7 | 已登记 |
| D36 | 2026-09-10 | 主题状态与旧站如何同步 | localStorage["theme"]=light\|dark 写 `<html data-theme>`,与旧站完全一致 | design §2 | 已核实 |
| D37 | 2026-09-10 | 动态表单复杂度被低估 | 拆 3 子任务 + 自研轻量渲染器(6 类字段),不引 RJSF | plan 里程碑 8 | 已登记 |
| D38 | 2026-09-10 | a11y 缺焦点管理/画布替代 | Modal/Drawer 焦点陷阱与恢复+Esc;图谱提供键盘可达列表视图 | ui 组件 / 里程碑 7 | 已登记 |
| D39 | 2026-09-10 | 完全没有测试策略 | Vitest + Playwright E2E + 视觉回归(浅深×断点),落在 frontend/tests | plan §8.2 | 已登记 |
| D40 | 2026-09-10 | 无性能预算与代码分割 | 主 bundle gzip ≤200KB;vis-network 动态 import + lazy;manualChunks | plan 里程碑 2 | 已登记 |
| D41 | 2026-09-10 | share 与登录态优先级不明 | 后端 can_view 是并集;share 作补充参数透传不覆盖登录态,仅特定场景提示 | plan 里程碑 7 | 已核实 |
| D42 | 2026-09-10 | 静态不缓存是刻意设计 | 禁止给 /static/ 加强缓存;SPA index.html 必须 no-store/no-cache;哈希资源本阶段同样不缓存 | plan §8.1 | 已登记 |
| D43 | 2026-09-10 | 稳定后改生产级静态部署(防遗忘) | ⏳ 待办:主链迁完+不再频繁改+你确认后,切 nginx 直发静态(collectstatic + alias + try_files),8 步清单与回退方案已写好;缓存仍需你确认 | plan §8.1 | 待办 |
| D44 | 2026-09-10 | dev 联调链路与资源路径 | dev 用 Vite proxy 免 CORS;base=/app/ + `<base href="/app/">`;public 资源用相对路径;vis-network 动态分包(主包 gzip 73KB) | plan §10 | 已实施 |
| D45 | 2026-09-10 | 流星层序(节点被盖住) | 运行时包装 `renderer._drawNodes`,先画流星再画节点 → 「边→流星→节点」;不改 node_modules,stop() 还原;参数与旧站 1:1 | `src/lib/meteorFx.ts` | 已实施 |
| D46 | 2026-09-10 | 工作区/项目主页是否强制登录 | 旧站 `/projects/`、`/project/<key>/` 对游客开放(只见公开),SPA 这两条路由**不套 RequireAuth**(与 plan §1「除 /login 外全包」不同);写操作按 `me.authenticated && (mine‖staff‖coadmin)` 页面内门控,后端仍二次校验。RequireAuth 保留给纯写路由 | `src/App.tsx`、`pages/Workspace.tsx`、`pages/ProjectHome.tsx` | 已实施 |
| D47 | 2026-09-10 | 图谱页体积与分包 | 图谱页走 `React.lazy` 路由级懒加载,vis-network(≈160KB gzip)独立 chunk;主包 gzip 36KB、GraphPage 8.9KB。小屏默认不初始化画布(列表形态),点「进入画布」才建 | `src/App.tsx`、`pages/GraphPage.tsx` | 已实施 |
| D48 | 2026-09-10 | 本机无 v3.14 真实图数据 | 库内 6 个项目全是旧管线产物(`CodeNode/CodeEdge` 为空、`parse_epoch=0`、`graph_rev=0`、无 Job),图谱/详情/搜索/分析只能以合成数据验收;已留档仓库内冒烟脚本(`29 项全通过` + 自动清理,含 `graph_rev/parse_langs` 还原) | `frontend/scripts/smoke_graph_api.py` | 已实施 |
| D49 | 2026-09-10 | 迁移期降级路由收敛 | 已迁入 SPA 的路由不再回退旧站:`/workspace`、`/p/:key`、`/p/:key/graph`、`/p/:key/node|search|analysis` 全部从 `legacy.ts` 移除(仅保留 `/login`、`/register` 旧站跳转);首页入口卡改指 `/app/workspace` | `src/legacy.ts` | 已实施 |
| D50 | 2026-09-10 | SPA 托管落地(方案 A) | 新增 `mysite/spa.py::spa_app` + `mysite/urls.py` 的 `^app(?:/…)?$`:命中 dist 真实文件走 `static.serve`(协商缓存),其余回 `index.html` 并**显式 no-store**;不改 nginx、不动 `/`。实测 `/app/`=200(no-store)、`/app/workspace`=200(前端路由回退)、`/app/assets/index-*.js`=200(Last-Modified,无 max-age)、`/`=200 旧首页不受影响 | `mysite/spa.py`、`mysite/urls.py` | 已实施 |
| D51 | 2026-09-10 | 用户上传的头像把导航撑爆 | 根因:SPA 复用了旧站 `core/nav.html` 的 class 名,但对应的 `<style>` 没搬过来 —— `.nav-avatar / .nav-user / .nav-role / .nav-badge / .nav-msg / .nav-btn.logout` 在 `components.css` 里**全部缺失**,于是 `<img class="nav-avatar">` 按原始分辨率渲染(2MB 内的大图直接把 54px 导航撑到半屏)。修复:按旧站数值 1:1 补齐整组导航样式(头像 24px 圆 + `object-fit:cover` + `flex:none` 锁死尺寸、用户胶囊 32px、角色胶囊、未读角标绝对定位、logout 红色、`svg.lucide` 15px、`:active` 缩放、≤640px 隐藏角色胶囊) | `src/styles/components.css`、`src/components/TopNav.tsx`(用户名加 `nav-username`) | 已实施 |
| D52 | 2026-09-10 | 头像文件本身是否要压缩 | ✅ 已实施(**原话:不能上传太大的头像或者一些恶意数据,能压缩头像、不影响展示效果就压缩**)。新增 `accounts/avatar.py::normalize_avatar` 单一入口:①`verify()` 结构校验;②**解码前**查单边 ≤10000px、总像素 ≤2500 万(防解压炸弹);③`exif_transpose` 摆正手机竖拍方向并**顺带丢弃 EXIF/GPS**;④压到 ≤**320px**(覆盖 88px 展示位的 3.6 倍图),含透明通道存 PNG、否则存 JPEG(q85);⑤动图只取**首帧**(小圆展示位用不到动画,且动图是最大体积来源)。上传视图改为「2MB 粗筛 → 归一化 → 落盘」,扩展名以压缩结果为准,响应追加 `bytes/source_bytes/source_size/size` 便于排查。历史数据:`manage.py compress_avatars [--apply]`(默认预览)批量压老文件,扩展名变化时同步更新 `UserProfile.avatar` | `accounts/avatar.py`(新)、`accounts/views/profile.py`、`accounts/management/commands/compress_avatars.py`(新) | 已实施 |
| D53 | 2026-09-10 | 动图头像的处理口径 | 上传/批处理一律**只保留首帧**(记录在 D52 实现里,先按「不影响展示效果」处理);若你后续要求保留动画,再改成逐帧缩放 + 帧数上限 | `accounts/avatar.py` | 已实施(可复议) |
| D55 | 2026-09-10 | 工作区卡片丢了旧站功能 | ✅ 已实施(**原话:项目工作区里的项目怎么没有删除按钮了?你看看以前的设计呢?有的功能要同样加上**)。查旧站 `assets/static/js/analysis_page.js` 的项目面板,owner 操作集有 7 项,SPA 卡片此前只有「进入项目 / 上传源码」。已按原样补齐:**编辑项目**(新 `ProjectEditModal`,PUT 局部更新 name/desc/category/icon)、**设为公开 / 取消公开**(PUT is_public)、**重新解析**(POST reparse)、**删除项目**(DELETE,红色)、**复制到我的工作区**(POST copy,他人公开项目);按钮只在「本人 + 已登录」时渲染(复制给登录用户看他人公开项目),后端仍二次校验。确认弹窗文案沿用旧站(公开/取消公开的后果说明、重新解析会覆盖图数据、删除时逐条列出将被删除的内容);新增通用 `ui/ConfirmDialog` 与 `.icon-btn` 样式 | `src/components/{ProjectCard,ProjectEditModal}.tsx`、`src/components/ui/ConfirmDialog.tsx`、`src/query/projects.ts`、`src/pages/Workspace.tsx`、`src/styles/components.css` | 已实施 |
| D56 | 2026-09-10 | ⚠ 本机没有作业 worker | 实测发现:`manage.py graphworker` **未在任何服务/容器里运行**(只有 `webapp.service`=daphne 与一个用户代码容器),而 `AppSetting.job_max_per_user=1`。后果:上传源码 / 重新解析 / 复制到工作区投递的作业**只会排队不执行**,项目会一直停在「解析中」;并且同一用户的第一个排队作业长期占满并发名额,导致该用户后续作业直接 `503 系统繁忙`(冒烟脚本因此拆成两个临时用户)。**待你决定**:是否常驻 graphworker(单机可 `--shards=all`),以及用 systemd 单元还是 nohup/tmux 守护 | 运维(D55 的复制/重解析按钮依赖它) | 待办 |
| D54 | 2026-09-10 | 非首页要有「返回 / 首页」入口 | 原话:除首页外,每个页面顶部左右两边分别放返回与首页按钮。实现放**全局顶栏**(而非各页各写一份):`isHome = pathname === '/'` 时整组不渲染,左端 `返回`(react-router `location.key === "default"` 判定无站内历史时回退到首页,避免点了没反应)→ `navigate(-1)`;右端 `首页` → `navigate('/')`;`≤640px` 只留图标(隐藏文案)以防 375px 下与头像胶囊挤爆导航;顶栏高度不变,图谱页的 `calc(100vh - 54px)` 不受影响 | `src/components/TopNav.tsx`、`src/styles/components.css` | 已实施 |

| D57 | 2026-09-10 | 作业消费者常驻 + 部署工件仓库化 | ✅ 已实施(用户确认「要,先拿现场数据」)。新增仓库内 `deploy/systemd/`:`webapp-graphworker.service`(单机 `--shards=all`、`Restart=always`、`MemoryMax=〈按实测内存设定〉` cgroup 兜底)、`webapp-graphworker@.service`(模板多实例,`/etc/default/webapp-graphworker-%i` 传 `SHARDS`),并把此前只存在于机器上的 `webapp.service`、`webapp-cleanup.{service,timer}`、`webapp-iptables.service` 一并纳入仓库(**此前仓库内 `.service` 文件数 = 0**,`reports/00-总检查报告-2026-08-19.md` 记过同类漏部署);`deploy/README.md` 写清安装步骤、并发路数选择、重启会打断作业、改分片空间前必须排空队列。同时把 `job_child_memory_mb` 由 2048 校准为 **1024**(★ 按当时实测的可用内存下调)。实测:worker 上线后自动消费队列,23 个作业中 22 done / 1 failed | `deploy/`、`deploy/systemd/*`、`deploy/README.md`、`core.AppSetting.job_child_memory_mb` | 已实施 |
| D58 | 2026-09-10 | ⚠ 子进程 fork 后 `close_all()` 会打断 worker 自己的数据库连接 | ★**根因级缺陷,已修**:`projects/jobs/child.py` 原先在子进程入口调用 Django 的 `connections.close_all()`。该方法经 pymysql 会向 socket 发送**明文 `COM_QUIT`**,而这个 socket 是从 worker 父进程**继承来的同一个 TLS 会话** → 明文写进 TLS 记录流,服务端回 `SSLV3_ALERT_BAD_RECORD_MAC`,父进程此后每次查询都 `pymysql.InterfaceError: (0,'')`,**直到重启为止**(表面现象:worker `active` 但永远领不到作业)。A/B 实验 `scripts/debug_worker_db.py` 复现并验证:子进程 `close_all()` → 父进程 `Lost connection to MySQL server during query`;改为「`socket.detach()` + `os.close(fd)` 只关子进程 fd 副本、一个字节不发」→ 父进程连接完好。修复:`child.discard_inherited_connections()`,worker 主循环异常时也用它自愈(`worker.py` 同时在每轮开头 `close_old_connections()`) | `projects/jobs/child.py`、`projects/jobs/worker.py`、`scripts/debug_worker_db.py` | 已实施 |
| D59 | 2026-09-10 | 作业处理器「首次真实运行」暴露的缺陷 | ★先跑真实作业的价值验证:worker 刚跑通就抓到 `projects/jobs/ops.py::_cleanup_backups` 的 `for pid, in ...values_list("pk", flat=True)` —— `flat=True` 产出的是 int,`for pid,` 解包直接 `TypeError: cannot unpack non-iterable int object`,导致 `cleanup:backups` 作业失败(修复后手动投递该作业 → `done / backups 完成,处理 0 项`)。结论:这批处理器代码此前**从未被真实执行过**,凡是依赖「没人跑过」的路径都应在本次重构里逐条跑通再改设计 | `projects/jobs/ops.py` | 已实施 |

| D60 | 2026-09-11 | ⚠ 后端 v3.33·v19 的对外契约从未登记到前端 | **缺口已核实**:8 份后端分册已定稿「主文 v3.33 · 评审稿 v19」,但 `frontend-contract.md` 停在 **v3.14(核对日期 2026-09-09)**,对 v17–v19 的契约变更 **0 命中**(`429`/`rate_limited`/`Retry-After`/`writer_token`/`derived_stale`/`X-Contract-Version`/`contract_incompatible`/`cursor` 逐个 grep 全为 0)。而主文 §7 自己规定「新开/弃用时间表**逐版本记进 `frontend-contract.md`**」→ 规矩在、从未执行。**处置**:新增 §14–§19 登记「**v3.33 目标契约(未实现)**」;既有 §1–§13 **保留 2026-09-09 实测结论原文、只加"⤴ 目标变更见 §NN"指针**;**不把目标写成完成态**(本文件是 api client 归一与 TS 类型的唯一依据,谎报会让前端按未实现契约编码) | `docs/frontend-contract.md`(头部 + §14–§19) | 已登记(未实施) |
| D61 | 2026-09-11 | ★限流被包成 401(现状缺陷,已核实为真) | 现状:`accounts/views/auth.py:61` 的 `login_validate` 返回的是**中文文案**(见 `:72` `return None, f"尝试过于频繁,请 {wait} 秒后再试"`),`authapi/views.py:54-57` 把该文案**无差别包成 `401 login_failed`** → 「密码错 / 被限流 / 账号锁定 / 弱密码 / 待审」5 类原因前端**无法区分**。目标(主文 §8.1 + 附录 B11):统一 **`429` + 响应头 `Retry-After`(秒) + `{ok:false,error:{code:"rate_limited"}}`**;**禁止**把限流包成 401;**锁定 / 弱密码改为"不在响应中返回"**(仅登录后或邮件提示,防账号枚举)。前端义务:按 `Retry-After` 自动退避 + 倒计时;**同步上传遇 429 不丢数据**(进本地 outbox 排队,不退化为失败)。代码侧改造(`login_validate` 改为返回 `(user, error_code, detail)`)按设计**待评审通过后另起一轮** | `docs/frontend-contract.md` §15 + §1/§12 指针 | 已登记(文档;代码未改) |
| D62 | 2026-09-11 | 前端合约协商机制(新增,前端必须实现) | 请求带 **`X-Contract-Version`**;服务端三态:①支持 → 正常 ②**宽限期内降级可用、不拒绝服务** —— 缺失字段在 JSON 里**不出现该 key(不是显式 `null`)**,降级信息走响应头 **`X-Contract-Degraded: field1,field2`**(无降级则该头不出现)→ 前端收到该头需提示"部分功能可能不可用,建议刷新" ③超宽限期 → **`409 contract_incompatible`**(**弃用 426**:语义错误 + "刷新仍是旧代码"死锁)→ 提示"应用已更新,请关闭标签页重新打开" + 请求 **`GET /api/version`**。**前置依赖**:静态资源必须版本化(`index.html` 不长缓存、资源名带 hash),否则"刷新"无效;⚠ **旧前端不认识该码会白屏** → 必须有**静态引导页兜底**,不得依赖旧前端自身处理 | `docs/frontend-contract.md` §16 | 已登记(未实施) |
| D63 | 2026-09-11 | 写路径新端点:`/graph/sync/` 与 `/hash-migration/` | ①**`POST /api/projects/<key>/graph/sync/`**(复用既有路由,不新开):请求体 `project_id` / `base_graph_rev` / `writer_token` / `writer_epoch` / `lease_seq` / `files[]{path,sha1,file_rev,state}` / `upserts{nodes,edges}` / `deletes{nodes,edges}` / `analysis`;其中 **`lifecycle` 常规期即必填**(节点 `active\|hidden`、边 `active\|deleted`;`deleted` 走软删除不进 `upserts`),**常规期禁含 `migration` / `old_vid*` / `new_vid*`**(JSON Schema `additionalProperties:false`,违者 `400` —— 否则客户端拼错字段名会被静默吞掉),迁移期反之(**缺 `migration` → `409 migration_required`**);传输 **CBOR + gzip**、按 **1 万节点/片**分片、失败可重放。②**新增 `POST` / `DELETE /api/projects/<key>/hash-migration/`**(发起 / 取消,仅 owner,协作者与 share 一律 403/404);**进度不另立端点** —— 由元数据 `GET /api/projects/<key>/` 返回 `migration{total,applied,last_client_activity_at}`,前端**轮询**(不引 SSE)。③本批新增状态码:`409 stale_baseline` / `no_write_lease` / `stale_writer` / `outbox_not_drained(_24h)` / `migrating_full_resync_required` / `hash_algo_unsupported` / `migration_in_progress` / `project_deleting` | `docs/frontend-contract.md` §17 | 已登记(未实施) |
| D64 | 2026-09-11 | 读路径新契约:分片改用 `cursor`,`analysis` 增 `derived_stale` | ①**`graph/edges/` 与跳数查询**:目标为 **`limit` 必填 + 服务端强制夹取**(起步上限 **2000**,超出按上限返回**不报错**)+ **不透明 `cursor`**(客户端**不得**解析成 offset;服务端不用深分页 offset)+ 响应 `{items, next_cursor(null=无更多), summary{node_count,edge_count,by_type}}`,多跳默认**只返回子图摘要**、`summary_only` 按需展开。②**`analysis/`**:`CodeAnalysisDerived.based_on_graph_rev == graph_rev` → 不带 `derived_stale`;否则带 **`derived_stale: true`**,前端显示"派生指标待更新"但**照常展示**,**读路径永不阻塞等待派生**;`analysis/`/`diagnostics/` 出口**读取时合并两表**,响应结构不变(前端零改动)。③⚠ **两条线并列登记,不覆盖**:现状 `limit`(默认 500、钳 1~5000)+ `offset` + `total`(2026-09-10 已冒烟验收),目标是 `limit + cursor` | `docs/frontend-contract.md` §18 + §6/§9 指针 | 已登记(未实施) |
| D65 | 2026-09-11 | ★两条「设备身份线」必须分家(命名禁止混用) | 后端 v17 已把写权身份**改名** `device_id → writer_token`,与本仓库既有的限流 Cookie `dev_id`(`core/device_id.py`)**撞名且语义相反**:`dev_id` = 限流二级维度(**HttpOnly Cookie、不可信、永不落库**、清 Cookie 即换、非法值退化为 `ip\|none`);`writer_token` = 写权身份(**服务端签发、必落库 `DeviceSession`、绑会话**、客户端**不得自选**)。**禁止事项(硬约束)**:①禁止把 Cookie 里的 `dev_id` 填进请求体的 `writer_token`(**会直接摧毁 A3.1 防冒充前提:清 Cookie 就能换写权身份、绕过租约接管与 `writer_epoch` 递增规则**)②禁止把 `writer_token` 用作限流键维度 ③禁止把 `dev_id` 写进 `DeviceSession` / `ProjectSyncState` 主键。前端 TS 类型、字段名、日志**三处逐字一致** | `docs/frontend-contract.md` §15/§17(后端依据:附录 A3.2) | 已登记(未实施) |
| D66 | 2026-09-11 | 客户端新增义务与 UI 文案(易漏项,统一登记) | ①**本地 store 按 `user_id + project_id` 命名空间**;删项目 / 登出**必须清本地**(含 `parse_cache`)——服务端**无法远程删本地**,删除/导出页必须提示"请在浏览器端清理" ②**软删除按 `lifecycle` 过滤**,**不得依赖 `dangling`**(`dangling` 只是边属性,不是删除标记) ③`graph_sync_status` 项目卡片文案:无租约只读要打 **`stale` 徽章** + 显示"最后同步时间 + 与服务端 `graph_rev` 差距",**超 7 天**未同步 → 强制提示重新拉取(不得静默展示过期图);`pending_repair` → "待修复(等本设备上线重传)";`migrating` → "迁移中不可编辑";`deleting` → 一切写操作被拒 ④解析图必须标注来源与置信度档(**本地/语法级** vs **服务端/语义级**),避免用户误信 ⑤**错误上报默认只带项目 key + 匿名标识,不带 `uid`/`file_path` 明文**(附录 B10) ⑥`uid` 字符集白名单与长度上限(`[A-Za-z0-9_:.\-#@/]`、≤1024)、`file_path` ≤4096 等**客户端本地先截断**,别等服务端拒(附录 B9.1) | `docs/frontend-contract.md` §19 | 已登记(未实施) |
| D67 | 2026-09-11 | 后端追加「`Project.key` 规范」,前端可见面同步登记(不动前端代码) | 后端新增主文 **§4.4**(依据 `B64`;用户原话"补一节 Project.key 规范",并强调"key 是项目唯一标识、让项目名与路径不耦合"、"项目名用户自取可能相同,靠 key 区分")。**前端受影响面(全部是"知情"而非"改造")**:①**key = URL 路径参数**:`frontend/src/query/*.ts` **统一用 `encodeURIComponent(key)`**(20+ 处,如 `projects.ts:54,66`、`graph.ts:18,69,100`、`edit.ts:32,37`、`search.ts:22`、`analysis.ts:14,27`、`nodes.ts:20,36`)→ **字符集收紧对前端零影响**,现有写法已安全;②**目标字符集** `^proj_[0-9a-f]{32}$`(新项目 37 字符、**128 bit 熵、不再嵌用户名**;现状 `proj_<用户名>_<8hex>` 仅 32 bit)→ 前端**不得从 key 解析用户名/归属**(**硬约束:key 不得作为授权凭证**,也不得用于反推归属);③**删除后语义**:项目删除后旧 key 一律 **404**,前端按"项目不存在"处理、**不重试**;④**旧 key 宽放行**:历史 key(若有)继续可用,前端**不得**因形态不同做分支;⑤**目录命名规则(`<项目名>_<key 后 8 位>`)与改名联动属服务端内部实现,不进前端契约** —— 前端只消费 key;⑥key 是**不可变**的:前端不得缓存"key→名称"的长期映射假设改名会换 key。**本轮不涉及任何前端代码改动**(仅文档) | `docs/backend-design.md` §4.4、`docs/frontend-contract.md`(1 行指针) | 已登记(未实施) |
| D68 | 2026-09-11 | 后端 v20 自洽性专项:前端可见面同步(仅两处) | 本轮后端只做**自洽性对齐**(10 P0 + 13 P1 + F3 拆分,依据 `backend-decisions.md` **B65**;**评审轮次 v19 → v20**)。前端受影响面**只有两处**:①**"缺失"分两种(v20 P0-7)**:**契约降级 → 该字段在 JSON 里不存在该 key**(前端按"功能不可用"处理,配合 §16 的 `X-Contract-Degraded`);**业务空值**(派生未算 / 无数据)→ **显式 `null`(标量)或空数组(集合)**(前端显示"暂无(需语义级解析)",**不得显示 0**);**判定规则**:`key` 不存在 = 契约降级;`key` 存在但值为 `null`/空数组 = 业务空值 —— **两者不得混用**。已落 `frontend-contract.md` §18.2。②**key 示例形态**:主文 §5.4 示例的 `project_id` 占位改为 **`proj_<32位小写hex>`**,并标注端点 `<key>` 必须匹配 **`^proj_[0-9a-f]{32}$`**(旧 key 按 §4.4.4 ① 宽放行)→ 前端现有 `encodeURIComponent(key)` 写法**不受影响**,**不需要新增校验**。**其余 10 P0 均为服务端内部 / 运维面**(Redis 独立实例、限流 AOF + IP 桶落库、outbox 删项目清空、审计匿名化、迁移探测算法、多标签页 `page_seq` 仲裁)**对前端契约无新增要求**;**本轮不涉及任何前端代码改动** | `docs/frontend-contract.md` §18.2、`docs/backend-design.md` §5.4 | 已登记(未实施) |
| D69 | 2026-09-12 | 后端 v21 落地可行性核查:前端可见面(导入长 key 拒绝 + 404 语义不变) | 本轮后端为**落地可行性核查**(5 P0 + 10 P1 + 6 P2,依据 `backend-decisions.md` **B67**;**评审轮次 v20 → v21**),**前端可见面只有两处**:①**导入 / 外部同步路径对 >48 字符的 key 显式拒绝 + 可读错误**(P0-1):后端定稿"列约束 48 + 导入路径拒绝";⚠ **实测 `.webapkg` 导入在代码中尚未实现** → **当前前端无任何改动**,仅登记"将来若有导入入口,前端必须能展示该可读错误"(错误形态建议与既有 `400` + 中文文案一致)②**404 语义收窄(P0-2,前端利好)**:后端把 URL 层校验降为"基本形态约束"、严格形态校验放视图层**仅作分支判定** → **404 只表示"项目不存在 / 无权"**,**不再表示"key 形态不符"** → 前端**不需要新增任何形态校验**,`encodeURIComponent(key)` 写法不变,**旧 key 继续可访问**。**其余 P0/P1/P2 均为服务端内部或运维面**(DB 列长、视图层分层、G1.1 登记、回滚窗口 24h、关闭 AOF、匿名化 `[:16]`、F1/F2 指标、`page_seq` 登记、F3 检查器构建)**对前端契约无新增要求**;**本轮不涉及任何前端代码改动** | `docs/frontend-contract.md`(导入错误语义 + 404 一句)、`docs/backend-design.md` §4.4.3(b) | 已登记(未实施) |
| D70 | 2026-09-12 | 后端 v22 交叉一致性核查:**本轮无前端可见变更**(知情登记) | 本轮后端为**交叉一致性核查**(5 P0 + 13 P1 + 4 P2,依据 `backend-decisions.md` **B69**;**评审轮次 v21 → v22**),**逐项核对后确认对前端零新增要求**,故**只登记不产生契约改动**:①`§5.4` 的 key 形态约束改为与 §4.4.3(b) 逐字一致 —— **前端语义不变**(旧 key 仍可访问、404 仍只表示"不存在 / 无权",v21 的 D69 已登记)②`AuditSecurityDetail` 补进 §4.1、位宽统一 `[:16]`、`page_seq` 序列实现、`AuthRateCounter` 兜底表、F1/F2/F3 各项 —— **均为服务端内部 / 运维面**,前端不感知③`parse_cache` 埋点补隐私边界(**仅同一 `user_id` 内跨项目、只上报聚合数值**)—— **对前端有利**(明确了"不上报 chunk 内容与项目标识"),但**当前无埋点实现**,前端**本阶段不需要改动**。**结论**:**前端代码零改动**;若将来实现"导入入口"或"`parse_cache` 埋点",再按 D69 与本条口径落地 | `docs/backend-design.md` §4.4 / §4.1、`docs/backend-decisions.md` **B69** | 已登记(无前端改动) |
| D71 | 2026-09-12 | 后端 v25 收口:**请求体字段改名 `project_id` → `project_key`** + `files[]` 只传 `base_file_rev`(前端可见) | 依据 `backend-decisions.md` **B75/B76**(评审轮次 **v24 → v25**;v23/v24 两轮**无前端可见变更**,故未单独登记)。**前端可见变更两处**:①**请求体顶层字段 `project_id` → `project_key`**(值 = `Project.key`,与 URL `<key>` 同源;⚠ **数字 `project_id` 由服务端元数据下发,仅用于算 VID** —— 用 key 代入会让**两端 VID 不同 → 图分裂**,详见 `frontend-contract.md` §17.1 末注);②**`files[]` 只传 `base_file_rev`**(服务端分配的 `file_rev` **只在响应回传**,不再出现在请求体)。**改名映射**见 `backend-observability-dr.md` **F3 7.4**;**本轮不改任何前端代码**(`frontend/**` 未动、`dist` 未重建) | `frontend-contract.md`(§17.1 + 字段表)、本表 | 已登记(待实施) |
| D72 | 2026-09-13 | **后端 v27 减法重构:前端契约**净减法**(删降级协商 / 删迁移期契约 / 分片与派生后置 / fencing 归一)** | 依据 `backend-decisions.md` **B79/B80**、`backend-implementation-gates.md` **E27**(评审轮次 **v26 → v27**)。**前端可见变更(全部是"删",无新增要求)**:①**删契约降级协商**:`X-Contract-Degraded` / 宽限期降级 / "缺失字段不出现该 key"的降级语义 / 引导页兜底**全部移除** → 只保留 **`X-Contract-Version`**;**不支持 → `409 contract_incompatible` + 提示「应用已更新,请关闭标签页重新打开」**;静态资源版本化即兜底;②**删迁移期契约**:§17.2 迁移期请求体(`hash_algo` / `migration` / `old_vid*` / `new_vid*`)、**`/hash-migration/` 端点**、迁移相关状态码(`outbox_not_drained(_24h)` / `migrating_full_resync_required` / `hash_algo_unsupported` / `migration_in_progress`)**整段删除** → 前端**不需要实现任何迁移上传**;③**分片 / `cursor` 后置**:原 §18.1(`limit` + `cursor` / `summary_only` / 深度展开)整体后置,**一期只做 `limit` 强制夹取(起步 2000)**;④**`derived_stale` 后置**:一期**不返回**该字段(前端不得依赖);⑤**fencing 归一**:请求体 **`writer_epoch` + `lease_seq` 两个字段 → 单一 `lease_epoch`**(所有写请求都带它;服务端按 `lease_epoch < $new` CAS);⑥**`graph_rev` 发号**:由全局序列改为 **`Project.next_graph_rev`(每项目)**(前端只需知道"**单调、允许空洞**");⑦**本地模型同步**:`local_project` 删 `writer_lease_until`/`writer_epoch`/`lease_seq` → 改 `lease_epoch`;**`parse_cache` 降为文件级 AST 缓存**(key = **`file_sha256 + parser_v`**,不再有 `hash_algo`/`chunk_hash`);⑧**服务端内部删除(前端无感)**:`AuditSecurityDetail` / `AuthRateCounter` / `PageSequence` / `PageAssignment` / `ProjectDeletion` / `graph_migration_log`;⑨**两处明确承认的安全回归**(不影响前端契约,但影响运维口径):Redis 与进程同时重启窗口内认证限流只剩本地内存 + 账号锁定;审计退回单表(放弃 B7 高保真通道)。**本轮不改任何前端代码**(`frontend/**` 未动、`dist` 未重建) | `docs/frontend-contract.md`(§14 变更表 / §16 / §17 / §18 / §19)、`docs/backend-decisions.md` **B79/B80** | 已登记(待实施) |

| D73 | 2026-09-16 | **前端新增「读懂体验」与发布审批契约(用户裁定:读懂陌生开源项目为产品第一定位)** | ①**契约新增 §20**(原 §20 顺延为 §21):锚点 / 解释 / 提问 / **采纳** / 阅读路径(含 **fork** 与 **生成初稿**)/ 进度 / **解释密度热力图** / **embed**(强制带 `license` / `author` / `source_repo` / `commit`)/ **发布审批**(`declare_rights: true` 必填、`publish/status` 五态 `local \| pending_review \| public \| rejected \| taken_down`、`/api/report/`);②**硬约束**:正文**禁止内嵌大段源码(> 20 行拒绝)**、`needs_review` 锚必须打「可能已过时」、**`why_now` 必填**、`source=ai_draft` 必须可见、**私有项目一律 404**、embed 不得隐藏许可四项;③**设计文档**:路由 `:key → :ref`、新增 **§4.8 导读页 `/p/:ref/read`(进入项目的主入口)** 与 **§4.9 会话态与合规引导**、登录标语与首页特性条改为「读懂」口径、实现顺序补第 8 步;④**前端义务**:`pending_review` / `rejected` / `taken_down` 必须可见、`local` 项目**隐藏 `is_public` 开关**、UGC 入口只在公开项目渲染、会话态引导三选一、**客户端等待名单** | `frontend-contract.md` · `frontend-design.md` · `frontend-decisions.md` | 已完成(纯文档) |
| D74 | 2026-09-17 | **写入通道分层:UGC 全开放 + 写者租约作用域收窄(用户提出:写租约限制太强;markdown 文档应人人可加解释与提问,只有创建者 / 管理员才能删)** | 依据 `backend-decisions.md` **B102**、主文 **§2.3.11**(新增)· §5.3 · §8 · §6.0(a4)。**前端可见变更**:①**§20.1 新增「写入权限与并发」矩阵**:`anchors` / `annotations` / `reading-paths` / `read-progress` / 删除 / `graph/sync`·`edit/` 逐条列出「**谁可写 + 并发控制**」;②**§20.2 硬约束补 6 条**:**UGC 写权不依赖 `can_edit`**(**不得**因「非协作者」隐藏写入口)、**编辑必须回传 `rev`**(收到 `409 stale_rev` → 提示「**已被他人修改,请刷新后合并**」,**不得静默重试覆盖**)、**不得原地编辑他人内容**(改为**并列新增** / 「提议修订」)、**删除按钮仅对作者本人 / 项目 owner / `is_staff` 渲染**(软删除 + 可申诉)、**游客只读**(未登录**不渲染任何写入口**,写请求 → `401`)、**UGC 限流可读**(`429` + `Retry-After`,§15 统一口径);③★**硬约束**:**UGC 端点不得接入 `lease_epoch` 校验** —— 「别人正在改图」**不构成**写解释 / 提问的阻塞条件;租约**只覆盖图与源码通道**(§2.3.11 通道①);④**写权口径修订**:笔记 / 解释 / 提问的写权由「owner / 协作者」改为「**任何登录用户且 `can_view`**」;**删除** = **作者本人 / 项目 owner / 网站管理员**;阅读路径 = 任何人可建 + 可 fork,编辑仅限本人。**本轮不改任何前端代码**(`frontend/**` 未动、`dist` 未重建) | `docs/frontend-contract.md`(§20.1 附 · §20.2)、`docs/backend-decisions.md` **B102**、主文 §2.3.11 | 已登记(待实施) |
| D75 | 2026-09-17 | **图不可变:前端写路径契约与同步状态大幅简化(用户裁定:上传解析后源码与图不可改;仅维护者可修补;由用户全权负责)** | 依据 `backend-decisions.md` **B103**、主文 **§2.3.12 / §2.3.13**。**前端可见变更(全部是「删」,净减法)**:①**§17.1 请求体**:删 `base_graph_rev` / `writer_token` / `lease_epoch` / `files[].base_file_rev` / `files[].state`,改为 **`snapshot{repo,commit,parser_v,snapshot_hash}`** + `files[{path,sha1}]`(主文 §5.4 为唯一权威);②**§15.7 整节删除**(「两条设备身份线」—— `writer_token` / `DeviceSession` 已不存在,**只剩 `dev_id` 一条限流线**);③**§17.6**:删「无租约的只读设备 / `stale` 徽章 / 落后 7 天强制重拉」(快照内容**永不陈旧**);④**§17.8**:`sync-state` 由 **5 态收敛为 2 态**(`not_published \| in_sync`);**删 `/resolve/` 冲突决策端点**与 **`diverged` 弹窗**;⑤**§19.1 本地模型**:`local_project` 删 `files_vector` / `base_graph_rev` / `writer_token` / `lease_epoch` → 改 `snapshot{...}` + `files[{path,sha1}]`;**删 `local_pending` 模型**;⑥**§20.1 写权矩阵**:**图通道无租约**;`graph/sync` = **服务端解析作业唯一写入**;`edit/` 限**项目维护者**(图修补,**LWW + 全量审计**);⑦**§1 现状表**:`edit/` 行标注目标改判;⑧**删错误码** `stale_baseline` / `no_write_lease` / `stale_writer` 及迁移期全部错误码。**本轮不改任何前端代码**(`frontend/**` 未动、`dist` 未重建) | `docs/frontend-contract.md`(§1 · §15.7 · §17.1 · §17.6 · §17.8 · §19.1 · §20.1)、`docs/backend-decisions.md` **B103** | 已登记(待实施) |
| D76 | 2026-09-17 | **新增 §20.5 媒体卡片契约:外部整合(跳转优先) + 版权署名前置** | 依据 `backend-decisions.md` **B104**、主文 **§2.3.14**。**前端可见变更**:①**新增 §20.5**:`media` 读 / 写 / 报告失效 / **embed** 四类端点;②**硬要求 12 条**:**默认跳转、不得自行 iframe 内嵌**(`embed_allowed` **一期恒 false**);**署名三项(`source_platform`/`author`/`source_url`)必须可见可点、不得隐藏折叠**;**跳转 URL 必须带匿名来源标识(不得带用户标识)**;**文章类只显示作者自写 `note`,不得拉取原文摘要或正文**;**`state=dead` 必须显式提示「原内容已失效」但解释正文与锚点照常渲染**;视频重剪 → 「该时间点可能已失准」;**封面三档 `upload`/`none`/`external`,禁止自动抓取对方封面**;**`kind` 决定卡片模板**(video/article/diagram);**媒体区必须显示「内容托管于第三方,本平台仅提供锚定与跳转」**;未认证创作者**必须显示「署名由提交者填写,平台未做核实」**;**每张卡片提供举报(侵权 / 署名错误冒名 / 已失效)**;⚠ **外部引用卡片周边不得投放广告**(保避风港);③**创建向导**:新增一次「版权与署名须知」(教育,不阻塞本地,随 `.webapkg` 携带);④**§20 标题**补「媒体整合 / 发现层」。**本轮不改任何前端代码** | `docs/frontend-contract.md`(**§20.5 新增** · §20 标题)、`docs/backend-decisions.md` **B104** | 已登记(待实施) |
| D77 | 2026-09-17 | **新增 §20.6 发现层与创作者契约:借短视频的「分发」,不借其「消费」** | 依据 `backend-decisions.md` **B105**、主文 **§2.3.15**。**前端可见变更**:①**新增 §20.6**:`GET /discover/`(发现流)/ `POST·DELETE /api/follows/`(关注)/ `GET /api/follows/feed/`(关注流)/ `GET /api/creator/stats/`(创作者面板)/ `POST …/media/<id>/claim/`(认领)/ `GET /api/share/card/`(卡片分享);②**硬要求 5 条**:**发现流「有边界」(limit 服务端夹取),不得做成无限流**;**每张卡片 `path_ref` 必填,不得出现「无归属的卡片」**;**推荐主信号 = 被路径采纳 + 完成率,不得把停留时长当正向信号**(代码场景中「卡住」是**负向**信号);**「提问数」是正向信号**(可渲染「这里很多人问过」);**卡片一律跳转卡,不得渲染播放器**。**本轮不改任何前端代码** | `docs/frontend-contract.md`(**§20.6 新增**)、`docs/backend-decisions.md` **B105** | 已登记(待实施) |
| D78 | 2026-09-17 | **新增 §20.7 第三方身份与归属验证契约(Gate 0)** | 依据 `backend-decisions.md` **B106**、主文 **§6.0(a1) / §2.3.14**。**前端可见变更**:①**新增 §20.7**:OAuth 绑定(start / callback)/ 我的绑定 / 解绑 / 归属校验 / 认领媒体 / 创作者主页 七类端点;②**硬要求 7 条**:**最小权限**(不得请求超出 `read:user`,⚠ **不提供读私有仓库入口**);**写解释 / 提问 / 阅读路径一律不得要求绑定**(绑定入口只出现在「发布源码 / 图谱」与「认领署名」流程);**未绑定必须显示「署名未核实」**;**`fork=true` 必须标注「Fork 自 owner/repo」,不得按原创展示**;**文案只能写「已验证账号归属」,不得写「已验证版权」**;**B 站绑定不得开放「发布源码 / 图谱」入口**;**外部卡片页零商业化**。**本轮不改任何前端代码** | `docs/frontend-contract.md`(**§20.7 新增**)、`docs/backend-decisions.md` **B106** | 已登记(待实施) |
| D79 | 2026-09-17 | **封面取消上传(改系统生成) + 前端不得提供媒体上传入口** | 依据 `backend-decisions.md` **B107**、主文 **§2.3.14 M10**。**前端可见变更**:①**§20.5 封面条款重写**:只有 **`generated`(系统生成,默认)/ `none`(占位卡)** 两档;⚠ **禁止用户上传封面、禁止自动抓取对方封面、禁止使用对方官方 logo 图片**;**来源标识只用文字平台名**;②**新增硬要求**:⚠ **前端不得提供「上传视频 / 图片 / 音频」的入口** —— 视频 / 文章 / 示意图**一律只填外部链接**;封面由系统按 `anchor` 哈希**确定性生成**(同一锚点永远同一张图);③`MediaRef.cover` 类型由 `{kind: upload｜none｜external, ref}` 改为 **`{mode: generated ｜ none}`**。**本轮不改任何前端代码** | `docs/frontend-contract.md`(§20.5)、`docs/backend-decisions.md` **B107** | 已登记(待实施) |
| D80 | 2026-09-17 | **前端契约对齐：私有项目也渲染 UGC 入口（仅本地）+ `parse_hash` 更名 + 登出保全（用户裁定：zip 项目能写解释，但所有写出的数据都存在用户本地，不可上传到服务器公开）** | 依据 `backend-decisions.md` **B109**、主文 **H5 / H6 / §3.3 / §6.0(a1)**。**前端可见变更**：①★ **私有项目同样渲染 UGC 入口**（解释 / 提问 / 阅读路径）—— 产物**只落本地**（新增本地模型 **`local_annotation`** / **`local_path`**，IndexedDB / OPFS），**写路径必须零网络请求**（抓包断言）；②★ **两种落点的 UI 必须可区分**（「服务端」/「本机」），避免用户误以为已发布；③★ **登出 / 删项目前必须提示导出**：「你有 N 条本地笔记，退出后无法恢复，建议先导出 `.webapkg`」——**不得静默清除**；④**文案硬约束**：**不得**出现「私有项目不能写解释」，正确表述 =「你写的解释只存在本机；想让大家看到，需要一个已公开的项目」；⑤**`snapshot_hash` → `parse_hash`**（§17.1 / §19.1 / §3 版本语义）；⑥**私有项目 UGC 落本地即持久**（不再显示「仅本次会话」），但**登出 / 删项目必须清本地**（§19.1 硬要求）；⑦**私有项目的 UGC 永不上行** ⇒ **无任何 UGC 相关上行调用**。**本轮不改任何前端代码**（`frontend/**` 未动、`dist` 未重建） | `docs/frontend-contract.md`(§19.1 · §20.1 附 · §20.4)、`docs/backend-decisions.md` **B109**、主文 H5 / §3.3 / §6.0(a2)(a3) | 已登记(待实施) |
| D81 | 2026-09-17 | **第 3 轮契约对齐：`publish` 端点语义变更为「请求建立快照」（用户裁定：开始第 3 轮）** | 依据 `backend-decisions.md` **B110**、主文 **H6 / §6.0(a1)**。**前端可见变更**：①★ **`POST …/publish/` 的 body 字段变更** —— 原 `{declare_rights, license_spdx?, source_repo?, commit?}`（三项可选）改为 **`{declare_rights: true, provider, source_repo, commit, license_spdx?}`**，其中 **`provider`（github / gitee）+ `source_repo` + `commit` 为必填** —— 语义从「**申请公开已有项目**」变为「**请求服务端去托管平台拉取并建立快照**」（H6）；②★ **前端不得提供任何「上传源码」入口**（H6；源码只能由服务端自己拉）；③`declare_rights` 不为 `true` → **400**（权利人声明，Gate 1）；④**`publish/status` 的 `state` 枚举新增语义**：`rejected` 的原因现在包含 **L2 copyleft / L3 source-available / L4 无许可证或混合许可**（前端必须展示可读理由 + 申诉入口）；⑤**前端不得自行判断许可证级别**（判据唯一权威 = 服务端 L1 白名单，主文 §6.0(a1)）。**本轮不改任何前端代码**（`frontend/**` 未动、`dist` 未重建） | `docs/frontend-contract.md`(§20.3 publish 端点 · 错误码) · 主文 H6 / §6.0(a1) · 附录 B3 | 已登记(待实施) |
| D82 | 2026-09-17 | **第 4 轮契约对齐：AI 生成内容的显式标识 + 内测期合规入口（用户裁定：先小范围内测，确认受欢迎后拉赞助，再解决现阶段无法解决的法律问题）** | 依据 `backend-decisions.md` **B111**、主文 **§2.3.8 / §6.0(a6)**。**前端可见变更**：①★ **AI 生成内容必须出现「AI 生成」中文可见字样** —— 原来只要求「`source` 字段可见」，**本轮加严**：**仅显示内部枚举值不够**，必须有**中文可读标识**（依据《人工智能生成合成内容标识办法》2025-09-01 施行；⚠ **不因内测豁免**）；②★ **`ai_draft` 字段必须保留在**：`.webapkg` 导出包 / **embed 响应** / **开放 API 响应** —— **前端在渲染与导出时不得抹掉该字段**（隐式标识，保证离开平台后仍可追溯）；③★ **内测期入口形态**：**必须支持邀请制**（邀请码 / 白名单 / 关闭公开注册）—— ⚠ **不得提供「公开注册但不宣传」的形态**（法律上等同公开服务；判据 = **是否对任何人开放**）；④**隐私告知页**（一页纸：收集什么 / 为什么 / 怎么删）在**内测期即须可达**；⑤**侵权联系入口**（邮箱 / 表单）在**页脚与关于页可见**，承诺 **24h 响应**；⑥**下架通知**：项目被 `taken_down` 时**前端必须向维护者展示理由摘要**与**申诉入口**（含**申诉时限倒计时**），**不得静默下架**；⑦**举报界面**：**举报人与被举报人身份互不可见**；**恶意举报**（窗口内多数不成立）会被降权 / 限频，前端需提示「**滥用举报将被限制**」。**本轮不改任何前端代码**（`frontend/**` 未动、`dist` 未重建） | `docs/frontend-contract.md`(§19.4 来源与置信度 · §20.3 举报与下架 · 新增内测入口约定) · 主文 §2.3.8 / §6.0(a6) / §2.3.14 · 附录 B10 | 已登记(待实施) |
