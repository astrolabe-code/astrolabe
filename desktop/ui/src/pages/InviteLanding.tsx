import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

/**
 * ★ 邀请链接落地页（`B171`）
 *
 * ## ★ 它存在的唯一理由：★ **让两种链接形态都能用**
 *
 * ★ 后端（`web/views/invites.py::_invite_url()`）拼的分享链接是：
 * `{ASTROLABE_SPA_URL}/invite/{token}` —— ⚠ 而**实测 `ASTROLABE_SPA_URL` 是未配置的默认值**
 * （`http://localhost:8080`）⇒ ★ 那条链接**本身打不开** ⚠
 *
 * ★★ 而 `AdminInvites.tsx::shareUrl()` 生成的是：
 * `/app/register?invite=<token>` ✅
 *
 * ⇒ ★★★ **本路由把前者转成后者** —— ★ 于是：
 * · ★ `/app/invite/<token>`（旧形态 / 别人手工拼的）
 * · ★ `/app/register?invite=<token>`（新形态）
 * ★★ **两条路都能走到注册页** ✅
 *
 * ⚠★ 用 `replace: true` —— ★ 否则用户点"后退"会在两条链接之间**来回弹** ⚠
 */
export default function InviteLanding() {
  const { token = '' } = useParams()
  const navigate = useNavigate()

  useEffect(() => {
    navigate(`/register?invite=${encodeURIComponent(token)}`, { replace: true })
  }, [token, navigate])

  // ★ 本页不留任何 UI（★ 转瞬即逝）—— ★ 但**不能返回 `null` 就完事**：
  //   万一路由参数为空，用户会看到一片空白 ⇒ ★ 给一句兜底
  return (
    <div className="page">
      <p className="text-text-faint">正在打开邀请…</p>
    </div>
  )
}
