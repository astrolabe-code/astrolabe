import { useState } from 'react'
import { Link } from 'react-router-dom'
import { errorMessage } from '../api/errors'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import SettingsForm from '../components/settings/SettingsForm'
import ProfileForm from '../components/profile/ProfileForm'
import { usePatchUserSettings, useUserSettings } from '../query/settings'

/**
 * ★ 用户设置页（`F2` · D92）——* `/me/settings`
 *
 * ★ 与项目设置页**同构**（同一 `SettingsForm`）——* ❌ 不抄两份表单 ⚠
 * ⚠★ 门禁项（`gated`，如历史版本数 / 存档间隔）**只有管理员能改**（`B190③`）✅
 */
export default function UserSettingsPage() {
  const settings = useUserSettings()
  const patch = usePatchUserSettings()
  const me = useMe()
  const [err, setErr] = useState('')

  const save = async (body: Record<string, unknown>) => {
    setErr('')
    try {
      await patch.mutateAsync(body)
    } catch (e) {
      const rejected = (e as { data?: { rejected?: Record<string, string> } })?.data?.rejected
      if (rejected && Object.keys(rejected).length > 0) {
        setErr(`这些设置没被接受：${Object.entries(rejected).map(([k, v]) => `${k}（${v}）`).join('；')}`)
      } else {
        setErr(errorMessage(e))
      }
    }
  }

  return (
    <AppLayout title="我的设置">
      {settings.isError ? (
        <div className="card" style={{ padding: 24 }}>
          <div className="faint" style={{ fontSize: 12.5 }}>
            {errorMessage(settings.error)}
          </div>
        </div>
      ) : settings.isLoading || !settings.data ? (
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      ) : (
        <>
          {/* ★ 个人资料（昵称 / 签名）—— 用户空间头部显示的就是它 ⚠ */}
          <ProfileForm />

          <div className="faint" style={{ fontSize: 12.5, marginBottom: 14 }}>
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
      )}

      <div className="mt-6">
        <Link to="/workspace">
          <Button>回工作区</Button>
        </Link>
      </div>
    </AppLayout>
  )
}
