import {
  Children,
  isValidElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
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
  /** 哪一栏是"固定尺寸、可拖拽"的（垂直时 left=上、right=下） */
  fixed: 'left' | 'right'
  /** ★ 分栏方向：horizontal（默认，左右）/ vertical（上下） */
  direction?: 'horizontal' | 'vertical'
  /** 初始宽度（px） */
  initial: number
  /** 可拖拽那一栏的最小宽度 */
  min: number
  /** 另一栏的最小宽度（用来算动态上限）
   *  · 传了 ⇒ 用它和「容器 45%」取小；
   *  · ⛔ 不传 ⇒ 直接用「容器 45%」当预算（嵌套时不用人肉累加子树最小值）
   *  ⚠ 嵌套分栏时若内层有硬性下限，仍建议传「另一侧子树最小宽之和」 */
  otherMin?: number
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

  /** 转上下分栏的**容器宽度**阈值 px（默认 520；⛔ 不是窗口宽度）
   *  · 传 0 ⇒ 关闭自动堆叠（本来就是上下分栏、或窄屏由页面自己处理时用） */
  breakpoint?: number
  /** 分隔条是否可拖拽（默认 true；ribbon / 功能面板这种固定宽度栏传 false） */
  resizable?: boolean
  /** 是否画分隔线（默认 true；子栏自带 borderRight 时传 false 避免双线） */
  divider?: boolean
  /** ★ 传了就自动持久化宽度到 localStorage（键名由调用方给，避免多处冲突） */
  storageKey?: string
}

type StyledElement = ReactElement<{ style?: CSSProperties }>

/**
 * 上限是动态的：容器宽 − 分隔条 − 另一栏最小宽（⛔ 不写死 680 之类）
 *
 * ⚠★ 2026-11-11 修「完全拖不动」：嵌套分栏里**容器已经被上层吃掉一大截**，
 *   调用方传的 otherMin 是按另一栏「内容需要多宽」估的（320/480/520），
 *   再拿它去减这个被挤窄的容器 ⇒ max 被压到等于 min ⇒ 可拖范围 0px。
 *   ⇒ otherMin 改成「占比上限」：最多只保留容器的 45%，且不小于调用方给的
 *     绝对下限；这样每一层都留得出可拖空间。
 */
function clampWidth(w: number, min: number, otherMin: number | undefined, inner: number) {
  const cap = Math.floor(inner * 0.45)
  // ★ 不传 otherMin ⇒ 只受「容器 45%」约束（嵌套时免去人肉累加子树最小宽）
  const budget = otherMin == null ? cap : Math.min(otherMin, cap)
  const max = Math.max(min, inner - HANDLE_WIDTH - budget)
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
 *   `breakpoint` / `className` / `style` 透传。
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
 * ★ 2026-11-27：**分页组件只管拖拽 + 占位容器**，⛔ 不管子元素长什么样。
 *   · 每栏自带一层 wrapper（grid，子项 stretch ⇒ 页面自动撑满）
 *   · 子元素一个 prop 都不用改、不用写 width/height
 *   · 没有 preserveChildStyle 之类的外观开关（已删除）
 */
export default function SplitPane({
  children,
  fixed,
  direction = 'horizontal',
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
  breakpoint = 520,
  resizable = true,
  divider = true,
  storageKey,
}: SplitPaneProps) {
  const innerRef = useRef<HTMLDivElement>(null)
  const ref = containerRef ?? innerRef
  const [width, setWidth] = useState(() => {
    if (!storageKey) return initial
    try {
      const n = Number(localStorage.getItem(storageKey))
      if (Number.isFinite(n) && n > 0) return Math.max(min, n)
    } catch {
      /* 隐私模式等读不到 ⇒ 用默认值 */
    }
    return initial
  })
  /**
   * ★★ 2026-11-11 修「把手都不见了」：断点必须看**容器宽度**，⛔ 不是窗口宽度。
   *   嵌套到第 4 层时容器只有 500 多 px，但窗口可能有 1080px —— 用
   *   matchMedia('(max-width:1100px)') 会在窗口 1080 时误判 stacked，
   *   于是分隔条根本不渲染，用户看到「完全不能左右拉伸」。
   */
  const [innerWidth, setInnerWidth] = useState(0)
  /** 断点触发的自动上下（容器太窄） */
  const autoStacked = breakpoint > 0 && innerWidth > 0 && innerWidth < breakpoint
  /** 显式要求上下 或 自动上下 */
  const vertical = direction === 'vertical' || autoStacked

  // ★ 宽度持久化：只在拖完 / 断点重算后落盘，⛔ 不跟每一次 pointermove
  useEffect(() => {
    if (!storageKey) return
    try {
      localStorage.setItem(storageKey, String(Math.round(width)))
    } catch {
      /* 写不进去就算了 */
    }
  }, [width, storageKey])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => setInnerWidth(el.clientWidth)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  const dragRef = useRef<{ startX: number; startY: number; startSize: number } | null>(null)
  /** ★ hover / 拖动时的蓝色反馈（VSCode sash 口径）：常驻仍是 1px 灰线 */
  const [hover, setHover] = useState(false)
  const [dragging, setDragging] = useState(false)
  // ★ 监听只注册一次 ⇒ 配置放 ref，避免闭包拿到旧的 min / fixed
  const cfg = useRef({ min, otherMin, fixed, vertical })
  cfg.current = { min, otherMin, fixed, vertical }

  // 预留接口：本批没有任何调用方使用，避免未使用变量告警
  void onCollapsedChange

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const drag = dragRef.current
      if (!drag) return
      const { min: mn, otherMin: om, fixed: fx } = cfg.current
      const el = ref.current
      const isV = (cfg.current as { vertical?: boolean }).vertical
      const inner = isV
        ? (el?.clientHeight ?? window.innerHeight)
        : (el?.clientWidth ?? window.innerWidth)
      // ★ base 必须是「当前这一栏的尺寸」（width state），
      //   ⛔ 不是容器尺寸 —— 否则一拖就从容器高度起算，直接撞上限（跳变）
      const delta = isV ? e.clientY - drag.startY : e.clientX - drag.startX
      const base = drag.startSize
      const next = clampWidth(base + (fx === 'left' ? delta : -delta), mn, om, inner)
      setWidth(next)
    }
    const onUp = () => {
      dragRef.current = null
      setDragging(false)
    }
    const onWin = () => {
      const { min: mn, otherMin: om, vertical: isV } = cfg.current
      const el = ref.current
      const inner = isV
        ? (el?.clientHeight ?? window.innerHeight)
        : (el?.clientWidth ?? window.innerWidth)
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
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startSize: width,
      }
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


    /**
     * ★★★ 给每一栏套一层**自己的** wrapper div，尺寸只作用在这层上。
     *
     * ⛔ 不再用 `cloneElement(el, { style })` 往子元素上塞样式 —— 那是隐式契约：
     *   要求子元素把 style 透传到根 DOM。子元素是 <div> 时侥幸能用；是
     *   <RibbonPanel /> / <RightSidebar /> 这类**自定义组件**时，React 只把
     *   style 塞进 props，组件内部不往下传 ⇒ 宽度根本没生效（实测界面纹丝不动）。
     *
     * VS Code 的做法是子视图实现 layout(size) 接口、自己应用尺寸；
     * 这里用 wrapper 表达同一件事：**谁的地盘谁做主**，子元素一个 prop 都不用改。
     */
    const decorate = (el: StyledElement | undefined, isLeft: boolean) => {
      if (!el) return null
      const side = isLeft ? 'left' : 'right'
      if (side === hiddenSide) return null
      const size: CSSProperties = hiddenSide || sole
        ? { flex: 1, minWidth: 0, minHeight: 0 }
        : autoStacked
          ? (direction === 'vertical'
              ? { height: '100%', minHeight: 0 }
              : { width: '100%', minWidth: 0 })
          : fixed === side
            ? (vertical
                ? { height: width, flex: 'none', minHeight: 0, minWidth: 0 }
                : { width, flex: 'none', minWidth: 0, minHeight: 0 })
            : { flex: 1, minWidth: 0, minHeight: 0 }
      return (
        <div
          key={side}
          className="sp-pane"
          style={{
            ...size,
            // ★★ 只做「容器」：grid 的单个子项默认 stretch ⇒ 页面自动撑满，
            //    子元素**不需要**写 width/height:100%（谁的地盘谁做主）
            display: 'grid',
            gridTemplate: '1fr / 1fr',
            overflow: 'hidden',
          }}
        >
          {el}
        </div>
      )
    }

  return (
    <div
      ref={ref}
      className={className}
      style={{
        display: 'flex',
        flexDirection: vertical ? 'column' : 'row',
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
      {divider && !autoStacked && !hiddenSide && !sole && rightEl && (
        <div
          onPointerDown={resizable ? onPointerDown : undefined}
          onMouseEnter={resizable ? () => setHover(true) : undefined}
          onMouseLeave={resizable ? () => setHover(false) : undefined}
          title={resizable ? (vertical ? '拖动调整高度' : '拖动调整宽度') : undefined}
          style={{
            // ★ 两个方向彻底分开：⛔ 不共用 min 值（竖向曾被 minHeight:24 撑成粗条）
            flex: '0 0 auto',
            ...(vertical
              ? { height: HANDLE_WIDTH, minHeight: HANDLE_WIDTH, width: '100%', minWidth: 0 }
              : { width: HANDLE_WIDTH, minWidth: HANDLE_WIDTH, alignSelf: 'stretch', minHeight: 0 }),
            touchAction: 'none',
            margin: 0,
            position: 'relative',
            cursor: resizable ? (vertical ? 'row-resize' : 'col-resize') : 'default',
            // ★ 常驻一条 1px 灰线，⛔ 不再 hover 变蓝（VSCode 分屏口径）
            background: 'var(--card-border)',
          }}
        >
          {/* ★ hover / 拖动 ⇒ 蓝色粗线（VSCode 拉动时的颜色反馈）；
              绝对定位、不占布局，宽度变化不会推挤两栏 */}
          <div
            style={{
              position: 'absolute',
              ...(vertical
                ? { top: -1.5, left: 0, right: 0, height: 4 }
                : { left: -1.5, top: 0, bottom: 0, width: 4 }),
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
              ...(vertical
                ? { top: -4, left: 0, right: 0, height: 9 }
                : { left: -4, top: 0, bottom: 0, width: 9 }),
              cursor: vertical ? 'row-resize' : 'col-resize',
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
