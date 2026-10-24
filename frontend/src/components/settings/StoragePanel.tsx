import { useQuery } from '@tanstack/react-query'
import { apiGet } from '../../api/client'
import { errorMessage, unwrap } from '../../api/errors'

/**
 * ★★ **存储与配额**（设置页分类之一 · 2026-10-24）⚠
 *
 * ```\n * GET /api/me/storage/ ⇒ 已用 / 上限 / 剩余 / 占比 / 单项目上限 / 各项目占用\n * ```
 *
 * ⚠ 数据来自后端的存储记账（* 不是扫描磁盘），* 删项目后会同步释放 ✅
 */
interface StorageData {
  ok: boolean
  reason_code: string
  message: string
  limit_bytes: number
  used_bytes: number
  remaining_bytes: number
  limit_files: number
  used_files: number
  used_ratio: number
  source: string
  repo_bytes_max: number
  repo_files_max: number
  projects: { project_ref?: string; name?: string; bytes?: number }[]
}

function fmtBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v >= 10 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`
}

export default function StoragePanel() {
  const q = useQuery({
    queryKey: ['my-storage'],
    queryFn: async (): Promise<StorageData> =>
      unwrap(await apiGet<StorageData>('/api/me/storage/', 'data')),
  })

  if (q.isLoading) return <div className="faint" style={{ fontSize: 12.5 }}>加载中…</div>
  if (q.isError || !q.data) {
    return (
      <div className="card" style={{ padding: 16 }}>
        <div className="faint" style={{ fontSize: 12.5 }}>{errorMessage(q.error)}</div>
      </div>
    )
  }

  const d = q.data
  const pct = Math.max(0, Math.min(100, Math.round((d.used_ratio || 0) * 100)))

  return (
    <div className="flex flex-col gap-3">
      <div className="card" style={{ padding: '16px 18px' }}>
        <div className="flex items-center gap-2" style={{ marginBottom: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 650 }}>空间用量</span>
          <span className="tag" style={{ fontSize: 10.5 }}>
            {d.source === 'vip' ? 'VIP' : d.source === 'user' ? '单独配额' : '普通用户'}
          </span>
          <span className="faint" style={{ fontSize: 11.5, marginLeft: 'auto' }}>
            {fmtBytes(d.used_bytes)} / {fmtBytes(d.limit_bytes)}
          </span>
        </div>

        <div
          style={{
            height: 8,
            borderRadius: 999,
            background: 'var(--bg-deep)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: '100%',
              background: pct >= 90 ? 'var(--err)' : 'var(--accent)',
              transition: 'width .2s',
            }}
          />
        </div>

        <div className="faint" style={{ fontSize: 11.5, marginTop: 8 }}>
          已用 {pct}% · 剩余 {fmtBytes(d.remaining_bytes)} · 文件{' '}
          {d.used_files.toLocaleString()} / {d.limit_files.toLocaleString()}
        </div>
      </div>

      <div className="card" style={{ padding: '16px 18px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>单个项目上限</div>
        <div className="faint" style={{ fontSize: 12 }}>
          {fmtBytes(d.repo_bytes_max)} · {d.repo_files_max.toLocaleString()} 个文件
        </div>
        <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
          ⚠ 超过上限时解析会被中止，已写入的内容会被清掉（不会留半个仓库）
        </div>
      </div>

      {d.projects.length > 0 && (
        <div className="card" style={{ padding: '16px 18px' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>各项目占用</div>
          <div className="flex flex-col gap-1.5">
            {d.projects.map((p) => (
              <div
                key={p.project_ref || p.name || ''}
                className="flex items-center"
                style={{ fontSize: 12 }}
              >
                <span>{p.name || p.project_ref || '（未知）'}</span>
                <span className="faint" style={{ marginLeft: 'auto' }}>
                  {fmtBytes(p.bytes || 0)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
