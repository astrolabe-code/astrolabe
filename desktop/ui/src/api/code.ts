/** ★ 代码展示的数据形状（与 `desktop/sidecar/source.py` 一一对应） */
export interface FileTreeNode {
  name: string
  /** 相对项目根的路径，用 `/` 分隔 */
  path: string
  type: 'dir' | 'file'
  children?: FileTreeNode[]
}

export interface FileTreeData {
  items: FileTreeNode[]
  /** 节点数/深度到上限 ⇒ 界面提示"只显示了一部分" */
  truncated: boolean
}

export interface SourceFile {
  path: string
  text: string
  lines: number
  /** 语言标识（'' = 纯文本），前端据此动态加载 CodeMirror 语言包 */
  lang: string
  size: number
  encoding: string
}
