import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Compass } from 'lucide-react'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import { errorMessage } from '../api/errors'
import { safeInternalPath } from '../lib/nav'
import { useMe } from '../hooks/useMe'
import { useAuthProviders, useLogin } from '../query/auth'

/**
 * ★ 登录页（`B170` · ★ **用户名 + 密码**）
 *
 * ## ⚠★★ 一处容易搞错的字段（★ 务必看 `RegistrationGate` 的说明）
 * ★ 判断"要不要显示注册入口"看的是 **`registration.registration_open`**，
 * ★ ❌ **不是 `allowed`** —— ★ 两者在"隐藏入口"时**不同**：
 * ★ `registration_open=false` 时 `allowed` **仍是 `true`**（★ 持邀请码者还能注册）⚠
 * ⇒ ★ 用错字段 ⇒ ★ **注册按钮会显示出来**，⚠ 而点进去又要求邀请码（★ 体验很怪）⚠
 *
 * ## ★ `next` 参数（★ 401 时由 `App.tsx` 埋进来的）
 * ★ 登录成功后回到**用户原本想去的地方**；⚠ 必须过 `safeInternalPath`（★ 防开放重定向）
 */
export default function Login() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeInternalPath(params.get('next'), '/')

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [err, setErr] = useState('')

  const providers = useAuthProviders()
  const me = useMe()
  const login = useLogin()

  const gate = providers.data?.registration
  const paused = !!gate?.paused
  const canRegister = !!gate?.registration_open

  /** ★ 给 `<body>` 加 `auth-page` 类 —— ★ `login.css` 的选择器是 `body.auth-page .page`
   *  ⚠ 不加这个类，整页样式不生效（★ 从旧站 1:1 搬过来时最容易漏的一步） */
  useEffect(() => {
    document.body.classList.add('auth-page')
    return () => document.body.classList.remove('auth-page')
  }, [])

  /** ★ 已经登录的人不该停在登录页 */
  useEffect(() => {
    if (me.data?.authenticated) navigate(next, { replace: true })
  }, [me.data?.authenticated, next, navigate])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      await login.mutateAsync({ username, password, remember })
      navigate(next, { replace: true })
    } catch (e2) {
      // ⚠★ 直接展示**后端文案** —— ★ 后端刻意把"用户名不存在"与"密码错"说成同一句
      //   （★ 防账号枚举），★ 前端**不要再自作聪明地区分** ⚠
      setErr(errorMessage(e2, '登录失败，请稍后重试。'))
    }
  }

  return (
    <div className="page">
      <div className="auth-card">
        <div className="glyph">
          <Compass size={20} />
        </div>
        <h1>登录</h1>
        <p className="sub">用本站账号登录，继续阅读与共建。</p>

        {err && <div className="error">{err}</div>}
        {paused && <div className="error">{gate?.message || '站点正在维护，暂时无法登录。'}</div>}

        <form onSubmit={handleSubmit}>
          <Input
            id="username"
            label="用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
          <Input
            id="password"
            label="密码"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />

          <label className="remember-row" htmlFor="remember">
            <input
              id="remember"
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            记住我（不勾选则 7 天后需重新登录）
          </label>

          <div className="auth-actions">
            <Button
              type="submit"
              variant="primary"
              block
              loading={login.isPending}
              disabled={paused}
            >
              登录
            </Button>
          </div>
        </form>

        <div className="auth-foot">
          {/* ★★ `B170`：注册入口**只在 `registration_open` 时对所有人可见** ——
              ⚠★ 隐藏时**不显示链接**（★ 但拿到邀请链接的人，
              ★ 从 `/register?invite=…` **直接就能进来**，★ 那是设计如此）✅ */}
          {paused ? null : canRegister ? (
            <Link to="/register">还没有账号？去注册</Link>
          ) : (
            <span>本站当前仅限邀请注册 —— 请使用你收到的邀请链接。</span>
          )}
        </div>
      </div>
    </div>
  )
}
