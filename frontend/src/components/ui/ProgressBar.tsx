import { cn } from '../../lib/cn'

interface ProgressBarProps {
  value: number
  /** idle(灰) / parsing(accent) / done(绿) / error(红) */
  status?: string
  className?: string
  /** 是否显示右侧百分比 */
  showValue?: boolean
}

const COLORS: Record<string, string> = {
  idle: 'var(--text-faint)',
  parsing: 'var(--accent)',
  done: 'var(--ok)',
  error: 'var(--err)',
}

/** 解析进度条:纯 Tailwind + 主题变量,无额外样式文件 */
export default function ProgressBar({ value, status = 'idle', className, showValue }: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, Math.round(value || 0)))
  const color = COLORS[status] || COLORS.idle

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div
        className="flex-1 rounded-full overflow-hidden"
        style={{ height: 6, background: 'var(--accent-dim)' }}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      {showValue && (
        <span className="mono text-xs text-text-faint shrink-0" style={{ minWidth: 34, textAlign: 'right' }}>
          {pct}%
        </span>
      )}
    </div>
  )
}
