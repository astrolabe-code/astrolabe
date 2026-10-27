/**
 * ★★★ **导读路径**（`D123` 修正版 · 2026-10-27）⚠
 *
 * ⚠★ 改名的原因：上一版把它叫「导读进度」，显示「N / M 章」，
 *   但那些数字其实是**作者的小结覆盖**，读者看了会以为是自己的进度 ⚠
 *
 * ## 所有者原话（逐字）
 *
 * > 「**我这直接导出成一本还算看的过去的书……多有成就感呀，
 * >   有成就感，才有坚持下去的动力，对付拖延。**」
 * > 「**实时反馈，就像游戏一样，就是很多笔记软件缺少的。**」
 *
 * ## 做什么
 *
 * 把「学习路径」（`B234`）当成关卡列表，显示每一站是否已经写过**小结**：
 *
 * ```\n * 导读进度            1 / 4 章\n * ▓▓▓▓▓░░░░░░░░░  25%\n * ✅ tcp_init\n * ✅ tcp_connect\n * ⬜ tcp_ack          ← 下一站\n * ⬜ tcp_cong_avoid\n * ```\n *
 * ## ⛔ 刻意不做的
 *
 * ```\n * · 打卡 / 连续天数 / 积分  —— 外生动机，断一次就全断 ⚠\n * · 分阶段导出成书          —— 半成品的书只会提醒「还没写完」⚠\n * ```\n *
 * ⚠ 进度只认「小结」：五类里只有它是**对象视角**（这段代码是什么），
 *   其余四类是「我」视角（我不懂 / 我踩过），不能算「这一站读懂了」⚠
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check } from 'lucide-react'

import { useReadingPath } from '../../query/readingPath'

interface PathProgressProps {
  projectRef: string
  /** ★ 默认只露几站，其余折叠（* 路径可能有几十站）⚠ */
  collapsed?: number
}

export default function PathProgress({ projectRef, collapsed = 5 }: PathProgressProps) {
  const nav = useNavigate()
  const pathQ = useReadingPath(projectRef)
  const [open, setOpen] = useState(false)

  const items = pathQ.data?.items ?? []
  const done = pathQ.data?.done ?? 0
  const total = items.length

  // ★ 「下一站」= 第一个还没写小结的（* 进度条之外最有用的一条信息）⚠
  const nextVid = useMemo(() => items.find((i) => !i.has_summary)?.vid ?? 0, [items])

  if (pathQ.isLoading || total === 0) return null

  const shown = open ? items : items.slice(0, collapsed)

  return (
    <div className="card" style={{ padding: '10px 12px', marginBottom: 12 }}>
      <div className="flex items-center gap-2" style={{ marginBottom: 8 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>导读路径</span>
        {/* ⚠ 这里显示的是「作者写了多少站」，⛔ 不是读者的进度 ⚠ */}
        <span className="faint" style={{ fontSize: 11 }}>
          {total} 站 · 已写 {done}
        </span>
      </div>

      <div className="flex flex-col gap-0.5">
        {shown.map((it) => {
          const isNext = it.vid === nextVid
          return (
            <button
              key={it.vid}
              type="button"
              onClick={() => nav(`/p/${encodeURIComponent(projectRef)}?node=${it.vid}`)}
              title={it.file_path ? `${it.file_path}:${it.line}` : it.name}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                width: '100%',
                textAlign: 'left',
                padding: '3px 6px',
                borderRadius: 6,
                border: 'none',
                background: isNext ? 'var(--accent-dim)' : 'transparent',
                cursor: 'pointer',
                fontFamily: 'var(--font-ui)',
              }}
            >
              <span
                style={{
                  width: 13,
                  height: 13,
                  borderRadius: 3,
                  flexShrink: 0,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: it.has_summary ? 'none' : '1px solid var(--card-border)',
                  background: it.has_summary ? 'var(--ok)' : 'transparent',
                }}
              >
                {it.has_summary && <Check size={9} color="#fff" strokeWidth={3} />}
              </span>
              <span
                className="faint"
                style={{ fontSize: 10.5, width: 14, flexShrink: 0, fontVariant: 'tabular-nums' }}
              >
                {it.ordinal + 1}
              </span>
              <span
                style={{
                  fontSize: 12,
                  color: it.has_summary ? 'var(--text-sub)' : 'var(--text-main)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {it.name}
              </span>
              {isNext && (
                <span className="faint" style={{ fontSize: 10.5, marginLeft: 'auto', flexShrink: 0 }}>
                  下一站
                </span>
              )}
            </button>
          )
        })}
      </div>

      {items.length > collapsed && (
        <button
          type="button"
          className="link-btn"
          style={{ marginTop: 4, paddingLeft: 6 }}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? '收起' : `展开全部 ${items.length} 站`}
        </button>
      )}
    </div>
  )
}
