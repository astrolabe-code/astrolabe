/**
 * 代码工作区的数据层：文件树 / 源码 / 当前文件。
 *
 * 抽出来是因为新布局把「文件树」放左栏、「源码」放右栏上半，
 * 两处都要同一份数据 —— ⛔ 不再各自 fetch 一遍。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { personalApi } from '../../api/personal'
import type { FileTreeData, FileTreeNode, SourceFile } from '../../api/code'
import type { GraphNode } from '../../lib/mergeGraph'

/** 默认只展开第一层目录（深层靠用户点开，避免几万文件一次铺开） */
export function firstLevelDirs(items: FileTreeNode[]): Set<string> {
  return new Set(items.filter((n) => n.type === 'dir').map((n) => n.path))
}

export interface CodeData {
  tree: FileTreeData | null
  treeError: string
  expanded: Set<string>
  toggleDir: (path: string) => void
  activePath: string
  pickFile: (path: string) => void
  source: SourceFile | null
  sourceError: string
  loading: boolean
  focusLine: number | null
}

/**
 * @param projectRef 项目
 * @param node       选中的节点（有 rel_path 就自动打开该文件并定位行）
 */
export function useCodeData(projectRef: string, node: GraphNode | null): CodeData {
  const [tree, setTree] = useState<FileTreeData | null>(null)
  const [treeError, setTreeError] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [activePath, setActivePath] = useState('')
  const [source, setSource] = useState<SourceFile | null>(null)
  const [sourceError, setSourceError] = useState('')
  const [loading, setLoading] = useState(false)
  const [focusLine, setFocusLine] = useState<number | null>(null)

  // ① 文件树
  useEffect(() => {
    let alive = true
    personalApi
      .fileTree(projectRef)
      .then((d) => {
        if (!alive) return
        setTree(d as unknown as FileTreeData)
        setExpanded(firstLevelDirs((d as unknown as FileTreeData).items))
        setTreeError('')
      })
      .catch((e: Error) => alive && setTreeError(e.message || '列文件树失败'))
    return () => {
      alive = false
    }
  }, [projectRef])

  // ② 点节点 ⇒ 自动打开对应文件并跳到那一行
  useEffect(() => {
    if (!node?.rel_path) return
    setActivePath(node.rel_path)
    setFocusLine(node.line > 0 ? node.line : null)
  }, [node?.rel_path, node?.line, node?.vid])

  // ③ 读文件内容
  useEffect(() => {
    if (!activePath) return
    let alive = true
    setLoading(true)
    setSourceError('')
    personalApi
      .readSource(projectRef, activePath)
      .then((d) => {
        if (!alive) return
        setSource(d)
        setSourceError('')
      })
      .catch((e: Error) => {
        if (!alive) return
        setSource(null)
        setSourceError(e.message || '读取失败')
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [projectRef, activePath])

  const toggleDir = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }, [])

  const pickFile = useCallback((path: string) => {
    setActivePath(path)
    setFocusLine(null)
  }, [])

  return useMemo(
    () => ({ tree, treeError, expanded, toggleDir, activePath, pickFile, source, sourceError, loading, focusLine }),
    [tree, treeError, expanded, toggleDir, activePath, pickFile, source, sourceError, loading, focusLine],
  )
}
