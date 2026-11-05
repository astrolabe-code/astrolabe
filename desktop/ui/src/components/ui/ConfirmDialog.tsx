import type { ReactNode } from 'react'
import Modal from './Modal'
import Button from './Button'

interface ConfirmDialogProps {
  open: boolean
  title: string
  message: ReactNode
  confirmText?: string
  cancelText?: string
  danger?: boolean
  loading?: boolean
  /** 操作失败的提示(显示在正文下方) */
  error?: string
  onConfirm: () => void
  onCancel: () => void
}

/** 确认弹窗:沿用站点弹窗外观;`message` 支持换行(white-space: pre-line) */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmText = '确定',
  cancelText = '取消',
  danger = false,
  loading = false,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      title={title}
      width={420}
      onClose={onCancel}
      footer={
        <>
          <Button onClick={onCancel} disabled={loading}>{cancelText}</Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            loading={loading}
            onClick={onConfirm}
          >
            {confirmText}
          </Button>
        </>
      }
    >
      <div className="text-text-sub" style={{ fontSize: 13.5, lineHeight: 1.9, whiteSpace: 'pre-line' }}>
        {message}
      </div>
      {error && <div className="text-xs mt-3" style={{ color: 'var(--err)' }}>{error}</div>}
    </Modal>
  )
}
