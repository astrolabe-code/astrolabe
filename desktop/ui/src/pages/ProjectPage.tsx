import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { FileCode2, Lock, Settings, Workflow } from 'lucide-react'
import type { GraphNode } from '../lib/mergeGraph'
import { errorMessage } from '../api/errors'
import { useProject } from '../query/projects'
import { useMediaQuery } from '../hooks/useMediaQuery'
import AppLayout from '../components/AppLayout'
import { PageBar, RailButton } from '../components/PageBar'
import CodeWorkspace from '../components/code/CodeWorkspace'
import Button from '../components/ui/Button'
import NodeList from '../components/node/NodeList'
import PathProgress from '../components/graph/PathProgress'
import WritingProgress from '../components/graph/WritingProgress'
import { clearResume, markResume, readResume } from '../lib/resume'
import { useSiteConfig } from '../query/siteConfig'
import NodePanel from '../components/node/NodePanel'

/**
 * ★ 项目页（`F2` · D92）——* 双栏：左节点列表 + 右笔记面板
 *
 * ## ⚠★ 与"图谱画布页"的关系（先划清界）
 *
 * | | 本页 | 画布页（2b，未做） |
 * |---|---|---|
 * | 节点呈现 | **列表**（搜索 + 过滤 + 分页） | 画布（布局 + 拖拽 + 缩放） |
 * | 解决的 | 「**怎么走到某个节点**」 | 「**看清结构关系**」 |
 *
 * ⚠★ 所以本页**刻意简单** ——* 它不是画布的临时替代，* 是笔记层的家 ✅
 *
 * ## ★★ 三条状态口径
 *
 * | # | 状态 | 前端表现 |
 * |---|---|---|
 * | ① | `state=hidden`（管理员隐藏） | ★★ **只有 owner 打得开**（后端 404 其余人）⇒ 顶部横幅显示 `moderation_reason` ✅ |
 * | ② | 私有项目 / 无权 | 404 文案「不存在或无权访问」——* ⛔ 不区分、* ⛔ 不提示"其实存在" ✅ |
 * | ③ | 未定版（图还没解析） | 节点列表空态引导去工作区拉取 ✅ |
 */
export default function ProjectPage() {
  const { projectRef = '' } = useParams<{ projectRef: string }>()
  const project = useProject(projectRef)
  // ★ `?think=1` ⇒ 自动选中首个节点并打开思考白板（* 首页「思考模式」卡片直达）⚠
  const navigate = useNavigate()
  const [sp] = useSearchParams()
  const autoThink = sp.get('think') === '1'
  /**
   * ★★ `?node=<vid>` 深链（`D120`）—— 「继续上次」跳回来时用 ⚠
   * ⚠ vid 是 stable_vid；解析失败就当没传 ✅
   */
  const deepVid = Number(sp.get('node') || 0) || undefined
  const siteCfg = useSiteConfig()
  const dwellMs = Math.max(0, Number(siteCfg.data?.resumeDwellSeconds ?? 20)) * 1000
  const [selected, setSelected] = useState<GraphNode | null>(null)
  // ★★ 窄屏 ⇒ 单列（* 否则 320px 列表 + 60px 正文，挤成一长条）⚠
  const isNarrow = useMediaQuery('(max-width: 900px)')
  // ★ 代码工作区（顶栏「源码」按钮打开；关闭后回到原来的两栏）
  const [codeOpen, setCodeOpen] = useState(false)

  // ★★★ 2026-11-05：**左栏可拖动改宽** ⚠
  //   所有者：「列表页也要像图谱页有左右拉伸的功能呀。」
  //   口径与图谱页一致（`ProjectGraphPage` 的 panelWidth）：
  //     · 左栏最小 220、右栏最小 320、分隔条 4px
  //     · 上限是**动态**的（容器宽 − 右栏最小 − 分隔条），⛔ 不是写死的
  const mainRef = useRef<HTMLDivElement>(null)
  const [listWidth, setListWidth] = useState(300)
  const resizeRef = useRef<{ startX: number; startW: number } | null>(null)
  const MIN_LIST = 220
  const MIN_NOTE = 320
  const RESIZER = 4

  const clampList = (w: number) => {
    const inner = mainRef.current?.clientWidth ?? window.innerWidth
    const max = Math.max(MIN_LIST, inner - RESIZER - MIN_NOTE)
    return Math.min(max, Math.max(MIN_LIST, w))
  }
  const onResizeMove = (e: PointerEvent) => {
    if (!resizeRef.current) return
    // ★ 向右拖 ⇒ 左栏变宽（与图谱页"向左拖右栏变宽"方向对称）
    const next = resizeRef.current.startW + (e.clientX - resizeRef.current.startX)
    setListWidth(clampList(next))
  }
  const onResizeEnd = () => {
    resizeRef.current = null
    window.removeEventListener('pointermove', onResizeMove)
    window.removeEventListener('pointerup', onResizeEnd)
  }
  const onResizeStart = (e: React.PointerEvent) => {
    e.preventDefault()
    resizeRef.current = { startX: e.clientX, startW: listWidth }
    window.addEventListener('pointermove', onResizeMove)
    window.addEventListener('pointerup', onResizeEnd)
  }
  useEffect(() => {
    const onWin = () => setListWidth((w) => clampList(w))
    window.addEventListener('resize', onWin)
    return () => {
      window.removeEventListener('resize', onWin)
      onResizeEnd()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * ★★★ 「继续上次」的**记录时机**（`D120`③ · 2026-10-27）⚠
   *
   * ```\n   * ⛔ 每次点击就记   ⇒ 存档漂移到「只是瞟了一眼」的节点\n   * ⛔ 只在写笔记时记 ⇒ 读两小时没写字，回来没存档\n   * ✅ 停留 ≥ 阈值 才记（阈值后台可调，0 = 关闭）\n   * ```\n
   * ⚠ 切换节点会清掉上一个计时器 —— 只有「待够久」的那个才算 ⚠
   */
  useEffect(() => {
    if (!selected || !projectRef) return
    if (dwellMs <= 0) return // ★ 0 = 关闭「继续上次」✅
    const vid = selected.vid
    const nm = selected.name
    const t = window.setTimeout(() => markResume(projectRef, vid, nm), dwellMs)
    return () => window.clearTimeout(t)
  }, [selected, projectRef, dwellMs])

  const p = project.data
  // ★★★ 解析状态是**写笔记的门槛**（所有者 2026-10-29）：
  //   解析出错 ⇒ 禁止写；只有重新解析成功、图完整了才放开
  const parseState = (p as unknown as { parse_state?: string })?.parse_state || 'ok'
  const parseOk = parseState !== 'failed'
  /** ★ 没有源码目录 = 手动结构（节点与连线全靠手补）*/
  const isBlank = !!(p as unknown as { is_blank?: boolean })?.is_blank
  // ★ 个人版：**没有身份判断** —— 能打开软件就能写（只受"解析成功"约束）
  const canWrite = parseOk

  // ★★ 存档指向的项目已经打不开 ⇒ 清掉存档（`D120` 防御）⚠
  //   · · 否则首页那条「继续」永远指向一个 404，点一次烦一次 ⚠
  if (project.isError) {
    const rp = readResume()
    if (rp && rp.ref === projectRef) clearResume()
    return (
      <AppLayout title="项目">
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>不存在或无权访问</div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
            {errorMessage(project.error)}
          </div>
          <div className="mt-4">
            <Link to="/workspace">
              <Button>回工作区</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  if (project.isLoading || !p) {
    return (
      <AppLayout title="项目">
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      </AppLayout>
    )
  }

  return (
    <AppLayout
      // ★★★ 不传 title / 不用 `.page` 容器 ——* 两个白面板要**尽量宽**，
      //   * 只留一点点左右边距（* 所有者：「两个白色区域要更宽一点呀，左右留出
      //   很多空白」）⚠
      page={false}
    >
      {/* ★★★ 顶栏工具条（公共组件 PageBar）⚠ */}
      {/* ★★★ 2026-11-05：只保留**顶栏这一处**入口 ⚠
          所有者：「原来的按钮没去掉吗？」——页面内那行「图谱 / 设置」已删除，
          否则同一个动作在顶栏和正文里各出现一次 */}
      <PageBar>
        <RailButton
          icon={<Workflow size={13} />}
          label="图谱"
          title="打开图谱（看它和谁连着）"
          onClick={() => navigate(`/p/${encodeURIComponent(projectRef)}/graph`)}
        />
        <RailButton
          icon={<Settings size={13} />}
          label="设置"
          title="项目设置"
          onClick={() => navigate(`/p/${encodeURIComponent(projectRef)}/settings`)}
        />
        <RailButton
          icon={<FileCode2 size={13} />}
          label="源码"
          title="打开代码工作区（当前节点的源码 + 笔记）"
          active={codeOpen}
          onClick={() => setCodeOpen((v) => !v)}
        />
      </PageBar>

      {/* ★★ 内容区：* 左右只留 18px（移动 10px）⇒* 白面板尽量宽 ⚠ */}
      <div style={{ padding: isNarrow ? '0 10px' : '0 18px' }}>
      

      {p.desc && (
        <div className="faint" style={{ fontSize: 12.5, marginBottom: 12 }}>
          {p.desc}
        </div>
      )}

      {/* ★★★ 双栏（* 窄屏单列）：
          · · 所有者：「这个页面的左边没有列表之类的，完全平铺很长，导致页面看起来
            很怪」——* 列表有 137 个节点却没限高 ⇒ 左栏 5977px，整页被拉成一条长列 ⚠
          · · ★ 左栏**独立滚动**（sticky + maxHeight）⇒ 页面高度只由右栏决定 ✅ */}
      <div
        ref={mainRef}
        style={{
          display: 'grid',
          // ★ 左栏宽度由分隔条决定（拖动改 listWidth）；窄屏仍单列
          gridTemplateColumns: isNarrow ? '1fr' : `${listWidth}px minmax(0, 1fr)`,
          gap: 14,
          alignItems: 'start',
          position: 'relative',
        }}
      >
        <div
          className="card"
          style={{
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            // ★ 桌面：粘在视口内、自己滚；* 窄屏：只占 42vh，避免把页面撑长 ⚠
            position: isNarrow ? 'static' : 'sticky',
            top: isNarrow ? undefined : 76,
            maxHeight: isNarrow ? '42vh' : 'calc(100vh - 96px)',
            overflow: 'hidden',
          }}
        >
          {/* ★★★ 解析没成功 ⇒ 只能修图，不能写笔记（所有者 2026-10-29）⚠ */}
          {!parseOk && (
            <div
              className="card"
              style={{
                padding: '8px 10px',
                marginBottom: 10,
                fontSize: 11.5,
                lineHeight: 1.7,
                borderColor: '#e5c9c9',
                background: 'rgba(200,0,0,.04)',
              }}
            >
              <b>解析没成功，先修好图</b>
              <div className="faint" style={{ marginTop: 2 }}>
                {String((p as unknown as { parse_error?: string })?.parse_error || '图不完整')}
              </div>
              <div className="faint" style={{ marginTop: 4 }}>
                去 <b>图谱 → 改图</b> 底部点「重新解析」；成功后这里会自动放开。
              </div>
            </div>
          )}

          {/* ★ 空白结构（不用源码）还没有节点 ⇒ 指路去改图里加 ⚠ */}
          {isBlank && (p?.node_count ?? 0) === 0 && (
            <div
              className="card"
              style={{ padding: '9px 11px', marginBottom: 10, fontSize: 11.5, lineHeight: 1.8 }}
            >
              <b>这是手动结构</b>
              <div className="faint" style={{ marginTop: 2 }}>
                去 <b>图谱 → 改图</b>：底部加一个节点，再点列表里的「连」把关系接起来。
                有了节点就能在它下面写笔记。
              </div>
            </div>
          )}

          {/* ★★★ 写作进度（覆盖率）—— 只有作者/协作者看得到（`D123`）⚠ */}
          {/* ★ 空白结构**不显示进度**（所有者：「这种空白的就不要显示进度了」）⚠ */}
          {canWrite && !isBlank && <WritingProgress projectRef={projectRef} />}

          {/* ★★ 导读路径 —— 阅读顺序（* 读者看这个，⛔ 不是"进度"）⚠ */}
          <PathProgress projectRef={projectRef} />

          <div className="flex items-center justify-between mb-2.5" style={{ flexShrink: 0 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>节点</span>
            <span className="faint" style={{ fontSize: 11 }}>
              {p.node_count ?? 0} 个
            </span>
          </div>
          {/* ★ 列表区**独立滚动**（* minHeight:0 是关键，否则 flex 子项不肯缩）⚠ */}
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
            <NodeList
              projectRef={projectRef}
              selectedUid={selected?.uid ?? null}
              onSelect={setSelected}
              // ★★★ 2026-11-05：**总是默认选中第一个节点**
              //   所有者：「不能在图谱和列表页都默认选择第一个节点吗？还需要用户自己点一个？」
              //   ⚠ 只在列表就绪时选一次，之后用户怎么点都不干预
              autoSelectFirst
              // ★★ 点一行 → 图谱里看它 + 直接邻居（图谱页有同一个右栏，能继续写笔记）⚠
              onOpenGraph={(n) =>
                navigate(`/p/${encodeURIComponent(projectRef)}/graph?node=${n.vid}`)
              }
              selectVid={deepVid}
              onOpenCode={() => setCodeOpen(true)}
            />
          </div>
        </div>

        {/* ★★ 左右拖动调整宽度（与图谱页同款手感：透明条，悬停变强调色）⚠ */}
        {!isNarrow && (
          <div
            onPointerDown={onResizeStart}
            title="拖动调整宽度"
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: listWidth + (14 - RESIZER) / 2,
              width: RESIZER,
              cursor: 'col-resize',
              background: 'transparent',
              transition: 'background .15s',
              zIndex: 5,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--accent)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          />
        )}

        {/* ★★★ 右侧**始终是一整块白色面板**（* 所有者：「右边的写作区也没有白色
            背景填满，而且没有一开始就出现」）——
            · · ⛔ 不再依赖 NodePanel 自己画卡：* 没选节点时它返回空态、没有背景 ⚠
            · · ★ 背景/边框/最小高度由这层统一给，* NodePanel 传 `flat` ✅ */}
        <div
          className="card"
          style={{
            minHeight: isNarrow ? 320 : 480,
            display: 'flex',
            flexDirection: 'column',
            padding: 0,
            overflow: 'hidden',
          }}
        >
          {/* ★★★ 右栏直接贴**同一个** CodeWorkspace（文件树 / 代码·笔记 tab / 三枚按钮全都有）
              ⚠ 空间窄就点右上角第一个按钮收起文件树 —— 那个按钮本来就是为这件事设计的 */}
          <CodeWorkspace
            projectRef={projectRef}
            node={selected}
            initialTab="notes"
            notePanel={
              <NodePanel
                projectRef={projectRef}
                node={selected}
                canWrite={canWrite}
                autoThink={autoThink}
                flat
              />
            }
          />
        </div>
      </div>

      </div>

      {/* ★★★ 代码工作区：占满内容区（顶栏仍在），关闭即回到原两栏 ⚠ */}
      {codeOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 'var(--nav-h, 40px) 0 0 0',
            zIndex: 90,
            background: 'var(--card, #fff)',
          }}
        >
          <CodeWorkspace
            projectRef={projectRef}
            node={selected}
            onClose={() => setCodeOpen(false)}
          />
        </div>
      )}
    </AppLayout>
  )
}
