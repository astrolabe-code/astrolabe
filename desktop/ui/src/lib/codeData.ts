/**
 * 代码域的数据契约。
 *
 * ★ 单独放在 `lib/` 而不是跟着 hook 走：`lib/ribbonBus.ts` 要用这个类型
 *   （全局目录面板从 bus 里取 codeData）。若类型留在 `pages/code/`，
 *   就会形成 lib → pages 的反向依赖。
 *   类型属于「领域契约」，本来就该在 lib。
 */
import type { FileTreeData, SourceFile } from '../api/code'

export interface CodeData {
  /** 文件树 */
  tree: FileTreeData | null
  treeError: string
  /** 已展开的目录路径 */
  expanded: Set<string>
  toggleDir: (path: string) => void
  /** 当前打开的文件（相对项目根） */
  activePath: string
  pickFile: (path: string) => void
  /** 源码 */
  source: SourceFile | null
  sourceError: string
  loading: boolean
  /** 要高亮的行号（选中节点所在行） */
  focusLine: number | null
}
