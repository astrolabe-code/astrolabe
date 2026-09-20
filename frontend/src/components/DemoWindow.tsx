import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import CodeDemo from './CodeDemo'

// D40:vis-network 体积较大,进入图谱 Tab 才加载
const MiniGraph = lazy(() => import('./MiniGraph'))

type PaneId = 'pane-code' | 'pane-graph' | 'pane-term'

const TABS: { id: PaneId; label: string; dot: string }[] = [
  { id: 'pane-code', label: '在线代码', dot: '#7cb8e8' },
  { id: 'pane-graph', label: '图谱', dot: '#ef4444' },
  { id: 'pane-term', label: '终端', dot: 'var(--ok)' },
]

const META: Record<PaneId, [string, string]> = {
  'pane-code': ['C · kernel', 'Ln 17, Col 20'],
  'pane-graph': ['graph · 10 nodes', '◉ sched.c 核心节点'],
  'pane-term': ['bash · linux-0.11', '○ 运行中'],
}

/** 演示窗口图谱:中心 + 6 环绕(固定坐标,与旧站一致) */
const DEMO_NODES = [
  { id: 'kernel/printk.c', label: 'printk.c', x: 260, y: 150, size: 28 },
  { id: 'kernel/sched.c', label: 'sched.c', x: 150, y: 60, size: 22, linkTo: 'kernel/printk.c' },
  { id: 'kernel/panic.c', label: 'panic.c', x: 370, y: 60, size: 22, linkTo: 'kernel/printk.c' },
  { id: 'fs/buffer.c', label: 'buffer.c', x: 100, y: 240, size: 22, linkTo: 'kernel/printk.c' },
  { id: 'mm/memory.c', label: 'memory.c', x: 420, y: 240, size: 22, linkTo: 'kernel/printk.c' },
  { id: 'lib/string.c', label: 'string.c', x: 260, y: 30, size: 20, linkTo: 'kernel/printk.c' },
  { id: 'init/main.c', label: 'main.c', x: 260, y: 275, size: 20, linkTo: 'kernel/printk.c' },
]

const DEMO_INTERVAL = 4500

export default function DemoWindow() {
  const [active, setActive] = useState<PaneId>('pane-code')
  const [replay, setReplay] = useState(0)
  const [graphReady, setGraphReady] = useState(false)
  const timer = useRef<number | null>(null)
  const idxRef = useRef(0)

  const activate = (id: PaneId) => {
    setActive(id)
    if (id === 'pane-code') setReplay((v) => v + 1)
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
      </div>

      <div className="stage">
        <div className={`pane${active === 'pane-code' ? ' active' : ''}`}>
          <CodeDemo replayKey={replay} />
        </div>

        <div className={`pane${active === 'pane-graph' ? ' active' : ''}`}>
          <div className="gwrap">
            {graphReady && (
              <Suspense fallback={null}>
                <MiniGraph nodes={DEMO_NODES} meteor={{ phase: 0, speed: 0.008 }} active={active === 'pane-graph'} />
              </Suspense>
            )}
            <div className="glegend">
              <span>
                <i style={{ background: '#ef4444' }} />
                核心
              </span>
              <span>
                <i style={{ background: '#f97316' }} />
                模块
              </span>
              <span>
                <i style={{ background: '#22c55e' }} />
                其他
              </span>
            </div>
          </div>
        </div>

        <div className={`pane${active === 'pane-term' ? ' active' : ''}`}>
          <div className="tpane">
            <div>
              <span className="p">$ </span>make &amp;&amp; make run
            </div>
            <div className="dim">compiling kernel/sched.c ...</div>
            <div className="dim">compiling kernel/fork.c ...</div>
            <div className="ok">✓ build succeeded in 2.41s</div>
            <div>
              <span className="p">$ </span>./linux-0.11
            </div>
            <div className="dim">Linux 0.11 booting ...</div>
            <div className="ok">✓ 127 files parsed · graph ready</div>
            <div>
              <span className="p">$ </span>
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
