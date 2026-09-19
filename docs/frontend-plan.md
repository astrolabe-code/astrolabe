# 前端重构实施方案(图谱工作区主链)

> 权威副本。配套文档:`frontend-decisions.md`(决策/改进登记)、`frontend-contract.md`(接口契约)。
> 创建:2026-09-09。计划工件 `plan.md/plan.json` 是镜像,改动须经 `plan_create` 重新生成。

---

## 1. 目标与范围

把「源码图谱系统」的图谱工作区主链用 React 18 + TypeScript 重写为**前后端分离的独立 SPA**,通过新增 token 认证接入 Django 现有 JSON API。

**本阶段主链**:登录 → 项目工作区(列表/新建上传) → 项目主页 → 图谱浏览 → 节点详情 → 搜索 → 分析面板。

**非目标**:旧前端页面迁移、全站 envelope 统一、管理后台/容器终端/留言/LSP 重构、B4/B5 引用边抽取。

---

## 2. 技术栈与约定

- 前端:React 18 + TypeScript 5 + Vite 5;react-router-dom 6;@tanstack/react-query 5;zustand 4;vis-network(npm 包);Tailwind CSS 3.4.17 + tailwind-merge 2.5.5 + tailwindcss-animate 1.0.7;lucide-react / react-icons;recharts(统计图表可选)。
- 后端:Django 5.2 普通 JSON 视图(不引入 DRF);新增 app `authapi`、两个中间件、一个只读边端点。
- **样式策略(D18/D19/D20)**:外观沿用现站点「晨光控制台」(浅色默认 + `[data-theme="dark"]` 夜穹变体),**不引入旧 `base.css`**;新写 `src/styles/tokens.css`(同名同值变量)+ `components.css`(精简语义类),Tailwind 映射这些变量做布局。旧 HTML/CSS/JS 仅作视觉与交互规格参考,逻辑全部重写。
- 工程约定:`tsconfig` 设 `verbatimModuleSyntax:false`、`noUnusedLocals/Parameters:false`;vite `server.host='0.0.0.0'`、`allowedHosts:true`;单文件不超过 300 行;保留站点外壳(sticky 顶栏 54px、`.page` 1120px、`.skyfx` 背景层、主题切换)。

---

## 3. 后端改造(先做,不动既有视图语义)

### 3.1 `authapi` app
- `ApiToken(user FK, token_hash 唯一, expires_at, created_at, revoked)`;token 随机 32 字节,库存 blake2b 哈希,明文仅返回一次;提供过期清理管理命令。
- 端点(全部 JSON、`csrf_exempt`):
  - `POST /api/auth/login/` `{username,password,remember}` → `{ok,data:{token,user:{id,username,is_staff,avatar},exp}}`;TTL 默认 168 小时,remember 720 小时(env `API_TOKEN_TTL_HOURS` / `API_TOKEN_TTL_HOURS_REMEMBER`)。
  - `POST /api/auth/logout/` 撤销当前 token(幂等)。
  - `GET /api/auth/me/` 返回当前用户与 exp。
- 登录校验从 `accounts/views/auth.py::login_view` 抽出共享函数 `login_validate(request, username, password)`,模板登录页与 token 视图共用,**保留**三桶限流(`core/ratelimit`)、账号锁定(`UserProfile.locked_until`)、弱密码拦截(`WEAK_PASSWORDS`)、失败计数与 `AuditLog(action="login")` 语义;登录页无 captcha(与现状一致)。

### 3.2 `mysite/bearer.py::BearerAuthMiddleware`
- 仅对 `/api/` 生效;排在 `CsrfViewMiddleware` **之前**。
- Authorization 合法 → 挂 `request.user` 并置 `request._dont_enforce_csrf_checks=True`(SPA 免 CSRF)。
- **三态判定(D11)**:① Bearer 合法 → 挂 `request.user` + `request._dont_enforce_csrf_checks=True`(免 CSRF);② **无 Authorization 头 → 原样放行**,走 session + CSRF(旧模板 `base.js` 已自动补 `X-CSRFToken`,不会 403);③ 有头但非法/过期/撤销 → `401 {ok:false,error:{code:"unauthenticated"}}`,**不回退 session**。
- `/api/auth/login`、`/api/auth/logout` 显式 `csrf_exempt`。
- env `API_STRICT_BEARER`(默认 `0`):置 `1` 时 `/api/` 无 Authorization 直接 401;仅旧模板全部迁移后启用,本阶段不动。

### 3.3 `mysite/cors.py::CorsAllowMiddleware`
- 中间件首位;白名单取 env `DJANGO_CORS_ORIGINS`;命中回 `Access-Control-Allow-Origin/Credentials`,处理 OPTIONS 预检;无 Origin 头放行同源。

### 3.4 只读分层边端点(D7)
`GET /api/projects/<key>/graph/edges/?level=file|symbol&type=&origin=&dangling=&limit=&offset=` → `{ok,total,items:[{from_uid,to_uid,type,level,confidence,resolution,dangling,origin,site_count}]}`。
实现放 `projects/views/graphdata.py`,路由加 `projects/urls.py`,沿用 `permission_service.view_err`。

---

## 4. 前端分层

```
demo/frontend/
├── vite.config.ts  tsconfig*.json  tailwind.config.js  postcss.config.js  .env.example  README.md
└── src/
    ├── main.tsx  App.tsx  router.tsx(RequireAuth)
    ├── api/{client.ts, types.ts, errors.ts}
    ├── query/{auth, projects, graph, nodes, search, analysis, jobs}.ts
    ├── store/{authStore, workspaceStore}.ts
    ├── graph/{adapter.ts, layout.ts}
    ├── styles/{tokens.css, components.css}   # 新写:现站变量(浅/深)+ 精简语义类(不引旧 base.css)
    ├── components/{AppLayout, ProjectCard, ParseStatus, SearchBox,
    │               VisGraph, VisGraphMobile, DiagnosticsPanel,
    │               NodeDetailDrawer, SpecForm}.tsx
    ├── components/ui/{Button, Input, Modal, Drawer, Toast, Tabs}.tsx
    └── pages/{Home, Login, Workspace, ProjectHome, GraphPage, NodeDetail, AnalysisSearch}.tsx
```

- **client.ts**:统一 `get/post/put/delete`,注入 Bearer,把 4 种 envelope 归一为 `{ok,data,error}`;401 清 token 跳登录;409 `stale_rev` 自动重读图版本后重放一次;单次变更超限时自动分批重放。
- **上传(D15)**:额外提供 `upload(url, file, {onProgress})`,用 XMLHttpRequest(fetch 无上传进度),`FormData` 且**不手设 Content-Type**,用于 zip 上传进度条。
- **types.ts**:`CodeNode`、`CodeEdge`、`GraphSummary`、`SearchResult`、`AnalysisOverview`、`Diagnostics`、`Job`、`ParseConfig`、`SpecSchema` 与后端字段一一对应。
- **query**:作业轮询 3s、图版本 5s,`document.hidden` 时暂停。
- **store**:zustand 管 token/当前用户、当前项目、图版本与选中态。
- **graph/adapter.ts**:uid→vis id,样式映射,DataSet 增量 update;默认 `level=file` 总览,点开文件/符号再取 symbol 级边。
- **性能默认(D16)**:默认节点上限 **500**(UI 可调至 2000 并提示);进入页面即按 `kind`/`type`/`origin` 前置过滤;`stabilizationIterationsDone` 后关闭 `physics`(或首屏静态/层级布局);超阈值按 `dir_path`/`cluster` 聚合展示,点开再展开。

---

## 5. 页面详设

1. **Login**:居中玻璃卡片;品牌标 + 标语;用户名/密码输入(聚焦光晕)、「记住我」开关、登录按钮(加载微动效)、错误提示条;成功后淡入工作台。
2. **Workspace**:顶部固定导航(品牌、全局搜索、头像);项目卡片网格(语言徽标、状态点、解析进度条、公开标记);右下悬浮「新建项目」+ 上传弹窗(拖拽区、进度、解析中状态)。
3. **ProjectHome**:顶部项目上下文条(名称、解析状态、图版本);左概览卡 + 语言画像条;右操作区(进入图谱、重新解析确认、解析配置抽屉);底部最近作业(状态与进度)。
4. **GraphPage**:全宽画布;顶部筛选与图版本胶囊;左下图例(origin/lifecycle/置信度/边类型);悬浮摘要;右侧详情面板。<lg 切「节点列表 + 搜索 + 底部详情抽屉」并提供「进入画布」全屏缩放。
5. **NodeDetail**:面包屑 + 签名区;元信息卡(参数/返回类型/可见性/位置/重载);关系区(调用者、被调用、成员、其它边,带置信度徽标);抽屉承载笔记编辑、spec-schema 动态规划表单、转正确认。
6. **AnalysisSearch**:顶部大搜索框 + 过滤;结果按 `matched`(all/partial/fuzzy)分组展示命中强度;分析区为统计卡 + 四张列表(入口点、死代码、聚类、环)+ 健康度面板。

---

## 6. 视觉语义映射

- **节点**:`origin=source` 实心(符号圆点、文件方角);`origin=planned` 虚线描边 + 琥珀;`lifecycle=drifted` 橙描边 + 角标;`hidden` 缩小置灰;kind 影响形状与图标。
- **边**:`confidence` → 透明度;`resolution` 为 name/heuristic → 虚线;`dangling` 目标端标记 ✕;`type` 用颜色 + 箭头区分并在图例展示。
- **主题**:石墨黑 `#0F1419 / #161D26 / #1F2937`,冷青 `#12B8A6`、琥珀 `#E8A33D`、蓝 `#5B8DEF`;玻璃拟态侧栏;克制动效(悬停抬升、加载微光、选中光晕)。

---

## 7. 移动端策略

`<lg(1024px)`:侧栏收为抽屉导航、底部 Tab(工作区/图谱/搜索/分析);图谱默认列表模式,点选弹出底部全屏详情抽屉;触控目标 ≥44px;导航固定并用 `pt/pb` 避让内容。

---

## 8. 里程碑与验收

| # | 里程碑 | 产出 | 验收 |
|---|---|---|---|
| 0 | **旧样式归档(D24)** | 把 `base.css`、`index.html`、`nav.html`、`base.html`、`_skyfx.html`、`login.html` 复制为 `docs/legacy-style/<原名>.legacy-YYYY-MM-DD`(只读) | 归档文件存在于仓库;内容与现网一致;归档未完成不得删除/改写旧文件 |
| 1 | 后端认证 | `authapi` + Bearer/CORS 中间件接入 settings/urls;契约留档 | curl 登录/me/401 通过;旧模板登录页回归无变化;`manage.py check` 无 issue |
| 2 | **前端骨架与样式层** | Vite+TS+Router+Tailwind;`tokens.css` + `components.css`(现站变量与语义类);`client` 归一;`authStore`;站点外壳(`.topnav`/`.page`/`.skyfx`/主题切换) | `npm run build` 通过;浅/深两主题变量生效;顶栏与背景层与现站一致 |
| 3 | **首页(D22,首个交付页)** | `pages/Home.tsx` 1:1 复刻现站首页:hero、demo 三 Tab(代码/图谱/终端)、feats、三张 entry 卡、footer | 浅/深两主题 × 1440/1024/640/420 与旧首页一致;通过后删 `index.html` 与 `index_page.js` |
| 4 | 只读边端点 | `graph/edges/` + 路由(可推迟到图谱页之前) | 真实项目返回 total 与分页;权限与 share 生效 |
| 5 | 登录页与工作区 | 登录页、布局壳、项目列表/新建上传 | 真项目可建、传 zip、看进度 |
| 6 | 项目主页 | 概览/语言画像/重解析/解析配置/作业 | 配置可读写;作业轮询与取消 |
| 7 | 图谱页 | adapter + 桌面画布/移动列表双形态 + 版本轮询 | 文件级边总览渲染;点开文件展开符号边;超阈值提示 |
| 8 | 详情与搜索 | 节点详情(笔记/动态表单/转正)、搜索结果分组 | 笔记读写成功;planned 新建/编辑/删除成功;搜索按 matched 分组 |
| 9 | 分析与验收 | 分析面板 + 健康度;主链联调;文档留档 | 统计与列表数据正确;docs 文档更新;仓库内留档(不落 /tmp) |

---

## 8.1 部署与托管(D25 事实 / D26 决策)

**现状(已实测)**:nginx 仅做反向代理 —— `/static/`、`/`、`/ws/` 全部 `proxy_pass` 到 `127.0.0.1:8000`,**无 try_files/alias**;进程是 systemd `webapp` 跑 `daphne -b 127.0.0.1 -p 8000 mysite.asgi:application`(ASGI);`DJANGO_DEBUG=0`;nginx 配置在 `/etc/nginx`(仓库外)。静态资源实际由 Django 侧提供。

**首页阶段(里程碑 2–3)**:Vite dev server(`0.0.0.0:5173`、`allowedHosts:true`)+ `VITE_API_BASE` 指向 Django;`DJANGO_CORS_ORIGINS` 加入 dev 源,CORS 中间件**仅此阶段启用**;**不动 nginx、不动线上、不改 `/`**。

**首页验收通过后三选一(默认 A)**
| 方案 | 做法 | 代价 |
|---|---|---|
| A(推荐)Django 托管 `/app/` | 构建产物进静态目录 + `urls.py` 加 `re_path(r'^app/.*$')` 返回 `index.html` | 零 nginx 改动,与现状一致 |
| B nginx 托管 | `/app/` 用 `alias` + `try_files` | 需改仓库外配置并留档 |
| C 降级 | 托管层不支持 fallback → 前端改 hash 路由 | URL 带 `#` |

**通用约束**:SPA 迁移期一律挂 `/app/` 前缀,fallback 只匹配 `^app/`,旧路由零影响。

**缓存策略(D42,刻意不缓存)**:现状 `Cache-Control: no-cache` + `Last-Modified`/`ETag`(可 304 协商),改完刷新即生效 —— 这是**有意设计**(用户频繁改静态文件,不想清缓存)。
- 禁止给 `/static/` 加 `max-age`/`immutable`;即使走方案 B(nginx 托管)也必须保留协商缓存。
- **SPA `index.html` 必须 `no-store`/`no-cache`**(catch-all 视图显式设置),否则发新版后浏览器仍用旧 HTML。
- Vite 带哈希的产物本阶段同样不缓存,保持与现状一致;确需优化时单独决策并登记。

**后续演进(D43 · ⏳ 待办,本阶段不做)**:稳定后切生产级静态部署 —— 触发条件「主链迁移完成 + 不再频繁改静态 + 你确认」。届时:加 `STATIC_ROOT` → `collectstatic` → 备份 nginx 配置 → `location /static/` 改 `alias`(去 `proxy_pass`)、`/app/` 用 `alias + try_files` → `asgi.py` 的 `ASGIStaticFilesHandler` 仅 dev 启用 → 重载并验证 → 保留 5 分钟回退路径。**缓存默认继续不缓存**,若要加长缓存只对带哈希的 Vite 产物,且需你确认。完整 8 步清单见 `frontend-decisions.md` D43。

---

## 8.2 测试与质量(D39)

| 层 | 工具 | 范围 |
|---|---|---|
| 单元 | Vitest | `client.ts` 归一(4 形态 + 边界)、`authStore`/`workspaceStore`、`graph/adapter` 映射 |
| E2E | Playwright | 登录、首页渲染与搜索、工作区建项目、图谱打开与选中、节点详情、搜索、分析 |
| 视觉回归 | Playwright 截图对比 | 旧首页 vs 新首页,浅/深 × 1440/1024/640/420,容差 0.5% |

- 目录:`frontend/tests/`(仓库内,**不落 /tmp**);`npm run test` / `npm run e2e` 接入里程碑验收。
- 质量门禁:`npm run build`(含体积预算 D40)+ `npm run test` + `manage.py check` 全绿才允许进入下一里程碑。

---

## 10. 执行进度(滚动更新)

| 里程碑 | 状态 | 说明 |
|---|---|---|
| 0 旧样式归档(D24/D32) | ✅ 完成 | 17 个文件归档到 `docs/legacy-style/*.legacy-2026-09-10` + `MANIFEST.sha256`;旧文件**未删未改** |
| 1 后端认证(authapi + Bearer/CORS) | ✅ 完成(2026-09-10) | `authapi`(ApiToken/迁移/`login·logout·me`/清理命令)+ `mysite/bearer.py`(三态)+ `mysite/cors.py`;`accounts/views/auth.py` 抽出 `login_validate` 供模板与 token 共用。冒烟:`me(无token)=401`、`me(坏token)=401`、`login(缺字段)=400`、`login(错误密码)=401 login_failed`、`me(有效token)=200`、`logout=200 revoked:true`、`logout 后 me=401`、`预检(白名单外)=403`、`旧 /login/ 页=200`;`manage.py check` 无 issue;`makemigrations --check` 无差异 |
| 2 前端骨架与样式层 | ✅ 完成 | `demo/frontend`(Vite5+TS+Router6+Query5+Zustand4+Tailwind3);`tokens.css`/`components.css`/`skyfx.css`/`home.css`;`api/client.ts` 归一;`useTheme` 与旧站同契约 |
| 3 首页 1:1 复刻(D22) | ✅ 完成(已目视验收) | hero/kicker/搜索(前端过滤 + 建议下拉)/双 CTA;demo 窗口三 Tab(代码逐行 typein、vis-network 图谱 + 三色图例、终端)自动轮播 4.5s 悬停暂停;feats;三张 entry 卡(含懒加载图谱);footer;`<lg`/`≤640`/`≤420` 断点与 skyfx 移动端降级均按旧站数值 |
| 4 `graph/edges/` 只读端点 | ✅ 完成(2026-09-10) | `projects/views/graphdata.py::graph_edges` + `projects/urls.py` 路由 + `views/__init__.py` 导出;过滤 `level/type/origin/dangling` + 扩展 `file=<uid前缀>`(支撑按文件展开 symbol 边),`limit` 默认 500 钳制 1~5000,排序固定保证分页稳定,统一 `{ok,data}` envelope。冒烟:合成 4 条边后 `level=file`→1、`symbol`→3、`dangling=0/1`→2/1、`file=`→4、`origin+type`→1、`limit=99999`→5000、分页稳定、坏 key→404,数据已清理 |
| 5 登录页(SPA) | ✅ 完成(2026-09-10) | `pages/Login.tsx`(旧站版式 1:1:居中卡片/顶部高光条/字段/错误条/底部"创建账号")+ `authStore` + `useMe`(token 优先,回退 whoami)+ client 的 401 统一处理(清 token → 跳 `/login?next=`);登录成功写 token 后跳 `next`(默认 `/`) |
| 6 工作区(项目列表/新建/上传) | ✅ 代码完成(2026-09-10) | `pages/Workspace.tsx` + `ProjectCard`/`ProjectCreateModal`/`UploadPanel`/`ui/{Button,Input,Modal,ProgressBar,EmptyState}`;`query/projects.ts`(列表/新建/编辑/上传/进度轮询/重解析);客户端过滤(沿用首页 D23 语义)+ `?q=` 回填;空态/错误态/骨架屏;右下悬浮新建 |
| 7 项目主页 | ✅ 代码完成(2026-09-10) | `pages/ProjectHome.tsx` + `ParseStatus`/`ParseConfigDrawer`;概览计数 + 语言画像横条 + 边类型分布;操作区(进入图谱/上传替换/重解析二次确认/解析配置抽屉);最近作业表(3s 轮询 + 取消);`graph-rev` 5s 轮询,版本变化才失效重取 |
| 8–9 图谱/详情搜索/分析 | ⏸ 待办 | 按序推进 |

**工程补充(2026-09-10)**
- `api/{client,types,errors}.ts`:`client` 增加 `apiPut/apiDelete/upload(XHR 进度)`,401 后置处理抽为 `afterResult`;`types` 补齐项目/图谱/作业/解析配置/边类型;新增 `errors.ts`(`unwrap`/`ApiRequestError`/`errorMessage`)。
- 新增 `query/{projects,graph,jobs}.ts`、`store/workspaceStore.ts`、`lib/{cn,icons,url}.ts`;`RequireAuth` 改为按 `useMe` 判定(**token 优先、回退 session**,避免迁移期误挡已登录浏览器)。
- **路由偏差(已登记)**:工作区与项目主页**不套 `RequireAuth`**,对游客开放只读(与旧站 `/projects/`、`/project/<key>/` 行为一致,游客只看公开项目);写操作由页面按登录态与 `mine/staff/coadmin` 门控,后端仍二次校验。`RequireAuth` 保留给后续纯写页面使用。
- 新增 CSS 为零:新页面全部用 Tailwind 工具类 + 站点 CSS 变量,外观沿用「晨光控制台」,未引入旧 `base.css`。
- 待执行验证:`npm run build`(类型 + 打包)、`npm run dev` 后主链联调(登录 → 工作区新建 → 上传 → 项目主页 → 作业/配置)。

**里程碑 5–7 进展(2026-09-10)**

| 里程碑 | 状态 | 说明 |
|---|---|---|
| 5 工作区(D46) | ✅ 代码完成 | `pages/Workspace.tsx`(卡片网格/客户端过滤/右下悬浮新建)+ `ProjectCreateModal`(基本信息 → 上传两步)+ `UploadPanel`(拖拽 + XHR 进度 + `/progress/` 轮询)+ `ui/{Button,Input,Modal,ProgressBar,EmptyState}`;游客可浏览公开项目,新建/上传按钮按登录态显隐;`useProjects/useCreateProject/useUploadZip/useProgress` |
| 6 项目主页 | ✅ 代码完成 | `pages/ProjectHome.tsx`:概览卡(节点/边/kind 分布)+ 语言画像条 + `by_type` 标签 + 解析状态与图版本胶囊 + 上传/重解析(二次确认)/配置入口 + 作业表(3s 轮询、可取消);`ParseConfigDrawer` 支持 limits 分层(显示 admin 上限与 clamped)、排除规则、开关与头文件映射读写 |
| 7 图谱页(D16/D47) | ✅ 代码完成(合成数据验收) | `graph/adapter.ts`(uid→短 id、kind/origin/lifecycle 形状与颜色、confidence→透明度、name/heuristic→虚线、dangling 灰虚线)+ `VisGraph`(DataSet 增量 update、稳定后关物理引擎、选中高亮一跳邻居、双击进详情)+ `GraphToolbar`/`GraphLegend`(边类型点击显隐)/`GraphSidePanel`(调用者/被调用/成员 + 打开详情)+ `VisGraphMobile`(<lg 列表 + 搜索 + 进入画布);5s 图版本轮询,版本变化自动重取并提示;新增 `frontend/scripts/smoke_graph_api.py`(29 项断言全通过,自动清理合成数据) |
| 8 详情与搜索 | ✅ 代码完成 | `pages/NodeDetail.tsx`(签名/参数表/元信息/父级 + 调用者/被调用/成员/其它边四组关系表,置信度徽标)+ `NodeDetailDrawer`(笔记 GET/PUT/DELETE、`SpecForm` 规划表单、隐藏/删除规划节点、手动转正)+ `pages/SearchPage.tsx`(大搜索框 + kind 过滤 + matched 强度分组 + score 条 + 命中词);`query/{nodes,search,edit}.ts` 就绪 |
| 9 分析与验收 | 🔄 部分完成 | `pages/AnalysisPage.tsx`(6 张统计卡 + 入口点/死代码/聚类/环四列表 + 执行流)+ `DiagnosticsPanel`(诊断键,异常置顶);**托管(方案 A)已实施并实测**(D50);剩余:真实 v3.14 解析数据下的主链联调(受 D48 限制) |

**D55 · 工作区卡片补齐旧站操作集(2026-09-10 实施)**:对照旧站 `analysis_page.js` 的项目面板,把「编辑项目 / 设为公开·取消公开 / 重新解析 / 删除项目 / 复制到我的工作区」全部加到项目卡片(图标按钮 + 旧站同款确认文案),权限与旧站一致(owner 项仅本人可见,后端二次校验)。回归脚本 `scripts/smoke_project_actions.py` **18 项全通过**(真实 HTTP:新建/编辑/公开开关/复制/删除 + 游客 401·403 + 审计日志;临时用户与项目自动清理,残留 0)。

**D56 · 环境缺口(2026-09-10)**:本机没有 `manage.py graphworker` 在跑 → 上传/重新解析/复制的作业只排队不执行,且 `job_max_per_user=1` 会让同一用户后续作业 503。**D55 的「复制 / 重新解析」要真正跑通,需先常驻 worker。**

**D54 · 全局「返回 / 首页」入口(2026-09-10 实施)**:在顶栏一处实现,首页不渲染 —— 左端 `返回`(`location.key === "default"` 时回退首页)、右端 `首页`;移动端(≤640px)自动降级为纯图标按钮,不改变顶栏高度。

**D52 · 头像压缩(2026-09-10 实施)**:上传路径改为「2MB 粗筛 → `accounts/avatar.normalize_avatar` 归一化(结构校验 / 像素上限 / EXIF 摆正并去元数据 / 压到 ≤320px / 动图取首帧)→ 落盘」,原图不再入库;历史头像用 `manage.py compress_avatars --apply` 批处理(实测 `avatars/1_admin/*.jpg`:1080×2400 1015KB → 144×320 **14KB**,省 99%,DB 路径保持一致)。回归脚本 `scripts/smoke_avatar_compress.py` **24 项全通过**(含端到端走 `/api/user/avatar/`:合法图 200 且落盘 320px/7KB;伪造内容 / 尺寸超限 / 超 2MB / svg 全部 400)。

**D51 · 回归修复(2026-09-10)**:SPA 顶部导航复用了旧站 class 名但漏搬样式,导致用户头像按原图尺寸渲染(半屏)。已按旧站数值 1:1 补齐 `.nav-avatar/.nav-user/.nav-role/.nav-badge/.nav-msg/.nav-btn.logout` 并重建发布 —— 教训:凡是从旧模板搬过来的 class,必须逐个核对目标 CSS 是否存在同名规则。

**D50 · SPA 托管(2026-09-10 实施)**:`mysite/spa.py::spa_app` + `^app(?:/(?P<path>.*))?$`;`/app/` 与任意前端路由回 `index.html`(`Cache-Control: no-store`),`/app/assets/*` 走 `static.serve` 协商缓存;`/` 与旧站路由零改动。生产访问:`http://<主机>/app/`。

**环境事实(D48)**:库内 6 个项目全部为旧解析管线产物(`CodeNode/CodeEdge` 表为空、`parse_epoch=0`、`graph_rev=0`、无 `Job` 记录),即 v3.14 新图管线在本机**从未真实跑过**;图谱/节点详情/搜索/分析的联调目前只能用合成数据(见冒烟脚本)。

**⚠️ 上线前必须**:线上 daphne(systemd `webapp`)需重启才会加载 `authapi`/中间件/新路由:`sudo systemctl restart webapp`;否则 dev 代理(→127.0.0.1:8000)访问 `/api/auth/*` 会 404。

**dev 访问**:`http://<主机>:5173/app/`(proxy → Django `127.0.0.1:8000`,浏览器同源免 CORS)。
**构建**:`npm run build` 通过;主包 gzip ≈ 73KB,vis-network 懒加载分包(161KB gzip)。

---

## 9. 风险与注意

- `login_validate` 抽取必须保证模板登录页行为零变化(限流/锁定/审计日志)。
- `request._dont_enforce_csrf_checks` 只对 `/api/` 且 Bearer 校验通过时设置,避免打开旧站 CSRF 缺口。
- `changes?since=` 暂不用于图同步(P9 债:节点 rev 不随重解析推进会漏报),本轮只用 `graph-rev` 判版本。
- 大项目边量可能巨大:默认 `level=file`,symbol 级按需拉取并分页;节点上限 500 起,超阈值聚合。
- **XSS(D12)**:token 存 localStorage,必须配套 CSP(`default-src 'self'`)、富文本 DOMPurify、禁用 `dangerouslySetInnerHTML`、7/30 天 TTL 与可撤销;同源部署后再评估迁移 httpOnly cookie。
- **envelope 治理(D17)**:新增接口(`/api/auth/*`、`graph/edges/`)统一 `{ok,data}`/`{ok:false,error:{code,message}}`;既有接口保持不动,逐接口原始形态见 `frontend-contract.md` §11。
