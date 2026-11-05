import { useState } from 'react'
import { Loader2, UserMinus, UserPlus, Users } from 'lucide-react'
import { errorMessage } from '../../api/errors'
import {
  useAddCollaborator,
  useCollaborators,
  useRemoveCollaborator,
} from '../../query/collaborators'
import Button from '../ui/Button'

/**
 * ★ 协作者区块（`F4` · D96 · 契约 §22.5）
 *
 * ## ★★ 形态（`B206` · 所有者原话）
 *
 * > 「写作者邀请**不要发链接**，用户管理页面给个选择用户成为协作者的按钮，
 * > **只要输入用户名就行**。跟微信小程序邀请其他同伴一起写小程序代码一样。」
 *
 * ```
 * ★★ 一个输入框 + 添加按钮 ——* ⛔ 不发链接、* ⛔ 不要 token、* ⛔ 无接受流程 ✅
 * ★★ 幂等：* 已是对员 ⇒* 提示「本来就是协作者」（* ⛔ 不报错）✅
 * ★★ 边界：* 用户名不存在 ⇒* 「用户名不存在」；* 输项目主自己 ⇒* 「不用加，项目主本来就全权」⚠
 * ```
 *
 * ⚠★ **只由父组件在 `can_manage` 时渲染**（* owner/staff）——
 *   · · ★ 加 / 移只有 owner 能干（* `B207`②：* 协作者**不能**加 / 移协作者）⚠
 *   · · ★★ 真正的拦截在后端（* `@staff_only` / `can_manage`）✅
 */
interface CollaboratorSectionProps {
  projectRef: string
}

export default function CollaboratorSection({ projectRef }: CollaboratorSectionProps) {
  const list = useCollaborators(projectRef)
  const add = useAddCollaborator(projectRef)
  const remove = useRemoveCollaborator(projectRef)
  const [name, setName] = useState('')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const submit = async () => {
    const username = name.trim()
    if (!username) return
    setMsg(null)
    try {
      const r = await add.mutateAsync(username)
      setMsg({
        kind: 'ok',
        text: r.already ? `「${username}」本来就是协作者` : `已把「${username}」加为协作者`,
      })
      setName('')
    } catch (e) {
      // ⚠ 后端文案原样显示（user_not_found / owner_not_allowed 等都有明确说法）
      setMsg({ kind: 'err', text: errorMessage(e) })
    }
  }

  const items = list.data?.items || []

  return (
    <div className="card" style={{ padding: '14px 16px', marginTop: 16 }}>
      <div className="flex items-center gap-2 mb-3">
        <Users size={15} style={{ color: 'var(--text-sub)' }} />
        <span style={{ fontSize: 13.5, fontWeight: 600 }}>协作者</span>
        <span className="faint" style={{ fontSize: 11.5 }}>
          合作写笔记和图谱的人 —— 除删项目外与项目主同权
        </span>
      </div>

      {/* 添加：输入用户名即加（B206） */}
      <div className="flex gap-2 items-center">
        <input
          className="input"
          style={{ maxWidth: 260, fontSize: 13 }}
          placeholder="输入用户名，比如 zhangsan"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void submit()
          }}
        />
        <Button
          variant="primary"
          icon={<UserPlus size={13} />}
          loading={add.isPending}
          disabled={!name.trim()}
          onClick={submit}
        >
          添加
        </Button>
      </div>

      {msg && (
        <div className="text-xs mt-2" style={{ color: msg.kind === 'ok' ? 'var(--ok)' : 'var(--err)' }}>
          {msg.text}
        </div>
      )}

      <div className="mt-3 flex flex-col gap-1.5">
        {list.isLoading ? (
          <div className="faint" style={{ fontSize: 12 }}>加载中…</div>
        ) : items.length === 0 ? (
          <div className="faint" style={{ fontSize: 12 }}>
            还没有协作者 —— 输入用户名就能拉人一起写。
          </div>
        ) : (
          items.map((c) => (
            <div key={c.username} className="flex items-center gap-2" style={{ fontSize: 13 }}>
              <span>{c.username}</span>
              <button
                type="button"
                className="flex items-center gap-1 faint"
                style={{ marginLeft: 'auto', fontSize: 11.5, cursor: 'pointer' }}
                disabled={remove.isPending}
                onClick={async () => {
                  setMsg(null)
                  try {
                    await remove.mutateAsync(c.username)
                    setMsg({ kind: 'ok', text: `已移除「${c.username}」` })
                  } catch (e) {
                    setMsg({ kind: 'err', text: errorMessage(e) })
                  }
                }}
              >
                {remove.isPending ? (
                  <Loader2 size={11} className="animate-spin" />
                ) : (
                  <UserMinus size={11} />
                )}
                移除
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
