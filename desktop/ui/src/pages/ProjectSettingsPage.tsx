import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

import AppLayout from '../components/AppLayout'
import { PageBar, RailButton } from '../components/PageBar'
import PersonalProjectSettings from '../components/settings/PersonalProjectSettings'

/**
 * ★★ 个人版「项目设置」
 *
 * 网页版有可见性、许可证、协作者；个人版只有你一个人 ⇒ 换成「事实 + 危险操作」那一版。
 */
export default function ProjectSettingsPage() {
  const { projectRef = '' } = useParams<{ projectRef: string }>()
  const navigate = useNavigate()

  return (
    <AppLayout title="项目设置">
      {/* ★★★ 顶栏工具条（公共组件 PageBar）⚠ */}
      <PageBar>
        <RailButton
          icon={<ArrowLeft size={13} />}
          label="项目"
          title="回到项目页"
          onClick={() => navigate(`/p/${encodeURIComponent(projectRef)}`)}
        />
      </PageBar>

      <PersonalProjectSettings projectRef={projectRef} />
    </AppLayout>
  )
}
