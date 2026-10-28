import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

interface ModalProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** 默认 min(360px, 86vw);宽表单可传更大值 */
  width?: number
  /**
   * ★ 内容区**不滚动**（* 由弹窗内部自己控制滚动）——
   *   用于「列表滚动 + 底部固定输入框」的形态（* 如段评）⚠
   */
  noScroll?: boolean
}

/** 弹窗:沿用站点 `.dlg-mask` / `.dlg` 外观,支持 Esc 关闭与滚动锁定 */
export default function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  width,
  noScroll,
}: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  /**
   * ★★★ 2026-10-28：**弹窗必须挂到 `body`（portal），⛔ 不能就地渲染** ⚠
   *
   * 现象（所有者）：「保存这篇笔记这个弹窗是以纸张定位的，不是以页面定位的吗？
   *   我点了保存，要往上翻到纸张中间，才能看见这个弹窗」
   *
   * 原因：`.dlg-mask` 是 `position: fixed`，但 **祖先只要有 transform，
   *   `fixed` 就以那个祖先为参照，不再相对视口** ⚠
   *   实测祖先链上 `.page.rise` 的动画结束值是 `transform: matrix(1,0,0,1,0,0)`
   *   （视觉上等于没位移，但**不等于 `none`**）⇒ 弹窗被"框"在纸里 ⚠
   *
   * ⇒ 挂到 body：不受任何祖先的 transform / filter / contain 影响 ✅
   *   （这也是 sticky 那个坑的同一类原因 —— 见 `D135`）
   */
  return createPortal(
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
        <div className={noScroll ? 'mt-3' : 'max-h-[68vh] overflow-y-auto mt-3'}>
          {children}
        </div>
        {footer && <div className="dlg-actions mt-5">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
