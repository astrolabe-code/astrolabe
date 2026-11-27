/**
 * ★★★ **失锚笔记**（扫描 + 手工重挂）⚠
 *
 * ## 为什么需要它
 *
 * 节点被删掉、或重新解析后 vid 变了，笔记的 `node_vid` 就可能指向一个
 * 已经不存在（或名字对不上）的节点 —— 这种笔记叫「失锚」。
 *
 * ⚠ 系统只会在解析时按 (kind, file, name) 尽力重挂一次，**剩下的不该靠猜**：
 *   自动挂错比不挂更糟（用户会以为挂对了）。所以这里把**所有失锚的都列出来**，
 *   由用户一条条选节点重挂。
 *
 * ## 数据来源
 *
 * `GET /api/projects/<ref>/notes/orphans/`
 *   ⇒ `{ items: [{ref, title, kind, node_vid, orphan_reason}], total }`
 *
 * `orphan_reason` 有两种：`未挂到任何节点`、`原来挂的节点已不存在`。
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Anchor, ChevronDown, ChevronRight } from 'lucide-react'

import AnchorPicker from '../notes/AnchorPicker'
import { apiGet } from '../../api/client'
import { unwrap } from '../../api/errors'
import { personalApi } from '../../api/personal'

interface OrphanNote {
  ref: string
  title: string
  kind: string
  node_vid: number
  orphan_reason: string
}

interface OrphanData {
  items: OrphanNote[]
  total: number
}

function useOrphanNotes(projectRef: string) {
  return useQuery({
    queryKey: ['orphan-notes', projectRef],
    enabled: !!projectRef,
    queryFn: async (): Promise<OrphanData> =>
      unwrap(
        await apiGet<OrphanData>(
          `/api/projects/${encodeURIComponent(projectRef)}/notes/orphans/`,
          'data',
        ),
      ),
  })
}

export default function OrphanNotes({ projectRef }: { projectRef: string }) {
  const q = useOrphanNotes(projectRef)
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [picking, setPicking] = useState<OrphanNote | null>(null)

  const data = q.data
  // ★ 没有失锚笔记就整块不出现（不占版面、也不制造焦虑）
  if (!data || !data.total) return null

  const remount = async (vid: number) => {
    if (!picking) return
    try {
      await personalApi.updateNote(picking.ref, { node_id: vid })
      setPicking(null)
      // 重挂成功后：孤儿列表、笔记列表、写作进度都要刷新
      void qc.invalidateQueries({ queryKey: ['orphan-notes', projectRef] })
      void qc.invalidateQueries({ queryKey: ['notes'] })
      void qc.invalidateQueries({ queryKey: ['writing-progress', projectRef] })
    } catch {
      /* 失败就保持面板打开，用户可以直接再选一次 */
    }
  }

  return (
    <div className="orphan-card">
      <button type="button" className="wp-head" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <AlertTriangle size={12} style={{ color: '#b45309' }} />
        失锚笔记
        <span className="faint">{data.total} 篇</span>
      </button>

      {open && (
        <div className="orphan-body">
          <div className="orphan-hint faint">
            这些笔记原来挂的节点不在了（或从来没挂上）。选一个节点重新挂上。
          </div>
          {data.items.map((n) => (
            <div key={n.ref} className="orphan-row">
              <span className="orphan-title" title={n.title || n.ref}>
                {n.title || n.ref}
              </span>
              <span className="orphan-why faint">{n.orphan_reason}</span>
              <button
                type="button"
                className="orphan-fix"
                title="选一个节点重新挂载"
                onClick={() => setPicking(n)}
              >
                <Anchor size={10} /> 重挂
              </button>
            </div>
          ))}
        </div>
      )}

      {picking && (
        <AnchorPicker
          open
          projectRef={projectRef}
          currentVid={picking.node_vid || undefined}
          onClose={() => setPicking(null)}
          onPick={(vid) => void remount(vid)}
        />
      )}
    </div>
  )
}
