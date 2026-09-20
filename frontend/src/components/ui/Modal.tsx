import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { X } from 'lucide-react'

interface ModalProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** 默认 min(360px, 86vw);宽表单可传更大值 */
  width?: number
}

/** 弹窗:沿用站点 `.dlg-mask` / `.dlg` 外观,支持 Esc 关闭与滚动锁定 */
export default function Modal({ open, title, onClose, children, footer, width }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="dlg-mask" onClick={onClose}>
      <div
        className="dlg"
        style={width ? { width: `min(${width}px, 92vw)` } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 mb-1">
          <div className="dlg-title mb-0">{title}</div>
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="flex items-center justify-center rounded-full shrink-0"
            style={{
              width: 28,
              height: 28,
              border: '1px solid var(--card-border)',
              color: 'var(--text-sub)',
              background: 'transparent',
              cursor: 'pointer',
            }}
          >
            <X size={14} />
          </button>
        </div>
        <div className="max-h-[68vh] overflow-y-auto mt-3">{children}</div>
        {footer && <div className="dlg-actions mt-5">{footer}</div>}
      </div>
    </div>
  )
}
