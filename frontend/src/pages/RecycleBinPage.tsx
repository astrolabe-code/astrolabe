import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  Download,
  FolderOpen,
  Loader2,
  RotateCcw,
  Upload,
} from 'lucide-react'
import type { DeletedNote, ImportResult } from '../api/types'
import { errorMessage } from '../api/errors'
import {
  downloadNotesBackup,
  groupByProject,
  useDeletedNotes,
  useImportNotes,
  useUndeleteNote,
} from '../query/notes'
import { useMe } from '../hooks/useMe'
import AppLayout from '../components/AppLayout'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'

/**
 * ★ 回收站（`F4` · D96 · `B231` / D103 · 契约 §22.7）
 *
 * ## ★★ `D103` 起改成【按项目组织】
 *
 * ```
 * ★★ 一个项目一张卡片：* 项目名 · ref · 版本 · 笔记数 · 删除时间 ✅
 * ★★ 点卡片 ⇒* 展开该项目的被删笔记（* 每篇带勾选框）✅
 * ★★ 「导出所选」⇒* 下载一个 `.astrolabe-backup`（* `B231`：* 一篇一个 .md
 *   + manifest；* `B232`：* 带签名，* 改一个位也验不过）✅
 * ★★ 「导入恢复」⇒* 选文件 + 目标项目 ⇒* 按 `node.vid` 挂回（* `B231`）✅
 * ```
 *
 * ⚠★ 管理员下架的内容**不在这里**（那是物理删，不可恢复）。
 */
export default function RecycleBinPage() {
  const me = useMe()
  const authed = !!me.data?.authenticated
  const deleted = useDeletedNotes({ limit: 200 })
  const undelete = useUndeleteNote()
  const importNotes = useImportNotes()

  const [openKey, setOpenKey] = useState<string | null>(null)
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [msg, setMsg] = useState<{ text: string; ref?: string } | null>(null)
  const [err, setErr] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [importTarget, setImportTarget] = useState('')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)

  const groups = useMemo(() => groupByProject(deleted.data?.items || []), [deleted.data])

  const toggle = (id: number) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleGroup = (notes: DeletedNote[]) => {
    setChecked((prev) => {
      const next = new Set(prev)
      const all = notes.every((n) => next.has(n.id))
      for (const n of notes) {
        if (all) next.delete(n.id)
        else next.add(n.id)
      }
      return next
    })
  }

  const restore = async (n: DeletedNote) => {
    setErr('')
    setMsg(null)
    try {
      await undelete.mutateAsync(n.id)
      setMsg({ text: `已恢复「${n.title || '（无标题）'}」`, ref: n.project_ref })
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  const doExport = async () => {
    if (checked.size === 0) return
    setErr('')
    setMsg(null)
    try {
      await downloadNotesBackup([...checked])
      setMsg({ text: `已导出 ${checked.size} 篇笔记（备份文件带签名，改动即失效）` })
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  const doImport = async () => {
    if (!importFile || !importTarget.trim()) return
    setErr('')
    setMsg(null)
    setImportResult(null)
    try {
      const r = await importNotes.mutateAsync({ file: importFile, projectRef: importTarget.trim() })
      setImportResult(r)
      setImportOpen(false)
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  if (!authed) {
    return (
      <AppLayout title="回收站">
        <div className="card" style={{ padding: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 14 }}>登录后可以查看你的回收站</div>
          <div className="mt-4">
            <Link to="/login">
              <Button variant="primary">去登录</Button>
            </Link>
          </div>
        </div>
      </AppLayout>
    )
  }

  return (
    <AppLayout title="回收站" crumbs={[{ label: '工作区', to: '/workspace' }, { label: '回收站' }]}>
      <div className="flex items-center gap-2 flex-wrap" style={{ marginBottom: 14 }}>
        <div className="faint" style={{ fontSize: 12.5, flex: 1, minWidth: 260 }}>
          被删的笔记按项目归在这里 —— 可恢复、可整份导出备份。⚠ 管理员下架的内容不在这里（彻底删除，不可恢复）。
        </div>
        <Button icon={<Upload size={14} />} onClick={() => setImportOpen((v) => !v)}>
          导入恢复
        </Button>
        <Button
          variant="primary"
          icon={<Download size={14} />}
          disabled={checked.size === 0}
          onClick={doExport}
        >
          导出所选{checked.size > 0 ? `（${checked.size}）` : ''}
        </Button>
      </div>

      {importOpen && (
        <div className="card" style={{ padding: 14, marginBottom: 12 }}>
          <div style={{ fontSize: 12.5, marginBottom: 8 }}>
            选择 <code>.astrolabe-backup</code> 备份文件与要恢复到的项目（笔记会按文件头记录的
            <code> node.vid </code>挂回该项目的节点；挂不上的仍会导入，但会提示）：
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <input
              className="input"
              placeholder="目标项目 ref（proj_…）"
              value={importTarget}
              onChange={(e) => setImportTarget(e.target.value)}
              style={{ flex: 1, minWidth: 220, fontSize: 12.5 }}
            />
            <input
              type="file"
              accept=".backup,.astrolabe-backup,application/octet-stream"
              onChange={(e) => setImportFile(e.target.files?.[0] || null)}
              style={{ fontSize: 12 }}
            />
            <Button
              variant="primary"
              disabled={!importFile || !importTarget.trim() || importNotes.isPending}
              onClick={doImport}
            >
              {importNotes.isPending ? '导入中…' : '开始导入'}
            </Button>
          </div>
        </div>
      )}

      {msg && (
        <div className="card" style={{ padding: '10px 14px', marginBottom: 12, borderColor: 'var(--ok)' }}>
          <div style={{ fontSize: 12.5 }}>
            {msg.text}
            {msg.ref && (
              <Link to={`/p/${encodeURIComponent(msg.ref)}`} style={{ marginLeft: 8 }}>
                去项目
              </Link>
            )}
          </div>
        </div>
      )}
      {importResult && (
        <div className="card" style={{ padding: '10px 14px', marginBottom: 12, borderColor: 'var(--ok)' }}>
          <div style={{ fontSize: 12.5 }}>
            {importResult.message}
            {importResult.unanchored_count > 0 && (
              <span style={{ marginLeft: 8, color: 'var(--warn)' }}>
                {importResult.unanchored.map((u) => u.title || u.file).join('、')} —— 没能挂回原节点
              </span>
            )}
          </div>
        </div>
      )}
      {err && (
        <div className="text-xs mb-3" style={{ color: 'var(--err)' }}>
          {err}
        </div>
      )}

      {deleted.isLoading ? (
        <div className="faint" style={{ fontSize: 13 }}>加载中…</div>
      ) : groups.length === 0 ? (
        <EmptyState
          title="回收站是空的"
          hint="删掉的笔记会先来这里，随时可以恢复或导出备份"
          icon={<ArchiveRestore size={28} />}
        />
      ) : (
        <div className="flex flex-col gap-3">
          {groups.map((g) => {
            const key = g.project_ref
            const open = openKey === key
            const allChecked = g.notes.every((n) => checked.has(n.id))
            const checkedInGroup = g.notes.filter((n) => checked.has(n.id)).length
            return (
              <div key={key} className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <div className="flex items-center gap-2" style={{ padding: '10px 12px' }}>
                  <button
                    type="button"
                    className="flex items-center gap-2"
                    style={{ flex: 1, textAlign: 'left', cursor: 'pointer', background: 'none', border: 'none' }}
                    onClick={() => setOpenKey(open ? null : key)}
                  >
                    {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <FolderOpen size={14} />
                    <span style={{ fontSize: 13.5, fontWeight: 500 }}>
                      {g.project_name || '（项目已删）'}
                    </span>
                    <span className="faint" style={{ fontSize: 11 }}>
                      {g.notes.length} 篇
                    </span>
                    {g.version_label && (
                      <span className="tag" style={{ fontSize: 10.5 }} title="这份笔记属于哪个代码版本">
                        {g.version_label}
                      </span>
                    )}
                  </button>
                  {g.project_ref && (
                    <Link to={`/p/${encodeURIComponent(g.project_ref)}`} className="faint" style={{ fontSize: 11.5 }}>
                      去项目
                    </Link>
                  )}
                  <button
                    type="button"
                    className="faint"
                    style={{ fontSize: 11.5, cursor: 'pointer', background: 'none', border: 'none' }}
                    onClick={() => toggleGroup(g.notes)}
                  >
                    {allChecked ? '取消全选' : `全选${checkedInGroup > 0 ? `（已选 ${checkedInGroup}）` : ''}`}
                  </button>
                </div>

                {open && (
                  <div style={{ borderTop: '1px solid var(--line)' }}>
                    {g.notes.map((n) => (
                      <div
                        key={n.id}
                        className="flex items-center gap-2 flex-wrap"
                        style={{ padding: '8px 12px', borderBottom: '1px solid var(--line)' }}
                      >
                        <input type="checkbox" checked={checked.has(n.id)} onChange={() => toggle(n.id)} />
                        <span style={{ fontSize: 13 }}>{n.title || '（无标题）'}</span>
                        <span className="tag" style={{ fontSize: 10.5 }}>{n.kind}</span>
                        <span className="faint" style={{ fontSize: 11 }}>
                          被 {n.deleted_by || '未知用户'} 删除 · {n.deleted_at?.replace('T', ' ').slice(0, 16)}
                        </span>
                        <button
                          type="button"
                          className="flex items-center gap-1"
                          style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--accent)', cursor: 'pointer' }}
                          disabled={undelete.isPending}
                          onClick={() => restore(n)}
                        >
                          {undelete.isPending ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                          恢复
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </AppLayout>
  )
}
