import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

import AppLayout from '../components/AppLayout'
import { PageBar, RailButton } from '../components/PageBar'
import PersonalUserSettings from '../components/settings/PersonalUserSettings'
import PersonalProjectSettings from '../components/settings/PersonalProjectSettings'
import { personalApi } from '../api/personal'

/**
 * ★★★ **个人版唯一的「设置」页面**（2026-11-06）
 *
 * 所有者：「点设置，只会出现项目设置页面，没有用户设置。
 *          你应该把两个设置都导入一个设置页面。」
 *
 * ```
 * 上半 = 全局设置：关于 / 笔记在哪 / 外观（流星·代码字号·代码字体）/ 账号
 * 下半 = 项目设置：读了哪个目录 / 笔记位置 / 图状态 / 重新解析 / 删除
 * ```
 *
 * ⚠ 两条路由都渲染这一页：
 * ```
 * /p/:projectRef/settings   ← 项目页顶栏「设置」（ref 直接来自路由）
 * /me/settings              ← 首页 / 工具菜单「设置」
 * ```
 *    从 `/me/settings` 进来没有项目上下文 ⇒ 取清单里的第一个项目，
 *    并在标题上写明是哪个项目（要换项目，去对应项目页点「设置」即可）。
 */
export default function SettingsPage() {
  const { projectRef: fromPath = '' } = useParams<{ projectRef: string }>()
  const [params] = useSearchParams()
  const projectFromQuery = params.get('project') || ''
  const navigate = useNavigate()
  const [fallback, setFallback] = useState<{ ref: string; name: string } | null>(null)

  useEffect(() => {
    if (fromPath || projectFromQuery) return
    let alive = true
    personalApi
      .listProjects()
      .then((d) => {
        const first = d.items?.[0]
        if (alive && first?.ref) {
          setFallback({ ref: String(first.ref), name: String(first.name || first.ref) })
        }
      })
      .catch(() => {
        /* 清单拿不到就显示空态，不报错 */
      })
    return () => {
      alive = false
    }
  }, [fromPath, projectFromQuery])

  const ref = fromPath || projectFromQuery || fallback?.ref || ''

  return (
    <AppLayout title="设置">
      <PageBar>
        <RailButton
          icon={<ArrowLeft size={13} />}
          label={fromPath ? '项目' : '首页'}
          title={fromPath ? '回到项目页' : '回到首页'}
          onClick={() => navigate(fromPath ? `/p/${encodeURIComponent(fromPath)}` : '/')}
        />
      </PageBar>

      {/* ① 全局设置（个人 / 外观 / 数据） */}
      <PersonalUserSettings />

      {/* ② 项目设置（目录 / 笔记位置 / 图状态 / 重新解析 / 删除） */}
      <div style={{ marginTop: 16, marginBottom: 8, fontSize: 13.5, fontWeight: 600 }}>
        项目设置{fallback?.name ? ` · ${fallback.name}` : ''}
      </div>
      {ref ? (
        <PersonalProjectSettings key={ref} projectRef={ref} />
      ) : (
        <div className="card faint" style={{ padding: 20, fontSize: 12.5 }}>
          还没有项目。回到首页添加一个目录后，这里会显示项目设置。
        </div>
      )}
    </AppLayout>
  )
}
