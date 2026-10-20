import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { errorMessage } from '../api/errors'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import SettingsForm from '../components/settings/SettingsForm'
import CollaboratorSection from '../components/settings/CollaboratorSection'
import { useProject } from '../query/projects'
import {
  usePatchProjectSettings,
  useProjectSettings,
} from '../query/settings'

/**
 * ★ 项目设置页（`F2` · D92）——* `/p/:projectRef/settings`
 *
 * ## 谁能进
 *
 * ★★ `can_edit`（* owner ∨ 协作者，* 后端判）⚠
 *   · · ★ 非成员 ⇒* 后端 403 ⇒* 照实显示（* 文案不泄露项目存在性）✅
 *
 * ⚠★ PATCH 体是**扁平的** `{键:值}`（契约 §22.1）；整件 400 ⇒ 显示被拒的键 ✅
 */
export default function ProjectSettingsPage() {
  const { projectRef = '' } = useParams<{ projectRef: string }>()
  const settings = useProjectSettings(projectRef)
  const project = useProject(projectRef)
  const patch = usePatchProjectSettings(projectRef)
  const [err, setErr] = useState('')

  const save = async (body: Record<string, unknown>) => {
    setErr('')
    try {
      await patch.mutateAsync(body)
    } catch (e) {
      // ⚠★ 整件 400：后端带 `applied` / `rejected`（ApiRequestError.data）——
      //   ★ 原样告诉用户哪几个键没被接受，⛔ 不做部分应用的假象 ✅
      const rejected = (e as { data?: { rejected?: Record<string, string> } })?.data?.rejected
      if (rejected && Object.keys(rejected).length > 0) {
        setErr(`这些设置没被接受：${Object.entries(rejected).map(([k, v]) => `${k}（${v}）`).join('；')}`)
      } else {
        setErr(errorMessage(e))
      }
    }
  }

  return (
    <AppLayout
      title="项目设置"
    >
      {settings.isError ? (
        <div className="card" style={{ padding: 24 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>打不开设置</div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
            {errorMessage(settings.error)}
          </div>
        </div>
      ) : settings.isLoading || !settings.data ? (
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      ) : (
        <>
          <div className="faint" style={{ fontSize: 12.5, marginBottom: 14 }}>
            这些是这个项目的运行参数。每项右上角标着它**为什么是这个值**（默认值 / 全局 / 项目）。
          </div>
          <SettingsForm data={settings.data} saving={patch.isPending} error={err} onSave={save} />
          {/* ★★ `F4`：协作者区块 ——* 只在 owner/staff（`can_manage`）时渲染 ⚠
              · · ⚠ 协作者**不能**加 / 移协作者（`B207`②）✅ */}
          {project.data?.can_manage && <CollaboratorSection projectRef={projectRef} />}
        </>
      )}

      <div className="mt-6">
        <Link to={`/p/${encodeURIComponent(projectRef)}`}>
          <Button>回项目</Button>
        </Link>
      </div>
    </AppLayout>
  )
}
