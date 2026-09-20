import { useState } from 'react'
import type { FormEvent } from 'react'
import { Copy, Link as LinkIcon, Plus, ShieldAlert, ShieldOff } from 'lucide-react'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import { errorMessage } from '../api/errors'
import type { InviteInfo } from '../api/types'
import { useMe } from '../hooks/useMe'
import { useCreateInvite, useInvites, useRevokeInvite } from '../query/invites'

/**
 * ★★★ 管理页 —— 一期只做【邀请码管理】（`B171`）
 *
 * ## ⚠★★ 权限：**这里的管理员判断【只决定"显不显示"】**
 *
 * ★ 真正的判定在后端（★ `web/views/invites.py` 的三个端点都带 `@staff_only`）⚠
 * ⇒ ★★ 就算有人在控制台里把这个页面**强行渲染出来**，
 *   ★ 他也**只会拿到 `403`** —— ★★ 这不是"运气好"，★ 而是**设计如此** ✅
 * ⇒ ★ **所以本页的检查是"体验"**（★ 非管理员看到一句得体的说明，★ 而不是一片空白）⚠
 *
 * ## ★★ 分享链接：**前端自己拼**（★ 不用后端返回的 `invite.url`）
 *
 * ★ 原因见 `shareUrl()` 的说明 —— ⚠ 后端那个用了**未配置**的 `ASTROLABE_SPA_URL` ⚠
 *
 * ## ⚠ 一期【不】做的（★ 归 `2e`）
 * ★ 审核队列（`admin/reviews/`）· ★ 参数中心（三个开关 / 配额）· ★ 账单之类
 */

/** ★ SPA 的基路径（★ `vite.config.ts` 的 `base: '/app/'`，⚠ 与 `BrowserRouter` 的 basename 一致） */
const SPA_BASE = (import.meta.env.BASE_URL || '/app/').replace(/\/$/, '')

/**
 * ★★★ **分享链接由【前端自己拼】**
 *
 * ⚠★ 为什么**不用**后端返回的 `invite.url`：
 *   ★ 它拼的是 `{ASTROLABE_SPA_URL}/invite/{token}`，★ 而**实测该配置是未填的默认值**
 *   （`http://localhost:8080`）⇒ ★★ **那条链接发出去就是打不开的** ⚠
 * ★★ 而**前端知道自己此刻的地址** ⇒ ★ 换个域名 / 端口访问，**不用改任何配置** ✅
 */
export function shareUrl(token: string): string {
  return `${window.location.origin}${SPA_BASE}/register?invite=${encodeURIComponent(token)}`
}

/** ★ 一条邀请的展示状态（★ 与后端 `is_usable()` 的口径一致）*/
function statusOf(inv: InviteInfo): { text: string; color: string } {
  if (inv.revoked) return { text: '已撤销', color: 'var(--err)' }
  if (inv.used >= inv.max_uses) return { text: '已用完', color: 'var(--text-faint)' }
  if (!inv.usable) return { text: '已过期', color: 'var(--err)' }
  return { text: '可用', color: 'var(--accent)' }
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('zh-CN', { hour12: false })
}

export default function AdminInvites() {
  const me = useMe()
  const isStaff = !!me.data?.is_staff

  const [maxUses, setMaxUses] = useState('1')
  const [validDays, setValidDays] = useState('7')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const [copied, setCopied] = useState('')

  const invites = useInvites(isStaff)
  const create = useCreateInvite()
  const revoke = useRevokeInvite()

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      await create.mutateAsync({
        // ⚠★ 后端限 `max_uses` 1–200 · `valid_days` 1–3650 —— ★ 越界会 400（★ 这里先转数字）
        max_uses: Number(maxUses) || 1,
        valid_days: Number(validDays) || 7,
        note,
      })
      setNote('')
    } catch (e2) {
      setErr(errorMessage(e2, '生成失败，请重试。'))
    }
  }

  async function copyLink(token: string) {
    const url = shareUrl(token)
    try {
      await navigator.clipboard.writeText(url)
      setCopied(token)
      window.setTimeout(() => setCopied(''), 2000)
    } catch {
      // ⚠ 剪贴板 API 在非 HTTPS / 无权限时会失败 —— ★ 退化成"让用户自己复制"
      window.prompt('复制这条链接：', url)
    }
  }

  async function handleRevoke(token: string) {
    setErr('')
    try {
      await revoke.mutateAsync(token)
    } catch (e2) {
      setErr(errorMessage(e2, '撤销失败，请重试。'))
    }
  }

  // ★★ 非管理员：★ 给一句得体的说明（★ 真正的拦截在后端 —— 见文件头）
  if (me.isLoading) {
    return (
      <AppLayout title="管理">
        <p className="text-text-faint">正在确认身份…</p>
      </AppLayout>
    )
  }
  if (!isStaff) {
    return (
      <AppLayout title="管理">
        <div className="card p-6 flex items-start gap-3">
          <ShieldAlert size={18} style={{ color: 'var(--err)' }} />
          <div>
            <p className="m-0 font-semibold">需要管理员权限</p>
            <p className="text-text-sub m-0 mt-1" style={{ fontSize: 13 }}>
              这个页面只有站点管理员能看。
              {me.data?.authenticated ? null : '（当前未登录）'}
            </p>
          </div>
        </div>
      </AppLayout>
    )
  }

  const list = invites.data || []

  return (
    <AppLayout
      title="邀请码管理"
      crumbs={[{ label: '工作区', to: '/workspace' }, { label: '管理' }]}
      actions={
        <Button
          variant="ghost"
          icon={<Plus size={15} />}
          loading={invites.isFetching}
          onClick={() => invites.refetch()}
        >
          刷新
        </Button>
      }
    >
      {/* ---------------- 生成 ---------------- */}
      <div className="card p-5 mb-5">
        <h3 className="m-0 mb-4" style={{ fontSize: 15 }}>
          生成一个新邀请
        </h3>
        <form onSubmit={handleCreate}>
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <Input
              id="max_uses"
              label="可用次数"
              type="number"
              min={1}
              max={200}
              value={maxUses}
              onChange={(e) => setMaxUses(e.target.value)}
              hint="默认 1 —— 用一次即失效"
            />
            <Input
              id="valid_days"
              label="有效天数"
              type="number"
              min={1}
              max={3650}
              value={validDays}
              onChange={(e) => setValidDays(e.target.value)}
              hint="必须 > 0（0 或负数会被后端拒绝）"
            />
            <Input
              id="note"
              label="备注（可选）"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="给谁的？比如「张三」"
              maxLength={200}
            />
          </div>

          {err && <div className="error mt-3">{err}</div>}

          <div className="mt-4">
            <Button type="submit" variant="primary" loading={create.isPending} icon={<Plus size={15} />}>
              生成邀请
            </Button>
          </div>
        </form>
      </div>

      {/* ---------------- 列表 ---------------- */}
      <div className="card p-0 overflow-hidden">
        <div className="px-5 py-4" style={{ borderBottom: '1px solid var(--card-border)' }}>
          <h3 className="m-0" style={{ fontSize: 15 }}>
            已发出的邀请（{list.length}）
          </h3>
        </div>

        {invites.isLoading && <p className="p-5 text-text-faint m-0">正在加载…</p>}
        {invites.isError && (
          <p className="p-5 m-0" style={{ color: 'var(--err)' }}>
            {errorMessage(invites.error, '加载失败。')}
          </p>
        )}
        {!invites.isLoading && !invites.isError && list.length === 0 && (
          <p className="p-5 text-text-faint m-0">还没有发出过邀请。</p>
        )}

        {list.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full" style={{ fontSize: 12.5, borderCollapse: 'collapse' }}>
              <thead>
                <tr className="text-text-faint" style={{ textAlign: 'left' }}>
                  <th className="px-4 py-3 font-normal">凭证</th>
                  <th className="px-4 py-3 font-normal">状态</th>
                  <th className="px-4 py-3 font-normal">用量</th>
                  <th className="px-4 py-3 font-normal">到期</th>
                  <th className="px-4 py-3 font-normal">备注</th>
                  <th className="px-4 py-3 font-normal">操作</th>
                </tr>
              </thead>
              <tbody>
                {list.map((inv) => {
                  const st = statusOf(inv)
                  return (
                    <tr key={inv.token} style={{ borderTop: '1px solid var(--card-border)' }}>
                      <td className="px-4 py-3">
                        <code className="text-text-sub" style={{ fontSize: 11.5 }}>
                          {inv.token.slice(0, 14)}…
                        </code>
                      </td>
                      <td className="px-4 py-3" style={{ color: st.color }}>
                        {st.text}
                      </td>
                      <td className="px-4 py-3">
                        {inv.used} / {inv.max_uses}
                      </td>
                      <td className="px-4 py-3 text-text-sub">{fmtDate(inv.expires_at)}</td>
                      <td className="px-4 py-3 text-text-sub">{inv.note || '—'}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            className="icon-btn"
                            title={copied === inv.token ? '已复制' : '复制分享链接'}
                            aria-label="复制分享链接"
                            disabled={!inv.usable}
                            onClick={() => copyLink(inv.token)}
                          >
                            {copied === inv.token ? <LinkIcon size={13} /> : <Copy size={13} />}
                          </button>
                          <button
                            type="button"
                            className="icon-btn danger"
                            title="撤销这条邀请"
                            aria-label="撤销邀请"
                            disabled={inv.revoked || revoke.isPending}
                            onClick={() => handleRevoke(inv.token)}
                          >
                            <ShieldOff size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="text-text-faint mt-4" style={{ fontSize: 12, lineHeight: 1.8 }}>
        ★ 分享链接形如 <code>{shareUrl('<token>')}</code>，★ 收到的人**直接打开就能注册**
        （★ 即使注册入口是隐藏的 —— ★ 那正是邀请制）✅
        <br />
        ⚠★ 生成时**有效期必须 &gt; 0** —— ★ 这是 `U4.7` 规则 2（「否则泄露了就永久有效」）。
      </p>
    </AppLayout>
  )
}
