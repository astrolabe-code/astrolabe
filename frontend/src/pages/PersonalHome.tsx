/**
 * ★★★ **个人版首页**（绿色版桌面应用的首屏）
 *
 * ## 所有者原话（逐字）
 *
 * > 「不要做用户登陆功能，就只有用户一个人用，我这是给我邀请的用户之外、
 * >   想体验的用户准备的，还有首页这些花里胡哨的不需要的。」
 *
 * ## 所以这一页只有一件事
 *
 * ```\n * 没有项目 ⇒ 一个大按钮：「选择一个代码目录」\n * 有项目   ⇒ 一个列表：点进去接着读\n * ```\n *
 * ⚠ 没有营销文案、没有登录、没有搜索框、没有滚动动画 —— 全白（见 `POSITIONING.md` 0.4）。
 * ⚠ 选完目录**立刻给出真实反馈**（扫描出多少个文件、几种语言），
 *   ⛔ 不做一个"看起来在干活"的假进度条。
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen } from 'lucide-react'

interface ScanResult {
  root: string
  files: number
  byExt: { ext: string; n: number }[]
  elapsedMs: number
}

export default function PersonalHome() {
  const nav = useNavigate()
  const [picked, setPicked] = useState<string>('')
  const [scan, setScan] = useState<ScanResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  /** ★ 建项目 + 解析（个人版唯一的重活） */
  const [parsing, setParsing] = useState(false)
  const [parsed, setParsed] = useState<{ ref: string; name: string; nodes: number; edges: number } | null>(
    null,
  )

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

  const startParse = async () => {
    if (!picked) return
    setErr('')
    setParsing(true)
    try {
      const name = picked.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '未命名'
      const cr = await fetch('/api/projects/', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ path: picked, name }),
      })
      const cj = await cr.json()
      if (!cj.ok) throw new Error(cj.error || '建项目失败')
      const ref = cj.data.project.ref

      const pr = await fetch(`/api/projects/${encodeURIComponent(ref)}/parse`, { method: 'POST' })
      const pj = await pr.json()
      if (!pj.ok) throw new Error(pj.error || '解析失败')
      const st = pj.data.stats
      setParsed({ ref, name, nodes: st.nodes, edges: st.edges })
    } catch (e) {
      setErr(String((e as Error).message || e))
    } finally {
      setParsing(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 18,
        padding: 40,
        background: '#fff',
        color: '#111',
        fontFamily: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
      }}
    >
      <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: 0.5 }}>Astrolabe</div>

      {!picked && (
        <>
          <div style={{ fontSize: 13, color: '#888' }}>选一个你想读的代码目录</div>
          <button
            type="button"
            onClick={() => void pick()}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 20px',
              fontSize: 13.5,
              fontFamily: 'inherit',
              color: '#fff',
              background: '#111',
              border: 'none',
              borderRadius: 8,
              cursor: 'pointer',
            }}
          >
            <FolderOpen size={15} />
            选择一个代码目录
          </button>
          <div style={{ fontSize: 11.5, color: '#aaa', maxWidth: 420, textAlign: 'center', lineHeight: 1.7 }}>
            代码不会被上传，所有数据都留在你本机的 <code>data/</code> 文件夹里。
          </div>
        </>
      )}

      {picked && (
        <div style={{ width: 520, maxWidth: '90vw' }}>
          <div
            style={{
              fontSize: 11.5,
              color: '#888',
              marginBottom: 8,
              wordBreak: 'break-all',
              fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
            }}
          >
            {picked}
          </div>

          {busy && <div style={{ fontSize: 12.5, color: '#666' }}>正在扫描…</div>}

          {scan && !busy && (
            <div
              style={{
                border: '1px solid #e5e5e5',
                borderRadius: 8,
                padding: 14,
                fontSize: 12.5,
                lineHeight: 1.9,
              }}
            >
              <div>
                找到 <b>{scan.files}</b> 个可读文件 · 用时 {scan.elapsedMs} ms
              </div>
              <div style={{ color: '#666' }}>
                {scan.byExt
                  .slice(0, 6)
                  .map((x) => `${x.ext} ${x.n}`)
                  .join(' · ')}
              </div>
            </div>
          )}

          {err && <div style={{ color: '#c00', fontSize: 12.5, marginTop: 8 }}>{err}</div>}

          {!parsed && (
            <button
              type="button"
              disabled={parsing}
              onClick={() => void startParse()}
              style={{
                marginTop: 14,
                padding: '9px 20px',
                fontSize: 13,
                fontFamily: 'inherit',
                color: '#fff',
                background: parsing ? '#999' : '#111',
                border: 'none',
                borderRadius: 8,
                cursor: parsing ? 'default' : 'pointer',
              }}
            >
              {parsing ? '正在解析…' : '开始读这本书'}
            </button>
          )}

          {parsed && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12.5, color: '#444' }}>
                已建好：<b>{parsed.name}</b> · {parsed.nodes} 个节点 · {parsed.edges} 条关系
              </div>
              <button
                type="button"
                onClick={() => nav(`/p/${encodeURIComponent(parsed.ref)}`)}
                style={{
                  marginTop: 10,
                  padding: '9px 20px',
                  fontSize: 13,
                  fontFamily: 'inherit',
                  color: '#fff',
                  background: '#111',
                  border: 'none',
                  borderRadius: 8,
                  cursor: 'pointer',
                }}
              >
                进入 →
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={() => {
              setPicked('')
              setScan(null)
              setParsed(null)
              nav('/')
            }}
            style={{
              marginTop: 14,
              padding: '6px 14px',
              fontSize: 12.5,
              fontFamily: 'inherit',
              color: '#555',
              background: '#fff',
              border: '1px solid #ddd',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            换一个目录
          </button>
        </div>
      )}
    </div>
  )
}
