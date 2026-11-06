/**
 * ★★ 个人版的界面偏好（本地存储，不需要后端）⚠
 *
 * 目前有三项：
 * ```
 * 流星特效     图谱里节点之间飞过的流光
 * 代码字号     CodeMirror 的字体大小（用户自己填，9–24px）
 * 代码字体     CodeMirror 的等宽字体栈
 * ```
 *
 * ⚠ 设置页采用 **「草稿 + 一次确认」**：控件改的是草稿，只有点「确认」
 *   才由 `saveAppearance()` 一次性写入并下发；「取消」把草稿还原成已保存值。
 *   ⇒ 不要在这里加"改一项存一项"的即时保存（所有者明确不要每项单独确认）。
 *
 * ⚠ 代码外观用 **CSS 变量**下发（`--code-font-size` / `--code-font-family`），
 *   CodeMirror 的 theme 读变量 ⇒ 确认后已打开的编辑器不用重建就能刷新。
 */
const KEY_METEORS = 'astrolabe.meteors'

/** 读「流星」开关（默认开）*/
export function getMeteors(): boolean {
  try {
    const v = localStorage.getItem(KEY_METEORS)
    return v === null ? true : v === '1'
  } catch {
    return true // 隐私模式 / 存储被禁 ⇒ 用默认值，不抛错
  }
}

// ---------------------------------------------------------------- 代码外观

/** 字号范围（用户自己填，⛔ 不再给固定档位选择） */
export const CODE_FONT_MIN = 9
export const CODE_FONT_MAX = 24
export const DEFAULT_CODE_FONT_SIZE = 12.5

/**
 * ★ 免版权顾虑的等宽字体（所有者：「换几个没版权限制的字体」）
 *
 * ⚠ **不随软件分发字体文件**：这些都是系统自带或 SIL OFL 等自由许可的字体，
 *   只写字体名，用本机已装的那一个；没装就按栈自动回退到系统等宽字体。
 *   ⇒ 不需要打包字体、不需要附许可证，也不会有授权风险。
 */
export const CODE_FONT_STACKS = [
  {
    label: '系统等宽（默认）',
    value:
      'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
  },
  {
    label: 'Cascadia Mono（Windows 自带 · OFL）',
    value: '"Cascadia Mono", "Cascadia Code", Consolas, "Courier New", monospace',
  },
  {
    label: 'JetBrains Mono（OFL）',
    value: '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", monospace',
  },
  {
    label: 'Fira Code（OFL）',
    value: '"Fira Code", "Source Code Pro", "DejaVu Sans Mono", monospace',
  },
  {
    label: 'Source Code Pro（OFL）',
    value: '"Source Code Pro", "Liberation Mono", monospace',
  },
  {
    label: 'DejaVu Sans Mono（自由许可 · Linux 常见）',
    value: '"DejaVu Sans Mono", "Liberation Mono", monospace',
  },
] as const

const KEY_CODE_FONT_SIZE = 'astrolabe.code.fontSize'
const KEY_CODE_FONT_FAMILY = 'astrolabe.code.fontFamily'
const DEFAULT_CODE_FONT_FAMILY = CODE_FONT_STACKS[0].value

/** 读字号：只校验范围，⛔ 不再限定几个固定档位（用户可自己填 13、15.5 等） */
export function getCodeFontSize(): number {
  try {
    const n = Number(localStorage.getItem(KEY_CODE_FONT_SIZE))
    return Number.isFinite(n) && n >= CODE_FONT_MIN && n <= CODE_FONT_MAX
      ? n
      : DEFAULT_CODE_FONT_SIZE
  } catch {
    return DEFAULT_CODE_FONT_SIZE
  }
}

export function getCodeFontFamily(): string {
  try {
    return localStorage.getItem(KEY_CODE_FONT_FAMILY) || DEFAULT_CODE_FONT_FAMILY
  } catch {
    return DEFAULT_CODE_FONT_FAMILY
  }
}

/**
 * ★ 把偏好写到根元素的 CSS 变量。
 * 应用启动时调一次（`main.tsx`），设置页点「确认」后再调一次。
 */
export function applyCodePrefs(): void {
  const root = document.documentElement
  root.style.setProperty('--code-font-size', `${getCodeFontSize()}px`)
  root.style.setProperty('--code-font-family', getCodeFontFamily())
}

export interface AppearancePrefs {
  meteors: boolean
  fontSize: number
  fontFamily: string
}

/** 读已保存的外观（设置页用它初始化「草稿」与「已保存」两份） */
export function getAppearance(): AppearancePrefs {
  return {
    meteors: getMeteors(),
    fontSize: getCodeFontSize(),
    fontFamily: getCodeFontFamily(),
  }
}

/** ★★ **全局确认**：三项一次性写入 + 一次下发（⛔ 不要每项单独保存/确认） */
export function saveAppearance(p: AppearancePrefs): void {
  try {
    localStorage.setItem(KEY_METEORS, p.meteors ? '1' : '0')
    localStorage.setItem(KEY_CODE_FONT_SIZE, String(p.fontSize))
    localStorage.setItem(KEY_CODE_FONT_FAMILY, p.fontFamily)
  } catch {
    /* 存不了就用本次会话的值，不抛错 */
  }
  applyCodePrefs()
}
