import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ShieldAlert, TriangleAlert } from 'lucide-react'
import type { ModerateAction } from '../../api/types'
import { errorMessage } from '../../api/errors'
import { useModerateNote, useModerateProject } from '../../query/moderate'
import Modal from '../ui/Modal'
import Button from '../ui/Button'

/**
 * ★ 管理处置弹窗（`F4` · D96 · 契约 §22.6）—— ★★ **管理员唯一的权力**
 *
 * ## ★★★ 三个动作（`B208` · 所有者原话，逐字见 A33/A34）
 *
 * | 动作 | 语义 | 弹窗文案 |
 * |---|---|---|
 * | `hide` | ★ 先藏着，核查中 | 「只有作者/项目主能看到，别人直链也打不开」 |
 * | `take_down` | ★★ **彻底删除、没有恢复机制** | 「⚠ 彻底从服务器删除数据 —— 普通删除进回收站，**这个不会**」 |
 * | `restore` | ★ 解除隐藏（仅 hidden→active） | 「恢复后所有人可见」 |
 *
 * ⚠★ **只能由 staff 打开本弹窗**（入口 `is_staff` 才渲染）——
 *   · · ★★ 真正的拦截在后端（`@staff_only`）；把按钮藏起来 ≠ 安全 ✅
 * ⚠★ `reason` 对 hide / take_down **必填**（* `B196`：* 作者来问"为什么"必须答得出）⚠
 */
interface ModeratePanelProps {
  open: boolean
  kind: 'project' | 'note'
  /** project = projectRef；note = noteId */
  target: string | number
  /** 当前状态（active / hidden）—— 决定「恢复」可不可用 */
  currentState?: string
  onClose: () => void
}

export default function ModeratePanel({
  open,
  kind,
  target,
  currentState,
  onClose,
}: ModeratePanelProps) {
  const qc = useQueryClient()
  const [action, setAction] = useState<ModerateAction>('hide')
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')

  const moderateProject = useModerateProject(kind === 'project' ? String(target) : null)
  const moderateNote = useModerateNote(kind === 'note' ? Number(target) : null)
  const mut = kind === 'project' ? moderateProject : moderateNote
  const isHidden = currentState === 'hidden'

  /** ★ 打开时重置（* 默认隐藏；* 已隐藏的默认恢复） */
  useEffect(() => {
    if (!open) return
    setErr('')
    setReason('')
    setAction(isHidden ? 'restore' : 'hide')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isHidden])

  const needReason = action === 'hide' || action === 'take_down'

  const submit = async () => {
    setErr('')
    if (needReason && !reason.trim()) {
      setErr('理由必填 —— 作者来问「为什么」时必须答得出')
      return
    }
    try {
      await mut.mutateAsync({ action, reason: reason.trim() })
      // ★ 处置完刷新：项目 / 笔记本体 + 列表（状态或干脆没了）
      void qc.invalidateQueries({ queryKey: ['project', String(target)] })
      void qc.invalidateQueries({ queryKey: ['note', Number(target)] })
      void qc.invalidateQueries({ queryKey: ['projects'] })
      void qc.invalidateQueries({ queryKey: ['notes'] })
      onClose()
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  const actions: { key: ModerateAction; label: string; hint: string }[] = [
    { key: 'hide', label: '隐藏', hint: '先藏着，核查中' },
    { key: 'take_down', label: '下架', hint: '彻底删除、不可恢复' },
    { key: 'restore', label: '恢复', hint: '解除隐藏' },
  ]

  return (
    <Modal
      open={open}
      title={`管理处置 · ${kind === 'project' ? '项目' : '笔记'}`}
      width={520}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={mut.isPending}>
            取消
          </Button>
          <Button
            variant={action === 'take_down' ? 'danger' : 'primary'}
            loading={mut.isPending}
            onClick={submit}
          >
            {action === 'take_down' ? '彻底删除' : action === 'restore' ? '解除隐藏' : '隐藏'}
          </Button>
        </>
      }
    >
      <div className="flex items-center gap-2 mb-3">
        <ShieldAlert size={15} style={{ color: 'var(--text-sub)' }} />
        <span className="faint" style={{ fontSize: 12 }}>
          {kind === 'project' ? `项目 ${target}` : `笔记 #${target}`}
          {currentState ? ` · 当前状态：${currentState}` : ''}
        </span>
      </div>

      {/* 动作三选一 */}
      <div className="flex flex-col gap-1.5">
        {actions.map((a) => {
          const disabled = a.key === 'restore' && !isHidden
          const active = action === a.key
          return (
            <button
              key={a.key}
              type="button"
              disabled={disabled}
              onClick={() => setAction(a.key)}
              className="text-left"
              style={{
                padding: '8px 10px',
                borderRadius: 8,
                fontSize: 13,
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.45 : 1,
                border: `1px solid ${active ? 'var(--accent)' : 'var(--card-border)'}`,
                background: active ? 'var(--accent-dim)' : 'transparent',
              }}
            >
              <span style={{ fontWeight: 600 }}>{a.label}</span>
              <span className="faint" style={{ marginLeft: 8, fontSize: 11.5 }}>
                {a.hint}
              </span>
              {a.key === 'restore' && !isHidden && (
                <span className="faint" style={{ marginLeft: 8, fontSize: 11 }}>
                  （当前不是隐藏状态）
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* 下架的加重警告（与普通删除的「可从回收站恢复」形成对照） */}
      {action === 'take_down' && (
        <div
          className="flex items-start gap-2 mt-3"
          style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--err)' }}
        >
          <TriangleAlert size={14} style={{ color: 'var(--err)', marginTop: 2 }} />
          <div style={{ fontSize: 12, lineHeight: 1.7 }}>
            <b>下架 = 彻底从服务器删除数据，没有恢复机制。</b>
            <div className="faint" style={{ fontSize: 11.5 }}>
              普通用户的删除是进回收站（可恢复）；这个不是。数据行、段落、评论、点赞一起没。
            </div>
          </div>
        </div>
      )}

      {/* 理由 */}
      <div className="mt-3">
        <div className="text-xs font-medium tracking-wide text-text-sub mb-1.5">
          理由{needReason ? '（必填，会留痕给作者）' : '（可空）'}
        </div>
        <textarea
          className="input"
          rows={3}
          style={{ resize: 'vertical', fontSize: 13, lineHeight: 1.7 }}
          placeholder={needReason ? '例如：确认侵权，按通知下架' : ''}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </div>

      {err && (
        <div className="text-xs mt-2" style={{ color: 'var(--err)' }}>
          {err}
        </div>
      )}
    </Modal>
  )
}
