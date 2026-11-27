/**
 * 右栏：上下分栏（复用通用 SplitPane，⛔ 不自己写拖动）。
 *
 *   上 = 你正在读/写的东西（代码 / 仿写 / 学习路径）
 *   下 = 关于当前节点的信息（知识点 / 社区 / 执行流 / 问答）
 */
import { useEffect, useState } from 'react'
import { personalApi } from '../../api/personal'
import type { SourceFile } from '../../api/code'
import type { GraphNode } from '../../lib/mergeGraph'
import SplitPane from '../../components/SplitPane'
import CodeViewer from '../code/CodeViewer'
import ImitationPanel from '../code/ImitationPanel'
import QaPanel from '../code/QaPanel'
import CommunityPanel from './CommunityPanel'
import FlowPanel from './FlowPanel'
import LearningPathPanel from './LearningPathPanel'

export type UpperPanel = 'code' | 'imitation' | 'path'
export type LowerTab = 'concepts' | 'community' | 'flow' | 'qa'

interface Props {
  projectRef: string
  node: GraphNode | null
  upper: UpperPanel
  onUpperChange: (p: UpperPanel) => void
  source: SourceFile | null
  sourceError: string
  loading: boolean
  focusLine: number | null
  onPickHighlight: (vids: number[], key: string | null) => void
  activeKey?: string | null
  nameOf: (vid: number) => string
  onPickNode?: (vid: number) => void
}

const UPPER_LABEL: Record<UpperPanel, string> = {
  code: '代码',
  imitation: '仿写',
  path: '学习路径',
}

const LOWER_LABEL: Record<LowerTab, string> = {
  concepts: '知识点',
  community: '社区',
  flow: '执行流',
  qa: '问答',
}

const tabStyle = (on: boolean) => ({
  padding: '3px 9px',
  borderRadius: 5,
  border: 'none',
  cursor: 'pointer' as const,
  fontSize: 11.5,
  background: on ? 'var(--accent-soft, #eff6ff)' : 'transparent',
  color: on ? 'var(--accent, #2563eb)' : 'var(--text-muted, #64748b)',
  fontWeight: on ? 600 : 400,
})

export default function RightSidebar({
  projectRef,
  node,
  upper,
  onUpperChange,
  source,
  sourceError,
  loading,
  focusLine,
  onPickHighlight,
  activeKey,
  nameOf,
  onPickNode,
}: Props) {
  const [lower, setLower] = useState<LowerTab>('concepts')
  const [lowerCollapsed, setLowerCollapsed] = useState(false)

  /** 知识点 */
  const [concepts, setConcepts] = useState('')
  const [conceptBusy, setConceptBusy] = useState(false)
  const [conceptErr, setConceptErr] = useState('')

  useEffect(() => {
    setConcepts('')
    setConceptErr('')
    if (!node?.vid) return
    let alive = true
    personalApi
      .getConcepts(projectRef, node.vid)
      .then((r) => {
        if (alive) setConcepts(String(r.concepts || ''))
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [projectRef, node?.vid])

  async function annotate() {
    if (!node?.vid) return
    setConceptBusy(true)
    setConceptErr('')
    try {
      const r = await personalApi.annotateConcepts(projectRef, node.vid)
      setConcepts(String(r.concepts || ''))
    } catch (e) {
      setConceptErr(String((e as Error)?.message || e))
    } finally {
      setConceptBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
      {/* ── 节点摘要（所有面板共用）── */}
      <div
        style={{
          padding: '8px 12px',
          flex: 'none',
          borderBottom: '1px solid var(--divider, #eef2f7)',
          background: 'var(--surface, #fcfdff)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 9,
              flex: 'none',
              background: node?.kind ? kindColorOf(node.kind) : '#94a3b8',
            }}
          />
          <b style={{ fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node?.qname && node.qname !== node.name ? node.qname : node?.name || '未选中节点'}
          </b>
          {node?.kind && (
            <span
              style={{
                fontSize: 10,
                padding: '1px 7px',
                borderRadius: 999,
                border: '1px solid var(--card-border, #c7d2fe)',
                color: 'var(--accent, #3730a3)',
                background: 'var(--accent-soft, #eef2ff)',
                flex: 'none',
              }}
            >
              {node.kind}
            </span>
          )}
        </div>
        {node?.rel_path && (
          <div
            style={{
              fontSize: 10.5,
              color: 'var(--text-faint, #94a3b8)',
              marginTop: 2,
              fontFamily: 'ui-monospace, monospace',
            }}
          >
            {node.rel_path}:{node.line}
          </div>
        )}
      </div>

      {/* ── 上下分栏（通用组件，direction=vertical）── */}
      <SplitPane
        direction="vertical"
        fixed="right"
        initial={220}
        min={90}
        breakpoint={0}
        collapsed={lowerCollapsed}
        collapsedSide="right"
      >
        {/* 上半：代码 / 仿写 / 路径 */}
        <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', width: '100%' }}>
          <div
            style={{
              height: 30,
              flex: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 2,
              padding: '0 8px',
              borderBottom: '1px solid var(--divider, #eef2f7)',
            }}
          >
            {(Object.keys(UPPER_LABEL) as UpperPanel[]).map((k) => (
              <button key={k} type="button" onClick={() => onUpperChange(k)} style={tabStyle(upper === k)}>
                {UPPER_LABEL[k]}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
            {upper === 'code' ? (
              loading ? (
                <div style={{ padding: 20, fontSize: 12.5, color: 'var(--text-muted, #94a3b8)' }}>正在读取…</div>
              ) : sourceError ? (
                <div style={{ padding: 20, fontSize: 12.5, color: 'var(--text-muted, #94a3b8)' }}>{sourceError}</div>
              ) : source ? (
                <CodeViewer text={source.text} lang={source.lang} focus={focusLine} />
              ) : (
                <div
                  style={{
                    padding: 20,
                    fontSize: 12,
                    color: 'var(--text-faint, #cbd5e1)',
                    textAlign: 'center',
                    lineHeight: 2,
                  }}
                >
                  在左侧目录选一个文件
                  <br />
                  <span style={{ fontSize: 11 }}>或从图谱里点节点，会自动定位到它所在行</span>
                </div>
              )
            ) : upper === 'imitation' ? (
              <ImitationPanel projectRef={projectRef} node={node} />
            ) : (
              <div style={{ padding: 10 }}>
                <LearningPathPanel
                  projectRef={projectRef}
                  selectedVid={node?.vid ?? null}
                  onPick={(vid) => onPickNode?.(vid)}
                />
              </div>
            )}
          </div>
        </div>

        {/* 下半：知识点 / 社区 / 执行流 / 问答 */}
        <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column', width: '100%' }}>
          <div
            style={{
              height: 30,
              flex: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 2,
              padding: '0 8px',
              borderBottom: '1px solid var(--divider, #eef2f7)',
            }}
          >
            {(Object.keys(LOWER_LABEL) as LowerTab[]).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => {
                  setLower(k)
                  setLowerCollapsed(false)
                }}
                style={tabStyle(lower === k)}
              >
                {LOWER_LABEL[k]}
              </button>
            ))}
            <span style={{ flex: 1 }} />
            <button
              type="button"
              onClick={() => setLowerCollapsed((v) => !v)}
              title={lowerCollapsed ? '展开' : '收起'}
              style={{
                border: 'none',
                background: 'transparent',
                cursor: 'pointer',
                color: 'var(--text-faint, #cbd5e1)',
                fontSize: 10,
                padding: '2px 4px',
              }}
            >
              {lowerCollapsed ? '▸' : '▾'}
            </button>
          </div>

          {!lowerCollapsed && (
            <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
              {lower === 'concepts' ? (
                <div style={{ padding: '8px 12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                    <span style={{ fontSize: 11.5, color: 'var(--text-faint, #94a3b8)' }}>
                      AI 读出这段代码用到的概念
                    </span>
                    <button
                      type="button"
                      disabled={conceptBusy || !node?.vid}
                      onClick={() => void annotate()}
                      style={{
                        marginLeft: 'auto',
                        border: 'none',
                        background: 'transparent',
                        color: 'var(--accent, #2563eb)',
                        fontSize: 10.5,
                        cursor: 'pointer',
                      }}
                    >
                      {conceptBusy ? '标注中…' : concepts ? '重新标注' : '标注'}
                    </button>
                  </div>
                  {concepts ? (
                    <div style={{ fontSize: 12, lineHeight: 1.7 }}>{concepts}</div>
                  ) : (
                    <div style={{ fontSize: 11.5, color: 'var(--text-faint, #cbd5e1)' }}>
                      （未标注 —— 点右上「标注」）
                    </div>
                  )}
                  {conceptErr && (
                    <div style={{ fontSize: 11, color: 'var(--err, #ef4444)', marginTop: 4 }}>{conceptErr}</div>
                  )}
                </div>
              ) : lower === 'community' ? (
                <div style={{ padding: 8 }}>
                  <CommunityPanel projectRef={projectRef} onPick={onPickHighlight} activeKey={activeKey} />
                </div>
              ) : lower === 'flow' ? (
                <div style={{ padding: 8 }}>
                  <FlowPanel
                    projectRef={projectRef}
                    vid={node?.vid ?? null}
                    nameOf={nameOf}
                    onPick={onPickHighlight}
                    activeKey={activeKey}
                  />
                </div>
              ) : (
                <QaPanel projectRef={projectRef} vid={node?.vid ?? null} name={node?.name} />
              )}
            </div>
          )}
        </div>
      </SplitPane>
    </div>
  )
}

/** 节点类型色（与图谱一致） */
function kindColorOf(kind: string): string {
  const m: Record<string, string> = {
    file: '#3b82f6',
    dir: '#94a3b8',
    class: '#a855f7',
    function: '#f97316',
    method: '#f59e0b',
    type: '#22c55e',
    variable: '#0ea5e9',
    manual: '#64748b',
  }
  return m[kind] || '#94a3b8'
}
