import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  HardDrive,
  LogOut,
  Settings as SettingsIcon,
  SlidersHorizontal,
  Trash2,
  User,
} from 'lucide-react'
import { errorMessage } from '../api/errors'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import SettingsForm from '../components/settings/SettingsForm'
import StoragePanel from '../components/settings/StoragePanel'
import ProfileForm from '../components/profile/ProfileForm'
import { usePatchUserSettings, useUserSettings } from '../query/settings'
import { useLogout } from '../query/auth'
import { IS_PERSONAL } from '../lib/personal'
import PersonalUserSettings from '../components/settings/PersonalUserSettings'

/**
 * ★★ **我的设置**（参考 B 站 · 2026-10-24）⚠
 *
 * ## ★★★ 所有者原话（逐字）
 *
 * > 「我的设置也类似B站，点击我的空间里的头像，就可以进入设置页。
 * >   设置页的设置功能要分类。左边是分类栏，点击后，右边出现相应设置条目。」
 *
 * ## ★ 布局
 *
 * ```\n * 左：分类栏（个人资料 / 图谱外观 / 存储 / 账号）\n * 右：该分类的设置条目 —— 切换分类**不重新拉数据**（各自的 query 自己缓存）✅\n * 窄屏：分类栏变成一行可横滑的标签 ✅\n * ```
 */
type Cat = 'profile' | 'graph' | 'storage' | 'account'

const CATS: { key: Cat; label: string; icon: typeof User }[] = [
  { key: 'profile', label: '个人资料', icon: User },
  { key: 'graph', label: '图谱外观', icon: SlidersHorizontal },
  { key: 'storage', label: '存储', icon: HardDrive },
  { key: 'account', label: '账号', icon: SettingsIcon },
]

export default function UserSettingsPage() {
  // ★★★ 个人版：没有资料/外观/存储/账号 ⇒ 只显示「关于 + 数据在哪」⚠
  if (IS_PERSONAL) {
    return (
      <AppLayout title="设置">
        <PersonalUserSettings />
      </AppLayout>
    )
  }

  const [cat, setCat] = useState<Cat>('profile')
  const settings = useUserSettings()
  const patch = usePatchUserSettings()
  const me = useMe()
  const logout = useLogout()
  const navigate = useNavigate()
  const [err, setErr] = useState('')

  const save = async (body: Record<string, unknown>) => {
    setErr('')
    try {
      await patch.mutateAsync(body)
    } catch (e) {
      const rejected = (e as { data?: { rejected?: Record<string, string> } })?.data?.rejected
      if (rejected && Object.keys(rejected).length > 0) {
        setErr(
          `这些设置没被接受：${Object.entries(rejected)
            .map(([k, v]) => `${k}（${v}）`)
            .join('；')}`,
        )
      } else {
        setErr(errorMessage(e))
      }
    }
  }

  const handleLogout = async () => {
    await logout.mutateAsync().catch(() => undefined)
    navigate('/', { replace: true })
  }

  return (
    <AppLayout title="我的设置">
      <div className="settings-layout">
        {/* ---- 左：分类栏 ---- */}
        <aside className="settings-nav card">
          {CATS.map((c) => {
            const Icon = c.icon
            const active = cat === c.key
            return (
              <button
                key={c.key}
                type="button"
                onClick={() => setCat(c.key)}
                className={`settings-nav-item${active ? ' active' : ''}`}
              >
                <Icon size={14} />
                {c.label}
              </button>
            )
          })}
        </aside>

        {/* ---- 右：内容 ---- */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {cat === 'profile' && <ProfileForm />}

          {cat === 'graph' &&
            (settings.isError ? (
              <div className="card" style={{ padding: 20 }}>
                <div className="faint" style={{ fontSize: 12.5 }}>
                  {errorMessage(settings.error)}
                </div>
              </div>
            ) : settings.isLoading || !settings.data ? (
              <div className="faint" style={{ fontSize: 13 }}>
                加载中…
              </div>
            ) : (
              <>
                <div className="faint" style={{ fontSize: 12.5, marginBottom: 12 }}>
                  你的默认参数。项目档可以覆盖它们；标着「门禁项」的只有站点管理员能改。
                </div>
                <SettingsForm
                  data={settings.data}
                  saving={patch.isPending}
                  error={err}
                  isAdmin={!!me.data?.is_staff}
                  onSave={save}
                />
              </>
            ))}

          {cat === 'storage' && <StoragePanel />}

          {cat === 'account' && (
            <div className="card" style={{ padding: '16px 18px' }}>
              <div style={{ fontSize: 14, fontWeight: 650, marginBottom: 4 }}>账号</div>
              <div className="faint" style={{ fontSize: 12, marginBottom: 14 }}>
                当前登录：@{me.data?.username || ''}
              </div>

              <div className="flex flex-col gap-2" style={{ alignItems: 'flex-start' }}>
                <Link to="/me" style={{ width: '100%' }}>
                  <Button style={{ width: '100%', justifyContent: 'flex-start' }}>
                    我的空间
                  </Button>
                </Link>
                <Link to="/me/deleted" style={{ width: '100%' }}>
                  <Button
                    icon={<Trash2 size={13} />}
                    style={{ width: '100%', justifyContent: 'flex-start' }}
                  >
                    回收站（已删除的笔记）
                  </Button>
                </Link>
                <Button
                  variant="danger"
                  icon={<LogOut size={13} />}
                  onClick={handleLogout}
                  style={{ width: '100%', justifyContent: 'flex-start' }}
                >
                  退出登录
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  )
}
