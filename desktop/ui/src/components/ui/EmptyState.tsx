import type { ReactNode } from 'react'
import { PackageOpen } from 'lucide-react'

interface EmptyStateProps {
  title: string
  hint?: ReactNode
  action?: ReactNode
  /** 自定义图标;默认空盒子 */
  icon?: ReactNode
  /** 错误态用红色标题 */
  tone?: 'muted' | 'error'
}

/** 空态/错误态占位:统一卡片内居中排版 */
export default function EmptyState({ title, hint, action, icon, tone = 'muted' }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-12 px-6">
      <div
        className="flex items-center justify-center rounded-2xl mb-4"
        style={{
          width: 46,
          height: 46,
          background: tone === 'error' ? 'rgba(220,38,38,0.10)' : 'var(--accent-dim)',
          color: tone === 'error' ? 'var(--err)' : 'var(--accent)',
        }}
      >
        {icon || <PackageOpen size={20} />}
      </div>
      <div className="h2 mb-1.5" style={tone === 'error' ? { color: 'var(--err)' } : undefined}>
        {title}
      </div>
      {hint && <div className="sub mb-0" style={{ maxWidth: 420 }}>{hint}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}
