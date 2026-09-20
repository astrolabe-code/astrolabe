import { CircleCheck, CircleX, Clock, LoaderCircle, Timer } from 'lucide-react'
import ProgressBar from './ui/ProgressBar'

/**
 * ★ 解析状态徽章（`B164` 改写）
 *
 * ## ⚠★ 取值变了 —— 旧项目对不上新后端
 *
 * | | 取值 |
 * |---|---|
 * | ⚠ 旧站 `Project.parse_status` | `idle` / `parsing` / `done` / `error`（4 个）|
 * | ★★ 新后端 `Job.state` | **`none` / `queued` / `running` / `done` / `error`**（5 个）|
 *
 * ⇒ ★★ **两点必须改**：
 * 1. ★ `idle` ⇒ **`none`**（★ 项目还没投递过解析）
 * 2. ★★★ `parsing` 在旧站是**一个**状态，★ 而新后端分成 **`queued`（排队）**
 *    与 **`running`（真在跑）** —— ⚠ 若只认 `parsing`，
 *    ★ 解析中的项目会**显示成"待解析"**（★ 用户会以为没开始）
 *
 * 依据：`app/web/views/projects.py::progress()` · `app/jobs/models.py`
 */
export type ParseState = 'none' | 'queued' | 'running' | 'done' | 'error'

interface ParseStatusProps {
  status?: string
  progress?: number
  /** 显示进度条（★ 卡片 / 主页用）；★ 只要徽章时传 false */
  bar?: boolean
  size?: 'sm' | 'md'
}

const LABELS: Record<ParseState, string> = {
  none: '待解析',
  queued: '排队中',
  running: '解析中',
  done: '已就绪',
  error: '解析失败',
}

const TONE: Record<ParseState, { color: string; bg: string }> = {
  none: { color: 'var(--text-sub)', bg: 'rgba(30,64,105,0.08)' },
  queued: { color: 'var(--warn)', bg: 'rgba(217,119,6,0.12)' },
  running: { color: 'var(--accent)', bg: 'var(--accent-dim)' },
  done: { color: 'var(--ok)', bg: 'rgba(5,150,105,0.12)' },
  error: { color: 'var(--err)', bg: 'rgba(220,38,38,0.10)' },
}

/** ★ 归一：认不出来的取值一律当 `none`（⚠ 不猜，免得显示错误状态） */
export function normalizeState(status?: string): ParseState {
  return status === 'queued' || status === 'running' || status === 'done' || status === 'error'
    ? status
    : 'none'
}

function StatusIcon({ state, size }: { state: ParseState; size: number }) {
  if (state === 'done') return <CircleCheck size={size} />
  if (state === 'error') return <CircleX size={size} />
  if (state === 'queued') return <Timer size={size} />
  if (state === 'running') return <LoaderCircle size={size} className="animate-spin" />
  return <Clock size={size} />
}

/** ★ 解析状态徽章（+ 可选进度条） */
export default function ParseStatus({ status, progress = 0, bar = false, size = 'md' }: ParseStatusProps) {
  const state = normalizeState(status)
  const tone = TONE[state]
  const iconSize = size === 'sm' ? 11 : 12

  return (
    <div className="flex flex-col gap-2">
      <span
        className="inline-flex items-center gap-1.5 rounded-full font-medium whitespace-nowrap"
        style={{
          padding: size === 'sm' ? '2px 9px' : '3px 11px',
          fontSize: size === 'sm' ? 11 : 12,
          color: tone.color,
          background: tone.bg,
        }}
        title={`job.state=${state}`}
      >
        <StatusIcon state={state} size={iconSize} />
        {LABELS[state]}
      </span>
      {bar && (state === 'queued' || state === 'running') && (
        <ProgressBar value={progress} status={state} showValue />
      )}
    </div>
  )
}
