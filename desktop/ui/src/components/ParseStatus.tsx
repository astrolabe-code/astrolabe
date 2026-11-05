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
 * | ★★ 新后端 `Job.state` | **`none` / `queued` / `running` / `done` / `failed` / `canceled``** |
 *
 * ⇒ ★★ **两点必须改**：
 * 1. ★ `idle` ⇒ **`none`**（★ 项目还没投递过解析）
 * 2. ★★★ `parsing` 在旧站是**一个**状态，★ 而新后端分成 **`queued`（排队）**
 *    与 **`running`（真在跑）** —— ⚠ 若只认 `parsing`，
 *    ★ 解析中的项目会**显示成"待解析"**（★ 用户会以为没开始）
 *
 * ## ⚠★★ 2026-10-13 再修两处（★ 都是"名字写错 / 判据写漏"）⚠
 *
 * ★★ 一、**失败态叫 `failed`，❌ 不叫 `error`** ⚠
 *   ★ 这一段文档当时写的是 `error` —— ★★ 而 `jobs/models.py::Job.STATE_CHOICES`
 *     里是 **`failed`**（★ 另有 `canceled`）⚠
 *   ⇒ ★★ 后果：★ **解析失败的项目显示成「待解析」**（★ 看起来像"没开始"）⚠
 *
 * ★★ 二、**"有图"与"作业状态"是两件事** ⚠
 *   ★ "复用现成基图"那条路**根本没有作业** ⇒ `status='none'`
 *   ⇒ ★★ 但项目**已经有图了**（★ 卡片的 `graph_built` 为真）⚠
 *   ★ 判据在**调用方**（★ 见 `ProjectCard`：有图就传 `'done'`）——
 *     ★ 因为"有没有图"只有调用方知道 ✅
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

/**
 * ★ 归一：认不出来的取值一律当 `none`（⚠ 不猜，免得显示错误状态）
 *
 * ⚠★★ 2026-10-13：★ 这里原先**漏了后端真实的失败态名** ⚠
 *   · ★ 后端是 **`failed`**（★ 见 `jobs/models.py::Job.STATE_CHOICES`）—— ❌ 不是 `error` ⚠
 *   · ★ 另有 `canceled` —— ★ 用户视角同样是"这次没成" ✅
 *   ⇒ ★★ 漏判的后果：★ **失败的项目徽章显示成「待解析」** ⚠
 *     ★（★ 用户看不出"跑过并且失败了"，★ 只会以为"还没开始"）⚠
 */
export function normalizeState(status?: string): ParseState {
  // ★ 后端的失败态（★ 两个名字都要认 —— 见上面那段）
  if (status === 'failed' || status === 'canceled') return 'error'
  return status === 'queued' || status === 'running' || status === 'done' ? status : 'none'
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
