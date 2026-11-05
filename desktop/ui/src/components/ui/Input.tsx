import type { InputHTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  hint?: ReactNode
  error?: string
}

/** 输入框:外观用站点语义类 `.input`,标签/提示用 Tailwind 排版 */
export default function Input({ label, hint, error, id, className, ...rest }: InputProps) {
  return (
    <div className="mb-4">
      {label && (
        <label
          htmlFor={id}
          className="block text-xs font-medium tracking-wide text-text-sub mb-1.5"
        >
          {label}
        </label>
      )}
      <input id={id} className={cn('input', className)} {...rest} />
      {error ? (
        <div className="text-xs mt-1.5" style={{ color: 'var(--err)' }}>{error}</div>
      ) : (
        hint && <div className="faint mt-1.5">{hint}</div>
      )}
    </div>
  )
}
