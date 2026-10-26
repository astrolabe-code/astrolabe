import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Lock, LockOpen, Trash2 } from 'lucide-react'
import type { NoteKind } from '../api/types'
import { errorMessage } from '../api/errors'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import MilkdownEditor, { type MilkdownEditorApi } from '../components/notes/MilkdownEditor'
import { NOTE_KINDS, KIND_META, kindMeta } from '../components/notes/kindMeta'
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
  /** ★ 初值灌进编辑器**只做一次**（* 否则一改就重建编辑器、光标丢失）⚠ */
  const [ready, setReady] = useState(!editing)
  const editorApi = useRef<MilkdownEditorApi | null>(null)

  const create = useCreateNote(projectRef)
  const update = useUpdateNote(id)
  const del = useDeleteNote()
  const busy = create.isPending || update.isPending || del.isPending

  // ★ 编辑模式：数据到了才灌初值
  useEffect(() => {
    if (!editing || ready || !note) return
    setKind(note.kind)
    setTitle(note.title ?? '')
    setBody(note.body ?? '')
    setIsPublic(note.is_public)
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

  const save = async () => {
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
    try {
      const data = editing
        ? await update.mutateAsync({ kind, title, body: text, is_public: isPublic })
        : await create.mutateAsync({
            kind,
            title,
            body: text,
            node_id: nodeId,
            is_public: isPublic,
          })
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
  return (
    <AppLayout>
      <div className="card note-edit-card">
        {/* ① kind 五选一（固定） */}
        <div className="mb-4">
          <div className="text-xs font-medium tracking-wide text-text-sub mb-1.5">类型</div>
          <div className="flex flex-wrap gap-1.5">
            {NOTE_KINDS.map((k) => {
              const m = KIND_META[k]
              const active = kind === k
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() => setKind(k)}
                  title={m.hint}
                  style={{
                    padding: '5px 10px',
                    borderRadius: 999,
                    fontSize: 12.5,
                    cursor: 'pointer',
                    border: `1px solid ${active ? m.color : 'var(--card-border)'}`,
                    background: active ? `${m.color}1f` : 'transparent',
                    color: active ? m.color : 'var(--text-sub)',
                  }}
                >
                  {m.label}
                </button>
              )
            })}
          </div>
          <div className="faint mt-1.5" style={{ fontSize: 11.5 }}>
            {kindMeta(kind).hint}
          </div>
        </div>

        {/* ② 标题（可空） */}
        <div className="mb-4">
          <label
            className="block text-xs font-medium tracking-wide text-text-sub mb-1.5"
            htmlFor="note-title"
          >
            标题（可空）
          </label>
          <input
            id="note-title"
            className="input"
            maxLength={120}
            placeholder="不填就自动取正文前几字"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        {/* ③ 正文：Milkdown 所见即所得（* 高度吃满页面，* 不再是弹窗里的小格子）⚠ */}
        <div className="mb-4">
          <label
            className="block text-xs font-medium tracking-wide text-text-sub mb-1.5"
            htmlFor="note-body"
          >
            正文（markdown）
          </label>
          {ready && (
            <MilkdownEditor
              initial={body}
              apiRef={editorApi}
              onRejectUpload={() => setHint('暂不支持上传图片（站内不存放图片文件）。')}
            />
          )}
          {hint && <div style={{ marginTop: 8, fontSize: 12, color: 'var(--err)' }}>{hint}</div>}
        </div>

        {/* ④ 公开 / 私有 */}
        <button
          type="button"
          onClick={() => setIsPublic((v) => !v)}
          className="flex items-center gap-2 w-full text-left"
          style={{
            padding: '8px 10px',
            borderRadius: 8,
            border: '1px solid var(--card-border)',
            background: 'transparent',
            cursor: 'pointer',
          }}
        >
          {isPublic ? <LockOpen size={14} /> : <Lock size={14} />}
          <span style={{ fontSize: 12.5 }}>{isPublic ? '公开' : '私有'}</span>
          <span className="faint" style={{ fontSize: 11.5 }}>
            {isPublic ? '项目里其他人能看到这篇' : '只有作者本人能看到这篇'}
          </span>
        </button>

        {/* ⑤ **唯一的操作栏**（⚠ 页头不再放按钮 —— 两套按钮所有者已指出太乱）⚠
            删除（编辑态）· 取消 · 保存/写下 —— 写完正好在底部，顺手 ✅ */}
        <div
          className="flex items-center gap-2"
          style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--card-border)' }}
        >
          {editing && note && (
            <Button
              variant="danger"
              icon={<Trash2 size={13} />}
              disabled={busy}
              onClick={remove}
            >
              删除
            </Button>
          )}
          {/* ⚠★ 提示必须挨着按钮 —— 原来放在内容区下面，
                内容空的时窗口没滚动，提示在视口外，点了像没反应 ⚠ */}
          {err && (
            <span style={{ color: 'var(--err)', fontSize: 12, lineHeight: 1.4 }}>{err}</span>
          )}
          <div style={{ marginLeft: 'auto' }} />
          <Button onClick={back} disabled={busy}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={save}>
            {editing ? '保存' : '写下'}
          </Button>
        </div>
      </div>
    </AppLayout>
  )
}
