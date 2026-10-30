/**
 * ★★ **个人版顶栏**（替代社区版那个带登录/搜索/我的的 TopNav）
 *
 * 所有者：「不要做用户登陆功能，就只有用户一个人用……首页这些花里胡哨的不需要的。」
 *
 * ```\n * Astrolabe                         [笔记位置 D:\我的笔记]  [数据]\n * ```\n *
 * ⚠ 只有三样：回项目的入口 · **笔记存哪** · 数据目录。
 *   ⛔ 不放搜索、头像、登录、通知 —— 单机单用户没有这些概念。
 *
 * ★★ 「笔记位置」是所有者 2026-10-30 要求的：
 *   「不能用户指定笔记的存放位置吗？……要是用户想指定其他位置呢？」
 */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen, HardDrive } from 'lucide-react'

interface DesktopApi {
  isDesktop?: boolean
  info?: () => Promise<{ version: string; dataDir: string }>
  openDataDir?: () => Promise<boolean>
  pickDirectory?: () => Promise<string | null>
}

export default function PersonalBar() {
  const nav = useNavigate()
  const [dataDir, setDataDir] = useState('')
  const [libRoot, setLibRoot] = useState('')
  /** 待确认的搬迁目标（选完目录再确认一次）*/
  const [pending, setPending] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const api = (window as unknown as { astrolabe?: DesktopApi }).astrolabe

  const loadLib = useCallback(async () => {
    try {
      const r = await fetch('/api/library/')
      const j = await r.json()
      if (j.ok) setLibRoot(j.data.root)
    } catch {
      /* 读不到就不显示 */
    }
  }, [])

  useEffect(() => {
    api?.info?.().then((i) => setDataDir(i.dataDir)).catch(() => {})
    void loadLib()
  }, [api, loadLib])

  const chooseDir = async () => {
    setErr('')
    if (!api?.pickDirectory) {
      setErr('只有在桌面版里才能改位置')
      return
    }
    const dir = await api.pickDirectory()
    if (!dir) return
    setPending(dir)
  }

  const doSwitch = async () => {
    if (!pending) return
    setBusy(true)
    setErr('')
    try {
      const r = await fetch('/api/library/switch', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ path: pending }),
      })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || '切换失败')
      // ★ 换库之后内存里的数据全变了 ⇒ 直接重载，最省心也最不容易出错
      window.location.reload()
    } catch (e) {
      setErr(String((e as Error).message || e))
      setBusy(false)
    }
  }

  const btn = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '3px 8px',
    fontSize: 11.5,
    fontFamily: 'inherit',
    color: '#777',
    background: 'transparent',
    border: '1px solid #e5e5e5',
    borderRadius: 6,
    cursor: 'pointer',
  } as const

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        height: 40,
        padding: '0 14px',
        borderBottom: '1px solid #eee',
        background: '#fff',
        fontFamily: 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
      }}
    >
      <button
        type="button"
        onClick={() => nav('/')}
        style={{
          padding: 0,
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          fontSize: 13,
          fontWeight: 600,
          color: '#111',
          fontFamily: 'inherit',
        }}
      >
        Astrolabe
      </button>

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
        {libRoot && (
          <button
            type="button"
            title={`笔记存在：${libRoot}\n点一下可以换地方`}
            onClick={() => void chooseDir()}
            style={btn}
          >
            <HardDrive size={12} />
            笔记位置
          </button>
        )}
        {dataDir && (
          <button
            type="button"
            title={dataDir}
            onClick={() => void api?.openDataDir?.()}
            style={btn}
          >
            <FolderOpen size={12} />
            数据
          </button>
        )}
      </div>

      {/* ★ 搬位置：选完目录先确认（会清空原位置，不能点错了没提示）⚠ */}
      {pending && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,.35)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 90,
          }}
          onClick={() => !busy && setPending('')}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#fff',
              borderRadius: 10,
              padding: 20,
              width: 460,
              maxWidth: '92vw',
              fontFamily: 'inherit',
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>把笔记搬到这儿？</div>
            <div
              style={{
                fontSize: 11.5,
                color: '#666',
                marginBottom: 14,
                wordBreak: 'break-all',
                fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
              }}
            >
              {pending}
            </div>
            <div style={{ fontSize: 12, color: '#444', lineHeight: 1.8, marginBottom: 14 }}>
              现在的位置：<span style={{ color: '#999' }}>{libRoot}</span>
              <br />
              {/* ★ 是**搬**不是复制（所有者：「要移动，不要复制，万一用户忘记了，
                  那里不是全都是垃圾数据了」）⚠ */}
              会连同笔记、索引、回收站一起**搬过去**，原位置会清空 ——
              不留副本，免得以后两边各改各的。
            </div>
            {err && <div style={{ color: '#c00', fontSize: 11.5, marginBottom: 10 }}>{err}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" disabled={busy} onClick={() => setPending('')} style={btn}>
                取消
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void doSwitch()}
                style={{ ...btn, background: '#111', color: '#fff', border: 'none' }}
              >
                {busy ? '搬移中…' : '搬过去'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
