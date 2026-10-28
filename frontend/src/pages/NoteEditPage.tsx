import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Lock, LockOpen, Trash2 } from 'lucide-react'
import type { NoteKind } from '../api/types'
import { errorMessage } from '../api/errors'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import Modal from '../components/ui/Modal'
import MilkdownEditor, { type MilkdownEditorApi } from '../components/notes/MilkdownEditor'
import { NOTE_KINDS, KIND_META, kindMeta } from '../components/notes/kindMeta'
import { autoTitle } from '../components/notes/autoTitle'
import { markResume } from '../lib/resume'
import { extractToc, scrollToHeading, type TocItem } from '../lib/toc'
import { useCollapsed } from '../lib/useCollapsed'
import { useCreateNote, useDeleteNote, useNote, useUpdateNote } from '../query/notes'

/**
 * ★★ **笔记编辑页**（`/p/:projectRef/notes/new` · `/p/:projectRef/notes/:noteId/edit`）⚠
 *
 * ## ★★★ 为什么从弹窗改成独立页面
 *
 * 所有者（2026-10-23，逐字）：「**编辑markdown文档不要整一个弹窗了，直接一个新页面。
 * 弹窗太挤了。**」
 *
 * ```
 * 弹窗（旧）：宽 760，正文区高 300 左右 —— * 写长文像在邮票上写字 ⚠
 * 页面（新）：整屏高度，正文跟随视口 —— * 写长文、看结构都舒服 ✅
 * ```
 *
 * ## ★ 入口
 *
 * ```
 * 新建：/p/<ref>/notes/new?node=<nodeId>
 * 编辑：/p/<ref>/notes/<noteId>/edit
 * ```
 *
 * ## ⚠ 口径（与旧弹窗一致，别丢）
 *
 * | # | 口径 | 依据 |
 * |---|---|---|
 * | ① | `kind` 五选一固定（⛔ 不让用户自定义） | `B201` |
 * | ② | 标题可留空（后端自动取正文前几字） | `B187` |
 * | ③ | 「私有」开关默认开（即公开） | `B187` |
 * | ④ | 保存后段落由后端重算 ⇒ 跳回阅读页拿新 blocks | `B203③` |
 * | ⑤ | ⚠ 图片上传**不提供**（站内不存图片文件） | 所有者 2026-10-23 |
 */
/** ★ SPA 的 basename（`/app`）—— * 与 `main.tsx` 的 BrowserRouter 同源 ⚠ */
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

/** ★ 去掉路径开头的 basename（* 已经是路由相对路径时原样返回）⚠ */
function stripBase(path: string): string {
  if (!BASE) return path
  if (path === BASE) return '/'
  if (path.startsWith(`${BASE}/`)) return path.slice(BASE.length)
  return path
}


export default function NoteEditPage() {
  const { projectRef = '', noteId } = useParams()
  const [sp] = useSearchParams()
  const nav = useNavigate()

  const editing = Boolean(noteId)
  // ★ 路由这一段是**笔记 ref**（* 不是自增 pk）⚠
  const id = noteId ?? null
  // ★ 新建时 node 从 query 来（* 弹窗时代是 props，* 页面化后只能走 URL）⚠
  const nodeId = Number(sp.get('node') || 0)
  // ★★ 来源页（* 从节点面板进来时带）：保存后回跳 ⚠
  //   · · ⛔ 只接受站内相对路径 —— 防开放重定向 ⚠
  //   · · ⚠★ 必须**剥掉 SPA 的 basename**（`/app`）：
  //       `location.pathname` 是浏览器地址、含 `/app`，
  //       而 `nav('/app/p/…')` 会被路由再叠一层 ⇒ `/app/app/p/…`
  //       ⇒ 匹配不到任何路由 ⇒ 掉回首页（所有者实测踩到）⚠
  const rawFrom = sp.get('from') || ''
  const from = rawFrom.startsWith('/') && !rawFrom.startsWith('//') ? stripBase(rawFrom) : ''

  const noteQ = useNote(id)
  const note = noteQ.data?.note

  const [kind, setKind] = useState<NoteKind>('flash')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [isPublic, setIsPublic] = useState(true)
  const [err, setErr] = useState('')
  const [hint, setHint] = useState('')
  // ★ 保存确认弹窗（`D112` 补）⚠
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')
  const [suggested, setSuggested] = useState('')
  const [pendingText, setPendingText] = useState('')
  // ★ 字数（`D129`）：**停止输入 1 秒**后算一次 —— 所有者明确要求，⛔ 不许每击键算 ⚠
  const [chars, setChars] = useState(0)
  const countTimer = useRef<number | null>(null)
  /**
   * ★★★ 写作区目录（`D131` · 2026-10-27）⚠
   *
   * 所有者：「**写作区加个目录，可折叠的，更好一点**」
   *
   * ⚠ 目录跟着**字数那次 1 秒防抖**一起更新 —— 同一份 markdown，一次计算，
   *   ⛔ 不为它单独再接一个 onChange（那会多一次整篇序列化）⚠
   */
  const [heads, setHeads] = useState<TocItem[]>([])
  const { collapsed: tocFolded, toggle: toggleToc } = useCollapsed('edit-toc')
  /** ★ 初值灌进编辑器**只做一次**（* 否则一改就重建编辑器、光标丢失）⚠ */
  const [ready, setReady] = useState(!editing)
  const editorApi = useRef<MilkdownEditorApi | null>(null)

  const create = useCreateNote(projectRef)
  const update = useUpdateNote(id)
  const del = useDeleteNote()
  const busy = create.isPending || update.isPending || del.isPending

  /**
   * ★★ 字数统计（`D129` · 2026-10-27）⚠
   *
   * ⚠ 所有者：「**要加字数统计，停止输入一秒后计数就行，不要弄出抖动**」
   *
   * ⚠ 这次接 `onChange` 是**安全**的，和 `D128` 那个抖动不是一回事：
   *   · · 这里**只更新 `chars`**，⛔ 绝不回写 `body`
   *   · · 而 `MilkdownEditor` 的 `initial={body}` 因此**永远不变**
   *     ⇒ `useEditor` 的依赖不变 ⇒ 编辑器不会被重建 ✅
   *   · · 再加上 1 秒防抖：长文连打时也不会频繁重渲染 ⚠
   */
  const scheduleCount = (md: string) => {
    if (countTimer.current) window.clearTimeout(countTimer.current)
    countTimer.current = window.setTimeout(() => {
      setChars(md.replace(/\s/g, '').length)
      setHeads(extractToc(md))
    }, 1000)
  }

  useEffect(() => {
    return () => {
      if (countTimer.current) window.clearTimeout(countTimer.current)
    }
  }, [])

  // ★ 编辑模式：数据到了才灌初值
  useEffect(() => {
    if (!editing || ready || !note) return
    setKind(note.kind)
    setTitle(note.title ?? '')
    setBody(note.body ?? '')
    setIsPublic(note.is_public)
    setChars((note.body ?? '').replace(/\s/g, '').length)
    setHeads(extractToc(note.body ?? ''))
    setReady(true)
  }, [editing, ready, note])

  // ★ 拖/粘图片的提示 4 秒后消失
  useEffect(() => {
    if (!hint) return
    const t = setTimeout(() => setHint(''), 4000)
    return () => clearTimeout(t)
  }, [hint])

  const back = () => {
    if (editing && id) nav(`/p/${encodeURIComponent(projectRef)}/notes/${id}`)
    else nav(`/p/${encodeURIComponent(projectRef)}`)
  }

  /**
   * ★★★ 点「保存」→ **先弹确认**（`D112` 补 · 2026-10-27）⚠
   *
   * 所有者原话（逐字）：
   *   「**你那个写作页面，抖动太厉害了，不要每次输入都记录了，
   *     否则遇到不兼容的浏览器就完蛋了。用户点击保存后，再弹出标题确认就好。**」
   *
   * ⚠ 为什么必须改：原来 `onChange` 每 300ms 把正文写回 state，
   *   而编辑器是 `<MilkdownEditor initial={body}>`、`useEditor` 只依赖 `initial`
   *   ⇒ **每敲几下就把编辑器销毁重建一次**（抖动的真正原因）⚠
   *
   * ⇒ 现在**写的时候一个字都不回写**，只在保存那一刻读一次正文，
   *   顺手算出默认名字，弹窗里让人看一眼、可改 ✅
   */
  const requestSave = () => {
    setErr('')
    // ★★ 正文从**编辑器**读（* Milkdown 序列化结果），* 原样保存、⛔ 不 trim ⚠
    const text = editorApi.current?.getMarkdown() ?? body
    if (!text.trim()) {
      setErr('正文不能为空')
      // ★ 顺手把光标送回正文，* 用户不用再自己找地方点 ⚠
      const el = document.querySelector<HTMLElement>('.milkdown-editor .ProseMirror')
      // ⚠ preventScroll：* 否则浏览器会把页面滚回正文，把按钮旁的提示挤出视口 ⚠
      el?.focus({ preventScroll: true })
      return
    }
    if (!editing && !nodeId) {
      setErr('缺少节点信息，无法新建笔记（请从节点面板进入）')
      return
    }
    // ★ 默认名字：手写优先，否则按正文首行推导（`D112`）⚠
    const auto = autoTitle(text)
    setPendingText(text)
    setSuggested(auto)
    setDraftTitle(title.trim() || auto)
    setConfirmOpen(true)
  }

  const save = async () => {
    const text = pendingText
    // ★ 名字和推导值一致 ⇒ 传空，让后端自己截（* 语义仍是「自动」）⚠
    const finalTitle = draftTitle.trim() === suggested ? '' : draftTitle.trim()
    try {
      const data = editing
        ? await update.mutateAsync({ kind, title: finalTitle, body: text, is_public: isPublic })
        : await create.mutateAsync({
            kind,
            title: finalTitle,
            body: text,
            node_id: nodeId,
            is_public: isPublic,
          })

      // ★★ 写完**立刻**记下位置（`D120` 补口 · 2026-10-27）⚠
      //   · · 停留计时只覆盖「读了一会儿」，⛔ 覆盖不到「停 5 秒写一条就走」⚠
      //   · · 用返回的锚点快照，⛔ 不要再查一次节点 ⚠
      const snap = data?.note?.node_snapshot
      if (snap?.vid) markResume(projectRef, snap.vid, snap.name)
      // ★ 有 from ⇒ 回原处（* 节点面板）；否则回阅读页
      //   · · 阅读页要用后端重算后的 blocks（* 段评锚点）⚠
      nav(from || `/p/${encodeURIComponent(projectRef)}/notes/${data.note.ref}`)
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  const remove = async () => {
    if (!note) return
    const ok = window.confirm(
      `删除「${note.title || '（无标题）'}」？\n删除后可从回收站恢复，评论和点赞都还在。`,
    )
    if (!ok) return
    try {
      await del.mutateAsync(note.ref)
      nav(`/p/${encodeURIComponent(projectRef)}`)
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  // ---- 编辑模式：加载 / 失败 ----
  if (editing && noteQ.isLoading) {
    return (
      <AppLayout title="编辑笔记">
        <div className="faint" style={{ fontSize: 13 }}>
          加载中…
        </div>
      </AppLayout>
    )
  }
  if (editing && (noteQ.isError || !note)) {
    return (
      <AppLayout title="编辑笔记">
        <div className="card" style={{ padding: 24 }}>
          <div className="faint" style={{ fontSize: 12.5 }}>
            这篇笔记打不开 —— 可能已被删除，或者你没有权限。
          </div>
          <div className="mt-4">
            <Button onClick={back}>返回</Button>
          </div>
        </div>
      </AppLayout>
    )
  }

  // ★★ 2026-10-26：**去掉页头大字「编辑笔记」**（所有者：
  //   「编辑页也是一样，有个黑色大字编辑笔记也去掉，解放这部分空间给纸张」）⚠
  //   · · 这个标题只是重复"你正在编辑"，没有信息量 ⚠
  //   · · 编辑态和新建态的切换，靠纸里的类型条和按钮文字已经能看出来 ✅
  // ★★ 纸张描边跟着当前类别走（`D132`）—— 类别挪到底栏后，靠边框颜色自报身份 ⚠
  const kindColor = KIND_META[kind].color

  return (
    <AppLayout>
      {/* ★★★ 写作区两栏（`D131`）：左目录（可折叠）＋ 纸 ⚠
          · · 目录是正文里的 `#` / `##` / `###`（⛔ 不含名字）
          · · 折叠状态记在本地，下次打开还是收着的 ⚠ */}
      <div className={`note-edit-layout${tocFolded ? ' is-folded' : ''}`}>
        <aside className={`note-edit-rail${tocFolded ? ' is-folded' : ''}`}>
          {tocFolded ? (
            <button
              type="button"
              className="note-edit-fold-btn"
              onClick={toggleToc}
              title="展开目录"
            >
              <ChevronRight size={13} />
              <span className="v">目录</span>
            </button>
          ) : (
            <div className="note-rail-card note-toc">
              <div className="note-toc-head">
                <h4>目录</h4>
                <button type="button" onClick={toggleToc} title="收起目录">
                  <ChevronLeft size={13} />
                </button>
              </div>
              {heads.length === 0 ? (
                <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.8 }}>
                  还没有章节。
                  <br />
                  正文里用 <code>#</code> 开头写一行，就会出现在这里。
                </div>
              ) : (
                heads.map((h, i) => (
                  <button
                    key={`${h.text}-${i}`}
                    type="button"
                    onClick={() => scrollToHeading(h.text, h.level, '.milkdown .ProseMirror')}
                    className={h.level > 1 ? `lv${Math.min(h.level, 3)}` : ''}
                  >
                    {h.text}
                  </button>
                ))
              )}
            </div>
          )}
        </aside>

        {/* ★★★ 2026-10-27（`D132`）：**纸张描边 = 当前类别色** ⚠
            所有者：「现在灵光一现等标签，放在底部了，不明显了，能不能给纸张加上
                    对应颜色的描边？让用户能一眼知道，自己在写的什么。」
            · · 2px 实线 + 一圈 3px 同色淡光 —— 有颜色但不刺眼 ✅
            · · ⚠ 别写 1.5px：Chrome 会把边框宽度**向下取整到整数设备像素**，
              1.5px 实际渲染成 1px（实测 computed 仍报 1px）⚠
            · · 改类别时边框**立刻**变色（点底栏胶囊即时反馈）✅ */}
        <div
          className="card note-edit-card"
          style={{
            position: 'relative',
            borderColor: kindColor,
            borderWidth: 2,
            boxShadow: `0 0 0 3px ${kindColor}14, var(--shadow-card)`,
          }}
        >
        {/* ★★ 右上角类别角标（`D132` 补充）：颜色 + 文字都有 ⇒ 不用记"琥珀色=灵光一闪" ⚠
            · · 纯展示，⛔ 不可点（改类别仍在底栏，避免两处都能改而造成困惑）⚠ */}
        <span
          style={{
            position: 'absolute',
            top: 12,
            right: 14,
            padding: '1px 9px',
            fontSize: 11,
            lineHeight: '18px',
            fontFamily: 'var(--font-ui)',
            whiteSpace: 'nowrap',
            color: kindColor,
            background: `${kindColor}14`,
            border: `1px solid ${kindColor}66`,
            borderRadius: 999,
            pointerEvents: 'none',
          }}
        >
          {KIND_META[kind].label}
        </span>

        {/* ② 名字 —— ★★ 2026-10-27 依 CSDN 结构改版：提到**最上、大字** ⚠
            · · 眼睛先落在「要写什么」，而不是「给这篇归哪类」⚠
            · · 但**不强制填**（`D112`：名字只是身份，⛔ 不是文章标题）⚠ */}
        <input
          id="note-title"
          maxLength={60}
          placeholder="名字（可留空）"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          style={{
            width: '100%',
            border: 'none',
            outline: 'none',
            background: 'transparent',
            fontSize: 22,
            fontWeight: 600,
            color: 'var(--text-main)',
            fontFamily: 'var(--font-ui)',
            padding: '2px 96px 10px 0',  /* ⚠ 右边留 96px 给类别角标，长名字不会压上去 ⚠ */
            borderBottom: '1px solid var(--card-border)',
            marginBottom: 6,
          }}
        />
        {/* ★★ 说明行：左边讲「名字」，右边讲「当前类别」（`D134` 修正）⚠
            · · 所有者：「你这个放在顶部不行吗？正好哪里也有一个徽标」
            · · ⇒ 说明不再挤在底栏（那里有保存按钮，抢注意力），
                改到**徽标下面这一行**的右端 —— 正好接住右上角那个角标 ✅
            · · ⛔ 不额外增加高度：和名字说明**同一行**，左右各一边 ⚠ */}
        <div className="faint note-edit-subline">
          <span className="sub-name">
            留空则自动取正文第一行；名字只用于搜索列表，正文里的 <code>#</code> 才是章节标题。
          </span>
          <span className="sub-kind" title={kindMeta(kind).hint} style={{ color: kindColor }}>
            {kindMeta(kind).hint}
          </span>
        </div>

        {/* ③ 正文 —— ★ 无边框、无标签，直接铺在纸上（* 和阅读页的纸一致）⚠ */}
        {ready && (
          <MilkdownEditor
            initial={body}
            apiRef={editorApi}
            onRejectUpload={() => setHint('暂不支持上传图片（站内不存放图片文件）。')}
            onChange={scheduleCount}
          />
        )}
        {hint && <div style={{ marginTop: 8, fontSize: 12, color: 'var(--err)' }}>{hint}</div>}

        {/* ④⑤ 底部常驻操作栏 —— ★★ 元信息（类型 / 公开）从正文上方**沉到这里** ⚠
            · · CSDN 也是这么放的：上面写字，下面设置，底栏常驻 ⚠
            · · `position: sticky` ⇒ 正文再长也不用滚到底找按钮 ✅ */}
        <div className="note-edit-bar">
          {/* 类型：默认灵光一闪，⛔ 不点也不影响（`D117` 零决策）⚠ */}
          {NOTE_KINDS.map((k) => {
            const m = KIND_META[k]
            const active = kind === k
            return (
              <button
                key={k}
                type="button"
                title={kindMeta(k).hint}
                onClick={() => setKind(k)}
                style={{
                  padding: '1px 8px',
                  borderRadius: 999,
                  fontSize: 11,
                  lineHeight: '17px',
                  fontFamily: 'var(--font-ui)',
                  whiteSpace: 'nowrap',
                  cursor: 'pointer',
                  border: `1px solid ${active ? m.color : 'var(--card-border)'}`,
                  background: active ? `${m.color}1f` : 'transparent',
                  color: active ? m.color : 'var(--text-faint)',
                }}
              >
                {m.label}
              </button>
            )
          })}

          {/* 公开 / 私有：从一整行压成一个小开关 ⚠ */}
          <button
            type="button"
            onClick={() => setIsPublic((v) => !v)}
            title={isPublic ? '项目里其他人能看到这篇' : '只有作者本人能看到这篇'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '1px 8px',
              borderRadius: 999,
              fontSize: 11,
              lineHeight: '17px',
              fontFamily: 'var(--font-ui)',
              cursor: 'pointer',
              border: '1px solid var(--card-border)',
              background: 'transparent',
              color: isPublic ? 'var(--text-sub)' : 'var(--text-faint)',
            }}
          >
            {isPublic ? <LockOpen size={11} /> : <Lock size={11} />}
            {isPublic ? '公开' : '私有'}
          </button>

          {/* ★ 字数：固定宽度 + tabular-nums ⇒ 数字变化时**不推动布局** ⚠ */}
          <span
            className="faint"
            style={{
              fontSize: 11.5,
              marginLeft: 'auto',
              width: 62,
              textAlign: 'right',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            共 {chars} 字
          </span>

          {err && (
            <span style={{ color: 'var(--err)', fontSize: 11.5, lineHeight: 1.4 }}>{err}</span>
          )}

          {editing && note && (
            <button
              type="button"
              className="link-btn"
              disabled={busy}
              onClick={remove}
              title="删除这篇笔记（可从回收站恢复）"
              style={{ color: 'var(--text-faint)' }}
            >
              <Trash2 size={12} /> 删除
            </button>
          )}

          <Button onClick={back} disabled={busy}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={requestSave}>
            {editing ? '保存' : '写下'}
          </Button>
        </div>
        </div>
      </div>

      {/*
        ★★★ 保存确认（`D112` 补 · 2026-10-27）——
        所有者：「用户点击保存后，再弹出标题确认就好。」
        · · 写的时候**一个字都不回写**（那才是抖动的根源）
        · · 到这一步才推导名字，让人看一眼、能改 ✅
      */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={editing ? '保存这篇笔记' : '记下这篇笔记'}
        width={480}
        footer={
          <div className="flex items-center gap-2">
            <div style={{ marginLeft: 'auto' }} />
            <Button onClick={() => setConfirmOpen(false)} disabled={busy}>
              再改改
            </Button>
            <Button variant="primary" loading={busy} onClick={() => void save()}>
              确认{editing ? '保存' : '记下'}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <div>
            <label
              className="block text-xs font-medium tracking-wide text-text-sub mb-1.5"
              htmlFor="confirm-title"
            >
              名字（可改）
            </label>
            <input
              id="confirm-title"
              className="input"
              maxLength={60}
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void save()
                }
              }}
            />
          </div>

          {/* ★ 一眼看出「不改的话会叫什么」——⛔ 不给空值，永远有名字 ⚠ */}
          <div
            style={{
              fontSize: 11.5,
              padding: '6px 10px',
              borderRadius: 8,
              background: 'var(--accent-dim)',
              color: 'var(--text-sub)',
              lineHeight: 1.7,
            }}
          >
            留空则按正文首行自动取：
            <b style={{ color: 'var(--text-main)', marginLeft: 4 }}>
              {suggested || '（正文为空）'}
            </b>
            <div style={{ opacity: 0.75, marginTop: 2 }}>
              名字只用于搜索列表和浏览器标签页；正文里的 <code>#</code> 才是章节标题。
            </div>
          </div>
        </div>
      </Modal>
    </AppLayout>
  )
}
