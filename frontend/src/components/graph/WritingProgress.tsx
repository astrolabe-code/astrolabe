/**
 * ★★★ **写作进度**（`D123` 修正版 · 2026-10-27）⚠
 *
 * ## 所有者原话（逐字）
 *
 * > 「**作者也那个进度应该是统计的意义，还有多少函数节点没写，
 * >   还有多少文件节点没写，写了多少之类的**」
 *
 * ## 和「导读路径」的分工
 *
 * ```\n * 写作进度  覆盖率 —— 这个项目的节点，写进书里多少了（给**作者**看）\n * 导读路径  阅读顺序 —— 先读哪个再读哪个（给**读者**看，`PathProgress`）\n * ```\n *
 * ⚠ 上一版把「路径有几站写了小结」当进度，混了这两件事 ⚠
 *
 * ## 只认「小结」
 *
 * 五类里只有「小结」是对象视角（这段代码是什么）⇒ 才算「写进书里了」。
 * 灵光 / 质疑 / 困惑 / 踩坑是「我」视角，写了也不算 ⚠
 */
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { useCollapsed } from '../../lib/useCollapsed'

import { apiGet } from '../../api/client'
import { unwrap } from '../../api/errors'

interface Bucket {
  total: number
  file: number
  function: number
  type: number
  other: number
}

interface ProgressData {
  nodes: Bucket
  summary: Bucket
  noted: { total: number }
}

function useWritingProgress(projectRef: string) {
  return useQuery({
    queryKey: ['writing-progress', projectRef],
    enabled: !!projectRef,
    queryFn: async (): Promise<ProgressData> =>
      unwrap(
        await apiGet<ProgressData>(
          `/api/projects/${encodeURIComponent(projectRef)}/writing-progress/`,
          // ⚠ 后端用的是 `ok({...})` ⇒ envelope 带一层 `data`，
          //   ⛔ 不能用 'spread'（那样拿到的是 `{data: {...}}`，字段全是 undefined）⚠
          'data',
        ),
      ),
  })
}

const ROWS: { key: keyof Bucket; label: string }[] = [
  { key: 'file', label: '文件' },
  { key: 'function', label: '函数' },
  { key: 'type', label: '类型' },
]

export default function WritingProgress({ projectRef }: { projectRef: string }) {
  // ★ 折叠状态按项目记（* 收起后下次打开还是收着的）⚠
  const { collapsed, toggle } = useCollapsed(`wp:${projectRef}`)
  const q = useWritingProgress(projectRef)
  if (q.isLoading || !q.data) return null

  const { nodes, summary, noted } = q.data
  if (!nodes.total) return null

  const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0)

  return (
    <div className="card" style={{ padding: '10px 12px', marginBottom: 12 }}>
      {/* ★ 整行可点 ⇒ 折叠（`D126` 后加：两张卡占的空间太多）⚠ */}
      <button
        type="button"
        onClick={toggle}
        title={collapsed ? '展开' : '收起'}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          width: '100%',
          padding: 0,
          marginBottom: collapsed ? 0 : 8,
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          fontFamily: 'var(--font-ui)',
          textAlign: 'left',
        }}
      >
        {collapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>写作进度</span>
        {!collapsed && (
          <span className="faint" style={{ fontSize: 11 }}>
            按「小结」算
          </span>
        )}
        <span className="faint" style={{ fontSize: 11.5, marginLeft: 'auto' }}>
          {summary.total} / {nodes.total}
        </span>
      </button>

      {collapsed ? null : (
      <>
      <div className="flex flex-col gap-1.5">
        {ROWS.map((r) => {
          const total = nodes[r.key]
          if (!total) return null
          const done = summary[r.key]
          const p = pct(done, total)
          return (
            <div key={r.key} className="flex items-center gap-2">
              <span className="faint" style={{ fontSize: 11.5, width: 30, flexShrink: 0 }}>
                {r.label}
              </span>
              <div
                style={{
                  flex: 1,
                  height: 4,
                  borderRadius: 999,
                  background: 'var(--card-border)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: `${p}%`,
                    height: '100%',
                    background: 'var(--accent)',
                    transition: 'width .3s',
                  }}
                />
              </div>
              <span
                style={{
                  fontSize: 11,
                  color: 'var(--text-faint)',
                  width: 54,
                  textAlign: 'right',
                  flexShrink: 0,
                  fontVariant: 'tabular-nums',
                }}
              >
                {done} / {total}
              </span>
            </div>
          )
        })}
      </div>

      <div
        className="faint"
        style={{ fontSize: 11, marginTop: 8, paddingTop: 7, borderTop: '1px solid var(--card-border)' }}
      >
        还有 <b style={{ color: 'var(--text-main)' }}>{nodes.total - summary.total}</b> 个节点没写小结
        {noted.total > summary.total && ` · ${noted.total} 个节点有笔记`}
      </div>
      </>
      )}
    </div>
  )
}
