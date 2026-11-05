import AppLayout from '../components/AppLayout'
import PersonalUserSettings from '../components/settings/PersonalUserSettings'

/**
 * ★★ 个人版「设置」
 *
 * 与网页版的区别不是"隐藏几个模块"，而是**根本没有那些模块**：
 * 没有资料/外观/存储/账号，只有「关于 + 数据在哪」。
 */
export default function UserSettingsPage() {
  return (
    <AppLayout title="设置">
      <PersonalUserSettings />
    </AppLayout>
  )
}
