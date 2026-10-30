/**
 * ★★★ **个人版首页**
 *
 * ## 所有者原话（逐字）
 *
 * > 「个人版怎么没有在首页显示已经解析的项目卡片？网页版首页有项目窗口，
 * >   可以点击进入创建的项目卡片，但个人版没有，你直接首页就出现这个项目窗口就可以了。」
 *
 * ## 这一页有两块
 *
 * ```\n * 已经导入的源码 ⇒ 卡片网格，点一下直接进（**默认屏就是它**）\n * ＋ 导入新源码  ⇒ 选目录 → 扫描 → 解析\n * ```\n *
 * ⚠ 没有营销文案、没有登录、没有搜索框 —— 全白（`POSITIONING.md` 0.4）。
 * ⚠ 解析失败的项目也在列表里（❌ 不隐藏）：卡片标红，点进去修图。
 */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen, Plus } from 'lucide-react'

interface ScanResult {
  root: string
  files: number
  byExt: { ext: string; n: number }[]
  /** ★ 是代码、但这一版解析器还不支持的语言（⛔ 不能混进"可读"里）*/
  otherFiles?: number
  otherByExt?: { ext: string; n: number }[]
  elapsedMs: number
}

interface ProjectRow {
  ref: string
  name: string
  root: string
  created_at: string
  parsed_at: string | null
  parse_state?: string
  node_count?: number
  note_count?: number
  /** ★ 数据目录（悬停卡片能看到笔记存哪）*/
  data?: string
}

export default function PersonalHome() {
  const nav = useNavigate()

  // ---- 已有项目
  const [projects, setProjects] = useState<ProjectRow[]>([])
  const [loading, setLoading] = useState(true)
  /** ★ 从零建一个结构（不用源码，自己加节点和连线）*/
  const [blankOpen, setBlankOpen] = useState(false)
  const [blankName, setBlankName] = useState('新结构')
  /** ★ 空白结构也要先选目录：笔记就存在那儿，用户得知道在哪 */
  const [blankDir, setBlankDir] = useState('')
  const [blankBusy, setBlankBusy] = useState(false)

  // ---- 新建流程
  const [picked, setPicked] = useState<string>('')
  const [scan, setScan] = useState<ScanResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [parsing, setParsing] = useState(false)
  /** ★ 源码目录里已有 `.astrolabe/` 且不是本程序建的 ⇒ 先问用户 */
  const [conflict, setConflict] = useState<{ path: string; name: string } | null>(null)
  const [parsed, setParsed] = useState<{
    ref: string
    name: string
    nodes: number
    edges: number
    failed?: boolean
    message?: string
  } | null>(null)

  const loadProjects = useCallback(async () => {
    try {
      const r = await fetch('/api/projects/')
      const j = await r.json()
      if (j.ok) setProjects((j.data.items || []) as ProjectRow[])
    } catch {
      /* 读不到就当空列表 */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadProjects()
  }, [loadProjects])

  /** ★ 开始建空白结构：**先选目录**（数据存那儿），再填名字 */
  const startBlank = async () => {
    setErr('')
    const api = (window as unknown as { astrolabe?: { pickDirectory: () => Promise<string | null> } })
      .astrolabe
    if (!api?.pickDirectory) {
      setErr('只有在桌面版里才能选目录')
      return
    }
    const dir = await api.pickDirectory()
    if (!dir) return
    const base = dir.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '新结构'
    setBlankDir(dir)
    setBlankName(base)
    setBlankOpen(true)
  }

  const createBlank = async () => {
    if (!blankDir) return
    setBlankBusy(true)
    setErr('')
    try {
      const r = await fetch('/api/projects/', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ blank: true, name: blankName.trim() || '新结构', path: blankDir }),
      })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || '创建失败')
      nav(`/p/${encodeURIComponent(j.data.project.ref)}`)
    } catch (e) {
      setErr(String((e as Error).message || e))
    } finally {
      setBlankBusy(false)
    }
  }

  const pick = async () => {
    setErr('')
    const api = (window as unknown as { astrolabe?: { pickDirectory: () => Promise<string | null> } })
      .astrolabe
    if (!api?.pickDirectory) {
      setErr('只有在桌面版里才能选择本地目录')
      return
    }
    const dir = await api.pickDirectory()
    if (!dir) return
    setPicked(dir)
    setBusy(true)
    try {
      const r = await fetch('/api/fs/scan', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ path: dir }),
      })
      const j = await r.json()
      if (j.ok) setScan(j.data as ScanResult)
      else setErr(String(j.error || '扫描失败'))
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const startParse = async (
    force = false,
    ref0?: string,
    extra?: { adopt?: boolean; dataDir?: string },
  ) => {
    if (!picked && !ref0) return
    setErr('')
    setParsing(true)
    try {
      const name = picked.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '未命名'
      let ref = ref0 || ''
      if (!ref) {
        const cr = await fetch('/api/projects/', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            path: picked,
            name,
            ...(extra?.adopt ? { adopt: true } : {}),
            ...(extra?.dataDir ? { data_dir: extra.dataDir } : {}),
          }),
        })
        const cj = await cr.json()
        if (!cj.ok) {
          // ★ 那个 .astrolabe/ 不是我们建的 ⇒ 停下来问用户，⛔ 不擅自接管
          if (cj.code === 'data_exists') {
            setConflict({ path: String(cj.path || ''), name })
            return
          }
          throw new Error(cj.error || '建项目失败')
        }
        ref = cj.data.project.ref
        // ★★ 这个目录已经读过了 ⇒ **直接进去**，⛔ 根本不发解析请求
        //   （所有者：「不允许重新解析」—— 连尝试都不该发生）
        if (cj.data.project.parse_state === 'ok') {
          nav(`/p/${encodeURIComponent(ref)}`)
          return
        }
      }

      const pr = await fetch(`/api/projects/${encodeURIComponent(ref)}/parse`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(force ? { force: true, reason: '解析失败，重试' } : {}),
      })
      const pj = await pr.json()
      if (!pj.ok) {
        // ★★★ 「这本已经读过了」不是失败（所有者：「不允许重新解析」）⚠
        //   同一个目录再点新建 ⇒ 边车回 graph_exists ⇒ **直接进去**，
        //   ⛔ 不显示「重新解析」（那个只在真失败时出现）
        if (pj.code === 'graph_exists') {
          nav(`/p/${encodeURIComponent(ref)}`)
          return
        }
        // ★ 真的解析失败 ⇒ 记住这个项目，只给"重新解析"，不给写笔记
        setParsed({ ref, name, nodes: 0, edges: 0, failed: true, message: pj.error || '解析失败' })
        void loadProjects()
        return
      }
      const st = pj.data.stats
      setParsed({ ref, name, nodes: st.nodes, edges: st.edges })
      void loadProjects()
    } catch (e) {
      setErr(String((e as Error).message || e))
    } finally {
      setParsing(false)
    }
  }

  const page: React.CSSProperties = {
    minHeight: '100vh',
    background: '#fff',
    color: '#111',
    fontFamily: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
    padding: '48px 40px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  }

  // ---------------------------------------------------------------- 新建流程
  if (picked) {
    return (
      <div style={page}>
        <Shell>
          <div
            style={{
              fontSize: 12,
              color: '#888',
              marginBottom: 10,
              wordBreak: 'break-all',
              fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
            }}
          >
            {picked}
          </div>

          {busy && <div style={{ fontSize: 13, color: '#666' }}>正在扫描…</div>}

          {scan && !busy && (
            <div style={{ border: '1px solid #e5e5e5', borderRadius: 8, padding: 14, fontSize: 12.5, lineHeight: 1.9 }}>
              <div>
                找到 <b>{scan.files}</b> 个可读文件 · 用时 {scan.elapsedMs} ms
              </div>
              <div style={{ color: '#666' }}>
                {scan.byExt.slice(0, 6).map((x) => `${x.ext} ${x.n}`).join(' · ')}
              </div>
              {!!scan.otherFiles && (
                <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>
                  另有 {scan.otherFiles} 个代码文件这一版还解析不了
                  {scan.otherByExt?.length ? `（${scan.otherByExt.map((x) => `${x.ext} ${x.n}`).join(' · ')}）` : ''}
                </div>
              )}
            </div>
          )}

          {err && <div style={{ color: '#c00', fontSize: 12.5, marginTop: 8 }}>{err}</div>}

          {!parsed && (
            <button
              type="button"
              disabled={parsing}
              onClick={() => void startParse()}
              style={{ ...primary, marginTop: 14, background: parsing ? '#999' : '#111' }}
            >
              {parsing ? '正在解析…' : '开始解析'}
            </button>
          )}

          {parsed && !parsed.failed && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12.5, color: '#444' }}>
                解析完成：<b>{parsed.name}</b> · {parsed.nodes} 个节点 · {parsed.edges} 条关系
              </div>
              <button
                type="button"
                onClick={() => nav(`/p/${encodeURIComponent(parsed.ref)}`)}
                style={{ ...primary, marginTop: 10 }}
              >
                打开
              </button>
            </div>
          )}

          {/* ★★ 解析失败：**不许写笔记**，只给"重新解析" */}
          {parsed?.failed && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12.5, color: '#b00', lineHeight: 1.7 }}>
                解析没成功：{parsed.message}
              </div>
              <div style={{ fontSize: 11.5, color: '#888', marginTop: 4, lineHeight: 1.7 }}>
                图不完整时写下的笔记会挂在不存在的锚点上 —— 先修好图，再写。
              </div>
              <button
                type="button"
                disabled={parsing}
                onClick={() => void startParse(true, parsed.ref)}
                style={{ ...primary, marginTop: 10, background: parsing ? '#999' : '#111' }}
              >
                {parsing ? '重新解析中…' : '重新解析'}
              </button>
            </div>
          )}

          {/* ★★ 源码目录里已有 `.astrolabe/`（且不是我们建的）⇒ 三选一 ⚠ */}
          {conflict && (
            <div
              style={{
                marginTop: 16,
                border: '1px solid #e5c9c9',
                background: 'rgba(200,0,0,.03)',
                borderRadius: 8,
                padding: 14,
                fontSize: 12,
                lineHeight: 1.8,
              }}
            >
              <b>这个源码目录里已经有一个 .astrolabe/ 了</b>
              <div
                className="faint"
                style={{
                  marginTop: 4,
                  wordBreak: 'break-all',
                  fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
                }}
              >
                {conflict.path}
              </div>
              <div className="faint" style={{ marginTop: 6 }}>
                它看起来不是本程序为这个仓库建的。要么接管它（里面的笔记会出现在这里），
                要么把笔记放到别的地方去。
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  disabled={parsing}
                  onClick={() => {
                    setConflict(null)
                    void startParse(false, undefined, { adopt: true })
                  }}
                  style={{ ...primary, fontSize: 12.5, padding: '7px 14px' }}
                >
                  用这个目录里的数据
                </button>
                <button
                  type="button"
                  disabled={parsing}
                  onClick={async () => {
                    const api = (
                      window as unknown as { astrolabe?: { pickDirectory: () => Promise<string | null> } }
                    ).astrolabe
                    const dir = await api?.pickDirectory?.()
                    if (!dir) return
                    setConflict(null)
                    void startParse(false, undefined, { dataDir: dir })
                  }}
                  style={{ ...secondary, fontSize: 12.5, padding: '7px 14px' }}
                >
                  笔记放到别处…
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setConflict(null)
                    setPicked('')
                    setScan(null)
                  }}
                  style={{ ...secondary, fontSize: 12.5, padding: '7px 14px' }}
                >
                  取消
                </button>
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={() => {
              setPicked('')
              setScan(null)
              setParsed(null)
              setConflict(null)
              setErr('')
              void loadProjects()
            }}
            style={{ ...secondary, marginTop: 16 }}
          >
            返回
          </button>
        </Shell>
      </div>
    )
  }

  // ---------------------------------------------------------------- 首页（项目列表）
  return (
    <div style={page}>
      <Shell wide>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 18 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>已导入的源码</div>
          <span style={{ fontSize: 12, color: '#999' }}>
            {/* ★ 只有一个时不显示数量（「1 个目录」读着别扭）⚠ */}
            {projects.length > 1 ? `共 ${projects.length} 个` : projects.length === 0 ? '还没有导入' : ''}
          </span>
          {/* ★ 空态时中间那个大按钮就是唯一入口，这里不再重复出现第二个（所有者：「每次只能出现一个」）⚠ */}
          {projects.length > 0 && (
            <button type="button" onClick={() => void pick()} style={{ ...secondary, marginLeft: 'auto' }}>
              <Plus size={12} /> 导入新源码
            </button>
          )}
        </div>

        {loading && <div style={{ fontSize: 13, color: '#888' }}>读取中…</div>}

        {/* 空状态：直接给选目录 */}
        {!loading && projects.length === 0 && (
          <div style={{ textAlign: 'center', padding: '56px 0 40px' }}>
            <div style={{ fontSize: 13.5, color: '#666', marginBottom: 18 }}>
              选择一个源码目录，解析出结构后，就能在函数旁边写笔记
            </div>
            <button
              type="button"
              onClick={() => void pick()}
              style={{ ...primary, fontSize: 15, padding: '14px 32px', gap: 10 }}
            >
              <FolderOpen size={18} /> 选择源码目录
            </button>
            <div style={{ marginTop: 16 }}>
              <button
                type="button"
                onClick={() => void startBlank()}
                style={{
                  border: 'none',
                  background: 'transparent',
                  padding: 0,
                  fontSize: 12,
                  fontFamily: 'inherit',
                  color: '#666',
                  cursor: 'pointer',
                  textDecoration: 'underline dotted',
                }}
              >
                或者：从零建一个结构（不用源码，自己加节点和连线）
              </button>
            </div>
            <div style={{ fontSize: 11.5, color: '#aaa', marginTop: 14, lineHeight: 1.7 }}>
              {/* ★ 提示语要跟着存储结构走：笔记在**你选的那个目录**的 .astrolabe/ 里，
                  不是程序目录的 data/（所有者 2026-10-30 指出这句过时了）⚠ */}
              笔记存在你选的那个目录里（.astrolabe/），不会上传。
            </div>
          </div>
        )}

        {/* 项目卡片 */}
        {projects.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: 12,
            }}
          >
            {projects.map((p) => {
              const failed = p.parse_state === 'failed'
              return (
                <button
                  key={p.ref}
                  type="button"
                  title={p.data ? `笔记存在：${p.data}` : undefined}
                  onClick={() => nav(`/p/${encodeURIComponent(p.ref)}`)}
                  style={{
                    textAlign: 'left',
                    fontFamily: 'inherit',
                    padding: '14px 16px',
                    background: '#fff',
                    border: `1px solid ${failed ? '#e5c9c9' : '#e5e5e5'}`,
                    borderRadius: 10,
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                  }}
                >
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#111' }}>{p.name}</div>
                  <div style={{ fontSize: 11.5, color: '#888' }}>
                    {p.node_count ?? 0} 个节点 · {p.note_count ?? 0} 篇笔记
                  </div>
                  <div style={{ fontSize: 11, color: failed ? '#b00' : '#aaa' }}>
                    {failed
                      ? '解析失败 · 点进去修图'
                      : !p.root
                        ? '手动结构'
                        : p.parsed_at
                          ? '已解析'
                          : '还没解析'}
                  </div>
                </button>
              )
            })}

            {/* ★ 从零建一个结构（不用源码）—— 非代码主题的结构化尝试 ⚠ */}
            <button
              type="button"
              onClick={() => void startBlank()}
              style={{
                padding: '14px 16px',
                background: '#fff',
                border: '1px dashed #ddd',
                borderRadius: 10,
                cursor: 'pointer',
                fontFamily: 'inherit',
                fontSize: 12.5,
                color: '#888',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
                minHeight: 92,
              }}
            >
              <Plus size={13} /> 新结构
            </button>
          </div>
        )}

        {err && <div style={{ color: '#c00', fontSize: 12.5, marginTop: 12 }}>{err}</div>}

        {/* ★ 从零建一个结构：不用源码，自己加节点和连线（`B184`）⚠ */}
        {blankOpen && (
          <div style={{ display: 'flex', gap: 8, marginTop: 14, alignItems: 'center', flexWrap: 'wrap' }}>
            <div
              className="faint"
              style={{
                width: '100%',
                fontSize: 11,
                wordBreak: 'break-all',
                fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
              }}
            >
              笔记会存在这个目录里（.astrolabe/）：{blankDir}
            </div>
            <input
              className="input"
              autoFocus
              value={blankName}
              onChange={(e) => setBlankName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void createBlank()
                if (e.key === 'Escape') setBlankOpen(false)
              }}
              placeholder="给它起个名字，比如「小说人物关系」"
              style={{ flex: 1, fontSize: 13 }}
            />
            <button type="button" disabled={blankBusy} onClick={() => void createBlank()} style={primary}>
              {blankBusy ? '创建中…' : '创建'}
            </button>
            <button type="button" onClick={() => setBlankOpen(false)} style={secondary}>
              取消
            </button>
          </div>
        )}
      </Shell>
    </div>
  )
}

// ---------------------------------------------------------------- 小积木

const primary: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  padding: '9px 20px',
  fontSize: 13,
  fontFamily: 'inherit',
  color: '#fff',
  background: '#111',
  border: 'none',
  borderRadius: 8,
  cursor: 'pointer',
}

const secondary: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 5,
  padding: '4px 12px',
  fontSize: 12,
  fontFamily: 'inherit',
  color: '#555',
  background: '#fff',
  border: '1px solid #ddd',
  borderRadius: 7,
  cursor: 'pointer',
}

function Shell({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div style={{ width: wide ? 760 : 520, maxWidth: '92vw', display: 'flex', flexDirection: 'column' }}>
      {children}
    </div>
  )
}
