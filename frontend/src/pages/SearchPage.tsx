import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, ChevronLeft, ChevronRight, FolderGit2, Search } from 'lucide-react'

import type { NoteSearchItem, ProjectSummary } from '../api/types'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import { ApiRequestError, errorMessage } from '../api/errors'
import { kindMeta } from '../components/notes/kindMeta'
import { useNoteSearch, useSearchSuggest } from '../query/notes'
import { useMe } from '../hooks/useMe'
import { useProjectSearch } from '../query/projects'

/**
 * ★★★ **搜索结果页**（`D109` · 2026-10-22）⚠
 *
 * > 「应该有个搜索结果页面，一条一条的条目。这样，在这个页面就可以有更多的排序
 * >  挑选功能了。点击量条目，再转到相应的项目和笔记。……你就直接写个 search 的
 * >  URL 路径吧，以后我方便改。」
 *
 * ## ★★ 形态
 *
 * ```
 * 列表条目（⛔ 不是首页那种卡片网格）—— 一条一行，才能一屏扫 10~20 条
 * URL: /search?q=&type=all|project|note&sort=relevance|newest&offset=
 *   · 筛选/排序/分页**都进 URL** ⇒ 刷新、分享、后退都能保持状态 ✅
 * ```
 */
const PAGE = 20

type Tab = 'all' | 'project' | 'note'
type Sort = 'relevance' | 'newest'

const fmt = (iso: string) => (iso ? iso.slice(0, 10) : '')

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()

  const q = params.get('q') ?? ''
  const tab = (params.get('type') as Tab) || 'all'
  const sort = (params.get('sort') as Sort) || 'relevance'
  const offset = Math.max(0, Number(params.get('offset')) || 0)

  const [input, setInput] = useState(q)
  useEffect(() => setInput(q), [q])

  // ★★★ 搜索框的联想（* 所有者：「搜索页的搜索框也要有联想词呀」）⚠
  const [focus, setFocus] = useState(false)
  const [typed, setTyped] = useState('')
  useEffect(() => {
    const t = window.setTimeout(() => setTyped(input.trim()), 250)
    return () => window.clearTimeout(t)
  }, [input])
  const suggest = useSearchSuggest(focus ? typed : '')
  const suggestItems = suggest.data || []

  // ★ 只看「项目」时不必查笔记（* 省一次请求）⚠
  // ★ 限流文案要区分登录/未登录（* 已登录不能叫他"去登录"）⚠
  const { data: me } = useMe()
  const loggedIn = !!me?.authenticated
  const notes = useNoteSearch(tab === 'project' ? '' : q, { limit: PAGE, offset, sort })
  const projects = useProjectSearch(tab === 'note' ? '' : q)

  const noteItems: NoteSearchItem[] = tab === 'project' ? [] : notes.data?.items ?? []
  const noteTotal = notes.data?.total ?? 0
  const projectItems: ProjectSummary[] = tab === 'note' ? [] : projects.data ?? []

  const patch = (next: Record<string, string | number | null>) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v === null || v === '' || v === 0) p.delete(k)
      else p.set(k, String(v))
    }
    setParams(p)
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const kw = input.trim()
    if (!kw) return
    // ★ 换关键词 ⇒ 回到第一页
    setParams({ q: kw, type: tab, sort })
  }

  const openProject = (ref: string) => navigate(`/p/${ref}`)
  const openNote = (n: NoteSearchItem) =>
    n.project?.project_ref ? navigate(`/p/${n.project.project_ref}/notes/${n.id}`) : navigate('/')

  const hasPrev = offset > 0
  const hasNext = offset + PAGE < noteTotal

  return (
    <AppLayout
      title={
        <span className="flex items-center gap-2">
          <Search size={18} />
          搜索
        </span>
      }
    >
      {/* ① 搜索框 + 联想 */}
      {/* ★ 外层的 margin 放在容器上（* 否则绝对定位的联想框会压到搜索按钮）⚠ */}
      <div style={{ position: 'relative', marginBottom: 16 }}>
      <form onSubmit={submit} style={{ display: 'flex', gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="搜项目、笔记、函数……"
          autoFocus
          onFocus={() => setFocus(true)}
          onBlur={() => window.setTimeout(() => setFocus(false), 150)}
          style={{
            flex: 1,
            padding: '9px 12px',
            borderRadius: 10,
            border: '1px solid var(--card-border)',
            background: 'var(--card)',
            color: 'var(--text-main)',
            fontSize: 13.5,
            outline: 'none',
          }}
        />
        <Button variant="primary" icon={<Search size={14} />} type="submit">
          搜索
        </Button>
      </form>

      {focus && suggestItems.length > 0 && (
        <div className="hero-suggest" style={{ top: '100%', marginTop: 6 }}>
          {suggestItems.slice(0, 6).map((it) => (
            <button
              key={it.text}
              type="button"
              // ★ 选中联想词 ⇒ 用它搜（* 不跳详情）⚠
              onMouseDown={() => {
                setInput(it.text)
                setFocus(false)
                setParams({ q: it.text, type: tab, sort })
              }}
            >
              <span>{it.text}</span>
            </button>
          ))}
        </div>
      )}
      </div>

      {!q ? (
        <div className="faint" style={{ fontSize: 12.5 }}>
          输入关键词开始搜索。
        </div>
      ) : (
        <>
          {/* ② 结果概况 + 筛选 + 排序 */}
          <div className="flex items-center" style={{ gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
            <span className="faint" style={{ fontSize: 11.5 }}>
              「{q}」·{' '}
              {tab === 'project'
                ? `${projectItems.length} 个项目`
                : tab === 'note'
                  ? `${noteTotal} 条笔记`
                  : `${noteTotal} 条笔记 · ${projectItems.length} 个项目`}
            </span>

            <div style={{ display: 'flex', gap: 2, marginLeft: 'auto' }}>
              {(
                [
                  ['all', '全部'],
                  ['project', '项目'],
                  ['note', '笔记'],
                ] as [Tab, string][]
              ).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => patch({ type: k, offset: 0 })}
                  style={chip(tab === k)}
                >
                  {label}
                </button>
              ))}
            </div>

            <div style={{ display: 'flex', gap: 2 }}>
              {(
                [
                  ['relevance', '相关度'],
                  ['newest', '最新'],
                ] as [Sort, string][]
              ).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => patch({ sort: k, offset: 0 })}
                  style={chip(sort === k)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* ★ 后端把「用户词 + 联想词」一次查完 ⇒ 如实说明来源 ⚠ */}
          {notes.data?.expanded && (
            <div className="faint" style={{ fontSize: 11.5, marginBottom: 8 }}>
              {notes.data.expanded.matched === 0
                ? `「${notes.data.expanded.query}」没有直接匹配，已按联想词`
                : '另外并入了联想词'}
              {notes.data.expanded.terms.map((t) => `「${t}」`).join('、')}
              {notes.data.expanded.matched === 0 ? '搜索' : '的结果'}
            </div>
          )}

          {/* ③ 列表 */}
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            {notes.isError &&
              (notes.error instanceof ApiRequestError && notes.error.status === 429 ? (
                <div style={{ padding: '26px 20px', textAlign: 'center' }}>
                  {loggedIn ? (
                    <>
                      <div style={{ fontSize: 13.5, color: 'var(--text-main)', marginBottom: 6 }}>
                        搜得有点快啦，歇一秒再试试～
                      </div>
                      <div className="faint" style={{ fontSize: 11.5 }}>
                        一下子搜太多，服务器有点跟不上。
                      </div>
                    </>
                  ) : (
                    <>
                      <div style={{ fontSize: 13.5, color: 'var(--text-main)', marginBottom: 6 }}>
                        这会儿搜索的人有点多，先喘口气～
                      </div>
                      <div className="faint" style={{ fontSize: 11.5, marginBottom: 14 }}>
                        登录后就有自己的专属通道，不用和大家挤在一起。
                      </div>
                      <Button
                        variant="primary"
                        onClick={() =>
                          navigate(
                            `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
                          )
                        }
                      >
                        去登录
                      </Button>
                    </>
                  )}
                </div>
              ) : (
                <div style={{ padding: 16, fontSize: 12, color: 'var(--err)' }}>
                  {errorMessage(notes.error)}
                </div>
              ))}

            {tab !== 'note' &&
              projectItems.map((p) => (
                <Row
                  key={`p-${p.project_ref}`}
                  icon={<FolderGit2 size={15} />}
                  color="#3b82f6"
                  title={p.name}
                  meta={[
                    p.owner ? `@${p.owner}` : '公开项目',
                    p.provider || '',
                    p.node_count != null ? `${p.node_count} 个节点` : '',
                  ]}
                  snippet={p.desc || '（这个项目还没有简介）'}
                  onClick={() => openProject(p.project_ref)}
                />
              ))}

            {tab !== 'project' &&
              noteItems.map((n) => {
                const meta = kindMeta(n.kind)
                const Icon = meta.icon
                return (
                  <Row
                    key={`n-${n.id}`}
                    icon={<Icon size={15} />}
                    color={meta.color}
                    badge={meta.label}
                    title={n.title || '（无标题）'}
                    meta={[
                      n.project?.project_name || '',
                      n.created_by ? `@${n.created_by}` : '',
                      fmt(n.created_at),
                    ]}
                    snippet={(n.body || '').replace(/[#*`>\n]/g, ' ').slice(0, 90)}
                    onClick={() => openNote(n)}
                  />
                )
              })}

            {!notes.isLoading && projectItems.length === 0 && noteItems.length === 0 && (
              <div className="faint" style={{ padding: 16, fontSize: 12.5 }}>
                没有匹配的项目或笔记 —— 换个关键词试试。
              </div>
            )}

            {notes.isLoading && (
              <div className="faint" style={{ padding: 16, fontSize: 12.5 }}>
                搜索中…
              </div>
            )}
          </div>

          {/* ④ 分页 */}
          {noteTotal > PAGE && (
            <div className="flex items-center" style={{ gap: 8, marginTop: 12, justifyContent: 'flex-end' }}>
              <span className="faint" style={{ fontSize: 11.5 }}>
                {offset + 1}–{Math.min(offset + PAGE, noteTotal)} / {noteTotal}
              </span>
              <Button
                disabled={!hasPrev}
                onClick={() => patch({ offset: Math.max(0, offset - PAGE) })}
                icon={<ChevronLeft size={13} />}
              >
                上一页
              </Button>
              <Button
                disabled={!hasNext}
                onClick={() => patch({ offset: offset + PAGE })}
                icon={<ChevronRight size={13} />}
              >
                下一页
              </Button>
            </div>
          )}
        </>
      )}
    </AppLayout>
  )
}

function chip(active: boolean): React.CSSProperties {
  return {
    padding: '3px 11px',
    borderRadius: 999,
    fontSize: 11.5,
    lineHeight: '18px',
    border: 'none',
    cursor: 'pointer',
    background: active ? 'var(--card)' : 'transparent',
    color: active ? 'var(--text-main)' : 'var(--text-sub)',
    boxShadow: active ? '0 1px 3px rgba(15,23,42,.12)' : 'none',
  }
}

function Row({
  icon,
  color,
  badge,
  title,
  meta,
  snippet,
  onClick,
}: {
  icon: React.ReactNode
  color: string
  badge?: string
  title: string
  meta: string[]
  snippet?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        width: '100%',
        textAlign: 'left',
        padding: '11px 14px',
        border: 'none',
        borderBottom: '1px solid var(--card-border)',
        background: 'transparent',
        cursor: 'pointer',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--bg-deep)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
      }}
    >
      <span style={{ color, marginTop: 2, flexShrink: 0 }}>{icon}</span>

      <span style={{ flex: 1, minWidth: 0 }}>
        <span className="flex items-center" style={{ gap: 6 }}>
          {badge && (
            <span
              style={{
                fontSize: 9.5,
                lineHeight: '15px',
                padding: '0 6px',
                borderRadius: 999,
                color,
                border: `1px solid ${color}`,
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              {badge}
            </span>
          )}
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--text-main)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {title}
          </span>
        </span>

        {snippet && (
          <span
            className="faint"
            style={{
              display: 'block',
              fontSize: 11.5,
              marginTop: 2,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {snippet}
          </span>
        )}

        <span className="faint" style={{ fontSize: 10.5, marginTop: 2, display: 'block' }}>
          {meta.filter(Boolean).join(' · ')}
        </span>
      </span>

      <ArrowRight size={13} style={{ color: 'var(--text-faint)', marginTop: 4 }} />
    </button>
  )
}
