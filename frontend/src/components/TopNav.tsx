import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useMediaQuery } from '../hooks/useMediaQuery'
import {
  ArrowLeft,
  EyeOff,
  Home,
  LogOut,
  Menu,
  Moon,
  Shield,
  Sun,
  Trash2,
  User,
  ChevronsUp,
  ChevronsDown,
  X,
} from 'lucide-react'
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
 * ## ★★ 移动端（≤700px）独立布局 —— 所有者口述的形
 *
 * ```
 * 常态（**与背景同色的横条**，占一行高）：
 * ┌──────────────────────────────────┐
 * │  (头像)          ⌃           ☰   │  左头像 · 中向上箭头 · 右汉堡
 * └──────────────────────────────────┘
 *
 * 点 ☰ ⇒ 横条下方拉出菜单（主题 / 管理 / 已处置 / 回收站 / 退出 / 首页 / 返回）
 * 点 ⌃ ⇒ 整个横条消失，顶部居中留「⌄⌄ 顶栏」胶囊（与电脑端一致）
 * ```
 *
 * ⚠ ★ 手机宽度放不下一排按钮 ——* 所以横条上**只留三样**，其余全塞进下拉菜单 ✅
 */
export default function TopNav() {
  const { theme, toggle } = useTheme()
  const logout = useLogout()
  const [open, setOpen] = useState(false)
  // ★★ 顶栏可**向上收起**（* 所有者：「首页按钮所在的标题栏也要做一个向上收缩按钮」）⚠
  //   · · ★ 收起后不占高度 ⇒* 图谱 / 阅读区更长 ✅ · 顶部居中留一个「顶栏」胶囊恢复 ⚠
  const [collapsed, setCollapsed] = useState(false)
  // ★★ 移动端（≤700px）走**独立布局**：* 左头像 / 中向上箭头 / 右汉堡 ⚠
  const isNarrow = useMediaQuery('(max-width: 700px)')

  // ★★ 顶栏高度交给 CSS 变量 ——* 页面用 `calc(100dvh - var(--nav-h))` 精确撑满 ⚠
  useEffect(() => {
    const apply = () => {
      // ★★★ 移动端横条**占布局高度**（48px）；* 收起后 0；* 桌面 54px ⚠
      //   · · ★ 之前移动端写 0（浮层）⇒* 横条压在图上、按钮没背景（* 已修正）⚠
      const h = collapsed ? 0 : window.innerWidth <= 700 ? 48 : 54
      document.documentElement.style.setProperty('--nav-h', `${h}px`)
    }
    apply()
    window.addEventListener('resize', apply)
    return () => {
      window.removeEventListener('resize', apply)
      document.documentElement.style.removeProperty('--nav-h')
    }
  }, [collapsed])

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

  // ★★ 收起态：只留顶部居中的恢复胶囊（* 桌面 / 移动端同一套）⚠
  if (collapsed) {
    return (
      <button
        type="button"
        className="nav-restore"
        onClick={() => setCollapsed(false)}
        title="展开顶栏"
      >
        <ChevronsDown size={11} />
        <span>顶栏</span>
      </button>
    )
  }

  // ============================================================ 移动端：横条（左头像 / 中上箭头 / 右汉堡）
  if (isNarrow) {
    return (
      <>
        <nav
          className="topnav"
          style={{
            // ★★★ **与背景同色的横条**（* 所有者：「初始状态就是一个青色的横长条，
            //   跟背景颜色一样」）——* 占布局高度、不加边框、不透明浮层 ⚠
            position: 'relative',
            zIndex: 30,
            height: 48,
            minHeight: 48,
            padding: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--bg)',
            borderBottom: 'none',
            boxShadow: 'none',
          }}
        >
          {/* ---- 左：用户头像（点进用户设置） ---- */}
          {me.authenticated ? (
            <Link
              to="/me/settings"
              title="用户设置"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '0 14px',
                height: '100%',
                textDecoration: 'none',
              }}
            >
              {me.avatar ? (
                <img
                  className="nav-avatar"
                  src={me.avatar}
                  alt="头像"
                  style={{ width: 28, height: 28 }}
                />
              ) : (
                <span
                  className="nav-avatar"
                  style={{ width: 28, height: 28, fontSize: 13 }}
                >
                  {String(me.username || '?').charAt(0).toUpperCase()}
                </span>
              )}
            </Link>
          ) : (
            <Link
              to="/login"
              title="登录"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '0 14px',
                height: '100%',
                textDecoration: 'none',
                color: 'var(--text-sub)',
              }}
            >
              <span
                className="nav-avatar"
                style={{ width: 28, height: 28, display: 'grid', placeItems: 'center' }}
              >
                <User size={15} />
              </span>
            </Link>
          )}

          {/* ---- 中：向上的箭头 ⇒ **整个导航栏向上收起**成胶囊 ---- */}
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            aria-label="收起顶栏"
            title="收起顶栏（内容更宽敞）"
            style={{
              flex: 1,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              background: 'none',
              border: 'none',
              color: 'var(--text-sub)',
              cursor: 'pointer',
              gap: 4,
            }}
          >
            <ChevronsUp size={18} />
          </button>

          {/* ---- 右：三根横线（展开菜单） ---- */}
          <button
            ref={burgerRef}
            type="button"
            className="nav-burger"
            aria-label={open ? '收起菜单' : '菜单'}
            onClick={() => setOpen((v) => !v)}
            style={{
              display: 'grid',
              placeItems: 'center',
              width: 40,
              height: 40,
              marginRight: 8,
              borderRadius: 999,
              background: 'transparent',
              border: 'none',
              color: 'var(--text-main)',
              cursor: 'pointer',
            }}
          >
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>

          {/* ---- 下拉菜单：横条下方拉出（absolute，不占布局高度） ---- */}
          {open && (
            <div
              ref={linksRef}
              style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                zIndex: 29,
                background: 'var(--card)',
                borderBottom: '1px solid var(--card-border)',
                boxShadow: '0 10px 24px rgba(15,23,42,.14)',
                padding: '10px 12px',
                display: 'flex',
                flexWrap: 'wrap',
                gap: 8,
              }}
            >
              {/* ★ 主题（* 手机上也要能切）⚠ */}
              <button className="nav-btn ghost-btn" onClick={toggle}>
                {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
                {theme === 'dark' ? '浅色' : '夜穹'}
              </button>
              {me.is_staff && (
                <Link className="nav-btn ghost-btn" to="/admin">
                  <Shield size={15} />
                  管理
                </Link>
              )}
              {me.is_staff && (
                <Link className="nav-btn ghost-btn" to="/admin/moderated">
                  <EyeOff size={15} />
                  已处置
                </Link>
              )}
              {me.authenticated && (
                <Link className="nav-btn ghost-btn" to="/me/deleted" title="回收站">
                  <Trash2 size={15} />
                  回收站
                </Link>
              )}
              {me.authenticated ? (
                <button className="nav-btn ghost-btn logout" onClick={handleLogout}>
                  <LogOut size={15} />
                  退出
                </button>
              ) : (
                <Link className="nav-btn ghost-btn" to="/login">
                  登录
                </Link>
              )}
              {!isHome && (
                <button className="nav-btn ghost-btn" onClick={() => navigate('/')}>
                  <Home size={15} />
                  首页
                </button>
              )}
              {!isHome && (
                <button className="nav-btn ghost-btn" onClick={goBack}>
                  <ArrowLeft size={15} />
                  返回
                </button>
              )}
            </div>
          )}
        </nav>

        {/* ★★ 菜单展开时的点击遮罩（* 点图或空白处收起）⚠ */}
        {open && (
          <div
            className="header-backdrop"
            onClick={() => setOpen(false)}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 25,
              background: 'rgba(15,23,42,.18)',
            }}
          />
        )}
      </>
    )
  }

  // ============================================================ 桌面端：原布局不变
  return (
    <>
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
              // ★★ 点头像 / 用户名 ⇒ **用户设置**（* 所有者：「不然很难找的」）⚠
              <Link
                className="nav-btn ghost-btn nav-user"
                to="/me/settings"
                title="用户设置（点击进入）"
              >
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
              </Link>
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
            onClick={() => setCollapsed(true)}
            aria-label="收起顶栏"
            title="收起顶栏（内容更宽敞）"
          >
            <ChevronsUp size={16} />
          </button>
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
            {/* ★★ `B171`：**管理入口** —— ★★ **只有 `is_staff` 才渲染** ⚠ */}
            {me.is_staff && (
              <Link className="nav-btn ghost-btn" to="/admin">
                <Shield size={15} />
                管理
              </Link>
            )}
            {/* ★★ `B215`：**已处置**（staff）——* 被隐藏的项目/笔记，* 从这儿恢复 ⚠ */}
            {me.is_staff && (
              <Link className="nav-btn ghost-btn" to="/admin/moderated">
                <EyeOff size={15} />
                已处置
              </Link>
            )}
            {/* ★★ `F4`（`D96`）：回收站入口 ——* 登录用户可见（* 游客点了也是空）✅ */}
            {me.authenticated && (
              <Link className="nav-btn ghost-btn" to="/me/deleted" title="回收站">
                <Trash2 size={15} />
                回收站
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
    </>
  )
}
