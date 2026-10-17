import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArchiveRestore, Loader2, RotateCcw } from 'lucide-react'
import type { DeletedNote } from '../api/types'
import { errorMessage } from '../api/errors'
import { useDeletedNotes, useUndeleteNote } from '../query/notes'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'

/**
 * ★ 回收站（`F4` · D96 · 契约 §22.7）
 *
 * ## ★★ 装什么（`B210` / `D86`）
 *
 * ```
 * ★★ deleted_at 非空的笔记 ——* 我是作者 ∨ 项目 owner ∨ 项目协作者 ✅
 * ★★ 列表显示「**被谁删的 / 何时删的**」（* 所有者要求分清谁删的）⚠
 * ★★ ⛔ 不含正文（* D86①：* 先看元信息，* 恢复后再看）✅
 * ★★ 管理员删的**不在这里** ——* 那是物理删（* take_down），* 行都没了 ⚠
 * ```
 *
 * ⚠★ 恢复后给「去项目」链接（* `project_ref`）——* 笔记回到原项目原节点 ✅
 */
export default function RecycleBinPage() {
  const me = useMe()
  const authed = !!me.data?.authenticated
  const deleted = useDeletedNotes({ limit: 50 })
  const undelete = useUndeleteNote()
  const [msg, setMsg] = useState<{ text: string; ref?: string } | null>(null)
  const [err, setErr] = useState('')

  const restore = async (n: DeletedNote) => {
    setErr('')
    setMsg(null)
    try {
      await undelete.mutateAsync(n.id)
      setMsg({
        text: `已恢复「${n.title || '（无标题）'}」`,
        ref: n.project_ref,
      })
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  if (!authed) {
    return (
      <AppLayout title="回收站">
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 14 }}>登录后可以查看你的回收站</div>
          <div className="mt-4">
            <Link to="/login">
              <Button variant="primary">去登录</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  return (
    <AppLayout title="回收站" crumbs={[{ label: '工作区', to: '/workspace' }, { label: '回收站' }]}>
      <div className="faint" style={{ fontSize: 12.5, marginBottom: 14 }}>
        这里是被删掉的笔记 —— 恢复后回到原项目原节点。⚠ 管理员下架的内容不在这里（那是彻底删除，不可恢复）。
      </div>

      {msg && (
        <div className="card" style={{ padding: '10px 14px', marginBottom: 12, borderColor: 'var(--ok)' }}>
          <div style={{ fontSize: 12.5 }}>
            {msg.text}
            {msg.ref && (
              <Link to={`/p/${encodeURIComponent(msg.ref)}`} style={{ marginLeft: 8 }}>
                去项目
              </Link>
            )}
          </div>
        </div>
      )}
      {err && (
        <div className="text-xs mb-3" style={{ color: 'var(--err)' }}>
          {err}
        </div>
      )}

      {deleted.isLoading ? (
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      ) : (deleted.data?.items || []).length === 0 ? (
        <EmptyState
          title="回收站是空的"
          hint="删掉的笔记会先来这里，随时可以恢复"
          icon={<ArchiveRestore size={28} />}
        />
      ) : (
        <div className="flex flex-col gap-2">
          {(deleted.data?.items || []).map((n) => (
            <div key={n.id} className="card" style={{ padding: '10px 12px' }}>
              <div className="flex items-center gap-2 flex-wrap">
                <span style={{ fontSize: 13.5, fontWeight: 500 }}>{n.title || '（无标题）'}</span>
                <span className="tag" style={{ fontSize: 10.5 }}>{n.kind}</span>
                <span className="faint" style={{ fontSize: 11 }}>
                  被 {n.deleted_by || '未知用户'} 删除 · {n.deleted_at?.replace('T', ' ').slice(0, 16)}
                </span>
                <button
                  type="button"
                  className="flex items-center gap-1"
                  style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--accent)', cursor: 'pointer' }}
                  disabled={undelete.isPending}
                  onClick={() => restore(n)}
                >
                  {undelete.isPending ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <RotateCcw size={12} />
                  )}
                  恢复
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </AppLayout>
  )
}
