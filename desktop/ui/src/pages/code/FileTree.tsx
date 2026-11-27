import type { FileTreeNode } from '../../api/code'
import { ChevronDown, ChevronRight, File as FileIcon, Folder, FolderOpen } from 'lucide-react'

interface FileTreeProps {
  items: FileTreeNode[]
  activePath: string
  expanded: Set<string>
  onToggle: (path: string) => void
  onPick: (path: string) => void
}

/** ★ 默认只展开第一层目录（深层靠用户点开，避免几万文件一次铺开） */
export function firstLevelDirs(items: FileTreeNode[]): Set<string> {
  return new Set(items.filter((n) => n.type === 'dir').map((n) => n.path))
}

interface RowProps {
  node: FileTreeNode
  depth: number
  activePath: string
  expanded: Set<string>
  onToggle: (path: string) => void
  onPick: (path: string) => void
}

function Row({ node, depth, activePath, expanded, onToggle, onPick }: RowProps) {
  const isDir = node.type === 'dir'
  const open = expanded.has(node.path)
  const active = !isDir && activePath === node.path

  return (
    <>
      <button
        type="button"
        title={node.path}
        onClick={() => (isDir ? onToggle(node.path) : onPick(node.path))}
        className="code-tree-row"
        style={{
          paddingLeft: 8 + depth * 14,
          background: active ? 'rgba(37,99,235,.10)' : 'transparent',
          color: active ? 'var(--accent, #2563eb)' : 'var(--text-sub, #6b7280)',
          fontWeight: active ? 600 : 400,
        }}
      >
        <span style={{ flex: 'none', width: 12, display: 'inline-flex' }}>
          {isDir ? (
            open ? <ChevronDown size={12} /> : <ChevronRight size={12} />
          ) : null}
        </span>
        <span style={{ flex: 'none', display: 'inline-flex', opacity: 0.85 }}>
          {isDir ? (
            open ? <FolderOpen size={13} /> : <Folder size={13} />
          ) : (
            <FileIcon size={13} />
          )}
        </span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.name}
        </span>
      </button>

      {isDir && open &&
        (node.children || []).map((child) => (
          <Row
            key={child.path}
            node={child}
            depth={depth + 1}
            activePath={activePath}
            expanded={expanded}
            onToggle={onToggle}
            onPick={onPick}
          />
        ))}
    </>
  )
}

/**
 * ★★ 文件树（个人版：**显示全部文件，⛔ 不按 .gitignore 过滤**）
 *
 * 所有者：「文件树不要按 .gitignore 过滤」
 * ⇒ 目录/文件一个不少；解析时仍由 codeparser/ignore.py 过滤，那是另一回事。
 */
export default function FileTree({ items, activePath, expanded, onToggle, onPick }: FileTreeProps) {
  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '6px 0' }}>
      {items.map((node) => (
        <Row
          key={node.path}
          node={node}
          depth={0}
          activePath={activePath}
          expanded={expanded}
          onToggle={onToggle}
          onPick={onPick}
        />
      ))}
    </div>
  )
}
