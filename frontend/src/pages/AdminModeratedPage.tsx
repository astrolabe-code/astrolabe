import { useState } from 'react'
import { Link } from 'react-router-dom'
import { EyeOff, ShieldAlert } from 'lucide-react'
import { errorMessage } from '../api/errors'
import { useMe } from '../hooks/useMe'
import { useModeratedItems } from '../query/moderate'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import ModeratePanel from '../components/admin/ModeratePanel'

/**
 * ★ 已处置列表（`F5` · D97 · `B215`）
 *
 * ## ★★ 补的是什么洞（`B208` → `B215`）
 *
 * ```
 * ★★ `B208` 切了管理员的额外读权限 ⇒* 被隐藏的项目 / 笔记对 staff 也 404
 *   ⇒* 「恢复」（仅管理员）在 UI 里**够不着** ⚠
 * ★★ 本页给 staff 一个入口：* 列出被隐藏的，* 带理由 / 处置人 / 时间，
 *   * 点「恢复」就回到 active（* `ModeratePanel` 复用，* 默认动作 restore）✅
 * ```
 *
 * ⚠★ **`take_down` 的不在这里** ——* 那是物理删除，* 行都没了，* 无从列出 ⚠
 * ⚠★ 页面入口只对 staff 渲染；* 真正的拦截在后端（* `@staff_only`）✅
 */
export default function AdminModeratedPage() {
  const me = useMe()
  const list = useModeratedItems()
  const [panel, setPanel] = useState<{ kind: 'project' | 'note'; target: string | number } | null>(null)

  if (!me.data?.is_staff) {
    return (
      <AppLayout title="已处置">
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 14 }}>只有站点管理员能看这里</div>
          <div className="mt-4">
            <Link to="/">
              <Button>回首页</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  const projects = list.data?.projects || []
  const notes = list.data?.notes || []
  const empty = projects.length === 0 && notes.length === 0

  return (
    <AppLayout
      title="已处置"
      crumbs={[{ label: '工作区', to: '/workspace' }, { label: '已处置' }]}
    >
      <div className="faint" style={{ fontSize: 12.5, marginBottom: 14 }}>
        被管理员隐藏的内容 —— 点「恢复」解除隐藏、所有人重新可见。
        ⚠ 下架（彻底删除）的内容不在这里：数据已从服务器删除，没有恢复机制。
      </div>

      {list.isError ? (
        <div className="text-sm" style={{ color: 'var(--err)' }}>
          {errorMessage(list.error)}
        </div>
      ) : list.isLoading ? (
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      ) : empty ? (
        <EmptyState
          title="没有被隐藏的内容"
          hint="管理员处置过的项目 / 笔记会出现在这里"
          icon={<ShieldAlert size={28} />}
        />
      ) : (
        <>
          <Section
            title="被隐藏的项目"
            count={projects.length}
            rows={projects.map((p) => ({
              key: p.project_ref,
              name: p.name || p.project_ref,
              meta: `项目主 ${p.owner} · ${p.moderation_reason || '（无理由）'} · 处置人 ${p.moderated_by}`,
              time: p.moderated_at,
              onRestore: () => setPanel({ kind: 'project', target: p.project_ref }),
            }))}
          />
          <Section
            title="被隐藏的笔记"
            count={notes.length}
            rows={notes.map((n) => ({
              key: String(n.id),
              name: n.title || '（无标题）',
              meta: `作者 ${n.created_by} · ${n.moderation_reason || '（无理由）'} · 处置人 ${n.moderated_by}`,
              time: n.moderated_at,
              onRestore: () => setPanel({ kind: 'note', target: n.id }),
            }))}
          />
        </>
      )}

      {/* ★ 恢复用同一个处置弹窗（currentState=hidden ⇒ 默认动作 restore） */}
      {panel && (
        <ModeratePanel
          open={!!panel}
          kind={panel.kind}
          target={panel.target}
          currentState="hidden"
          onClose={() => setPanel(null)}
        />
      )}
    </AppLayout>
  )
}

/** ★ 一个区块（项目 / 笔记各一）——* 行内「恢复」⚠ */
function Section({
  title,
  count,
  rows,
}: {
  title: string
  count: number
  rows: {
    key: string
    name: string
    meta: string
    time: string
    onRestore: () => void
  }[]
}) {
  if (rows.length === 0) return null
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-2">
        <EyeOff size={13} style={{ color: 'var(--text-sub)' }} />
        <span style={{ fontSize: 13, fontWeight: 600 }}>{title}</span>
        <span className="faint" style={{ fontSize: 11.5 }}>{count}</span>
      </div>
      <div className="flex flex-col gap-2">
        {rows.map((r) => (
          <div key={r.key} className="card flex items-center gap-2 flex-wrap" style={{ padding: '9px 12px' }}>
            <span style={{ fontSize: 13.5, fontWeight: 500 }}>{r.name}</span>
            <span className="faint" style={{ fontSize: 11.5 }}>{r.meta}</span>
            <span className="faint" style={{ fontSize: 11 }}>
              {r.time?.replace('T', ' ').slice(0, 16)}
            </span>
            <Button
              variant="primary"
              style={{ marginLeft: 'auto', padding: '3px 10px', fontSize: 12 }}
              onClick={r.onRestore}
            >
              恢复
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}
