import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

import AppLayout from '../components/AppLayout'
import { PageBar, RailButton } from '../components/PageBar'
import PersonalUserSettings from '../components/settings/PersonalUserSettings'

/**
 * ★★ 个人版「设置」
 *
 * 与网页版的区别不是"隐藏几个模块"，而是**根本没有那些模块**：
 * 没有资料/外观/存储/账号，只有「关于 + 数据在哪」。
 */
export default function UserSettingsPage() {
  const navigate = useNavigate()

  return (
    <AppLayout title="设置">
      {/* ★★★ 顶栏工具条（公共组件 PageBar）⚠ */}
      <PageBar>
        <RailButton
          icon={<ArrowLeft size={13} />}
          label="首页"
          title="回到首页"
          onClick={() => navigate('/')}
        />
      </PageBar>

      <PersonalUserSettings />
    </AppLayout>
  )
}
