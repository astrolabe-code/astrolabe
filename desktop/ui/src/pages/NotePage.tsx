import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { GitBranch, List, ListTree, Lock, Pencil, X } from 'lucide-react'
import { ApiRequestError, errorMessage } from '../api/errors'
import { useNote, useUpdateNote } from '../query/notes'
import { cardId } from '../api/code'
import { useProject } from '../query/projects'
import AppLayout from '../components/AppLayout'
import { PageBar, RailButton } from '../components/PageBar'
import Button from '../components/ui/Button'
import SplitPane from '../components/SplitPane'
import MilkdownLazy from '../components/notes/MilkdownLazy'
import AnchorPicker from '../components/notes/AnchorPicker'
import { kindMeta } from '../components/notes/kindMeta'
import { extractToc, scrollToHeading } from '../lib/toc'
import { useCollapsed } from '../lib/useCollapsed'
import { setTabTitle } from '../lib/tabBus'
import { setNotePaneTitle } from '../lib/notePaneBus'

/** ★ embedded 时用「铺满容器的滚动壳」代替整页 .page 外壳，业务 JSX 原样包裹 */
function NoteShell({ children, embedded }: { children: ReactNode; embedded?: NoteEmbeddedProps }) {
  // ★ 独立页：包一层标记，让 CSS 给 .page 一个确定高度（flex:1 才撑得满）
  if (!embedded) return (
    <div className="note-pane-root note-page-full">
      <AppLayout>{children}</AppLayout>
    </div>
  )
  return (
    <div
      className="note-pane-root note-pane-body"
      style={{
        flex: 1,
        minHeight: 0,
        // ★ flex 列 ⇒ 里面的 .note-layout 能 flex:1 撑满整个容器高度
        display: 'flex',
        flexDirection: 'column',
        overflow: 'auto',
        padding: '10px 16px',
      }}
    >
      {children}
    </div>
  )
}

/** 标题字号按长度分档（`D112`⑥ 实测：25 字 22px = 624px，可用 712px）⚠ */
function titleSize(len: number): number {
  if (len <= 12) return 26
  if (len <= 18) return 24
  return 22
}

/**
 * ★ 笔记阅读页（`F3` · `/p/:projectRef/notes/:noteId`）
 *
 * ## ★★ 为什么必须是独立页（* ⛔ 不是抽屉 / 弹窗）
 *
 * ```
 * ★★ 评论 / 点赞 / 段评都挂在**笔记**上（* 不是节点）⇒* 它需要一个
 *   「能停下来读」的地方：* 可分享的 URL + 足够的纵向空间 ✅
 * ★★ 而 F2 的编辑器是 **Modal**（* 顺手改一笔就走）—— * 两件事形态不同，
 *   * ⛔ 不硬塞进同一个容器 ✅
 * ```
 *
 * ## ★★ 页面结构（* 自上而下）
 *
 * | 块 | 内容 |
 * |---|---|
 * | ① | 头部：* 返回项目 ·* kind 徽标 ·* 标题 ·* 作者/时间 ·* **章赞** ·* 编辑入口 |
 * | ② | 正文：* 按**后端 blocks** 逐段渲染（* `B188`：* 段落按空行分隔）✅ |
 * | ③ | 每段：* 段赞 + 写段评 + 该段的段评（* 默认折叠） |
 * | ④ | 章评区：* 输入框 + 列表（* 含失锚段评，* 后端已按策略并入） |
 *
 * ⚠★ 隐藏态（* `state=hidden`）：* **只有作者看得见** ⇒* 这里看到就打横幅 ✅
 * ⚠★ markdown 渲染**本批不做**（* 按段纯文）——* 段评锚点本来就在段上，* 不影响使用；
 *   * 上 markdown 渲染是后面一件独立的小事 ✅
 */
/** ★ 段评浮层宽度（* 窄屏铺满，宽屏 420）⚠ */
function panelWidth(): number {
  return Math.min(420, window.innerWidth - 24)
}

/**
 * ★★ **段评浮层的落点**（2026-10-23）⚠
 *
 * ## ★★★ 所有者原话（逐字）
 *
 * > 「翻来翻去的干啥？固定段评窗口长度，然后加滑块。」
 *
 * ## ★ 规则（⛔ 不再按空间翻上翻下）
 *
 * ```
 * 高度**固定**（420 或 58vh 取小）· 内容长就在面板内部滚动（有滑块）
 * 位置**永远贴在锚点下方** 8px
 * 只做一件事：整块超出视口底部时，* 把整个面板往上推回视口内（⛔ 不翻到上方）
 * ```
 */


/** ★ 2026-11-09：嵌进工作区容器时的可选参数（⛔ 不改任何业务逻辑） */
export interface NoteEmbeddedProps {
  projectRef?: string
  noteRef?: string
  /** 容器内的「跳转」：把站内路径交给 notePaneBus 翻译成容器动作 */
  onNavigate?: (path: string) => void
  /** 页面工具挂到工作区自己的插槽，避免与外层页面工具混在一起 */
  toolsSlotId?: string
}

export default function NotePage(embedded?: NoteEmbeddedProps) {
  const { projectRef: routeProject = '', noteId = '' } = useParams<{ projectRef: string; noteId: string }>()
  // ★ 路由里的这一段现在是**笔记 ref**（* 不是自增 pk）⚠
  // ★ embedded 时改由容器注入（此时 URL 仍是项目/图谱页）
  const projectRef = embedded?.projectRef ?? routeProject
  const ref = embedded?.noteRef ?? noteId
  const note = useNote(ref || null)
  const project = useProject(projectRef)
  const routerNav = useNavigate()
  const nav = embedded?.onNavigate ?? routerNav
  const [anchorOpen, setAnchorOpen] = useState(false)
  // ★ 右栏目录可折叠（与编辑页同款 hook；key 独立，两边互不干扰）
  const { collapsed: tocFolded, toggle: toggleToc } = useCollapsed('read-toc')
  const slotId = embedded?.toolsSlotId

  const n = note.data?.note
  // ★★ 改锚点用（`D125`）—— 必须放在 `n` 之后（* 它要 `n.ref`）⚠
  const updateNote = useUpdateNote(n?.ref)
  const blocks = note.data?.blocks || []

  // ★ 标签栏显示笔记真实标题：独立路由改 tabBus，内嵌 pane 报给 notePaneBus
  const loc = useLocation()
  useEffect(() => {
    if (!n?.title) return
    if (embedded) setNotePaneTitle(n.title)
    else setTabTitle(loc.pathname, n.title)
  }, [n?.title, loc.pathname, embedded])


  // ★★ 可写 = 作者 ∨ 项目成员（* `B207`③）✅
  // ★ 个人版：没有身份判断 —— 能打开就能编辑
  const canWrite = !!n
  // ★★ 删除判据上下文（* 逐条判：* 评论作者本人 / 项目成员 / 管理员，* `B207`⑤）✅

  if (note.isError) {
    return (
      <NoteShell embedded={embedded}>
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          {/* ★ 从搜索结果点进来时，索引可能比库慢半拍 ⇒ 明确告诉他"被移除了" ⚠ */}
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {note.error instanceof ApiRequestError && note.error.status === 404
              ? '这篇笔记已经被移除了'
              : '不存在或无权访问'}
          </div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
            {note.error instanceof ApiRequestError && note.error.status === 404
              ? '可能是作者删除了，或者被管理员隐藏了。'
              : errorMessage(note.error)}
          </div>
          <div className="mt-4">
            <Link to={`/p/${encodeURIComponent(projectRef)}`}>
              <Button>回项目</Button>
            </Link>
          </div>
        </div>
      </NoteShell>
    )
  }

  if (note.isLoading || !n) {
    return (
      <NoteShell embedded={embedded}>
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      </NoteShell>
    )
  }

  const meta = kindMeta(n.kind)
  const Icon = meta.icon
  // ★ 名字标题永远有（手写 or 服务端兜底的 25 字，`D112`）⚠
  const titleText = n.title || '（无标题）'
  /**
   * ★ 点目录 ⇒ 滚到对应标题（2026-10-26）⚠
   *
   * ⚠ 不靠锚点 id：Milkdown 渲染的标题没有 id，
   *   所以在 `.ProseMirror` 里按「级别 + 文字」找那个元素再滚 ⚠
   *   · · 找不到就退回滚到正文顶部（至少有个反应）✅
   */
  const jumpToHeading = (text: string, level: number) =>
    scrollToHeading(text, level, '.note-body-card .ProseMirror', 'note-body')
  const toc = extractToc(n.body || '')
  const displayName = n.created_by_display || n.created_by || ''

  return (
    <NoteShell embedded={embedded}>
      {/* ★★★ 顶栏工具条（公共组件 PageBar）⚠ */}
      <PageBar slotId={slotId}>
        {/* ★ Obsidian 口径：顶栏的大纲开关（高亮 = 面板展开），
            点一下整块面板消失、正文自动铺满 */}
        <RailButton
          icon={<ListTree size={13} />}
          label="大纲"
          title={tocFolded ? '显示大纲（目录）' : '隐藏大纲（目录）'}
          active={!tocFolded}
          onClick={toggleToc}
        />
        <RailButton
          icon={<List size={13} />}
          label="节点"
          title="回到节点列表"
          onClick={() => nav(`/p/${encodeURIComponent(projectRef)}`)}
        />
        {/* ★★ 深入在**阅读页**：看着这篇继续想，新开一张空白笔记挂成子代
            （所有者：「深入按钮不要在编辑页，要在阅读页呀」） */}
        {n && (
          <RailButton
            icon={<GitBranch size={13} />}
            label="深入"
            title="在这篇基础上继续写：新开一张空白笔记，挂成它的子代"
            onClick={() =>
              nav(
                `/p/${encodeURIComponent(projectRef)}/notes/new?node=${
                  n.node_snapshot?.vid ?? n.node_id ?? 0
                }` +
                  `&parent=${encodeURIComponent(cardId(projectRef, n.ref || ref))}` +
                  `&from=${encodeURIComponent(
                    `/p/${encodeURIComponent(projectRef)}/notes/${ref}`,
                  )}`,
              )
            }
          />
        )}
      </PageBar>

      {/* ★★★ 2026-11-09（所有者）：
          「阅读页左边不需要用户标签和说明挂在哪里，只需要一个可以折叠的
            目录或者说大纲就行，跟编辑页一样」
          ⇒ 作者卡 / 「挂在哪个节点」卡整块删掉，左栏只留可折叠目录。
          折叠状态存 localStorage（useCollapsed('read-toc')），与编辑页独立。
          ⚠ 「改挂到别的节点」功能不删 —— 移到文末操作条，跟「编辑」并排。 */}
      {/* ★★ 2026-11-11：内层改用统一的 SplitPane（嵌套二分页）
          · DOM 顺序 = children 顺序：纸在左、大纲在右，⛔ 不再靠 CSS order
          · 折叠走 collapsed 接口；隐藏按钮仍用顶栏「大纲」/ 面板 ×
          · preserveChildStyle：纸与大纲的边框由 CSS 管，别被组件抹掉 */}
      <SplitPane
        className="note-layout"
        fixed="right"
        initial={264}
        min={200}
        otherMin={240}
        collapsed={tocFolded}
        preserveChildStyle
      >
        <div className="note-article">
          

          {/* 纸：名字标题 + 信息行 + 正文 + 文末操作，全在一张卡里 ⚠ */}
          <div className="card note-body-card flex flex-col">
            {/* ★★★ 「名字」标题：居中 + 字距 2px + 独立颜色
                ⇒ 一眼看出「这是哪篇」而不是「哪一章」⚠ */}
            <h1 className="note-title" style={{ fontSize: titleSize(titleText.length) }}>
              {titleText}
            </h1>

            {/* ★ 信息行：编号 · 类型 · 私有 · 作者 · 时间 ⚠ */}
            <div className="note-meta">
              <span className="note-no">№{String(n.seq || 0).padStart(3, '0')}</span>
              {/* ★ 类型徽标用该类型的专属色（所有者：「这些还要有颜色呀」）⚠ */}
              <span
                style={{
                  fontSize: 10.5,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 3,
                  whiteSpace: 'nowrap',
                  padding: '1px 8px',
                  borderRadius: 999,
                  lineHeight: '16px',
                  color: meta.color,
                  border: `1px solid ${meta.color}`,
                  background: 'transparent',
                }}
              >
                <Icon size={11} />
                {meta.label}
              </span>
              {!n.is_public && (
                <span
                  className="tag"
                  style={{
                    fontSize: 10.5,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 3,
                    whiteSpace: 'nowrap',
                  }}
                  title="只有作者可见"
                >
                  <Lock size={10} />
                  私有
                </span>
              )}
              <span>
                <Link to={`/u/${encodeURIComponent(n.created_by)}`} style={{ color: 'inherit' }}>
                  {displayName}
                </Link>{' '}
                · {n.created_at?.replace('T', ' ').slice(0, 16)}
              </span>
            </div>
            {/* ②③ 正文：整篇 Milkdown 只读渲染（`D108` / `B242`）
                ★★ 段评气泡由 MilkdownView 用 ProseMirror Decoration 挂在段落末尾 ✅ */}
            <div id="note-body" className="flex flex-col gap-5">
              <MilkdownLazy
                text={n.body || ''}
                blocks={blocks}
              />
            </div>

            {/* ★★★ 文末操作条（`D111`④）：章赞在左、编辑/管理在右且更小 ⚠ */}
            <div className="note-foot">
              {/* ★ 点赞是社区功能（需要"别人"）⇒ 个人版不渲染 ⚠ */}
              
              <span className="note-foot-hint">读到这里才点得顺手</span>
              <span className="note-foot-right">
                {canWrite && (
                  <>
                    {/* ★ 左栏「挂在哪个节点」卡撤掉后，改挂入口移到文末操作条 */}
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => setAnchorOpen(true)}
                      title="把这篇笔记改挂到别的节点"
                    >
                      <GitBranch size={12} /> 改挂
                    </button>
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => nav(`/p/${encodeURIComponent(projectRef)}/notes/${n.ref}/edit`)}
                    >
                      <Pencil size={12} /> 编辑
                    </button>
                  </>
                )}
                </span>
            </div>
          </div>

          {/* ④ 章评区 —— ★ 个人版没有第二个用户，评论没有对象 ⇒ 整块不渲染 ⚠ */}
          
        </div>

        {/* ------------------------------------------------------ 大纲（右栏） */}
        <aside className="note-rail">
          <div className="note-rail-card note-toc">
            {/* ★ 面板自己的一行工具条：标题 + ×（Obsidian 口径） */}
            <div className="note-toc-head">
              <h4>大纲</h4>
              <button type="button" onClick={toggleToc} title="关闭大纲（顶栏可再打开）" aria-label="关闭大纲">
                <X size={13} />
              </button>
            </div>
            {toc.length === 0 ? (
              <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.8 }}>
                还没有章节。
                <br />
                正文里用 <code>#</code> 开头写一行，就会出现在这里。
              </div>
            ) : (
              toc.map((h, i) => (
                <button
                  key={`${h.text}-${i}`}
                  type="button"
                  onClick={() => jumpToHeading(h.text, h.level)}
                  className={h.level > 1 ? `lv${Math.min(h.level, 3)}` : ''}
                >
                  {h.text}
                </button>
              ))
            )}
          </div>
        </aside>
      </SplitPane>


      {/* ⑤ **选中文字后的浮动工具条**（* 一行按钮，以后可加更多）⚠
            · · ⛔ 不再用右键：所有者：「不要右键弹出评论按钮了……评论按钮和
              原生的浏览器右键弹窗同时出现了」⚠ */}
      

      

      {/* ★★ 改锚点弹窗（`D125`）⚠ */}
      <AnchorPicker
        open={anchorOpen}
        projectRef={projectRef}
        currentVid={n.node_snapshot?.vid}
        onClose={() => setAnchorOpen(false)}
        onPick={(vid) => {
          updateNote.mutate({ node_id: vid })
          setAnchorOpen(false)
        }}
      />

    </NoteShell>
  )
}
