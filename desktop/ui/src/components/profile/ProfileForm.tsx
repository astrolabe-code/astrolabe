import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorMessage } from '../../api/errors'
import Button from '../ui/Button'
import { useMyProfile, useUpdateMyProfile } from '../../query/userSpace'

/**
 * ★★ **个人资料**（昵称 / 签名 · 2026-10-24）⚠
 *
 * ```\n * 昵称：≤40 字，**可空** —— 空就全站回落到 username（* 后端同口径）\n * 签名：≤120 字，单行（* 换行会被后端折成空格）\n * ⚠ username 不可改：那是身份，不是资料 ⚠\n * ```
 */
export default function ProfileForm() {
  const profile = useMyProfile()
  const update = useUpdateMyProfile()
  const [name, setName] = useState('')
  const [bio, setBio] = useState('')
  const [err, setErr] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!profile.data) return
    setName(profile.data.raw_display_name || '')
    setBio(profile.data.bio || '')
  }, [profile.data])

  const save = async () => {
    setErr('')
    setDone(false)
    try {
      await update.mutateAsync({ display_name: name, bio })
      setDone(true)
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  return (
    <div className="card" style={{ padding: '16px 18px', marginBottom: 16 }}>
      <div className="flex items-center gap-2" style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 14, fontWeight: 650 }}>个人资料</div>
        <span className="faint" style={{ fontSize: 11.5 }}>
          显示在笔记、评论和你的空间页
        </span>
        <Link
          to={profile.data ? `/u/${encodeURIComponent(profile.data.username)}` : '/me'}
          className="faint"
          style={{ fontSize: 11.5, marginLeft: 'auto' }}
        >
          查看我的空间 →
        </Link>
      </div>

      <div className="flex flex-col gap-3" style={{ maxWidth: 520 }}>
        <div>
          <label
            className="block text-xs font-medium tracking-wide text-text-sub mb-1.5"
            htmlFor="profile-name"
          >
            昵称（可空，空就用用户名 @{profile.data?.username || ''}）
          </label>
          <input
            id="profile-name"
            className="input"
            maxLength={40}
            placeholder={profile.data?.username || '昵称'}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div>
          <label
            className="block text-xs font-medium tracking-wide text-text-sub mb-1.5"
            htmlFor="profile-bio"
          >
            一句话签名（可空，120 字内）
          </label>
          <input
            id="profile-bio"
            className="input"
            maxLength={120}
            placeholder="读代码像读散文"
            value={bio}
            onChange={(e) => setBio(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-2">
          <Button variant="primary" loading={update.isPending} onClick={save}>
            保存资料
          </Button>
          {done && (
            <span style={{ fontSize: 11.5, color: 'var(--ok)' }}>已保存</span>
          )}
          {err && <span style={{ fontSize: 11.5, color: 'var(--err)' }}>{err}</span>}
        </div>
      </div>
    </div>
  )
}
