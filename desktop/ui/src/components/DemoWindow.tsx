import { Suspense, lazy, useEffect, useRef, useState } from 'react'

// D40:vis-network 体积较大,进入图谱 Tab 才加载
const MiniGraph = lazy(() => import('./MiniGraph'))

// ★★ 三个 tab 必须都对应**现在真实存在的功能**（* 所有者：「现在也只有图谱
//   标题是有对应物了，其他两个都没有」）⚠
type PaneId = 'pane-note' | 'pane-graph' | 'pane-think'

const TABS: { id: PaneId; label: string; dot: string }[] = [
  { id: 'pane-note', label: '节点笔记', dot: '#f59e0b' },
  { id: 'pane-graph', label: '依赖图谱', dot: '#ef4444' },
  { id: 'pane-think', label: '思考模式', dot: '#a855f7' },
]

const META: Record<PaneId, [string, string]> = {
  'pane-note': ['notes · 5 类盒子', '● 灵光一闪 / 质疑 / 困惑 / 踩坑 / 小结'],
  'pane-graph': ['graph · 6 nodes', '◉ 与左侧五条笔记一一对应'],
  'pane-think': ['thinking · 白布', '拖动卡片 · 位置自动保存'],
}

/** 演示窗口图谱:中心 + 6 环绕(固定坐标,与旧站一致) */
/**
 * ★★★ 演示窗小图：* **与「节点笔记」里的五条笔记一一对应**（* 所有者：
 *   「下一个轮播的图谱界面的节点跟第一个节点笔记的内容要对应呀，比如名称，连线」）⚠
 *   · · ★ 节点名 = 笔记里讲的函数：printk / fork / kmalloc / list_for_each / strcpy
 *   · · ★ 连线 = 它们之间的调用 / 归属关系
 *   · · ★ 颜色沿用五种笔记盒子的色 ⇒ 与第一屏的胶囊同色 ✅
 */
const DEMO_NODES = [
  // 中心：main（入口）
  { id: 'init/main.c', label: 'main', x: 260, y: 145, size: 26, color: '#f59e0b' },
  // 笔记 5：fork 之后谁先跑
  { id: 'kernel/fork.c', label: 'fork', x: 140, y: 60, size: 22, linkTo: 'init/main.c', color: '#3b82f6' },
  // 笔记 1：printk 为什么要关中断
  { id: 'kernel/printk.c', label: 'printk', x: 380, y: 60, size: 22, linkTo: 'init/main.c', color: '#a855f7' },
  // 笔记 3：kmalloc 和 vmalloc
  { id: 'mm/slab.c', label: 'kmalloc', x: 108, y: 232, size: 22, linkTo: 'kernel/fork.c', color: '#ef4444' },
  // 笔记 2：list_for_each
  { id: 'include/list.h', label: 'list_for_each', x: 300, y: 262, size: 20, linkTo: 'kernel/fork.c', color: '#10b981' },
  // 笔记 4：strcpy
  { id: 'lib/string.c', label: 'strcpy', x: 430, y: 205, size: 20, linkTo: 'kernel/printk.c', color: '#f59e0b' },
]

const DEMO_INTERVAL = 4500

export default function DemoWindow() {
  const [active, setActive] = useState<PaneId>('pane-note')
  const [graphReady, setGraphReady] = useState(false)
  const timer = useRef<number | null>(null)
  const idxRef = useRef(0)

  const activate = (id: PaneId) => {
    setActive(id)
    if (id === 'pane-graph') setGraphReady(true)
  }

  const stop = () => {
    if (timer.current !== null) {
      window.clearInterval(timer.current)
      timer.current = null
    }
  }
  const restart = () => {
    stop()
    timer.current = window.setInterval(() => {
      idxRef.current = (idxRef.current + 1) % TABS.length
      activate(TABS[idxRef.current].id)
    }, DEMO_INTERVAL)
  }

  useEffect(() => {
    restart()
    return stop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const meta = META[active]

  return (
    <div
      className="demo rise d1"
      onMouseEnter={stop}
      onMouseLeave={restart}
    >
      <div className="bar">
        <span className="lights">
          <i />
          <i />
          <i />
        </span>
        <div className="tabs">
          {TABS.map((t, i) => (
            <button
              key={t.id}
              type="button"
              className={`tab${active === t.id ? ' active' : ''}`}
              onClick={() => {
                idxRef.current = i
                activate(t.id)
                restart()
              }}
            >
              <span className="tdot" style={{ background: t.dot }} />
              {t.label}
            </button>
          ))}
        </div>
        {/* ★ 全局提示：* 整个窗口都是演示，不是真实数据 ⚠ */}
        <span className="demo-badge" title="以下内容为虚构演示，不是真实项目与笔记">
          演示
        </span>
      </div>

      <div className="stage">
        {/* ★ 节点笔记预览（* 五条笔记把窗口填满；* 作者是**虚构演示账号**，
            内容只挑大家都知道的公共函数 ⇒ 不暴露真实用户与真实笔记）⚠ */}
        <div className={`pane${active === 'pane-note' ? ' active' : ''}`}>
          <div className="npane">
            <span className="pane-badge">演示 · 虚构笔记</span>
            <div className="nrow">
              <div className="nhead">

                <span className="chip" style={{ color: '#f59e0b', borderColor: '#f59e0b' }}>● 灵光一闪</span>

                <span className="who">0xNull · 5 分钟前</span>

              </div>
              <div className="ntitle">printk 为什么要关中断？</div>
              <div className="nbody">日志要完整写出去，中途被调度打断就会和其他输出串在一起。</div>
            </div>
            <div className="nrow">
              <div className="nhead">

                <span className="chip" style={{ color: '#3b82f6', borderColor: '#3b82f6' }}>● 质疑</span>

                <span className="who">未定义行为 · 12 分钟前</span>

              </div>
              <div className="ntitle">list_for_each 为什么不用判空？</div>
              <div className="nbody">链表头是哨兵节点，遍历到它自己就停下来，省掉一次边界判断。</div>
            </div>
            <div className="nrow">
              <div className="nhead">

                <span className="chip" style={{ color: '#a855f7', borderColor: '#a855f7' }}>● 困惑</span>

                <span className="who">栈底观测者 · 40 分钟前</span>

              </div>
              <div className="ntitle">kmalloc 和 vmalloc 差在哪？</div>
              <div className="nbody">前者拿物理连续页，后者只保证虚拟地址连续，大块内存才用得上。</div>
            </div>
            <div className="nrow">
              <div className="nhead">

                <span className="chip" style={{ color: '#ef4444', borderColor: '#ef4444' }}>● 踩坑</span>

                <span className="who">SegFault_骑士 · 1 小时前</span>

              </div>
              <div className="ntitle">strcpy 不检查目标长度</div>
              <div className="nbody">源串一长就写穿缓冲区，换成 strncpy 并手动补 \0 才稳。</div>
            </div>
            <div className="nrow">
              <div className="nhead">

                <span className="chip" style={{ color: '#10b981', borderColor: '#10b981' }}>● 小结</span>

                <span className="who">未定义行为 · 2 小时前</span>

              </div>
              <div className="ntitle">fork 之后谁先跑？</div>
              <div className="nbody">顺序由调度器决定，父子都可能先执行 —— 别把顺序当保证。</div>
            </div>
            <div className="nrow">
              <div className="nhead">
                <span className="chip" style={{ color: '#3b82f6', borderColor: '#3b82f6' }}>
                  ● 质疑
                </span>
                <span className="who">Ctrl_Z · 3 小时前</span>
              </div>
              <div className="ntitle">自旋锁和互斥锁怎么选？</div>
              <div className="nbody">能睡眠的上下文用互斥锁，中断里只能自旋，别把两者用反。</div>
            </div>
            <div className="nrow">
              <div className="nhead">
                <span className="chip" style={{ color: '#10b981', borderColor: '#10b981' }}>
                  ● 小结
                </span>
                <span className="who">0xNull · 昨天</span>
              </div>
              <div className="ntitle">中断上下文里不能睡眠</div>
              <div className="nbody">kmalloc 要用 GFP_ATOMIC，普通分配可能触发调度直接崩溃。</div>
            </div>
          </div>
        </div>

        <div className={`pane${active === 'pane-graph' ? ' active' : ''}`}>
          <div className="gwrap">
            {graphReady && (
              <Suspense fallback={null}>
                <MiniGraph nodes={DEMO_NODES} meteor={{ phase: 0, speed: 0.008 }} active={active === 'pane-graph'} />
              </Suspense>
            )}
            {/* ★ 图例与笔记盒子的颜色一致（* 不再用目录配色）⚠ */}
            <div className="glegend">
              <span>
                <i style={{ background: '#f59e0b' }} />
                灵光
              </span>
              <span>
                <i style={{ background: '#3b82f6' }} />
                质疑
              </span>
              <span>
                <i style={{ background: '#a855f7' }} />
                困惑
              </span>
              <span>
                <i style={{ background: '#ef4444' }} />
                踩坑
              </span>
              <span>
                <i style={{ background: '#10b981' }} />
                小结
              </span>
            </div>
          </div>
        </div>

        {/* ★ 思考模式预览：* 点阵白布 + 散落的笔记卡 ⚠ */}
        <div className={`pane${active === 'pane-think' ? ' active' : ''}`}>
          <div className="thinkpane">
            <span className="pane-badge">演示 · 虚构卡片</span>
            {/* ★★ 白布上的卡片**带文字**，* 内容直接取自「节点笔记」那几条 ⚠ */}
            <div className="tc" style={{ left: 24, top: 26, borderLeftColor: '#f59e0b' }}>
              printk 关中断
            </div>
            <div className="tc" style={{ left: 146, top: 50, borderLeftColor: '#3b82f6' }}>
              list_for_each 不用判空
            </div>
            <div className="tc" style={{ left: 58, top: 122, borderLeftColor: '#a855f7' }}>
              kmalloc vs vmalloc
            </div>
            <div className="tc" style={{ left: 300, top: 96, borderLeftColor: '#ef4444' }}>
              strcpy 写穿缓冲区
            </div>
            <div className="tc" style={{ left: 196, top: 186, borderLeftColor: '#10b981' }}>
              fork 之后谁先跑
            </div>
          </div>
        </div>
      </div>

      <div className="status">
        <span className="lang">{meta[0]}</span>
        <span>{meta[1]}</span>
      </div>
    </div>
  )
}
