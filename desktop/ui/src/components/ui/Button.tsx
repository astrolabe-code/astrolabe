import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { LoaderCircle } from 'lucide-react'
import { cn } from '../../lib/cn'

type Variant = 'primary' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  loading?: boolean
  icon?: ReactNode
  block?: boolean
}

/**
 * 按钮:外观沿用站点语义类 `.btn + .primary/.ghost/.danger`(D20),
 * 布局与禁用态由 Tailwind 工具类补充。
 */
export default function Button({
  variant = 'ghost',
  loading = false,
  icon,
  block = false,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={cn('btn', variant, block && 'w-full', className)}
      disabled={disabled || loading}
      style={disabled || loading ? { opacity: 0.6, cursor: 'not-allowed' } : undefined}
      {...rest}
    >
      {loading ? <LoaderCircle size={15} className="animate-spin" /> : icon}
      {children}
    </button>
  )
}
