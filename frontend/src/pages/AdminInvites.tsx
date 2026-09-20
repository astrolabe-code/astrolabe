import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Link as LinkIcon,
  Plus,
  Power,
  ShieldAlert,
  ShieldOff,
} from 'lucide-react'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import ConfirmDialog from '../components/ui/ConfirmDialog'
import CopyField from '../components/ui/CopyField'
import Input from '../components/ui/Input'
import Modal from '../components/ui/Modal'
import { errorMessage } from '../api/errors'
import type { AppSettingInfo, InviteInfo } from '../api/types'
import { useMe } from '../hooks/useMe'
import { useAdminSettings, useUpdateSettings } from '../query/admin'
import { INVITES_PAGE_SIZE, useCreateInvite, useInvites, useRevokeInvite } from '../query/invites'

/**
 * ★★★ 管理页 —— **邀请码 + 注册开关**（`B171` 建 · ★★ `B172` 三项扩充）
 *
 * ## ★★ 权限：**这里的管理员判断【只决定"显不显示"】**
 *
 * ★ 真正的判定在后端（★ `web/views/invites.py` 与 `web/views/admin.py` 都带 `@staff_only`）⚠
 * ⇒ ★★ 就算有人在控制台里把这个页面**强行渲染出来**，
 *   ★ 他也**只会拿到 `403`** —— ★★ 这不是"运气好"，★ 而是**设计如此** ✅
 * ⇒ ★ **所以本页的检查是"体验"**（★ 非管理员看到一句得体的说明，★ 而不是一片空白）⚠
 *
 * ## ★★★ `B172` 加的三样
 *
 * | # | 加什么 | 为什么 |
 * |---|---|---|
 * | ① | **注册 / 邀请 / 登录开关** | ★ 用户原话：「**管理员管理页面应该有打开和关闭注册以及邀请的按钮**」 |
 * | ② | **列表分页** | ★ 用户原话：「**已发出列表太长了，应该分页**」 |
 * | ③ | **自写弹窗**（★ 替代 `window.prompt`）| ★ 用户原话：「**显示注册邀请连接的弹窗是浏览器自带的，把我服务器IP地址都显示了，你应该自己写一个弹窗，这样以后弹窗可以通用**」 |
 *
 * ## ⚠★★ 第 ③ 条的真实根因（★ 值得记一笔）
 *
 * ★ 所有者从 `http://192.168.3.91:5173` 访问 —— ★★ **那不是安全上下文**
 * ⇒ ★ **`navigator.clipboard` 是 `undefined`** ⇒ ★ 原来的 `catch` 降级**必然触发**
 * ⇒ ⚠★ 而 `window.prompt` **会把整条 URL（含服务器 IP）显示在标题栏** ⚠
 * ⇒ ★★ 现在改用 `ui/Modal` + `ui/CopyField` —— ★ 后者有**三级降级**（★ 见该文件）✅
 *
 * ## ★ 分享链接：**前端自己拼**（★ 不用后端返回的 `invite.url`）
 *
 * ★ 原因见 `shareUrl()` 的说明 —— ⚠ 后端那个用了**未配置**的 `ASTROLABE_SPA_URL` ⚠
 *
 * ## ⚠ 一期【不】做的（★ 归 `2e`）
 * ★ 审核队列（`admin/reviews/`）· ★ 配额 / 令牌 TTL 等**其余参数**（★ 本页只挑注册相关的四个）· ★ 账单
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

/**
 * ★★ 管理页的**开关清单**（`B172`）
 *
 * ⚠★ 为什么**硬编码这四个 key**、而不是把 `appsettings.KEYS` 全列出来：
 * ★ 参数中心里还有配额、令牌 TTL、OAuth 时限…（★ 十几个）——
 * ★★ 而那些是"调参"，★ 本页是"**管理开关**" ⚠
 * ⇒ ★ 挑出**与"能不能注册 / 能不能登录 / 站还开不开"直接相关的四个** ✅
 * （★ 将来要调其余参数，★ 再单独做一个"全部参数"页 —— ⚠ 那时也只是**加**一个列表，★ 不漏改这里）
 */
const GATE_KEYS = ['registration_open', 'invite_required', 'login_open', 'paused'] as const

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

/**
 * ★ 一个开关（`B172`）
 *
 * ⚠★★ 三条设计（★ 都为了"**别让管理员误操作**"）：
 * ① ★ **`editable === false` ⇒ 禁用 + 说明原因**（★ 门禁类只有 superuser 能改）——
 *    ⚠★ 而不是"点了再吃 403"（★ 那是让用户白点一次）⚠
 * ② ★ `paused` 是**重锤**（★ `KeySpec` 原文：「这不是普通开关」）⇒ ★ **必须二次确认** ⚠
 * ③ ★ 提交中禁用 ⇒ ⚠ 防止连点导致竞态（★ 点两次 = 两次写库 + 两条审计）
 */
function SettingRow({
  item,
  busy,
  onToggle,
}: {
  item: AppSettingInfo
  busy: boolean
  onToggle: (item: AppSettingInfo, next: boolean) => void
}) {
  const value = !!item.value
  return (
    <label
      className="flex items-start gap-3 py-3"
      style={{
        cursor: item.editable && !busy ? 'pointer' : 'not-allowed',
        opacity: item.editable ? 1 : 0.55,
      }}
    >
      <input
        type="checkbox"
        checked={value}
        disabled={!item.editable || busy}
        onChange={(e) => onToggle(item, e.target.checked)}
        style={{ marginTop: 3, width: 16, height: 16, flexShrink: 0 }}
      />
      <span className="flex-1">
        <span className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold" style={{ fontSize: 13.5 }}>
            {item.label}
          </span>
          <code className="text-text-faint" style={{ fontSize: 11 }}>
            {item.key}
          </code>
          {item.gated && (
            <span
              className="flex items-center gap-1"
              style={{ fontSize: 11, color: 'var(--warn, var(--err))' }}
            >
              <Power size={11} />
              门禁
            </span>
          )}
          {!item.editable && (
            <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>（需要超级管理员）</span>
          )}
        </span>
        {/* ⚠★ `KeySpec` 的 `note` —— ★★ "没有说明的参数是灾难"，★ 所以那句说明必须真的显示出来 */}
        <span className="block text-text-sub mt-1" style={{ fontSize: 12, lineHeight: 1.7 }}>
          {item.note}
        </span>
      </span>
    </label>
  )
}

export default function AdminInvites() {
  const me = useMe()
  const isStaff = !!me.data?.is_staff

  const [maxUses, setMaxUses] = useState('1')
  const [validDays, setValidDays] = useState('7')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  /** ★★ `B172`：生成成功后**弹出自写弹窗**显示链接（❌ 不再 `window.prompt`） */
  const [created, setCreated] = useState<InviteInfo | null>(null)
  /** ★★ `B172`：待二次确认的重锤开关（★ 目前只有 `paused`） */
  const [confirmPaused, setConfirmPaused] = useState<boolean | null>(null)
  /** ★★ `B172` 分页 —— ★ 0 基页码（★ 换成 offset 就是 `page * PAGE_SIZE`） */
  const [page, setPage] = useState(0)

  const invites = useInvites(isStaff, { limit: INVITES_PAGE_SIZE, offset: page * INVITES_PAGE_SIZE })
  const settings = useAdminSettings(isStaff)
  const updateSettings = useUpdateSettings()
  const create = useCreateInvite()
  const revoke = useRevokeInvite()

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      const inv = await create.mutateAsync({
        // ⚠★ 后端限 `max_uses` 1–200 · `valid_days` 1–3650 —— ★ 越界会 400（★ 这里先转数字）
        max_uses: Number(maxUses) || 1,
        valid_days: Number(validDays) || 7,
        note,
      })
      setNote('')
      // ★★ 弹出**自写弹窗**显示链接 —— ★ 这正是 `B172` 第 ④ 条要修的 ✅
      setCreated(inv)
    } catch (e2) {
      setErr(errorMessage(e2, '生成失败，请重试。'))
    }
  }

  /**
   * ★ 改一个开关
   *
   * ⚠★ `paused` 走**二次确认** —— ★ 它是 `gated=True` 的重锤（★ 打开后**所有人**都被拦）⚠
   */
  async function handleToggle(item: AppSettingInfo, next: boolean) {
    setErr('')
    if (item.key === 'paused') {
      setConfirmPaused(next)
      return
    }
    await submitSetting(item.key, next)
  }

  async function submitSetting(key: string, next: boolean) {
    setErr('')
    try {
      await updateSettings.mutateAsync({ [key]: next })
    } catch (e2) {
      setErr(errorMessage(e2, '修改失败，请重试。'))
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

  const list = invites.data?.invites || []
  const total = invites.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / INVITES_PAGE_SIZE))
  // ★ 顺序按后端清单排（★ 后端返回的是 `KEYS` 的声明顺序）——
  //   ⚠ 用 `find` 而不是"按 GATE_KEYS 顺序再排"：★ 这样**后端没给的键不会凭空出现** ✅
  const gateItems = GATE_KEYS.map((k) => settings.data?.settings.find((s) => s.key === k)).filter(
    (s): s is AppSettingInfo => !!s,
  )

  return (
    <AppLayout
      title="管理与邀请"
      crumbs={[{ label: '工作区', to: '/workspace' }, { label: '管理' }]}
      actions={
        <Button
          variant="ghost"
          icon={<Plus size={15} />}
          loading={invites.isFetching}
          onClick={() => {
            invites.refetch()
            settings.refetch()
          }}
        >
          刷新
        </Button>
      }
    >
      {err && <div className="error mb-4">{err}</div>}

      {/* ---------------- ① 注册 / 登录开关（★ `B172`） ---------------- */}
      <div className="card p-5 mb-5">
        <h3 className="m-0" style={{ fontSize: 15 }}>
          注册与登录
        </h3>
        <p className="text-text-sub m-0 mt-1 mb-2" style={{ fontSize: 12.5, lineHeight: 1.7 }}>
          ★ 改一下就会**立刻生效**（★ 后端每次请求都读实时值，❌ 没有缓存）。
          <br />★ 每个开关下面那句话是它**为什么存在** —— ★ 改之前请读一遍。
        </p>

        {settings.isLoading && <p className="text-text-faint m-0 py-3">正在加载参数…</p>}
        {settings.isError && (
          <p className="m-0 py-3" style={{ color: 'var(--err)' }}>
            {errorMessage(settings.error, '参数加载失败。')}
          </p>
        )}

        {gateItems.length > 0 && (
          <div style={{ borderTop: '1px solid var(--card-border)' }}>
            {gateItems.map((item) => (
              <SettingRow
                key={item.key}
                item={item}
                busy={updateSettings.isPending}
                onToggle={handleToggle}
              />
            ))}
          </div>
        )}
      </div>

      {/* ---------------- ② 生成 ---------------- */}
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

          <div className="mt-4">
            <Button type="submit" variant="primary" loading={create.isPending} icon={<Plus size={15} />}>
              生成邀请
            </Button>
          </div>
        </form>
      </div>

      {/* ---------------- ③ 列表（★ `B172` 加分页） ---------------- */}
      <div className="card p-0 overflow-hidden">
        <div className="px-5 py-4 flex items-center justify-between gap-3 flex-wrap" style={{ borderBottom: '1px solid var(--card-border)' }}>
          <h3 className="m-0" style={{ fontSize: 15 }}>
            已发出的邀请（共 {total}）
          </h3>
          {pageCount > 1 && (
            // ★★ `B172` 分页 —— ★ 显示"第几页 / 共几页"，⚠ 而不是让用户自己数
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="icon-btn"
                title="上一页"
                aria-label="上一页"
                disabled={page === 0 || invites.isFetching}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                <ChevronLeft size={14} />
              </button>
              <span className="text-text-sub" style={{ fontSize: 12.5 }}>
                第 {page + 1} / {pageCount} 页
              </span>
              <button
                type="button"
                className="icon-btn"
                title="下一页"
                aria-label="下一页"
                disabled={!invites.data?.has_more || invites.isFetching}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>

        {invites.isLoading && <p className="p-5 text-text-faint m-0">正在加载…</p>}
        {invites.isError && (
          <p className="p-5 m-0" style={{ color: 'var(--err)' }}>
            {errorMessage(invites.error, '加载失败。')}
          </p>
        )}
        {!invites.isLoading && !invites.isError && list.length === 0 && (
          <p className="p-5 text-text-faint m-0">
            {total > 0 && page > 0 ? '这一页没有内容 —— 试试回到上一页。' : '还没有发出过邀请。'}
          </p>
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
                            title="查看 / 复制分享链接"
                            aria-label="分享链接"
                            disabled={!inv.usable}
                            // ★★ `B172`：★ 点它**打开自写弹窗**（❌ 不再直接复制 + 失败弹 prompt）✅
                            onClick={() => setCreated(inv)}
                          >
                            <LinkIcon size={13} />
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

      {/* ---------- ★★ `B172`：分享链接弹窗（★ 自写，❌ 不是浏览器 prompt） ---------- */}
      <Modal
        open={!!created}
        title="邀请链接已生成"
        onClose={() => setCreated(null)}
        footer={
          <Button variant="primary" onClick={() => setCreated(null)}>
            好了
          </Button>
        }
      >
        {created && (
          <>
            <p className="text-text-sub m-0 mb-3" style={{ fontSize: 12.5, lineHeight: 1.8 }}>
              ★ 把下面这条链接发给对方，★ 他打开就能注册。
              <br />⚠★ 生成时**有效期必须 &gt; 0** —— ★ 这是 `U4.7` 规则 2（「否则泄露了就永久有效」）。
            </p>
            <CopyField
              label="分享链接"
              value={shareUrl(created.token)}
              hint={`★ 可用 ${created.max_uses} 次 · ★ 到期 ${fmtDate(created.expires_at)}${
                created.note ? ` · ★ 备注：${created.note}` : ''
              }`}
            />
          </>
        )}
      </Modal>

      {/* ---------- ★★ `B172`：重锤开关的二次确认（★ `paused`） ---------- */}
      <ConfirmDialog
        open={confirmPaused !== null}
        title={confirmPaused ? '确认「整站停服」？' : '确认恢复服务？'}
        message={
          confirmPaused
            ? '★ 打开后【所有人】（含已登录）都会被拦 —— ★ 这是重锤，不要当普通开关用。\n\n★ 确定要停服吗？'
            : '★ 恢复后所有人可以正常访问。\n\n★ 确定恢复吗？'
        }
        confirmText={confirmPaused ? '停服' : '恢复'}
        // ★★ 停服是**破坏性动作** ⇒ ★★ 按钮用红色（★ `danger`）—— ⚠ 让"确认"这一步真的有分量
        danger={confirmPaused === true}
        onCancel={() => setConfirmPaused(null)}
        onConfirm={async () => {
          const next = confirmPaused
          setConfirmPaused(null)
          if (next !== null) await submitSetting('paused', next)
        }}
      />
    </AppLayout>
  )
}
