import { useEffect, useMemo, useState } from 'react'
import { Lock } from 'lucide-react'
import type { SettingsData, SettingsSpec } from '../../api/types'
import Button from '../ui/Button'

/**
 * ★ 设置表单（`F2` · D92）——* 项目档与用户档**共用**
 *
 * ## ⚠★ 四条口径
 *
 * | # | 口径 | 依据 |
 * |---|---|---|
 * | ① | ★ 每项显示 **`source`**（默认/全局/用户/项目）—— 「这一项为什么是这个值」 | `B203②` |
 * | ② | ★ `gated=true` 对**非管理员**禁用并标注（管理员才能改） | `B190③` |
 * | ③ | ★ PATCH 请求体是**扁平的** `{键:值}`（⛔ 不包 `settings`） | 契约 §22.1 |
 * | ④ | ★★ 整件 400 `bad_setting` ⇒ 原样显示被拒的键（⛔ 不做部分应用） | 契约 §22.1 |
 *
 * ⚠★ 控件按 `type` 渲染（`bool` 开关 / `int` 数字框 / 其余文本框）——
 *   ★ 新增类型时这里加一个分支，* ⛔ 不让后端随便加类型前端猜 ⚠
 */

const SOURCE_LABEL: Record<string, string> = {
  default: '默认值',
  global: '全局设置',
  user: '用户设置',
  project: '项目设置',
}

interface SettingsFormProps {
  data: SettingsData
  saving?: boolean
  error?: string
  /** ★ 只有管理员能改 gated 键 */
  isAdmin?: boolean
  onSave: (patch: Record<string, unknown>) => void
}

export default function SettingsForm({ data, saving, error, isAdmin, onSave }: SettingsFormProps) {
  const [draft, setDraft] = useState<Record<string, unknown>>({})

  /** ★ 数据换了（重新拉取成功）就重置草稿 —— ⛔ 不把用户的半成品盖回去 */
  useEffect(() => {
    setDraft({})
  }, [data])

  const dirtyKeys = useMemo(
    () => Object.keys(draft).filter((k) => draft[k] !== valueOf(data, k)),
    [draft, data],
  )

  const set = (spec: SettingsSpec, v: unknown) => {
    setDraft((d) => ({ ...d, [spec.key]: v }))
  }

  const submit = () => {
    const patch: Record<string, unknown> = {}
    for (const k of dirtyKeys) patch[k] = draft[k]
    onSave(patch)
  }

  return (
    <div>
      <div className="flex flex-col gap-3">
        {data.specs.map((spec) => {
          const value = spec.key in draft ? draft[spec.key] : spec.value
          const gatedLocked = spec.gated && !isAdmin
          return (
            <div
              key={spec.key}
              className="card"
              style={{ padding: '10px 12px', opacity: gatedLocked ? 0.75 : 1 }}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span style={{ fontSize: 13, fontWeight: 600 }}>{spec.label}</span>
                <span className="tag" style={{ fontSize: 10 }}>
                  {SOURCE_LABEL[spec.source] || spec.source}
                </span>
                {spec.gated && (
                  <span className="tag" style={{ fontSize: 10, color: 'var(--err)' }} title="只有站点管理员能改">
                    <Lock size={9} style={{ marginRight: 2, verticalAlign: -1 }} />
                    {gatedLocked ? '管理员可改' : '门禁项'}
                  </span>
                )}
              </div>
              {spec.note && (
                <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>
                  {spec.note}
                </div>
              )}
              <div className="mt-2 flex items-center gap-2">
                {spec.type === 'bool' ? (
                  <button
                    type="button"
                    disabled={gatedLocked}
                    onClick={() => set(spec, !value)}
                    style={{
                      width: 40,
                      height: 22,
                      borderRadius: 999,
                      border: '1px solid var(--card-border)',
                      background: value ? 'var(--accent)' : 'transparent',
                      cursor: gatedLocked ? 'not-allowed' : 'pointer',
                      position: 'relative',
                    }}
                    aria-label={spec.label}
                  >
                    <span
                      style={{
                        position: 'absolute',
                        top: 2,
                        left: value ? 20 : 2,
                        width: 16,
                        height: 16,
                        borderRadius: '50%',
                        background: value ? '#fff' : 'var(--text-sub)',
                        transition: 'left .15s',
                      }}
                    />
                  </button>
                ) : spec.type === 'int' ? (
                  <input
                    className="input"
                    style={{ width: 120, fontSize: 13 }}
                    type="number"
                    disabled={gatedLocked}
                    value={Number(value ?? 0)}
                    onChange={(e) => set(spec, Number(e.target.value))}
                  />
                ) : (
                  <input
                    className="input"
                    style={{ maxWidth: 320, fontSize: 13 }}
                    disabled={gatedLocked}
                    value={String(value ?? '')}
                    onChange={(e) => set(spec, e.target.value)}
                  />
                )}
              </div>
            </div>
          )
        })}
      </div>

      {error && (
        <div className="text-xs mt-3" style={{ color: 'var(--err)' }}>
          {error}
        </div>
      )}

      <div className="mt-4 flex items-center gap-3">
        <Button
          variant="primary"
          loading={saving}
          disabled={dirtyKeys.length === 0}
          onClick={submit}
        >
          {dirtyKeys.length > 0 ? `保存（${dirtyKeys.length} 项改动）` : '保存'}
        </Button>
        {dirtyKeys.length > 0 && (
          <Button disabled={saving} onClick={() => setDraft({})}>
            放弃改动
          </Button>
        )}
      </div>
    </div>
  )
}

/** ★ 取这一项的"已保存值"（`draft` 里的才算改动）✅ */
function valueOf(data: SettingsData, key: string): unknown {
  const spec = data.specs.find((s) => s.key === key)
  return spec ? spec.value : undefined
}
