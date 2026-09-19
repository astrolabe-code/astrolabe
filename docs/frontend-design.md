# 前端详细设计方案(图谱工作区主链 SPA)

> 依据:`frontend-decisions.md`(D1–D17 决策)、`frontend-contract.md`(接口契约)、`frontend-plan.md`(实施方案)。
> 本文只讲**前端**:信息架构、设计系统、组件、每屏详设、图画布、数据层、错误与移动端策略。
> 技术栈:React 18 + TypeScript 5 + Vite 5 + Tailwind 3.4.17(mobile-first)+ React Query 5 + Zustand 4 + react-router-dom 6 + vis-network(npm)+ lucide-react。

---

## 1. 信息架构与路由

```text
/login                                    登录(唯一无 token 可访问的主链页)
/                                         工作区(项目列表 + 新建)
/p/:ref                                   项目主页(概览/配置/作业)
/p/:ref/read                              导读页(阅读路径 / 解释 / 进度)   ← v28 新增,进入项目的主入口
/p/:ref/graph                             图谱浏览(可带 ?focus=<uid>&share=<token>)
/p/:ref/node/*                            节点详情(uid 含 #,URL 编码;?share=)
/p/:ref/search?q=                         搜索结果
/p/:ref/analysis                          分析面板与健康度
```

- **登录门控(已调整,见 plan §10 工程补充)**:工作区 `/workspace` 与项目主页 `/p/:ref` **对游客开放只读**(与旧站 `/projects/`、`/project/<key>/` 一致:游客只见公开项目);写操作由页面按登录态门控 + 后端二次校验。`<RequireAuth>`(按 `useMe` 判定:token 优先、回退 session)保留给后续纯写路由。
- SPA 实际路由前缀为 basename `/app/`(迁移期,D26/D27);上表路径均为 basename 内相对路径。
- `?share=<token>` 全程透传(只读/协作访问),进入时写入 `workspaceStore`,所有请求自动带上。
- 布局:沿用站点外壳 —— **sticky 顶栏 `.topnav`(54px,`≤640px` 48px)**:左品牌/用户区、右主题切换 + 导航链 + 汉堡(`≤640px` 收进下拉);内容区 `.page`(max-width 1120px);背景 `.skyfx` 特效层。
- 旧代码处置:见 §13(D19/D21:不移植旧逻辑,迁移一个删一个)。

---

## 2. 设计系统(沿用现站点视觉,D18)

> ★ 计划生成器给的石墨黑配色作废。**一切以现站点「晨光控制台」为准**:浅色默认 + `[data-theme="dark"]` 夜穹深色变体。
> 落地方式(D20):新写 `src/styles/tokens.css`(同名同值变量)+ `tailwind.config.js` 映射 + `components.css` 精简语义类;**不引入旧 `base.css`**。

**颜色 token(浅色 → 深色,写入 `tokens.css`)**

| 变量 | 浅色 | 深色(`[data-theme="dark"]`) |
|---|---|---|
| `--bg` / `--bg-deep` | `#eef3f9` / `#e6edf6` | `#16213e` / `#101b2e` |
| `--card` | `#ffffff` | `#252536` |
| `--card-border` / `--card-border-hover` | `rgba(30,64,105,.10)` / `rgba(8,145,178,.50)` | `rgba(148,163,184,.18)` / `rgba(77,184,214,.55)` |
| `--text-main` / `--text-sub` / `--text-faint` | `#101d33` / `#57687f` / `#93a2b8` | `#d4d4d4` / `#8b8b9e` / `#6b6b80` |
| `--accent` / `--accent-strong` / `--accent-dim` | `#0891b2` / `#0e7490` / `rgba(8,145,178,.10)` | `#4db8d6` / `#6dc8e0` / `rgba(77,184,214,.14)` |
| `--ok` / `--warn` / `--err` | `#059669` / `#d97706` / `#dc2626` | `#34d399` / `#fbbf24` / `#f87171` |
| `--code-bg` / `--code-bar` / `--code-text` | `#f6f8fa` / `#edf2f7` / `#24292f` | `#1e1e2e` / `#252536` / `#d7e2f2` |
| `--code-key/-str/-fn/-com/-num` | `#0550ae` `#0a7a3f` `#953800` `#6a737d` `#cf222e` | `#7dd3fc` `#86efac` `#fcd34d` `#55607a` `#fca5a5` |

深色下 `.btn.primary` = `#23768f`(hover `#2a87a4`),不用亮 accent 作底色(刺眼)。

**字体**:UI `"MiSans","PingFang SC","Microsoft YaHei",sans-serif`;等宽 `"JetBrains Mono","SF Mono","Consolas",monospace`(代码、签名、面包屑、表头、mono 文案)。

**尺寸**:`--radius 14px` / `--radius-sm 9px`;顶栏高 54px(`≤640px` 48px);页面容器 `.page` max-width **1120px**(`≥1600px` → 1240px),padding `36px 30px 64px`(`≤1100px` `30/22/52`,`≤900px` `24/16/44`,`≤640px` `18/12/36`)。

**组件外观(重写为精简语义类)**

| 语义 | 外观要点 |
|---|---|
| `.btn.primary` | 实心 accent + 白字,hover 上浮 1px + 光晕;深色用 `#23768f` |
| `.btn.ghost` | 透明底 + `--card-border`,hover 边框/文字变 accent |
| `.btn.danger` | 透明底 + 红边红字,hover 淡红底 |
| `.card` | 白/深底 + 1px 边框 + 14px 圆角 + 轻阴影;`hoverable` hover 上浮 **3px** + 边框变 accent 系 |
| `.input` | 9px 13px padding、9px 圆角;focus 边框 accent + 3px `accent-dim` ring |
| `table.data` | 表头 11px 大写等宽 + `--th-bg`;行 hover `--tr-hover` |
| `.tag` / `.tag.online` / `.tag.active` | 999px 圆角 11px;在线绿、激活 accent-dim |
| 进场 | `.rise` 0.45s 上浮 8px;`.d1/.d2/.d3` 延迟 .06/.12/.18s |
| 弹窗 | `.dlg-mask` 遮罩 + `.dlg` 360px(w≤86vw)14px 圆角 + 弹出动画 |

**背景层 `.skyfx`**:光束 beam(12s 呼吸)、暗角 vignette、地平线微光、冰面反光、上升光尘、闪烁星辰、启明星;`≤768px` 仅保留 6 颗星并固定定位(性能降级)。`body.page-hidden` 时全部动画暂停。

**断点**:`≥1600` / `≤1100` / `≤900` / `≤768`(特效降级)/ `≤640`(顶栏 48px、汉堡菜单、卡片 12px)/ `≤420`(首页 demo 精简)。

**间距与密度**:列表行高 36–40px;卡片内边距 20–22px;信息密度中偏高;画布区不留多余 padding。

---

## 3. 组件清单

**基础组件 `components/ui/`**
`Button`(primary/ghost/danger + loading)、`Input`、`Select`、`Switch`、`Modal`、`Drawer`(桌面右侧/移动底部全屏)、`Toast`、`Tabs`、`Badge`、`ProgressBar`、`Skeleton`、`EmptyState`、`ErrorState`、`Tooltip`。

**业务组件 `components/`**

| 组件 | 职责 |
|---|---|
| `AppLayout` | 导航壳;桌面左栏、移动底部 Tab + 抽屉;承载全局搜索与头像菜单 |
| `SearchBox` | 顶部常驻;输入防抖 300ms;下拉前 8 条快速跳转,Enter 进结果页 |
| `ProjectCard` | 语言徽标、状态点、解析进度条、公开标记、进入按钮 |
| `ParseStatus` | 解析状态徽章 + 进度 + 活跃作业轮询(3s) |
| `VisGraph` | vis-network 画布(桌面),分层加载、样式映射、图例、选中/悬浮 |
| `VisGraphMobile` | 移动列表模式 + 「进入画布」全屏缩放入口 |
| `NodeDetailDrawer` | 节点详情容器(桌面右侧面板 / 移动底部抽屉) |
| `SpecForm` | spec-schema 驱动的动态规划表单 |
| `DiagnosticsPanel` | 健康度闸门与诊断键展示 |

---

## 4. 页面详设

> **首页 `/`** 是本阶段首个落地页,规格见 **§12**(D22)。以下 4.1–4.7 在首页之后实施。

### 4.1 登录页 `/login`
- 布局:居中玻璃卡片(最大宽 400px),品牌标 + 标语「**读懂源码 · 一边看图谱一边读解释**」。
- 表单:用户名/密码 `<input>`(聚焦 `ring-brand/50`)、「记住我」`Switch`、登录 `Button`(loading 态)。
- 交互:提交 → `POST /api/auth/login`;成功写 token/localStorage + `authStore` → 跳 `next` 或 `/`;失败展示错误条(后端文案直出,如「账号已锁定,请 N 分钟后再试」)。
- 状态:加载中禁用按钮;401 与限流文案不做二次改写。

### 4.2 工作区 `/workspace`(✅ 已实现)
- 顶部固定导航:品牌、全局 `SearchBox`、头像菜单(登出)由全局 `TopNav` 提供。
- 项目卡片网格(`grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4`):图标(lucide)、名称、分类、状态点、解析进度条、公开/归属标记。
- 过滤:输入框走客户端过滤(name/desc/owner/category),并同步 `?q=`(承接首页搜索跳转,D23)。
- 右下悬浮「新建项目」→ `ProjectCreateModal`(两步:名称/简介/分类/图标 → 上传 zip/`tar.gz`/`tgz`)→ `POST /api/projects/` → `client.upload()`(XHR 进度条)→ 轮询 `/progress/`。
- 卡片可直接「上传源码」(登录且非解析中);空态(区分「无项目」与「无匹配」)与错误态均带重试/清除过滤。
- 权限:游客可见公开项目,新建/上传入口改为「登录后新建」(跳 `/login?next=/workspace`)。
- 备注:`POST /api/projects/` 后端不接受 `is_public`(新建默认私有),公开切换走 `PUT /api/projects/<key>/ {is_public:bool}`。

### 4.3 项目主页 `/p/:ref`(✅ 已实现)
- 顶部项目上下文条:项目名、`<ParseStatus>`、图版本胶囊(`v<graph_rev>`)+ 刷新/进入图谱。
- 左栏:概览卡(节点/边/语言构成,来自 `graph/summary` 的 `counts` 与 `lang_breakdown`,语言占比用横条)。
- 右栏:操作区(进入图谱、重新解析带二次确认、解析配置抽屉)。
- 配置抽屉:`GET …/parse-config/` 展示 `limits`(含 clamped 提示)、`exclude_names/suffix`、`header_dir_map`、`parse_parameters`、`sig_strict_defaults`;`POST` 部分提交。
- 底部:最近作业(`GET …/jobs/`,3s 轮询活跃项,可取消)。

### 4.4 图谱页 `/p/:ref/graph`
见 §5(核心)。

### 4.5 节点详情 `/p/:ref/node/*`
- 顶部面包屑(项目 / 文件 / 父级 / 当前)+ 签名区(等宽、`signature`)。
- 元信息卡:参数表(`params`)、`return_type`、`visibility`、`file_path:line`、`overloaded/is_primary` 徽标、`rev`。
- 关系区 Tabs:调用者 / 被调用(每行显示 `site_count` 与 `resolution` 置信度徽标)/ 成员 / 其它边;各列表上限按后端 200/300/100,超出提示收窄。
- 抽屉:笔记(`GET/PUT notes/<uid>/`)、规划表单(`SpecForm`,创建/编辑/删除)、`drifted|planned` 节点显示「转正」按钮(`promote/confirm`,二次确认并展示校验失败原因)。
- 移动:整页即详情,底部按钮呼起抽屉。

### 4.6 搜索 `/p/:ref/search`
- 顶部大搜索框 + kind 过滤;结果按 `matched` 分组(all / partial / fuzzy),每条显示 kind 徽标、`file_path:line`、签名、`score` 强度条、`terms` 命中词。
- 空词:引导;无结果:提示 n-gram 兜底已尝试;错误:重试。

### 4.7 分析面板 `/p/:ref/analysis`
- 统计卡:入口点 / 死代码 / 已聚类 / 环 / 节点 / 边(`analysis.counts` + `diagnostics.counts` + `metrics_stats`)。
- 四张列表:入口点、死代码(可翻页取 `graph/nodes?is_dead=1`)、聚类、环;行点击跳节点详情。
### 4.8 导读页 `/p/:ref/read`（v28 新增,**进入项目的主入口**)

> **为什么是主入口**:本平台的第一定位是「**读懂陌生开源项目**」(主文 §2.2)。因此进入项目**默认落导读页**,而不是一进来就丢一张全项目大图。

- 顶部:路径选择器(多条并存,按「被采纳 / 认同数 / 新鲜度」排序)+ `target_reader` 过滤器;
- 主体:**步骤清单**(第 N/M 步),每步显示 `title` / **`why_now`** / `what_to_notice` / `check`;
- 每步右侧:**锚点代码视图**(按锚渲染,**不内嵌副本**)+ 该锚的**解释 / 提问**侧栏;
- **路径健康度**:`needs_review` 的步骤打「**可能已过时**」徽章,并提供「重新定位」入口;
- **维护入口**:「生成初稿」(从 `entry_points` / `processes`)/ 「Fork」/ 「把笔记提升为步骤」;
- **进度**:断点续读(「继续读第 7/23 步」)、稍后读、自检统计;
- **空态**:无路径时给「**生成初稿**」与「**从我的笔记生成**」两个按钮(冷启动)。

### 4.9 会话态与合规引导（v28 新增）

| 位置 | 引导(**就地**,不弹窗劝退) |
|---|---|
| 上传压缩包时(一次性) | 「**浏览器不长期保存,关闭 / 刷新即丢失**。三条出路:**① 学习公开项目(有解释与阅读路径) ② 导出 `.webapkg` ③ 等待桌面客户端**」 |
| 项目主页空态 | 展示**已有人解释的公开项目**推荐位(不是空话),并给「浏览公开项目」按钮 |
| 私有(`local`)项目 | **不渲染** UGC 创作入口(解释 / 路径 / 提问);若需临时笔记,标「**仅本次会话;导出才能保留**」 |
| 发布入口 | `local` 项目**隐藏** `is_public` 开关;公开须走**权利人声明 + 自动核验**(主文 §6.0(a1):正常**秒级自动放行**,仅存疑才转管理员);`pending_review` / `rejected` / `taken_down` 必须可见 |
| 全局 | 提供「**桌面客户端等待名单**」留邮箱入口(主文 §3.4) |

- `DiagnosticsPanel`:健康度闸门与诊断键(`diagnostics` 原始键),异常项置顶。

---

## 5. 图谱画布详设(核心)

### 5.1 数据加载(分层)
1. 进入:`graph/summary` 取规模与语言;`graph/nodes?kind=…&limit=500` 取点;
2. 边:`graph/edges?level=file` 取**文件级边**做全局总览(D7);
3. 点开文件/符号:再取 `level=symbol` 边(可按 `type`、`origin`、`dangling` 过滤)增量并入;
4. `graph-rev` 5s 轮询(`document.hidden` 暂停),版本号变化才整体重取并提示「图谱已更新」。

### 5.2 样式映射

| 语义 | 规则 |
|---|---|
| `origin=source` | 实心;符号圆点、文件/目录方角 |
| `origin=planned` | 虚线描边 + 琥珀 `#E8A33D` |
| `lifecycle=drifted` | 橙 `#D29922` 描边 + 右上角三角 |
| `hidden` | 缩放 0.7 + 50% 灰(可开关) |
| `kind` | 形状 + lucide 图标(function/method/type/file/dir/macro 等) |
| 边 `confidence` | 1.0 实线 0.9 透明度;≤0.8 降透明度;`name/heuristic` 改虚线 |
| 边 `dangling` | 目标端标记 ✕ |
| 边 `type` | CALLS 冷青 / IMPORTS 蓝 / EXTENDS 琥珀 / READS·WRITES 灰蓝 / SAME_AS 虚灰;箭头区分 |
| 选中 | `ring-brand` 光晕 + 邻居高亮一跳,其余降透明度 |

### 5.3 布局与性能(D16)
- 首次用 `physics`(barnesHut)稳定后关闭:`stabilizationIterationsDone` → `setOptions({physics:false})`;或首屏直接层级布局。
- 默认节点上限 **500**;UI 可调至 2000 并提示风险;进入即按 `kind`/`type`/`origin` 前置过滤(不是先全量后裁)。
- 超阈值按 `dir_path` 或 `cluster` **聚合展示**(聚合节点显示成员数),点开再展开子图。
- DataSet 增量 `update()`,避免整图重绘。

### 5.4 交互
- 悬浮:tooltip 摘要(kind、qname、file:line、signature 前 80 字)。
- 单击:选中 + 右侧/底部详情(不跳页)。
- 双击 / 详情内「打开」:跳节点详情路由。
- 图例(左下):origin、lifecycle、置信度、边类型,可点击切换显示。
- 顶部:筛选条(kind / type / origin / 隐藏 hidden)、图版本胶囊、刷新。

### 5.5 移动形态(<lg)
画布默认收起,展示**节点列表**(无限滚动,`graph/nodes` 分页)+ 搜索;点选弹出**底部全屏详情抽屉**;另有「进入画布」进入全屏可缩放模式(双指缩放/平移)。

---

## 6. 数据层

### 6.1 `api/client.ts`
- 统一 `get/post/put/delete`:注入 `Authorization: Bearer`、JSON 头、`credentials: 'omit'`(跨域不带 cookie)、超时与中止。
- 归一:4 种 envelope → `{ok:true,data}` / `{ok:false,error:{code,message,status}}`(规则见契约 §11)。
- 401 `unauthenticated` → 清 token、跳登录(只触发一次,避免并发刷屏)。
- 409 `stale_rev` → 重读 `graph-rev` 后**自动重放一次**;仍失败转 toast。
- `too_many_changes` → 自动切分 `changes` 分批提交。
- `upload(url, file, {onProgress})`:XHR + `FormData`,不手设 `Content-Type`(D15)。

### 6.2 `api/types.ts`
`CodeNode`、`CodeEdge`、`GraphSummary`、`NodeDetail`、`SearchResult`、`AnalysisOverview`、`Diagnostics`、`Job`、`ParseConfig`、`SpecSchema`、`Project`、`ApiError` 等,字段与契约一一对应(全部 `export`)。

### 6.3 React Query
- queryKey 规范:`['projects']`、`['project', key]`、`['graph', key, 'summary']`、`['graph', key, 'nodes', filters]`、`['graph', key, 'edges', {level,…}]`、`['node', key, uid]`、`['search', key, q, kind]`、`['analysis', key]`、`['diagnostics', key]`、`['jobs', key]`、`['parse-config', key]`、`['graph-rev', key]`。
- 轮询:作业 3s、图版本 5s;`refetchIntervalInBackground:false` + `document.hidden` 判断。
- 写操作 `useMutation` 成功后失效相关 key(节点、边、graph-rev、jobs)。

### 6.4 Zustand
- `authStore`:`token`、`user`、`exp`、`login`、`logout`、`hydrate`(启动时 `me` 校验)。
- `workspaceStore`:当前项目 key、`share`、图版本 `graphRev`、选中 uid、筛选条件、画布/列表模式。
- token 存 `localStorage`;登出调用 `/api/auth/logout` 后清空本地。

---

## 7. 认证与权限流程

1. 启动:有 token → `GET /api/auth/me` 校验;失败即清 token 进登录。
2. 请求:统一注入 Bearer(D11 三态由后端保证;前端不发送 CSRF 头)。
3. 401:清 token + 跳登录并带 `next`。
4. 游客/分享:`?share=` 只读访问公开项目;前端对写操作做 `RequireAuth` 拦截(后端仍二次校验)。
5. 安全(D12):CSP `default-src 'self'`;笔记等富文本 DOMPurify;禁用 `dangerouslySetInnerHTML` 直出。

---

## 8. 错误与反馈

| 场景 | 处理 |
|---|---|
| 网络失败 | Toast「网络异常,稍后重试」+ 页面内重试按钮 |
| 403/404(③形态文案) | 页面错误态直出后端文案 |
| `project_busy` | Toast「项目正忙」并暂停自动重放 |
| `graph_not_ready` | 顶部提示解析未完成,禁用编辑入口 |
| `stale_rev` 二次失败 | Toast「图谱已更新,已刷新,请重试」 |
| 空数据 | `EmptyState`(区分「无数据」与「无权限」) |
| 加载 | 骨架屏(列表/卡片),画布区用 loading 遮罩 |

---

## 9. 移动端与可访问性

- 断点沿用现站:`≥1600` / `≤1100` / `≤900` / `≤768`(背景特效降级)/ `≤640`(顶栏 48px + 汉堡菜单)/ `≤420`。
- 顶栏 `position: sticky; top:0`(54px);内容区自然避让,不额外加 `pt`(与现站一致)。
- 关键操作触控目标 ≥40px(顶栏控件沿用现站 34px 圆钮);列表行高 ≥40px;抽屉支持下滑关闭。
- 语义化标签与 `aria-label`;焦点可见(`focus-visible:ring`);颜色对比满足正文 ≥4.5:1;图例不只靠颜色区分(配形状/虚线)。

---

## 10. 实现顺序与验收

| 步骤 | 内容 | 验收 |
|---|---|---|
| 1 | 脚手架(Vite/TS/Tailwind/Router/Query/Zustand)+ 主题 tokens + ui 基础组件 | `npm run build` 通过;深色主题与 tokens 生效 |
| 2 | `api/client.ts` 归一 + `types.ts` + `authStore` + `RequireAuth` | 登录后可持久;401 自动跳登录 |
| 3 | 登录页 + `AppLayout` + 工作区(列表/新建/上传进度) | 真项目可建、可传 zip、看进度 |
| 4 | 项目主页(概览/语言画像/重解析/配置/作业) | 配置可读写;作业轮询与取消 |
| 5 | 图谱页(adapter + 桌面画布 + 移动列表 + 图例 + 版本轮询) | 文件级边总览;点开展开符号边;阈值提示 |
| 6 | 节点详情(关系/笔记/SpecForm/转正) + 搜索页 | 笔记读写;planned 增删改;搜索分组 |
| 7 | 分析面板 + 健康度 + 主链联调 | 数据正确;docs 三份文档同步更新 |
| 8 | **导读页(阅读路径 + 锚点解释 + 进度) + 解释密度热力图 + 发布审批态** | 能走完一条路径;`needs_review` 可见;私有项目无 UGC 入口 |

---

## 11. 目录与文件职责

```text
demo/frontend/src/
├── main.tsx / App.tsx / router.tsx          # 入口、Provider(Query/Auth)、路由与 RequireAuth
├── api/{client,types,errors}.ts             # 归一请求层、类型、错误码映射
├── query/{auth,projects,graph,nodes,search,analysis,jobs}.ts
├── store/{authStore,workspaceStore}.ts
├── graph/{adapter,layout}.ts                # vis-network 映射与布局
├── styles/index.css                         # Tailwind 指令 + 主题变量
├── components/                              # AppLayout/ProjectCard/ParseStatus/SearchBox/
│                                            # VisGraph/VisGraphMobile/NodeDetailDrawer/SpecForm/DiagnosticsPanel
├── components/ui/                           # Button/Input/Select/Switch/Modal/Drawer/Toast/Tabs/… 
└── pages/{Login,Workspace,ProjectHome,GraphPage,NodeDetail,AnalysisSearch}.tsx
```

---

## 12. 首页:第一个落地页(D22/D23,1:1 复刻)

**目标**:React 首页与现站首页视觉、文案、交互一致;通过后删除旧首页资产。

> ★ **v28 追加变更(待实施;依据主文 §2.3.15 / `B105`)**:**首页从「搜索框 + 项目列表」改为「精选阅读路径 + 卡片流」** —— ①新增 **`/discover` 发现页**(**有边界**的卡片流,⚠ **不做无限流**);②首页首屏 = **3 条精选路径** + **卡片流**;③每张卡片**必须回链路径**(`path_ref` 必填);④**推荐排序主信号 = 被路径采纳 + 完成率**,⚠ **不得用停留时长**;⑤卡片里的外部媒体一律**跳转卡**(§2.3.14,**一期不做站内播放**)。

### 12.1 页面结构(对照 `core/templates/core/index.html`)

```text
<div class="page">
  ├─ .hero (grid 1fr 1.1fr, gap 56px, padding 64/0/40)
  │   ├─ 左 .rise
  │   │   ├─ .kicker  "Code Analysis Console"(12px 大写 字距2.5 mono,前 24px 短线)
  │   │   ├─ h1 38px/650  "让代码 / 像星辰一样 清晰"("清晰"用 .accent-word)
  │   │   ├─ p.sub 15px/1.85  两行文案
  │   │   ├─ .hero-search  input[search] + .btn.primary「搜索」+ hint「游客也可搜索并浏览公开项目」
  │   │   └─ .hero-actions  「开始使用 →」(.btn.primary) 「浏览手册」(.btn.ghost) hint「无需安装 · 浏览器即开即用」
  │   └─ 右 .demo.rise.d1 (413px 高, 圆角14, 代码窗口配色, 阴影)
  │       ├─ .bar  三色灯(#f87171/#fbbf24/#34d399) + .tabs(在线代码/图谱/终端)
  │       ├─ .stage 三 pane: 代码 pre(sched.c 16 行, 行号 .ln 44px, typein 逐行淡入)
  │       │                 图谱(#demoGraph vis-network + 图例 核心#ef4444/模块#f97316/其他#22c55e)
  │       │                 终端 .tpane(make && make run → 127 files parsed · graph ready)
  │       └─ .status 左「C · kernel」 右「Ln 17, Col 20」
  ├─ .feats.rise.d2  三项(绿点脉冲):**读懂陌生项目**(阅读路径) / **解释钉在代码上**(锚点 markdown) / 上传即解析·本地优先
  ├─ .grid  三张 .card.hoverable.entry:
  │     代码分析 ANALYZE(pre-code python 3 行) → /projects/
  │     依赖图谱 GRAPH(pre-graph vis-network) → /projects/
  │     代码控制台 CONSOLE(pre-term 3 行) → /tools/code/
  └─ .foot.rise.d3   左「● 服务运行中」  右 mono「小铃铛 · console」
```

### 12.2 交互
- demo 三 Tab 切换:`.pane.active` 透明度 + 上移 12px 过渡(0.5s/0.55s cubic-bezier);Tab 激活态用 `accent-dim` 底 + 边框。
- 代码 pane 逐行 `typein` 动画(0.22s,逐行延迟)。
- 图谱 pane 用 **vis-network**(npm 包)渲染少量节点;`core` 节点呼吸动画、部分节点 `floaty` 浮动、热点边 `dashflow`。
- hero 搜索:输入防抖 → 在已拉到的项目列表里过滤;Enter 跳工作区并带 `q`(D23)。
- 卡片 `hoverable` 上浮 3px。

### 12.3 数据
- `GET /api/projects/`(游客:公开项目;`icon_lucide`/`name`/`desc`/`owner`/`is_public`/`score`)→ **前端按 name/desc/owner 过滤**,无后端 q 端点(D23)。
- 导航登录态:`GET /api/auth/me`(有 token)/ 游客态;登录、注册按钮临时链旧站 `/login/`、`/register/`。

### 12.4 响应式(沿用现站断点)
- `≤1024`:hero 单列 gap36;`.grid` 两列。
- `≤640`:hero padding 40/0/24;h1 30px;`.grid` 单列 gap20;demo 改 `height:auto`、stage 300px、代码 11px、行号 34px;`.topnav` 48px;导航文字链收进汉堡下拉。
- `≤420`:demo tabs 去掉左边距、隐藏三色灯。
- `≤768`:`.skyfx` 仅保留 6 颗星并改为顶部 45vh 区域(性能降级)。

### 12.5 验收与收尾
- 浅色/深色**两主题**、宽度 **1440 / 1024 / 640 / 420** 四档与旧首页逐屏对比,视觉一致(不要求像素级,但颜色/间距/字号/动效一致)。
- 通过后删除 `core/templates/core/index.html`、`assets/static/js/index_page.js`(删除前确认视图不再 render、static 引用摘除、`manage.py check` 通过)。

---

## 13. 旧资产处置:重写 + 迁移一个删一个(D19 / D21)

**原则**:旧 HTML/CSS/JS **不逐行移植**。它们只提供视觉规格与交互事实;逻辑在 React 里重写(更清晰、无历史 hack)。外观必须与现站一致(第 2 节 token)。

**步骤 0 · 先归档(D24,强制前置)**:动任何旧样式/模板之前,先把它们**只读归档**到 `docs/legacy-style/`,命名 `<原名>.legacy-YYYY-MM-DD`。归档未完成时,不得删除或改写旧文件。新样式出现视觉偏差时,与归档逐条 diff 变量与规则。

首批归档:`assets/static/css/base.css`、`base.css.bak-theme`、`core/templates/core/index.html`、`nav.html`、`base.html`、`_skyfx.html`、`accounts/templates/accounts/login.html`。

**规格来源(只读参考,不复制代码)**

| 旧资产 | 提供什么规格 |
|---|---|
| `assets/static/css/base.css` | 颜色/圆角/阴影/顶栏/卡片/按钮/输入/表格/标签/进场/弹窗/背景特效/断点 |
| `core/templates/core/nav.html` + `js/nav.js` | 顶栏结构、主题切换、汉堡菜单、头像与身份标签、未读徽标 |
| `core/templates/core/index.html` + `js/index_page.js` | 首页 hero / demo 三 Tab / 特性条 / 入口卡 / 页脚文案与断点 |
| `accounts/templates/accounts/login.html` + `js/login_page.js` | 登录文案与失败表现(`X-Login-Fail`、锁定/限流文案) |
| `projects/templates/projects/*` + `graph_page.js` / `analysis_page.js` | 图谱与分析页的既有交互事实(非样式基线) |

**删除清单**(在 React 对应页联调通过后勾选删除;未迁移页面保留)

| # | 待删旧资产 | 由哪个 React 页替代 | 状态 |
|---|---|---|---|
| 1 | `core/templates/core/index.html` + `assets/static/js/index_page.js` | (首页不在本阶段主链,保留) | 保留 |
| 2 | `accounts/templates/accounts/login.html` + `js/login_page.js` | `pages/Login.tsx` | 待删 |
| 3 | `projects/templates/projects/projects.html` + 相关 js | `pages/Workspace.tsx` | SPA 已替代(待联调通过后删) |
| 4 | `projects/templates/projects/home.html` + `js/project_home.js` | `pages/ProjectHome.tsx` | SPA 已替代(待联调通过后删) |
| 5 | `projects/templates/projects/browse.html` + `js/graph_page*.js` | `pages/GraphPage.tsx` | 待删 |
| 6 | 旧节点详情/搜索/分析模板与 js | `NodeDetail` / `AnalysisSearch` | 待删 |
| 7 | `assets/static/css/base.css` | `src/styles/tokens.css` + `components.css`(全站迁移完后) | 最后删 |

**删除前检查**:确认 Django 视图不再 `render` 该模板、无其它模板 `include`、`static` 引用已摘除;`manage.py check` 与页面冒烟通过后再提交删除。
