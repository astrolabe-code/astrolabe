import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'

import { langFromPath, type ImitationItem } from '../../api/code'
import { personalApi } from '../../api/personal'
import type { GraphNode } from '../../lib/mergeGraph'
import CodeEditor from './CodeEditor'

interface ImitationPanelProps {
  projectRef: string
  node: GraphNode | null
}

/**
 * ★★★ **仿写**（2026-11-06）
 *
 * 所有者：「仿写也不止写一段代码呀，它可能和笔记一样，有多份代码文件，
 *         毕竟理解的深入，写出的代码也不同」＋「仿写的意义就在于默写」
 *
 * ⇒ 一个节点下可以有任意多份仿写；这里**只有编辑器**，⛔ 不放原文、不做对照，
 *   想看原文点上面的「代码」tab 即可。
 *
 * 存储：`<项目数据目录>/imitations/<vid>/<标题>.<扩展名>`（见 sidecar/imitation.py）
 */
export default function ImitationPanel({ projectRef, node }: ImitationPanelProps) {
  const vid = node?.vid ?? 0
  const ext = (node?.file_path || '').split('.').pop() || 'txt'
  const lang = langFromPath(node?.file_path || '')

  const [items, setItems] = useState<ImitationItem[]>([])
  const [activeName, setActiveName] = useState('')
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [renameInput, setRenameInput] = useState('')

  /** 最近一次「已保存 / 刚加载」的内容：一样就不重复发保存请求 */
  const lastSaved = useRef('')
  const activeRef = useRef('')
  activeRef.current = activeName

  /** ★ 换版本：**先把内容读回来，再一起 set** —— 否则 CodeEditor 会用上一版内容挂载 */
  const applyVersion = useCallback(
    async (name: string) => {
      try {
        const d = await personalApi.imitation(projectRef, vid, name)
        lastSaved.current = d.text
        setText(d.text)
        setActiveName(name)
        setError('')
      } catch (e) {
        setError((e as Error).message || '读取失败')
      }
    },
    [projectRef, vid],
  )

  const refresh = useCallback(
    async (prefer?: string) => {
      if (!vid) return
      try {
        const d = await personalApi.imitations(projectRef, vid)
        setItems(d.items)
        setError('')
        const pick =
          prefer && d.items.some((i) => i.name === prefer)
            ? prefer
            : d.items.length
              ? d.items[d.items.length - 1].name
              : ''
        if (!pick) {
          setActiveName('')
          setText('')
          lastSaved.current = ''
          return
        }
        if (prefer || pick !== activeRef.current) await applyVersion(pick)
      } catch (e) {
        setError((e as Error).message || '读取仿写列表失败')
      }
    },
    [projectRef, vid, applyVersion],
  )

  // ① 进入 / 换节点 ⇒ 拉列表
  useEffect(() => {
    void refresh()
  }, [refresh])

  // ③ 自动保存（停下 800ms）
  useEffect(() => {
    if (!activeName || !vid) return
    if (text === lastSaved.current) return
    const name = activeName
    setSaving(true)
    const timer = window.setTimeout(() => {
      personalApi
        .saveImitation(projectRef, vid, name, text)
        .then(() => {
          lastSaved.current = text
          setSaving(false)
          setError('')
          // 行数会变，静默刷一下列表
          void personalApi
            .imitations(projectRef, vid)
            .then((d) => setItems(d.items))
            .catch(() => {})
        })
        .catch((e: Error) => {
          setSaving(false)
          setError(e.message || '保存失败')
        })
    }, 800)
    return () => window.clearTimeout(timer)
  }, [text, activeName, projectRef, vid])

  const createOne = async () => {
    if (!vid) return
    try {
      const d = await personalApi.createImitation(projectRef, vid, ext)
      await refresh(d.name)
    } catch (e) {
      setError((e as Error).message || '新建失败')
    }
  }

  const removeOne = async () => {
    if (!activeName || !vid) return
    if (!window.confirm(`删除「${activeName}」？删除后不可恢复。`)) return
    try {
      await personalApi.deleteImitation(projectRef, vid, activeName)
      await refresh()
    } catch (e) {
      setError((e as Error).message || '删除失败')
    }
  }

  const submitRename = async () => {
    if (!activeName || !vid || !renameInput.trim()) return
    try {
      const d = await personalApi.renameImitation(projectRef, vid, activeName, renameInput.trim())
      setRenaming(false)
      await refresh(d.name)
    } catch (e) {
      setError((e as Error).message || '改名失败')
    }
  }

  if (!node) {
    return (
      <div className="faint" style={{ padding: 20, fontSize: 12.5 }}>
        先选中一个节点，再写仿写。
      </div>
    )
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {/* 版本标签 */}
      <div
        style={{
          flex: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 10px',
          borderBottom: '1px solid var(--card-border)',
          overflowX: 'auto',
        }}
      >
        {items.map((it) => (
          <button
            key={it.name}
            type="button"
            onClick={() => void applyVersion(it.name)}
            title={`${it.name} · ${it.lines} 行`}
            style={{
              flex: 'none',
              padding: '3px 10px',
              borderRadius: 999,
              fontSize: 11.5,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              border: `1px solid ${activeName === it.name ? 'var(--accent)' : 'var(--card-border)'}`,
              background: activeName === it.name ? 'var(--accent-dim)' : 'transparent',
              color: activeName === it.name ? 'var(--accent)' : 'var(--text-sub)',
            }}
          >
            {it.title}
          </button>
        ))}
        <button
          type="button"
          onClick={() => void createOne()}
          title="新建一份空白仿写"
          style={{
            flex: 'none',
            padding: '3px 8px',
            borderRadius: 999,
            fontSize: 11.5,
            cursor: 'pointer',
            border: '1px dashed var(--card-border)',
            background: 'transparent',
            color: 'var(--text-sub)',
            display: 'inline-flex',
            alignItems: 'center',
          }}
        >
          <Plus size={12} />
        </button>
      </div>

      {/* 状态 + 重命名 / 删除 */}
      {activeName && (
        <div
          className="faint"
          style={{
            flex: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '4px 10px',
            fontSize: 11.5,
            borderBottom: '1px solid var(--card-border)',
          }}
        >
          {renaming ? (
            <>
              <input
                className="input"
                autoFocus
                value={renameInput}
                onChange={(e) => setRenameInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void submitRename()
                  if (e.key === 'Escape') setRenaming(false)
                }}
                style={{ fontSize: 11.5, height: 24, maxWidth: 220 }}
              />
              <button type="button" className="code-icon-btn" onClick={() => void submitRename()}>
                确定
              </button>
              <button type="button" className="code-icon-btn" onClick={() => setRenaming(false)}>
                取消
              </button>
            </>
          ) : (
            <>
              <span>{saving ? '保存中…' : `已保存 · ${text.split('\n').length} 行`}</span>
              <button
                type="button"
                className="code-icon-btn"
                style={{ marginLeft: 'auto' }}
                onClick={() => {
                  setRenameInput(activeName.replace(/\.[^.]+$/, ''))
                  setRenaming(true)
                }}
              >
                重命名
              </button>
              <button
                type="button"
                className="code-icon-btn"
                title="删除这一份仿写"
                onClick={() => void removeOne()}
              >
                <Trash2 size={13} strokeWidth={1.5} />
              </button>
            </>
          )}
        </div>
      )}

      {error && (
        <div style={{ flex: 'none', padding: '4px 10px', fontSize: 11.5, color: 'var(--err)' }}>
          {error}
        </div>
      )}

      {/* 编辑器 / 空态 */}
      {activeName ? (
        <div style={{ flex: 1, minHeight: 0 }}>
          <CodeEditor
            key={activeName}
            docKey={activeName}
            initialText={text}
            lang={lang}
            onChange={setText}
          />
        </div>
      ) : (
        <div
          className="faint"
          style={{
            flex: 1,
            display: 'grid',
            placeItems: 'center',
            textAlign: 'center',
            fontSize: 12.5,
            lineHeight: 2,
          }}
        >
          还没有仿写
          <br />
          <button
            type="button"
            className="code-icon-btn"
            onClick={() => void createOne()}
            style={{ gap: 4, color: 'var(--accent)' }}
          >
            <Plus size={13} strokeWidth={1.5} /> 写第一版
          </button>
        </div>
      )}
    </div>
  )
}
