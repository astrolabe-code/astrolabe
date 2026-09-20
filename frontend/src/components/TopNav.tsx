import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft, Home, LogOut, Moon, Shield, Sun, User } from 'lucide-react'
import type { Me } from '../hooks/useMe'
import { useMe } from '../hooks/useMe'
import { useTheme } from '../hooks/useTheme'
import { useLogout } from '../query/auth'

/**
 * ★ 顶栏（B163 精简版）
 *
 * ## ⚠★ 与原版的差别 —— 都源于「本项目没有旧站」
 *
 * | 原版 | 现在 | 为什么 |
 * |---|---|---|
 * | ★ 退出走**表单 POST `/logout/`** + CSRF cookie | ★ 改调 **`POST /api/auth/logout/`** | ★★ 那是**旧站**的 session 登出；★ 新后端是 **Bearer token**，★ 登出应走 API ✅ |
 * | ★ 手册 / 留言 / 管理 / 注册 / LSP / 信箱 | ★ **删除** | ⚠ 那些**页面还不存在** ⇒ 留着只会 404 |
 * | ★ `LEGACY_LINKS.*`（旧站 URL）| ★ `SPA_LINKS.*` | ★ 见 `src/legacy.ts` 的重写说明 |
 *
 * ★★★ **保留全部视觉类名**（`.topnav` · `.nav-btn` · `.nav-avatar` · `.nav-badge` …）
 *   —— ★ 这样 `styles/components.css` **一行都不用改** ✅
 *
 * ## ★ 一处刻意保留的设计（来自原版）
 *
 * ★★ **登出【绝不能走 GET】** —— ⚠ 否则浏览器的**预取 / 链接扫描**会把你登出 ⚠
 *   ★ 原版是为此刻意用 POST 表单的；★ 本版改成 **POST API**，★ 同样不是 GET ✅
 */
export default function TopNav() {
  const { theme, toggle } = useTheme()
  const logout = useLogout()
  const [open, setOpen] = useState(false)
  const linksRef = useRef<HTMLDivElement>(null)
  const burgerRef = useRef<HTMLButtonElement>(null)

  const { pathname, key: locKey } = useLocation()
  const navigate = useNavigate()
  const isHome = pathname === '/'
  // ★ react-router 首个 entry 的 key 为 "default"，此时没有可回的站内历史 → 回首页
  const goBack = () => (locKey !== 'default' ? navigate(-1) : navigate('/'))

  const { data } = useMe()
  const me = data ?? ({ authenticated: false } as Me)

  // ★ 点外部收起移动端菜单
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const menu = linksRef.current
      const burger = burgerRef.current
      if (!menu || !burger || !open) return
      const t = e.target as Node
      if (!menu.contains(t) && !burger.contains(t)) setOpen(false)
    }
    document.addEventListener('click', onDoc)
    return () => document.removeEventListener('click', onDoc)
  }, [open])

  /**
   * ★ 退出：走 API（⚠★ **不是 GET** —— 否则浏览器的**预取 / 链接扫描**会把你登出）
   *
   * ★ 改走 `useLogout()`（`B170`）—— ★ 它在 **`onSettled`** 里清本地登录态：
   *   ⚠★ **哪怕请求失败也清** —— ★ 否则用户会卡在"点了退出、但界面还是登录状态"
   *     这种最别扭的状态里 ⚠
   */
  async function handleLogout() {
    await logout.mutateAsync().catch(() => undefined)
    navigate('/', { replace: true })
  }

  return (
    <nav className="topnav">
      <div className="nav-left">
        {!isHome && (
          <button
            type="button"
            className="nav-quick-btn"
            onClick={goBack}
            title="返回上一页"
            aria-label="返回上一页"
          >
            <ArrowLeft size={15} />
            <span className="nav-quick-label">返回</span>
          </button>
        )}
        <div className="nav-user-slot">
          {me.authenticated ? (
            <span className="nav-btn ghost-btn nav-user" title="当前登录身份">
              {me.avatar ? (
                <img className="nav-avatar" src={me.avatar} alt="头像" />
              ) : (
                <span className="nav-avatar">
                  {String(me.username || '?').charAt(0).toUpperCase()}
                </span>
              )}
              <span className="nav-username">{me.username}</span>
              <span className={`nav-role${me.is_staff ? '' : ' user'}`}>
                {me.is_staff ? '管理员' : '用户'}
              </span>
            </span>
          ) : (
            <Link className="nav-btn ghost-btn nav-user" to="/login" title="登录">
              <span className="nav-avatar">
                <User size={14} />
              </span>
              <span>游客</span>
            </Link>
          )}
        </div>
      </div>

      <div className="nav-right-group">
        <button
          className="theme-toggle"
          onClick={toggle}
          aria-label="切换主题"
          title="切换浅色 / 夜穹"
        >
          {theme === 'dark' ? <Moon size={16} /> : <Sun size={16} />}
        </button>
        <button
          ref={burgerRef}
          className="nav-burger"
          aria-label="菜单"
          onClick={() => setOpen((v) => !v)}
        >
          ☰
        </button>
        <div ref={linksRef} className={`nav-links${open ? ' open' : ''}`}>
          {/* ★★ `B171`：**管理入口** —— ★★ **只有 `is_staff` 才渲染** ⚠
              ⚠★ 但请记住：★ 这里的判断**只决定"显不显示按钮"** ——
                ★ **真正的权限在后端**（`web/views/invites.py` 的 `@staff_only`）⚠
                ★★ 「把按钮藏起来」**不等于**安全：★ 有人手输 `/app/admin` 一样会被后端挡住 ✅ */}
          {me.is_staff && (
            <Link className="nav-btn ghost-btn" to="/admin">
              <Shield size={15} />
              管理
            </Link>
          )}
          {me.authenticated ? (
            <button className="nav-btn ghost-btn logout" onClick={handleLogout} data-nav-logout>
              <LogOut size={15} />
              退出
            </button>
          ) : (
            <Link className="nav-btn ghost-btn" to="/login">
              登录
            </Link>
          )}
        </div>
        {!isHome && (
          <button
            type="button"
            className="nav-quick-btn"
            onClick={() => navigate('/')}
            title="返回首页"
            aria-label="返回首页"
          >
            <Home size={15} />
            <span className="nav-quick-label">首页</span>
          </button>
        )}
      </div>
    </nav>
  )
}
