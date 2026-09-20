import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'

interface AppLayoutProps {
  children: ReactNode
  /** 面包屑:如 [{label:'工作区', to:'/workspace'}, {label:'图谱'}] */
  crumbs?: Array<{ label: string; to?: string }>
  /** 页面标题与右侧操作 */
  title?: ReactNode
  actions?: ReactNode
  /** 是否使用 1120px 内容容器(默认 true;画布页传 false 走全宽) */
  page?: boolean
  /** 页面级淡入动画(默认开) */
  rise?: boolean
}

/**
 * 布局壳:顶栏为全局 `TopNav`(见 App.tsx),这里只负责内容容器与页头。
 * 与现站一致:`.page` 1120px 居中、36/30/64 内边距。
 */
export default function AppLayout({
  children,
  crumbs,
  title,
  actions,
  page = true,
  rise = true,
}: AppLayoutProps) {
  const inner = (
    <>
      {crumbs && crumbs.length > 0 && (
        <div className="crumbs flex items-center gap-1.5 flex-wrap">
          {crumbs.map((c, i) => (
            <span key={`${c.label}-${i}`} className="flex items-center gap-1.5">
              {i > 0 && <ChevronRight size={12} />}
              {c.to ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
            </span>
          ))}
        </div>
      )}
      {(title || actions) && (
        <div className="page-head">
          {title && <div className="h1">{title}</div>}
          {actions && <div className="head-actions">{actions}</div>}
        </div>
      )}
      {children}
    </>
  )

  if (!page) {
    return <div className="relative z-[1]">{inner}</div>
  }
  return <div className={`page${rise ? ' rise' : ''}`}>{inner}</div>
}
