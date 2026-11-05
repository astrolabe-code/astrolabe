/**
 * ★★★ **顺手写**（`D125` 的配套 · 2026-10-27）⚠
 *
 * ## 设计口径（这一路讨论的结论）
 *
 * ```\n * ① 零摩擦      想到就写：一次触发 → 光标已在输入框，⛔ 不选类型、⛔ 不起名字\n * ② 必须有锚点  所有者：「漂流笔记不要……每篇必须有挂的明确的节点，哪怕是挂错了」\n *                ⇒ 锚点走**已有的判定链**，⛔ 不引入"收件箱 / 未归位"\n * ③ 默认值      类型默认「灵光一闪」（`D117`）、名字服务端自动截（`D112`）\n * ```\n *
 * ## 锚点怎么定（**不新增概念**，只是给「当前节点」多一个兜底）
 *
 * ```\n * ① resume 有效（`D120` 的存档，7 天内）  ⇒ 就用那个节点\n * ② 没有任何存档                          ⇒ 不给写，提示先去选节点\n * ```\n *
 * ⚠ 之所以敢这么定：`D125` 已经保证「打开网站 → 回到上次的节点」，
 *   所以绝大多数时候第一步就命中 ⚠
 *
 * ## 触发方式
 *
 * ```\n * · 右下角常驻按钮「写一笔」\n * · 键盘 `n`（* 在输入框里打字时**不触发**）\n * · `Ctrl / ⌘ + Enter` 保存\n * ```\n
 */
import { useEffect, useState } from 'react'
import { PenLine } from 'lucide-react'

import { useMe } from '../../hooks/useMe'
import { clearResume, markResume, readResume, type ResumePoint } from '../../lib/resume'
import { useCreateNote } from '../../query/notes'
import { NOTE_KINDS, KIND_META } from './kindMeta'
import type { NoteKind } from '../../api/types'
import AnchorPicker from './AnchorPicker'
import Modal from '../ui/Modal'

export default function QuickNote() {
  const me = useMe()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [kind, setKind] = useState<NoteKind>('flash')
  const [point, setPoint] = useState<ResumePoint | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  // ★ 自己选的锚点（覆盖 resume 里的）⚠
  const [picked, setPicked] = useState<{ vid: number; name: string } | null>(null)
  const [done, setDone] = useState('')

  const create = useCreateNote(point?.ref)
  const authed = !!me.data?.authenticated

  // ★ 打开时读一次存档（* 每次打开都重读，⛔ 不在挂载时缓存，避免过期）⚠
  useEffect(() => {
    if (!open) return
    setPoint(readResume())
    setPicked(null)
  }, [open])

  const anchorVid = picked?.vid ?? point?.vid ?? 0
  const anchorName = picked?.name ?? point?.name ?? ''

  // ★ 快捷键 `n`：在输入框里打字时不触发 ⚠
  useEffect(() => {
    if (!authed) return
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return
      if (e.key !== 'n' && e.key !== 'N') return
      const t = e.target as HTMLElement | null
      const tag = t?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return
      if (t?.isContentEditable) return
      e.preventDefault()
      setOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [authed])

  const save = async () => {
    const body = text.trim()
    if (!body || !point || !anchorVid) return
    try {
      const res = await create.mutateAsync({
        kind,
        title: '', // ★ 留空 ⇒ 服务端自动截首行 25 字（`D112`）⚠
        body,
        node_id: anchorVid,
        is_public: true,
      })
      // ★★ 写完**立刻**存档：停 5 秒就写的那篇，下次也能回到这儿（`D120` 补口）⚠
      const snap = res?.note?.node_snapshot
      markResume(point.ref, snap?.vid || anchorVid, snap?.name || anchorName)
      setOpen(false)
      setText('')
      setPicked(null)
      setKind('flash')
      setDone(`已记下 №${String(res?.note?.seq || 0).padStart(3, '0')}`)
      window.setTimeout(() => setDone(''), 2600)
    } catch {
      // ★ 失败就留在弹窗里（* 文本还在，别让人白写）⚠
    }
  }

  if (!authed) return null

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="顺手写一笔（快捷键 n）"
        style={{
          position: 'fixed',
          right: 20,
          bottom: 20,
          zIndex: 60,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '8px 14px',
          fontSize: 13,
          fontFamily: 'var(--font-ui)',
          color: '#fff',
          background: 'var(--accent)',
          border: 'none',
          borderRadius: 999,
          boxShadow: 'var(--shadow-card-hover)',
          cursor: 'pointer',
        }}
      >
        <PenLine size={14} />
        {done || '写一笔'}
      </button>

      <Modal open={open} onClose={() => setOpen(false)} title="顺手写一笔" width={560}>
        <div className="flex flex-col gap-3">
          {/* ★ 锚点：始终可见，可换 ⚠ */}
          <div
            className="flex items-center gap-2 flex-wrap"
            style={{
              fontSize: 12,
              padding: '7px 10px',
              borderRadius: 8,
              background: 'var(--accent-dim)',
            }}
          >
            <span style={{ color: 'var(--text-sub)' }}>挂在</span>
            {point ? (
              <>
                <b style={{ color: 'var(--text-main)' }}>{anchorName || `#${anchorVid}`}</b>
                <button
                  type="button"
                  className="link-btn"
                  style={{ marginLeft: 'auto' }}
                  onClick={() => setPickerOpen(true)}
                >
                  换
                </button>
              </>
            ) : (
              <span style={{ color: 'var(--warn)' }}>
                还没有可用的节点 —— 先去项目里点开一个节点，之后再写
              </span>
            )}
          </div>

          {/* ★ 类型：默认灵光一闪，⛔ 不强制选 ⚠ */}
          <div className="flex items-center gap-1 flex-wrap">
            {NOTE_KINDS.map((k) => {
              const active = kind === k
              const c = KIND_META[k].color
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() => setKind(k)}
                  style={{
                    padding: '2px 9px',
                    fontSize: 11,
                    lineHeight: '17px',
                    fontFamily: 'var(--font-ui)',
                    color: active ? c : 'var(--text-faint)',
                    background: active ? `${c}1a` : 'transparent',
                    border: `1px solid ${active ? c : 'var(--card-border)'}`,
                    borderRadius: 999,
                    cursor: 'pointer',
                  }}
                >
                  {KIND_META[k].label}
                </button>
              )
            })}
          </div>

          <textarea
            autoFocus
            className="input"
            rows={6}
            placeholder="想到什么就写，不用起名字 —— 保存时会自动取第一行当名字"
            style={{ resize: 'vertical', lineHeight: 1.7, fontSize: 13.5 }}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault()
                void save()
              }
            }}
          />

          <div className="flex items-center gap-2">
            <span className="faint" style={{ fontSize: 11 }}>
              Ctrl / ⌘ + Enter 保存 · Esc 关闭
            </span>
            <button
              type="button"
              className="link-btn"
              style={{ marginLeft: 'auto' }}
              onClick={() => {
                clearResume()
                setPoint(null)
              }}
              title="清掉「上次看到的位置」，之后不再自动带锚点"
            >
              不用这个位置
            </button>
            <button
              type="button"
              disabled={!text.trim() || !point || create.isPending}
              onClick={() => void save()}
              style={{
                padding: '6px 16px',
                fontSize: 13,
                fontFamily: 'var(--font-ui)',
                color: '#fff',
                background: !text.trim() || !point ? 'var(--text-faint)' : 'var(--accent)',
                border: 'none',
                borderRadius: 999,
                cursor: !text.trim() || !point ? 'not-allowed' : 'pointer',
              }}
            >
              {create.isPending ? '保存中…' : '记下'}
            </button>
          </div>
        </div>
      </Modal>

      {/* ★ 换锚点（* 复用阅读页那个选择器）⚠ */}
      {point && (
        <AnchorPicker
          open={pickerOpen}
          projectRef={point.ref}
          currentVid={anchorVid}
          onClose={() => setPickerOpen(false)}
          onPick={(vid, name) => {
            setPicked({ vid, name })
            setPickerOpen(false)
          }}
        />
      )}
    </>
  )
}
