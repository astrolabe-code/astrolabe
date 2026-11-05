import { useParams } from 'react-router-dom'

import AppLayout from '../components/AppLayout'
import PersonalProjectSettings from '../components/settings/PersonalProjectSettings'

/**
 * ★★ 个人版「项目设置」
 *
 * 网页版有可见性、许可证、协作者；个人版只有你一个人 ⇒ 换成「事实 + 危险操作」那一版。
 */
export default function ProjectSettingsPage() {
  const { projectRef = '' } = useParams<{ projectRef: string }>()

  return (
    <AppLayout title="项目设置">
      <PersonalProjectSettings projectRef={projectRef} />
    </AppLayout>
  )
}
