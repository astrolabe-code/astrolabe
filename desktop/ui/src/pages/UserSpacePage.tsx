import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { EyeOff, MessageSquare, ThumbsUp } from 'lucide-react'
import type { SpaceItem, SpaceNote, SpaceProject } from '../api/types'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import ProfileHeader from '../components/profile/ProfileHeader'
import { kindMeta, KIND_META, NOTE_KINDS } from '../components/notes/kindMeta'
import { useMe } from '../hooks/useMe'
import {
  useUserActivity,
  useUserNotes,
  useUserProjects,
  useUserSpace,
} from '../query/userSpace'

/**
 * ★★ **用户空间**（参考 B 站 · 2026-10-24）⚠
 *
 * ## ★★★ 所有者原话（逐字）
 *
 * > 「我想参考B站的用户空间设计。」
 * > 「昵称/签名要加。私有内容在自己的空间里要显示」
 *
 * ## ★ 三个 Tab
 *
 * ```\n * 主页 ⇒ 笔记 + 项目按时间合并（* B 站的「动态」）\n * 笔记 ⇒ 只有笔记，可按「最新 / 最热」排\n * 项目 ⇒ 只有项目\n * ```
 *
 * ⚠ `/u/:username` 公开可看（只给公开内容）；`/me` 是本人视角（含私有）⚠
 */
type Tab = 'home' | 'notes' | 'projects'

const TABS: { key: Tab; label: string }[] = [
  { key: 'home', label: '主页' },
  { key: 'notes', label: '笔记' },
  { key: 'projects', label: '项目' },
]

function SpaceNoteRow({ item }: { item: SpaceNote }) {
  const nav = useNavigate()
  const meta = kindMeta(item.kind)
  const open = () =>
    item.project && nav(`/p/${encodeURIComponent(item.project.project_ref)}/notes/${item.ref}`)

  return (
    <div
      className="card"
      style={{ padding: '12px 14px', cursor: item.project ? 'pointer' : 'default' }}
      onClick={open}
    >
      <div className="flex items-center gap-2 flex-wrap">
        {/* ★ 编号（`D113`）—— 让「这是第几篇」在列表里也看得见 ⚠ */}
        <span
          style={{
            fontSize: 10.5,
            lineHeight: '16px',
            padding: '0 5px',
            borderRadius: 4,
            fontFamily: 'var(--font-mono, ui-monospace, monospace)',
            color: 'var(--text-faint)',
            border: '1px solid var(--card-border)',
          }}
        >
          №{String(item.seq || 0).padStart(3, '0')}
        </span>
        <span
          style={{
            fontSize: 10.5,
            lineHeight: '16px',
            padding: '1px 8px',
            borderRadius: 999,
            color: meta.color,
            border: `1px solid ${meta.color}66`,
            background: `${meta.color}1a`,
          }}
        >
          {meta.label}
        </span>
        {!item.is_public && (
          <span className="tag" style={{ fontSize: 10.5 }} title="只有作者可见">
            <EyeOff size={10} style={{ marginRight: 3, verticalAlign: -1 }} />
            仅自己可见
          </span>
        )}
        {item.state === 'hidden' && (
          <span className="tag" style={{ fontSize: 10.5, color: 'var(--err)' }}>
            已被隐藏
          </span>
        )}
        <span className="faint" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {item.project?.project_name || '（无项目）'} · {item.created_at.slice(0, 10)}
        </span>
      </div>
      <div style={{ fontSize: 13.5, fontWeight: 500, marginTop: 6 }}>
        {item.title || '（无标题）'}
      </div>
      {item.excerpt && (
        <div className="faint" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.6 }}>
          {item.excerpt}
        </div>
      )}
      <div className="flex items-center gap-3 faint" style={{ fontSize: 11, marginTop: 8 }}>
        <span className="flex items-center gap-1">
          <ThumbsUp size={11} /> {item.like_count}
        </span>
        <span className="flex items-center gap-1">
          <MessageSquare size={11} /> {item.comment_count}
        </span>
      </div>
    </div>
  )
}

function SpaceProjectRow({ item }: { item: SpaceProject }) {
  return (
    <Link
      to={`/p/${encodeURIComponent(item.project_ref)}`}
      className="card"
      style={{ padding: '12px 14px', display: 'block' }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span style={{ fontSize: 13.5, fontWeight: 600 }}>{item.name}</span>
        {!item.is_public && (
          <span className="tag" style={{ fontSize: 10.5 }}>
            <EyeOff size={10} style={{ marginRight: 3, verticalAlign: -1 }} />
            仅自己可见
          </span>
        )}
        <span className="faint" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {item.provider || '自建'} · {item.created_at.slice(0, 10)}
        </span>
      </div>
      {item.desc && (
        <div className="faint" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.6 }}>
          {item.desc}
        </div>
      )}
      <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
        {item.node_count} 节点 · {item.edge_count} 边
      </div>
    </Link>
  )
}

function ItemRow({ item }: { item: SpaceItem }) {
  return item.type === 'note' ? <SpaceNoteRow item={item} /> : <SpaceProjectRow item={item} />
}

export default function UserSpacePage() {
  const { username: routeName } = useParams<{ username?: string }>()
  const me = useMe()
  const username = routeName || me.data?.username || ''

  const [tab, setTab] = useState<Tab>('home')
  const [sort, setSort] = useState<'new' | 'hot'>('new')
  // ★★★ 2026-10-27：**按类别筛**（设计理念：五个盒子要能聚合，不只是一个颜色）⚠
  const [kind, setKind] = useState<string>('all')

  const space = useUserSpace(username)
  const notes = useUserNotes(username, sort, kind, tab === 'notes')
  const projects = useUserProjects(username, tab === 'projects')
  const activity = useUserActivity(username, tab === 'home')

  const feed = tab === 'notes' ? notes : tab === 'projects' ? projects : activity
  const items = useMemo<SpaceItem[]>(
    () => (feed.data?.pages ?? []).flatMap((p) => p.items ?? []),
    [feed.data],
  )

  // ---- 未登录访问 /me ----
  if (!username) {
    return (
      <AppLayout title="我的空间">
        <div className="card" style={{ padding: 24 }}>
          <div className="faint" style={{ fontSize: 12.5 }}>
            请先登录，才能查看自己的空间。
          </div>
          <div className="mt-4">
            <Link to="/login">
              <Button variant="primary">去登录</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  if (space.isLoading) {
    return (
      <AppLayout title="用户空间">
        <div className="faint" style={{ fontSize: 13 }}>
          加载中…
        </div>
      </AppLayout>
    )
  }

  if (space.isError || !space.data) {
    return (
      <AppLayout title="用户空间">
        <div className="card" style={{ padding: 24 }}>
          <div className="faint" style={{ fontSize: 12.5 }}>
            这个用户不存在。
          </div>
          <div className="mt-4">
            <Link to="/">
              <Button>回首页</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  const data = space.data
  const emptyText =
    tab === 'projects'
      ? data.is_self
        ? '还没建过项目'
        : 'TA 还没有公开的项目'
      : data.is_self
        ? '还没写过笔记'
        : 'TA 还没有公开的笔记'

  return (
    <AppLayout title={null}>
      <div className="flex flex-col gap-4">
        <ProfileHeader data={data} />

        {/* Tab 栏 */}
        <div
          className="flex items-center gap-1"
          style={{ borderBottom: '1px solid var(--card-border)', paddingBottom: 0 }}
        >
          {TABS.map((t) => {
            const active = tab === t.key
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                style={{
                  padding: '9px 14px',
                  fontSize: 13,
                  fontFamily: 'var(--font-ui)',
                  color: active ? 'var(--text-main)' : 'var(--text-sub)',
                  background: 'transparent',
                  border: 'none',
                  borderBottom: `2px solid ${active ? 'var(--accent)' : 'transparent'}`,
                  cursor: 'pointer',
                  fontWeight: active ? 600 : 400,
                }}
              >
                {t.label}
              </button>
            )
          })}

          {tab === 'notes' && (
            <div className="flex items-center gap-1" style={{ marginLeft: '10px' }}>
              {(['all', ...NOTE_KINDS] as const).map((k) => {
                const active = kind === k
                const color = k === 'all' ? 'var(--text-sub)' : KIND_META[k].color
                return (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setKind(k)}
                    style={{
                      padding: '3px 9px',
                      fontSize: 11,
                      lineHeight: '17px',
                      fontFamily: 'var(--font-ui)',
                      whiteSpace: 'nowrap',
                      color: active ? color : 'var(--text-faint)',
                      background: active ? `${k === 'all' ? 'transparent' : color + '1a'}` : 'transparent',
                      border: `1px solid ${active ? color : 'var(--card-border)'}`,
                      borderRadius: 999,
                      cursor: 'pointer',
                    }}
                  >
                    {k === 'all' ? '全部' : KIND_META[k].label}
                  </button>
                )
              })}
            </div>
          )}
          {tab === 'notes' && (
            <div className="flex items-center gap-1" style={{ marginLeft: 'auto' }}>
              {(['new', 'hot'] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSort(s)}
                  style={{
                    padding: '4px 10px',
                    fontSize: 11.5,
                    fontFamily: 'var(--font-ui)',
                    color: sort === s ? 'var(--text-main)' : 'var(--text-faint)',
                    background: sort === s ? 'var(--bg-deep)' : 'transparent',
                    border: 'none',
                    borderRadius: 999,
                    cursor: 'pointer',
                  }}
                >
                  {s === 'new' ? '最新' : '最热'}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 内容流 */}
        {feed.isLoading ? (
          <div className="faint" style={{ fontSize: 12.5, padding: 8 }}>
            加载中…
          </div>
        ) : items.length === 0 ? (
          <EmptyState title={emptyText} />
        ) : (
          <div className="flex flex-col gap-2">
            {items.map((item) => (
              <ItemRow
                key={item.type === 'note' ? `n-${item.ref}` : `p-${item.project_ref}`}
                item={item}
              />
            ))}

            {feed.hasNextPage && (
              <div className="flex justify-center" style={{ padding: '10px 0' }}>
                <Button
                  onClick={() => void feed.fetchNextPage()}
                  loading={feed.isFetchingNextPage}
                  style={{ fontSize: 12 }}
                >
                  加载更多
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </AppLayout>
  )
}
