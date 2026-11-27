/**
 * 工作台外壳：活动栏 / 侧边栏 / 内容 三者的**语义**集中在这里。
 *
 * ## 为什么要有这一层
 *
 * 分栏本身由 `SplitPane` 负责（只管拖拽 + 占位容器）；
 * 但「有哪几栏、各自什么约束、侧栏开合」属于**工作台布局**，
 * 散在 App.tsx 里会变成一堆裸数字（36 / 260 / 200 / 320…），
 * 加一栏就要再嵌一层。VS Code 对应的是 `Layout` 那层。
 *
 * ## 分层对照
 *
 * ```
 * VS Code           我们
 * -------           -------------------
 * Grid          →   SplitPane（拖拽 + 占位）
 * Part          →   Ribbon / RibbonPanel（各自管内部）
 * Layout        →   本组件（有哪几栏、什么约束）
 * ```
 *
 * ## 只给「能拖的线」用 SplitPane
 *
 * - 活动栏（Ribbon）宽度固定 36px，**不可拖** ⇒ 普通 div，⛔ 不套 SplitPane
 * - 侧边栏（RibbonPanel）宽度可拖 ⇒ SplitPane
 * - 内容区吃剩余 ⇒ flex:1
 */
import type { ReactNode } from 'react'
import SplitPane from '../SplitPane'

interface WorkbenchShellProps {
  /** 最左图标栏（固定宽度，不可拖） */
  activityBar: ReactNode
  /** 侧边面板；传 null ⇒ 收起（不挂载、不取数） */
  sideBar?: ReactNode | null
  /** 活动栏宽度（默认 36，VS Code Activity Bar 口径） */
  activityBarWidth?: number
  /** 侧边栏初始/最小宽度 */
  sideBarInitialWidth?: number
  sideBarMinWidth?: number
  children: ReactNode
}

export default function WorkbenchShell({
  activityBar,
  sideBar,
  activityBarWidth = 36,
  sideBarInitialWidth = 260,
  sideBarMinWidth = 200,
  children,
}: WorkbenchShellProps) {
  return (
    <div style={{ display: 'flex', flex: 1, minHeight: 0, minWidth: 0 }}>
      {/* ── 活动栏：固定宽度，⛔ 不是分栏（SplitPane 的拖拽/测量全都用不上）── */}
      <div
        style={{
          width: activityBarWidth,
          flex: 'none',
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
        }}
      >
        {activityBar}
      </div>

      {/* ── 侧栏 + 内容：这一条线才是真能拖的 ── */}
      <SplitPane
        fixed="left"
        initial={sideBarInitialWidth}
        min={sideBarMinWidth}
        storageKey="astrolabe.workbench.sideBarWidth"
        collapsed={!sideBar}
        collapsedSide="left"
      >
        {sideBar ?? <div />}
        <div
          className="app-scroll"
          style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', overflowX: 'hidden' }}
        >
          {children}
        </div>
      </SplitPane>
    </div>
  )
}
