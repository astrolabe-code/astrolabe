import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Compass } from 'lucide-react'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import { errorMessage } from '../api/errors'
import { safeInternalPath } from '../lib/nav'
import { useMe } from '../hooks/useMe'
import { useAuthProviders, useRegister } from '../query/auth'

/**
 * ★ 注册页（`B170` · ★ 用户名 + 密码 +（可能）邀请码）
 *
 * ## ★★★ 本页最要紧的一件事：**"入口隐藏"不等于"进不来"**
 *
 * ★ `B170` 定的语义（★ 所有者原话：「**管理员能隐藏或开启注册入口，如果隐藏了，
 *   那就只有有邀请码的才能看见**」）：
 *
 * | `registration_open` | 前端表现 |
 * |---|---|
 * | ★ `true` | ★ **登录页显示"去注册"链接** —— 谁都能点进来 |
 * | ★★ `false` | ★★ **登录页【不显示】链接**；★ 但**拿到邀请链接的人直接打开本页**（`?invite=…`）✅ |
 *
 * ⇒ ★★ 所以本页**没有"入口关了就把你赶走"的逻辑** —— ★ 它只做三件事：
 * ① ★ `paused` / `!allowed` ⇒ 显示原因，❌ 不出表单
 * ② ★★ **需要码却没带码** ⇒ **显示引导语**（⚠ 不显示表单，★ 免得用户填完才被拒）
 * ③ ★ 否则出表单（★ 码从 `?invite=` **自动填好**）✅
 *
 * ## ⚠★ 与登录页的一处对照（★ 别搞混）
 * ★ 登录失败**要说含糊**（★ 防账号枚举）；★ **注册失败必须说清楚**
 * （★ 重名 / 码无效 / 密码太弱）—— ★ 因为注册**躲不掉**，⚠ 不说清用户只会反复试 ⚠
 */
export default function Register() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeInternalPath(params.get('next'), '/')

  // ★ 邀请链接带来的码（★ `/app/register?invite=xxx`）—— ★ 只取一次
  const [invite, setInvite] = useState(() => (params.get('invite') || '').trim())
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')

  const providers = useAuthProviders()
  const me = useMe()
  const reg = useRegister()

  const gate = providers.data?.registration
  const paused = !!gate?.paused
  const allowed = !!gate?.allowed
  const needInvite = !!gate?.invite_required
  const visible = !!gate?.registration_open

  useEffect(() => {
    document.body.classList.add('auth-page')
    return () => document.body.classList.remove('auth-page')
  }, [])

  useEffect(() => {
    if (me.data?.authenticated) navigate(next, { replace: true })
  }, [me.data?.authenticated, next, navigate])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      // ★ 注册成功**即已登录**（★ 后端直接签发 token）⇒ ★ 不用再走一次登录 ✅
      await reg.mutateAsync({ username, password, invite_token: invite })
      navigate(next, { replace: true })
    } catch (e2) {
      setErr(errorMessage(e2, '注册失败，请稍后重试。'))
    }
  }

  const blocked = paused || !allowed
  // ⚠★ 需要码、但手上没有 ⇒ **不出表单**（★ 让用户先去拿邀请链接）
  const needCodeButNone = !blocked && needInvite && !invite.trim()

  return (
    <div className="page">
      <div className="auth-card">
        <div className="glyph">
          <Compass size={20} />
        </div>
        <h1>注册</h1>
        <p className="sub">创建本站账号 —— ★ 用户名 + 密码，不需要第三方账号。</p>

        {err && <div className="error">{err}</div>}

        {paused && (
          <div className="error">{gate?.message || '站点正在维护，暂时无法注册。'}</div>
        )}
        {!paused && !allowed && (
          <div className="error">{gate?.message || '本站当前未开放注册。'}</div>
        )}

        {/* ⚠★ 需要码却没有码 —— ★ 只给引导，❌ 不给表单 */}
        {needCodeButNone && (
          <>
            <div className="error">{gate?.message || '本站当前仅限邀请注册。'}</div>
            <p className="quota-hint">
              ★ 如果你收到了邀请链接，请**用那条链接**打开本页（码会自动带上）。
            </p>
          </>
        )}

        {!blocked && !needCodeButNone && (
          <form onSubmit={handleSubmit}>
            {/* ★ 需要码时才有这个框；★ 从邀请链接进来时**已经填好了** */}
            {needInvite && (
              <Input
                id="invite"
                label="邀请码"
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                autoComplete="off"
                placeholder="邀请链接里的那段 token"
                required
              />
            )}
            <Input
              id="username"
              label="用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              hint="3–30 位，中英文 / 数字 / 下划线 / 连字符 / 点"
              autoFocus
              required
            />
            <Input
              id="password"
              label="密码"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              hint="至少 8 位，且不能是纯数字或纯字母"
              required
            />

            <div className="auth-actions">
              <Button type="submit" variant="primary" block loading={reg.isPending}>
                注册并登录
              </Button>
            </div>
          </form>
        )}

        <div className="auth-foot">
          {/* ⚠★ 入口隐藏时**不给"去注册"的暗示**（★ 那个链接在登录页已经藏了），
              只留一条回登录页的路 ✅ */}
          <Link to={visible ? '/login' : '/login'}>已有账号？去登录</Link>
        </div>
      </div>
    </div>
  )
}
