import { CalendarDays, MessageSquare, Pencil, ThumbsUp } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { UserSpaceData } from '../../api/types'
import Button from '../ui/Button'

/**
 * ★★ **用户空间头部**（参考 B 站个人空间 · 2026-10-24）⚠
 *
 * ```\n * 渐变头图（★ 用站点 `--accent` 调色 —— ⛔ 不按用户名随机取色，* 那样会飘到品红/橙，和站点撞色）\n * 圆形头像（昵称首字 + 同色系）\n * 昵称 / @username / 加入时间 / 一句话签名\n * 四个数字：项目 · 笔记 · 获赞 · 评论\n * 本人可见「编辑资料」\n * ```
 *
 * ⚠ 关注/粉丝**暂不做**（所有者：「等我把项目完善一点了，再加上」）⚠
 */
function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex flex-col items-center" style={{ minWidth: 56 }}>
      <span style={{ fontSize: 16, fontWeight: 650, lineHeight: 1.2 }}>{value}</span>
      <span className="faint" style={{ fontSize: 11 }}>
        {label}
      </span>
    </div>
  )
}

export default function ProfileHeader({ data }: { data: UserSpaceData }) {
  const initial = (data.display_name || data.username).trim().slice(0, 1).toUpperCase()
  const joined = data.joined_at ? data.joined_at.slice(0, 7).replace('-', ' 年 ') + ' 月' : ''
  const privateNotes = data.is_self ? (data.stats.notes_all ?? 0) - data.stats.notes : 0

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* ① 渐变头图 */}
      <div
        style={{
          height: 92,
          // ★★ 只用站点主色的"淡色叠加"：浅色主题是青蓝洗，深色是同一族的微光
          //   · · 两端都混入 `--card` ⇒ 自动跟随主题，⛔ 不再是写死的颜色 ⚠
          background:
            'linear-gradient(120deg, color-mix(in srgb, var(--accent) 26%, var(--card)), color-mix(in srgb, var(--accent) 6%, var(--card)))',
          borderBottom: '1px solid var(--card-border)',
        }}
      />

      {/* ② 资料区 */}
      <div style={{ padding: '0 20px 16px' }}>
        <div className="flex items-end gap-3" style={{ marginTop: -30 }}>
          <div
            aria-hidden
            style={{
              width: 66,
              height: 66,
              borderRadius: '50%',
              // ★ 底色用 --accent，字色用 --card：浅色=白字、深色=深字，两边都够对比 ⚠
              background: 'var(--accent)',
              color: 'var(--card)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 26,
              fontWeight: 650,
              border: '3px solid var(--card)',
              flex: 'none',
            }}
          >
            {initial}
          </div>

          <div style={{ paddingBottom: 2, minWidth: 0 }}>
            <div className="flex items-center gap-2 flex-wrap">
              <span style={{ fontSize: 18, fontWeight: 700, lineHeight: 1.2 }}>
                {data.display_name || data.username}
              </span>
              <span className="faint" style={{ fontSize: 12 }}>
                @{data.username}
              </span>
            </div>
            {joined && (
              <div
                className="faint flex items-center gap-1"
                style={{ fontSize: 11.5, marginTop: 2 }}
              >
                <CalendarDays size={11} /> 加入于 {joined}
              </div>
            )}
          </div>

          <div style={{ marginLeft: 'auto' }}>
            {data.is_self ? (
              <Link to="/me/settings">
                <Button icon={<Pencil size={12} />} style={{ fontSize: 12 }}>
                  编辑资料
                </Button>
              </Link>
            ) : null}
          </div>
        </div>

        {/* ③ 签名 */}
        {data.bio && (
          <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--text-sub)', lineHeight: 1.7 }}>
            {data.bio}
          </div>
        )}

        {/* ④ 数字 */}
        <div className="flex items-center gap-1" style={{ marginTop: 12 }}>
          <Stat value={data.stats.projects} label="项目" />
          <Stat value={data.stats.notes} label="笔记" />
          <Stat value={data.stats.likes} label="获赞" />
          <Stat value={data.stats.comments} label="评论" />
          {privateNotes > 0 && (
            <span className="faint" style={{ fontSize: 11, marginLeft: 8 }}>
              （含私有 {privateNotes} 篇）
            </span>
          )}
          <span className="faint flex items-center gap-1" style={{ fontSize: 11, marginLeft: 'auto' }}>
            <ThumbsUp size={11} /> <MessageSquare size={11} />
          </span>
        </div>
      </div>
    </div>
  )
}
