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

/** ★ 仿写：一个节点下的一份代码卡 */
export interface ImitationItem {
  /** 文件名（含扩展名），也是这份卡片的唯一名 */
  name: string
  /** 标题（= 文件名去掉扩展名） */
  title: string
  ext: string
  lines: number
  /** 秒级时间戳（排序用） */
  updated_at: number
}

/** ★ 按后缀猜语言（与 sidecar/source.py 的 LANG_BY_EXT 对齐常用项） */
const LANG_BY_EXT: Record<string, string> = {
  py: 'python', pyi: 'python',
  js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', tsx: 'typescript',
  java: 'java', c: 'c', h: 'c',
  cpp: 'cpp', cc: 'cpp', cxx: 'cpp', hpp: 'cpp',
  go: 'go', rs: 'rust', php: 'php', rb: 'ruby',
  cs: 'csharp', swift: 'swift', kt: 'kotlin', kts: 'kotlin',
  sql: 'sql', json: 'json', jsonc: 'json',
  md: 'markdown', markdown: 'markdown',
  yaml: 'yaml', yml: 'yaml', toml: 'toml', ini: 'ini',
  html: 'html', htm: 'html', vue: 'html', xml: 'xml',
  css: 'css', scss: 'css', less: 'css',
  sh: 'shell', bash: 'shell', zsh: 'shell', ps1: 'shell',
}

export function langFromPath(path: string): string {
  const ext = (path.split('.').pop() || '').toLowerCase()
  return LANG_BY_EXT[ext] || ''
}
