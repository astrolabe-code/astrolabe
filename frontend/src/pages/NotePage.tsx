import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { EyeOff, Lock, Pencil, ShieldAlert } from 'lucide-react'
import { ApiRequestError, errorMessage } from '../api/errors'
import { useNote, useUpdateNote } from '../query/notes'
import { useProject } from '../query/projects'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import LikeButton from '../components/likes/LikeButton'
import CommentSection from '../components/comments/CommentSection'
import ParagraphComments from '../components/comments/ParagraphComments'
import MilkdownLazy from '../components/notes/MilkdownLazy'
import AnchorPicker from '../components/notes/AnchorPicker'
import type { SelectionInfo } from '../components/notes/MilkdownView'
import ModeratePanel from '../components/admin/ModeratePanel'
import { kindMeta } from '../components/notes/kindMeta'
import { extractToc, scrollToHeading } from '../lib/toc'

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
function panelLayout(a: { top: number; left: number; width: number; height: number } | null) {
  const GAP = 8
  const width = panelWidth()
  const height = Math.min(420, Math.round(window.innerHeight * 0.58))

  if (!a) {
    return {
      style: {
        top: Math.max(GAP, Math.round((window.innerHeight - height) / 2)),
        left: Math.max(12, Math.round((window.innerWidth - width) / 2)),
        width,
        height,
      },
      scrollBy: 0,
    }
  }

  const left = Math.max(12, Math.min(a.left, window.innerWidth - width - 12))
  const rawTop = a.top + a.height + GAP
  // ★ 下面放不下 ⇒ **把页面滚一点**（而不是翻到上方，也不盖住选中的字）⚠
  const overflow = Math.max(0, rawTop + height + GAP - window.innerHeight)
  return {
    style: { top: rawTop - overflow, left, width, height },
    scrollBy: overflow,
  }
}


export default function NotePage() {
  const { projectRef = '', noteId = '' } = useParams<{ projectRef: string; noteId: string }>()
  // ★ 路由里的这一段现在是**笔记 ref**（* 不是自增 pk）⚠
  const ref = noteId
  const note = useNote(ref || null)
  const project = useProject(projectRef)
  const me = useMe()
  const nav = useNavigate()
  // ★ 当前打开段评面板的那一段（* 由 Milkdown 里的气泡点击驱动）⚠
  const [activeFp, setActiveFp] = useState('')
  // ★ 右键「选中文字」小菜单 + 面板里预填的引用原文 ⚠
  const [sel, setSel] = useState<SelectionInfo | null>(null)
  const [panelQuote, setPanelQuote] = useState('')
  // ★ 面板贴着哪个位置弹出（* 选区 / 气泡的视口矩形）⚠
  const [panelAnchor, setPanelAnchor] = useState<{ top: number; left: number; width: number; height: number } | null>(null)
  const [moderating, setModerating] = useState(false)
  const [anchorOpen, setAnchorOpen] = useState(false)

  const n = note.data?.note
  // ★★ 改锚点用（`D125`）—— 必须放在 `n` 之后（* 它要 `n.ref`）⚠
  const updateNote = useUpdateNote(n?.ref)
  const blocks = note.data?.blocks || []
  const activeBlock = blocks.find((b) => b.fingerprint === activeFp)

  // ★ 面板下面空间不够 ⇒ 轻轻滚一下页面，* 让它正好落在选中文字下方 ⚠
  useEffect(() => {
    if (!activeBlock || !panelAnchor) return
    const { scrollBy } = panelLayout(panelAnchor)
    if (scrollBy > 0) window.scrollBy({ top: scrollBy, behavior: 'auto' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeBlock, panelAnchor])

  // ★ 点别处 / 滚动 / Esc 都关掉右键小菜单
  useEffect(() => {
    if (!sel) return
    const close = () => setSel(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSel(null)
    }
    // ⚠ 用 mousedown 而不是 click：* 拖选结束时常伴随一次 click，
    //   会在工具条刚出现时又把它关掉（竞争）⚠
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null
      if (t?.closest('.sel-toolbar')) return // 点工具条自身 ⇒ 不关
      if (t?.closest('.milkdown .ProseMirror')) return // 点正文 ⇒ 交给选区上报
      close()
    }
    document.addEventListener('mousedown', onDown, true)
    document.addEventListener('scroll', close, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown, true)
      document.removeEventListener('scroll', close, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [sel])
  const authed = !!me.data?.authenticated
  const canEdit = !!project.data?.can_edit
  const meUsername = me.data?.username
  const isStaff = !!me.data?.is_staff
  // ★★ 可写 = 作者 ∨ 项目成员（* `B207`③）✅
  const canWrite = !!n && (n.created_by === meUsername || canEdit)
  // ★★ 删除判据上下文（* 逐条判：* 评论作者本人 / 项目成员 / 管理员，* `B207`⑤）✅
  const perm = { meUsername, canEdit, isStaff }

  if (note.isError) {
    return (
      <AppLayout>
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
      </AppLayout>
    )
  }

  if (note.isLoading || !n) {
    return (
      <AppLayout>
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      </AppLayout>
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
    <AppLayout>
      {/* ★★★ 2026-10-26（`D111` / `D114`）——
          所有者：「还是要右栏好看一点，不过放在左边」
                  「作者信息要放在目录上边」
                  「这个居中显示，颜色字体与#不太一样就行，这样就真的是标题」
          · · 页头彻底清空：大标题删掉（`D110`），操作移到文末（CSDN 口径）
          · · 左栏 264（作者卡在上 / 目录在下，sticky）＋ 纸 760 ⚠ */}
      <div className="note-layout">
        {/* ---------------------------------------------------------- 左栏 */}
        <aside className="note-rail">
          <div className="note-rail-card">
            <div className="note-author">
              <div className="note-avatar">{(displayName || '?').slice(0, 1)}</div>
              <div style={{ minWidth: 0 }}>
                <div className="note-author-name">
                  <Link
                    to={`/u/${encodeURIComponent(n.created_by)}`}
                    style={{ color: 'inherit', textDecoration: 'none' }}
                  >
                    {displayName}
                  </Link>
                </div>
                <div className="note-author-sub">查看他的空间 →</div>
              </div>
            </div>
          </div>

          {/* ★★★ 「挂在哪个节点」（`D125`）——
              结构要**看得见**：每篇笔记都明确知道自己挂在代码的哪个位置 ⚠ */}
          <div className="note-rail-card">
            <div
              className="faint"
              style={{ fontSize: 11, letterSpacing: 0.5, marginBottom: 6 }}
            >
              挂在
            </div>
            <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.5 }}>
              {n.node_snapshot?.name || '（节点已不存在）'}
            </div>
            <div
              className="faint"
              style={{
                fontSize: 11,
                marginTop: 2,
                fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                wordBreak: 'break-all',
              }}
            >
              {n.node_snapshot?.file_path}
              {n.node_snapshot?.line ? `:${n.node_snapshot.line}` : ''}
            </div>
            {canWrite && (
              <button
                type="button"
                className="link-btn"
                style={{ marginTop: 6, paddingLeft: 0 }}
                onClick={() => setAnchorOpen(true)}
              >
                改挂到别的节点
              </button>
            )}
          </div>

          {/* ★ 正文没有 # 标题就整块不渲染（空框比没有更难看）⚠ */}
          {toc.length > 0 && (
            <div className="note-rail-card note-toc">
              <h4>目录</h4>
              {toc.map((h, i) => (
                <button
                  key={`${h.text}-${i}`}
                  type="button"
                  onClick={() => jumpToHeading(h.text, h.level)}
                  className={h.level > 1 ? `lv${Math.min(h.level, 3)}` : ''}
                >
                  {h.text}
                </button>
              ))}
            </div>
          )}
        </aside>

        {/* ---------------------------------------------------------- 纸 */}
        <div className="note-article">
          {/* 隐藏横幅：只有作者看得到 */}
          {n.state === 'hidden' && (
            <div
              className="card flex items-start gap-2"
              style={{ padding: '10px 14px', marginBottom: 14, borderColor: 'var(--err)' }}
            >
              <EyeOff size={15} style={{ color: 'var(--err)', marginTop: 2 }} />
              <div style={{ fontSize: 12.5, lineHeight: 1.7 }}>
                <b>这篇笔记已被管理员隐藏</b>
                {n.moderation_reason ? `：${n.moderation_reason}` : ''}
                <div className="faint" style={{ fontSize: 11.5 }}>
                  隐藏期间只有你（作者）能看到它。恢复请联系管理员。
                </div>
              </div>
            </div>
          )}

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
                authed={authed}
                onOpenBlock={(b, anchor) => {
                  setPanelQuote('')
                  setPanelAnchor(anchor ?? null)
                  setActiveFp(b.fingerprint)
                }}
                onSelection={(info) => setSel(info)}
              />
            </div>

            {/* ★★★ 文末操作条（`D111`④）：章赞在左、编辑/管理在右且更小 ⚠ */}
            <div className="note-foot">
              <LikeButton noteId={n.ref} anchor="chapter" />
              <span className="note-foot-hint">读到这里才点得顺手</span>
              <span className="note-foot-right">
                {canWrite && (
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => nav(`/p/${encodeURIComponent(projectRef)}/notes/${n.ref}/edit`)}
                  >
                    <Pencil size={12} /> 编辑
                  </button>
                )}
                {isStaff && (
                  <button type="button" className="link-btn" onClick={() => setModerating(true)}>
                    <ShieldAlert size={12} /> 管理
                  </button>
                )}
              </span>
            </div>
          </div>

          {/* ④ 章评区 */}
          <div className="card mt-4" style={{ padding: '16px 18px' }}>
            <CommentSection noteId={n.ref} authed={authed} perm={perm} />
          </div>
        </div>
      </div>

      {/* ⑤ **选中文字后的浮动工具条**（* 一行按钮，以后可加更多）⚠
            · · ⛔ 不再用右键：所有者：「不要右键弹出评论按钮了……评论按钮和
              原生的浏览器右键弹窗同时出现了」⚠ */}
      {/* ⚠★ 必须用 portal 挂到 body：`.page.rise` 上有 `transform`（单位矩阵也算），
            会让 `position: fixed` 相对它定位而不是视口 ⇒ 工具条飘到别处 ⚠ */}
      {sel &&
        createPortal(
          <div
            className="sel-toolbar"
          onMouseDown={(e) => e.preventDefault()}
          style={{
            position: 'fixed',
            // ★★ 贴着选区上沿（* 只留 6px 缝）—— 所有者：「就在选中文字上方一点点就可以了」⚠
            //   · · 用 translateY(-100%) 让**底边**对齐，* 不用猜工具条高度 ✅
            //   · · 太靠页面顶部时改放选区下方，* 避免被裁掉 ⚠
            top: sel.rect.top > 44 ? sel.rect.top - 6 : sel.rect.top + sel.rect.height + 6,
            transform: sel.rect.top > 44 ? 'translateY(-100%)' : undefined,
            left: Math.max(
              8,
              Math.min(
                sel.rect.left + sel.rect.width / 2 - 44,
                window.innerWidth - 108,
              ),
            ),
            zIndex: 90,
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            padding: 3,
            background: 'var(--card)',
            border: '1px solid var(--card-border)',
            borderRadius: 999,
            boxShadow: 'var(--shadow-card-hover)',
          }}
        >
          {[
            {
              key: 'comment',
              label: '评论',
              title: sel.block ? '对选中的文字写段评' : '这段没能对上段落，暂不支持段评',
              disabled: !sel.block,
              run: () => {
                if (!sel.block) return
                setPanelQuote(sel.quote)
                setPanelAnchor(sel.rect)
                setActiveFp(sel.block.fingerprint)
                setSel(null)
              },
            },
            // ★ 以后要加按钮就往这个数组里塞（* 高亮 / 复制 / 引用…）⚠
          ].map((a) => (
            <button
              key={a.key}
              type="button"
              disabled={a.disabled}
              title={a.title}
              onMouseDown={(e) => e.preventDefault()}
              onClick={a.run}
              style={{
                padding: '5px 12px',
                fontSize: 12,
                fontFamily: 'var(--font-ui)',
                lineHeight: 1.2,
                color: a.disabled ? 'var(--text-faint)' : 'var(--text-main)',
                background: 'transparent',
                border: 'none',
                borderRadius: 999,
                cursor: a.disabled ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {a.label}
            </button>
            ))}
          </div>,
          document.body,
        )}

      {/* ④ 段评面板（* 只渲染当前那一段，* 文字由上面的 Milkdown 画）⚠ */}
        {/* ★★ 段评面板：**贴着选中文字 / 气泡**弹出（2026-10-23）⚠
            · · 所有者：「段评的弹窗就贴在选中文字下方弹出呀。现在总是在页面中间，
              要翻很长才能看见」
            · · 用 portal 挂 body：`.page.rise` 的 transform 会让 fixed 相对它定位 ⚠ */}
        {activeBlock &&
          createPortal(
            <div
              className="block-comment-panel"
              style={{
                position: 'fixed',
                ...panelLayout(panelAnchor).style,
                overflow: 'auto', // ★ 固定高度 + 内部滑块（所有者要求）⚠
                zIndex: 95,
                background: 'var(--card)',
                border: '1px solid var(--card-border)',
                borderRadius: 12,
                boxShadow: 'var(--shadow-card-hover)',
                padding: '12px 14px',
              }}
            >
              <ParagraphComments
                noteId={n.ref}
                block={activeBlock}
                authed={authed}
                perm={perm}
                renderText={false}
                panelOpen
                quote={panelQuote}
                onPanelOpenChange={(o) => {
                  if (!o) {
                    setActiveFp('')
                    setPanelQuote('')
                    setPanelAnchor(null)
                  }
                }}
              />
            </div>,
            document.body,
          )}

      {/* ★★ `F4`：管理处置（隐藏 / 下架 / 恢复）—— 仅 staff 能打开 */}
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

      <ModeratePanel
        open={moderating}
        kind="note"
        target={n.id}
        currentState={n.state}
        onClose={() => setModerating(false)}
      />
    </AppLayout>
  )
}
