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

const HANDLE_WIDTH = 4

interface SplitPaneProps {
  /** 恰好两个子元素：左栏、右栏（条件渲染出的 false 会被忽略） */
  children: ReactNode
  /** 哪一栏是"固定宽度、可拖拽"的 */
  fixed: 'left' | 'right'
  /** 初始宽度（px） */
  initial: number
  /** 可拖拽那一栏的最小宽度 */
  min: number
  /** 另一栏的最小宽度（用来算动态上限） */
  otherMin: number
  /** 需要读容器尺寸的页面传入自己的 ref（图谱页窄屏抓手要用） */
  containerRef?: RefObject<HTMLDivElement>
  /** 只用于页面特有的差异（列表页的 alignItems）；通用布局组件自己写死 */
  style?: CSSProperties
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
 * ⇒ 列表页 `ProjectPage` 与图谱页 `ProjectGraphPage` 现在都只贴这个组件：
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
}: SplitPaneProps) {
  // ★ 窄屏判定属于组件自己：两页都是 900px 断点，⛔ 不该让调用方重复传
  const stacked = useMediaQuery('(max-width: 900px)')
  const innerRef = useRef<HTMLDivElement>(null)
  const ref = containerRef ?? innerRef
  const [width, setWidth] = useState(initial)
  const dragRef = useRef<{ startX: number; startW: number } | null>(null)
  // ★ 监听只注册一次 ⇒ 配置放 ref，避免闭包拿到旧的 min / fixed
  const cfg = useRef({ min, otherMin, fixed })
  cfg.current = { min, otherMin, fixed }

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
    },
    [width],
  )

  const kids = Children.toArray(children).filter(isValidElement) as StyledElement[]
  const [leftEl, rightEl] = kids

  const decorate = (el: StyledElement | undefined, isLeft: boolean) => {
    if (!el) return null
    const size: CSSProperties = stacked
      ? { width: '100%' }
      : fixed === (isLeft ? 'left' : 'right')
        ? { width, flex: 'none', minWidth: 0 }
        : { flex: 1, minWidth: 0, width: undefined }
    return cloneElement(el, {
      style: { ...(el.props.style || {}), ...size, minHeight: 0 },
    })
  }

  return (
    <div
      ref={ref}
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
      {!stacked && rightEl && (
        <div
          onPointerDown={onPointerDown}
          title="拖动调整宽度"
          style={{
            width: HANDLE_WIDTH,
            flexShrink: 0,
            // ★★ 不管父容器 alignItems 是什么，分隔条都要撑满高度：
            //   列表页传了 alignItems:'flex-start'，不写这行 handle 会被压成 0 高 ⇒ 拖不动
            alignSelf: 'stretch',
            minHeight: 24,
            touchAction: 'none',
            margin: 0,
            cursor: 'col-resize',
            background: 'transparent',
            transition: 'background .15s',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--accent)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
        />
      )}
      {decorate(rightEl, false)}
    </div>
  )
}
