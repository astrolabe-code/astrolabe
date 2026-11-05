import type { ReactNode } from 'react'

interface AppLayoutProps {
  children: ReactNode
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
 *
 * ⚠★ **不再支持路径面包屑**（`crumbs`）—— 所有者：
 *   「我跟你说了不要这个路径面包屑了」「你直接把显示面包屑的代码删了，不就完了？
 *     怎么一个页面一个页面得区删引用？」
 *   ⇒ ★ 渲染逻辑**已整段删除**，* 任何页面都渲染不出面包屑 ✅
 */
export default function AppLayout({
  children,
  title,
  actions,
  page = true,
  rise = true,
}: AppLayoutProps) {
  const inner = (
    <>
      {(title || actions) && (
        // ⚠ 没有 title、只剩操作按钮时加一个类 ⇒ 收紧下边距，
        //   否则会留下一条窄而空的横条（* 2026-10-26 去掉阅读页/编辑页大标题后暴露）⚠
        <div className={`page-head${title ? '' : ' page-head--actions-only'}`}>
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
