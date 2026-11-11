import {
  Children,
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useMediaQuery } from '../hooks/useMediaQuery'
import type {
  CSSProperties,
  PointerEvent as ReactPointerEvent,
  ReactElement,
  ReactNode,
  RefObject,
} from 'react'

const HANDLE_WIDTH = 1

interface SplitPaneProps {
  /** 恰好两个子元素：左栏、右栏（条件渲染出的 false 会被忽略） */
  children: ReactNode
  /** 哪一栏是"固定宽度、可拖拽"的 */
  fixed: 'left' | 'right'
  /** 初始宽度（px） */
  initial: number
  /** 可拖拽那一栏的最小宽度 */
  min: number
  /** 另一栏的最小宽度（用来算动态上限）
   *  ⚠ 嵌套分栏时这里要传「另一侧整个子树的最小宽之和」，
   *    否则外层拖到最右会把内层挤得比它自己的固定栏还窄 */
  otherMin: number
  /** 需要读容器尺寸的页面传入自己的 ref（图谱页窄屏抓手要用） */
  containerRef?: RefObject<HTMLDivElement>
  /** 只用于页面特有的差异（列表页的 alignItems）；通用布局组件自己写死 */
  style?: CSSProperties
  /** 让既有 CSS 的 `.xxx > child` / `.xxx .grandchild` 选择器继续生效 */
  className?: string

  // ---------------------------------------------------------------- 隐藏接口
  /**
   * ★★ 2026-11-11（所有者：「隐藏按钮先不做出来，留个接口就行」）
   * 组件**不画**任何隐藏按钮。调用方自己渲染开关（顶栏 / ribbon / 面板 ×），
   * 用 `collapsed` 受控；`onCollapsedChange` 是给将来那个开关预留的回调接口，
   * `renderToggle` 是预留的按钮插槽 —— 本批都不使用，只在接口上留好位置。
   */
  collapsed?: boolean
  onCollapsedChange?: (next: boolean) => void
  renderToggle?: () => ReactNode
  /** 收起时隐藏哪一栏（默认隐藏固定宽那一栏 = 侧栏） */
  collapsedSide?: 'fixed' | 'left' | 'right'

  /** 窄屏断点（默认 900；阅读/编辑页传 1100） */
  breakpoint?: number
  /** 默认抹掉两栏的 border / 圆角 / 阴影；编辑页纸的类别色描边要保留 */
  preserveChildStyle?: boolean
  /** 分隔条是否可拖拽（默认 true；ribbon / 功能面板这种固定宽度栏传 false） */
  resizable?: boolean
  /** 是否画分隔线（默认 true；子栏自带 borderRight 时传 false 避免双线） */
  divider?: boolean
}

type StyledElement = ReactElement<{ style?: CSSProperties }>

/** 上限是动态的：容器宽 − 分隔条 − 另一栏最小宽（⛔ 不写死 680 之类） */
function clampWidth(w: number, min: number, otherMin: number, inner: number) {
  const max = Math.max(min, inner - HANDLE_WIDTH - otherMin)
  return Math.min(max, Math.max(min, w))
}

/**
 * ★★★ **左右两栏 + 可拖拽分隔条的唯一组件**（2026-11-06）
 *
 * 所有者：「你对如此相同布局的两个页面分别写了两套骨架？」
 * ⇒ 列表页 `ProjectPage` 与图谱页 `ProjectGraphPage` 现在都只贴这个组件。
 *
 * ★ 2026-11-11：所有者「二分页和三分页，甚至四分页都可以在二分页的基础上
 *   嵌套出来」⇒ 不再做 N 栏容器，**嵌套本组件**即可表达任意多栏。
 *   因此新增 `collapsed` 等隐藏接口（按钮暂不实现），并支持嵌套所需的
 *   `breakpoint` / `preserveChildStyle` / `className` / `style` 透传。
 *
 * ```tsx
 * <SplitPane fixed="left" initial={300} min={220} otherMin={320}>
 *   <div className="card" style={...}>左栏</div>
 *   <div className="card" style={...}>右栏</div>
 * </SplitPane>
 * ```
 *
 * ## 为什么不另做 hook
 *
 * ```
 * 宽度状态、pointer 监听、window resize、clamp、分隔条 DOM 全在这里；
 * 页面只提供"两栏内容 + 几个数字"，没有第二套骨架。
 * ```
 *
 * ⚠ 用 `cloneElement` 给两栏注入宽度样式，是为了**不额外包一层 div** ——
 *   列表页左栏的 `position:sticky`、图谱页右栏的边框/圆角都留在页面里照旧生效。
 */
export default function SplitPane({
  children,
  fixed,
  initial,
  min,
  otherMin,
  containerRef,
  style,
  className,
  collapsed = false,
  onCollapsedChange,
  renderToggle,
  collapsedSide = 'fixed',
  breakpoint = 900,
  preserveChildStyle = false,
  resizable = true,
  divider = true,
}: SplitPaneProps) {
  // ★ 窄屏判定属于组件自己，断点可配：两页 900、note 页 1100
  const stacked = useMediaQuery(`(max-width: ${breakpoint}px)`)
  const innerRef = useRef<HTMLDivElement>(null)
  const ref = containerRef ?? innerRef
  const [width, setWidth] = useState(initial)
  const dragRef = useRef<{ startX: number; startW: number } | null>(null)
  /** ★ hover / 拖动时的蓝色反馈（VSCode sash 口径）：常驻仍是 1px 灰线 */
  const [hover, setHover] = useState(false)
  const [dragging, setDragging] = useState(false)
  // ★ 监听只注册一次 ⇒ 配置放 ref，避免闭包拿到旧的 min / fixed
  const cfg = useRef({ min, otherMin, fixed })
  cfg.current = { min, otherMin, fixed }

  // 预留接口：本批没有任何调用方使用，避免未使用变量告警
  void onCollapsedChange

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const drag = dragRef.current
      if (!drag) return
      const { min: mn, otherMin: om, fixed: fx } = cfg.current
      const inner = ref.current?.clientWidth ?? window.innerWidth
      const delta = e.clientX - drag.startX
      setWidth(clampWidth(drag.startW + (fx === 'left' ? delta : -delta), mn, om, inner))
    }
    const onUp = () => {
      dragRef.current = null
      setDragging(false)
    }
    const onWin = () => {
      const { min: mn, otherMin: om } = cfg.current
      const inner = ref.current?.clientWidth ?? window.innerWidth
      setWidth((w) => clampWidth(w, mn, om, inner))
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('resize', onWin)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('resize', onWin)
      dragRef.current = null
    }
  }, [ref])

  const onPointerDown = useCallback(
    (e: ReactPointerEvent) => {
      e.preventDefault()
      dragRef.current = { startX: e.clientX, startW: width }
      setDragging(true)
    },
    [width],
  )

  const kids = Children.toArray(children).filter(isValidElement) as StyledElement[]
  const [leftEl, rightEl] = kids
  /** ★ 只有一个有效子元素（面板收起 / 画布全屏 / 嵌套少一栏）⇒ 铺满，
   *  ⛔ 不能给它套固定栏宽度；原来图谱页靠 fixed=right 隐式绕过，现统一处理 */
  const sole = kids.length === 1

  /** 收起时：整块不渲染、分隔条也消失、另一栏铺满（⛔ 不留占位） */
  const hiddenSide: 'left' | 'right' | null = collapsed
    ? collapsedSide === 'fixed'
      ? fixed
      : collapsedSide
    : null

  const decorate = (el: StyledElement | undefined, isLeft: boolean) => {
    if (!el) return null
    const side = isLeft ? 'left' : 'right'
    if (side === hiddenSide) return null
    const size: CSSProperties = hiddenSide || sole
      ? { flex: 1, minWidth: 0, width: undefined }
      : stacked
        ? { width: '100%' }
        : fixed === side
          ? { width, flex: 'none', minWidth: 0 }
          : { flex: 1, minWidth: 0, width: undefined }
    // ★★ 两栏是「贴边的平铺面板」，不是两张浮起来的卡片：
    //   去掉 .card 的边框 / 圆角 / 阴影，中间只靠 1px 分隔线分界
    const pane: CSSProperties = preserveChildStyle
      ? {}
      : { border: 'none', borderRadius: 0, boxShadow: 'none' }
    return cloneElement(el, {
      style: { ...(el.props.style || {}), ...size, ...pane, minHeight: 0 },
    })
  }

  return (
    <div
      ref={ref}
      className={className}
      style={{
        display: 'flex',
        flexDirection: stacked ? 'column' : 'row',
        // ★ 两栏间隙统一为 0（所有者：「gap也要统一呀，都变成0就行了」）
        gap: 0,
        minHeight: 0,
        minWidth: 0,
        flex: 1,
        position: 'relative',
        ...style,
      }}
    >
      {decorate(leftEl, true)}
      {divider && !stacked && !hiddenSide && !sole && rightEl && (
        <div
          onPointerDown={resizable ? onPointerDown : undefined}
          onMouseEnter={resizable ? () => setHover(true) : undefined}
          onMouseLeave={resizable ? () => setHover(false) : undefined}
          title={resizable ? '拖动调整宽度' : undefined}
          style={{
            width: HANDLE_WIDTH,
            flexShrink: 0,
            alignSelf: 'stretch',
            minHeight: 24,
            touchAction: 'none',
            margin: 0,
            position: 'relative',
            cursor: resizable ? 'col-resize' : 'default',
            // ★ 常驻一条 1px 灰线，⛔ 不再 hover 变蓝（VSCode 分屏口径）
            background: 'var(--card-border)',
          }}
        >
          {/* ★ hover / 拖动 ⇒ 蓝色粗线（VSCode 拉动时的颜色反馈）；
              绝对定位、不占布局，宽度变化不会推挤两栏 */}
          <div
            style={{
              position: 'absolute',
              left: -1.5,
              top: 0,
              bottom: 0,
              width: 4,
              background: 'var(--accent)',
              opacity: hover || dragging ? 1 : 0,
              transition: 'opacity .12s',
              pointerEvents: 'none',
            }}
          />
          {/* 视觉只有 1px，命中区放宽到 9px 才好拖（绝对定位，不占布局） */}
          <div
            style={{
              position: 'absolute',
              left: -4,
              top: 0,
              bottom: 0,
              width: 9,
              cursor: 'col-resize',
            }}
          />
        </div>
      )}
      {decorate(rightEl, false)}
      {/* ★ 预留的隐藏按钮插槽：本批不渲染任何内置按钮，
          将来调用方传 renderToggle 才出现（不占布局） */}
      {renderToggle && (
        <div style={{ position: 'absolute', top: 0, right: 0, zIndex: 6 }}>
          {renderToggle()}
        </div>
      )}
    </div>
  )
}
