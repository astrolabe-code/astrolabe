/**
 * ★★ **个人版顶栏**（30 行，替代社区版那个带登录/搜索/我的的 TopNav）
 *
 * 所有者：「不要做用户登陆功能，就只有用户一个人用……首页这些花里胡哨的不需要的。」
 *
 * ```\n * Astrolabe                                    [数据目录]\n * ```\n *
 * ⚠ 只有两个东西：一个回项目的入口、一个「数据在哪」。
 *   ⛔ 不放搜索、头像、登录、通知 —— 单机单用户没有这些概念。
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen } from 'lucide-react'

interface DesktopApi {
  isDesktop?: boolean
  info?: () => Promise<{ version: string; dataDir: string }>
  openDataDir?: () => Promise<boolean>
}

export default function PersonalBar() {
  const nav = useNavigate()
  const [dataDir, setDataDir] = useState('')
  const api = (window as unknown as { astrolabe?: DesktopApi }).astrolabe

  useEffect(() => {
    // ★ 只在桌面版里有；浏览器里打开就什么都不显示（不报错）
    api?.info?.().then((i) => setDataDir(i.dataDir)).catch(() => {})
  }, [api])

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
        {dataDir && (
          <button
            type="button"
            title={dataDir}
            onClick={() => void api?.openDataDir?.()}
            style={{
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
            }}
          >
            <FolderOpen size={12} />
            数据目录
          </button>
        )}
      </div>
    </div>
  )
}
