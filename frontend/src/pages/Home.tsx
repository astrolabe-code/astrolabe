import { Suspense, lazy, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
// ★ `B173`：删掉 `useQuery` / `apiGet` / `ProjectListData` ——
//   ★ 项目列表改走 `useProjects()`（★ 口径只有一处），★ 这三个都**不再需要** ✅
//   （⚠ 保留 `ProjectSummary` —— ★ 下面的 `suggestions` 还要用它做类型）
import type { ProjectSummary } from '../api/types'
import type { Me } from '../hooks/useMe'
import { useMe } from '../hooks/useMe'
import { SPA_LINKS } from '../legacy'
import { useInView } from '../hooks/useInView'
import { useProjects } from '../query/projects'
import DemoWindow from '../components/DemoWindow'

// D40:卡片预览图谱懒加载(进入视口才请求 vis-network 分包)
const MiniGraph = lazy(() => import('../components/MiniGraph'))

/** 卡片预览图谱:6 节点横排(固定坐标,与旧站一致) */
const CARD_NODES = [
  { id: 'kernel/printk.c', label: 'printk.c', x: 40, y: 50, size: 20, linkTo: 'kernel/sched.c' },
  { id: 'kernel/sched.c', label: 'sched.c', x: 120, y: 50, size: 20, linkTo: 'fs/buffer.c' },
  { id: 'fs/buffer.c', label: 'buffer.c', x: 200, y: 50, size: 20, linkTo: 'mm/memory.c' },
  { id: 'mm/memory.c', label: 'memory.c', x: 280, y: 50, size: 20, linkTo: 'lib/string.c' },
  { id: 'lib/string.c', label: 'string.c', x: 360, y: 50, size: 20, linkTo: 'init/main.c' },
  { id: 'init/main.c', label: 'main.c', x: 440, y: 50, size: 20 },
]

export default function Home() {
  const [q, setQ] = useState('')
  const [focus, setFocus] = useState(false)
  const { ref: cardRef, inView: cardInView } = useInView<HTMLDivElement>()

  const { data: me } = useMe()

  // ★★★ `B173`：改用 `useProjects()` —— ★★ 口径**只有一处**（URL 拼接 + `unwrap` 都在数据层）✅
  //
  //   ⚠★ 改之前这里是**自己拼 URL、自己吞错**：
  //       `return r.ok ? r.data.projects || [] : []`
  //     ⇒ ★★ 后端 500 / 网络断时，它会**静默变成空数组** ——
  //       ★ 而首页拿这个数组**只做搜索建议** ⇒ ★★ 后果是"搜索框一条建议也不给"，
  //       ⚠ 用户以为「搜不到」，★ 而**不知道是接口挂了** ⚠
  //       （★ 与 `_int_in_range` 注释里骂的"静默做错事"是同一类）
  //   ★ 现在走 `unwrap()` ⇒ ★ 错误**会抛出去** ⇒ ★ `isError` 真的有值 ✅
  //     ⇒ ★ 将来首页要提示"搜索暂时不可用"时，★ **有这个信号可用** ✅
  //
  // ⚠★★ `staleTime: 60_000` **必须显式带上** —— ★ 它是首页**原有**的节奏：
  //   ★ `useProjects()` 的默认值是 `0`（`useQuery` 的默认）⇒
  //   ★★ 不传就会变成"每次挂载都重拉一遍全量列表" ⚠
  const { data: projects } = useProjects({ staleTime: 60_000 })

  const user = me ?? ({ authenticated: false } as Me)
  const name = user.is_staff ? '老大' : user.username || ''

  // 首页搜索:后端无 q 参数,沿用旧站语义在前端过滤(name/desc/owner)
  const suggestions = useMemo<ProjectSummary[]>(() => {
    const kw = q.trim().toLowerCase()
    if (!kw) return []
    return (projects || [])
      .filter((p) =>
        [p.name, p.desc, p.owner || ''].some((v) => String(v || '').toLowerCase().includes(kw)),
      )
      .slice(0, 6)
  }, [projects, q])

  const submitSearch = (e: FormEvent) => {
    e.preventDefault()
    const kw = q.trim()
    window.location.href = kw ? `/projects/?q=${encodeURIComponent(kw)}` : '/projects/'
  }

  // ★ B163：本项目没有旧站 ⇒ 登录后一律去工作区（原版按角色分「管理 / 控制台」，那两个页面还没有）
  const startHref = user.authenticated ? SPA_LINKS.workspace : SPA_LINKS.login
  const startText = user.authenticated ? '进入工作区 →' : '开始使用 →'

  return (
    <div className="page">
      <div className="hero">
        <div className="rise">
          <div className="kicker">Code Analysis Console</div>
          <h1>
            {user.authenticated ? (
              <>
                {name},<br />
                让代码像星辰一样<span className="accent-word">清晰</span>
              </>
            ) : (
              <>
                让代码
                <br />
                像星辰一样<span className="accent-word">清晰</span>
              </>
            )}
          </h1>
          <p className="sub">
            {user.authenticated ? (
              user.is_staff ? (
                <>
                  欢迎回来，老大。管理好站点，带大家探索源码世界吧~
                  <br />
                  上传源码，解析结构，即刻开始。
                </>
              ) : (
                <>
                  欢迎回来，{user.username}。去探索源码的世界吧~
                  <br />
                  上传源码，解析结构，即刻开始。
                </>
              )
            ) : (
              <>
                上传源码，解析结构，探索依赖图谱。
                <br />
                在云端控制台里，打开编辑器，即刻开始编程。
              </>
            )}
          </p>

          <form className="hero-search" onSubmit={submitSearch}>
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onFocus={() => setFocus(true)}
              onBlur={() => window.setTimeout(() => setFocus(false), 150)}
              placeholder="搜索公开项目：名称 / 简介 / 作者…"
              maxLength={80}
              aria-label="搜索公开项目"
            />
            <button type="submit" className="btn primary">
              搜索
            </button>
            <span className="hint">游客也可搜索并浏览公开项目</span>
            {focus && suggestions.length > 0 && (
              <div className="hero-suggest">
                {suggestions.map((p) => (
                  <button key={p.project_ref} type="button" onClick={() => (window.location.href = `/app/p/${p.project_ref}`)}>
                    <span>{p.name}</span>
                    <span className="s-desc">{p.owner ? `@${p.owner}` : '公开项目'}</span>
                  </button>
                ))}
              </div>
            )}
          </form>

          <div className="hero-actions">
            <a href={startHref} className="btn primary">
              {startText}
            </a>
            <a href={SPA_LINKS.workspace} className="btn ghost">
              进入工作区
            </a>
            <span className="hint">无需安装 · 浏览器即开即用</span>
          </div>
        </div>

        <DemoWindow />
      </div>

      <div className="feats rise d2">
        <div className="f">
          <i />
          <b>即时解析</b> · 上传即分析
        </div>
        <div className="f">
          <i />
          <b>依赖图谱</b> · 结构可视化
        </div>
        <div className="f">
          <i />
          <b>云端终端</b> · 随时运行代码
        </div>
      </div>

      <div className="grid">
        <a className="card hoverable entry rise d1" href={SPA_LINKS.workspace}>
          <div className="prev">
            <div className="pre-code">
              <span>
                <span className="ln">1</span>
                <span className="tk-key">def</span> <span className="tk-fn">parse</span>(src):
              </span>
              <span>
                <span className="ln">2</span>    <span className="tk-key">return</span>{' '}
                <span className="tk-str">"structure"</span>
              </span>
              <span>
                <span className="ln">3</span>    <span className="tk-com"># 34 个函数 · 12 个模块</span>
              </span>
            </div>
          </div>
          <div className="body">
            <h3>
              代码分析 <span className="n">ANALYZE</span>
            </h3>
            <p>上传源码，自动解析函数、变量与调用关系，生成结构化分析报告。</p>
            <span className="go">enter analysis →</span>
          </div>
        </a>

        <a className="card hoverable entry rise d2" href={SPA_LINKS.workspace}>
          <div className="prev">
            <div className="pre-graph" ref={cardRef}>
              {cardInView && (
                <Suspense fallback={null}>
                  <MiniGraph nodes={CARD_NODES} meteor={{ phase: 0.5, speed: 0.012 }} />
                </Suspense>
              )}
            </div>
          </div>
          <div className="body">
            <h3>
              依赖图谱 <span className="n">GRAPH</span>
            </h3>
            <p>以节点与连线呈现模块间依赖，定位核心模块与潜在风险环。</p>
            <span className="go">enter graph →</span>
          </div>
        </a>

        <a className="card hoverable entry rise d3" href={SPA_LINKS.workspace}>
          <div className="prev">
            <div className="pre-term">
              <span>
                <span className="p">$ </span>make &amp;&amp; make run
              </span>
              <span className="ok">✓ build succeeded in 2.41s</span>
              <span>
                <span className="p">$ </span>./os
              </span>
            </div>
          </div>
          <div className="body">
            <h3>
              代码控制台 <span className="n">CONSOLE</span>
            </h3>
            <p>内置编辑器与终端，直接在浏览器中修改、执行并观察输出。</p>
            <span className="go">enter console →</span>
          </div>
        </a>
      </div>

      <div className="foot rise d3">
        <span className="status">
          <span className="pulse" /> 服务运行中
        </span>
        <span className="mono">小铃铛 · console</span>
      </div>
    </div>
  )
}
