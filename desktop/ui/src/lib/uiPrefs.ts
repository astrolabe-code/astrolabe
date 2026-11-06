/**
 * ★★ 个人版的界面偏好（本地存储，不需要后端）⚠
 *
 * 目前有三项：
 * ```
 * 流星特效     图谱里节点之间飞过的流光
 * 代码字号     CodeMirror 的字体大小
 * 代码字体     CodeMirror 的等宽字体栈
 * ```
 *
 * 为什么单独抽出来：
 *   它们原来散在图谱页的「工具」下拉里 —— 所有者（2026-11-05）：
 *   「流星这个应该在设置页面出现，怎么出现在这个下拉栏了？」
 *   ⇒ 统一移到 设置 → 外观，页面只读这里的值。
 *
 * ⚠ 代码外观用 **CSS 变量**下发（`--code-font-size` / `--code-font-family`），
 *   CodeMirror 的 theme 读变量 ⇒ 改设置**立刻生效**，不用重建编辑器。
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

/** 写「流星」开关 */
export function setMeteors(on: boolean): void {
  try {
    localStorage.setItem(KEY_METEORS, on ? '1' : '0')
  } catch {
    /* 存不了就算了，下次还是默认开 */
  }
}

// ---------------------------------------------------------------- 代码外观

/** 代码字号档位（px）；默认 12.5，与原来的写死值一致 */
export const CODE_FONT_SIZES = [11, 12.5, 14, 16, 18] as const

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
const DEFAULT_CODE_FONT_SIZE = 12.5
const DEFAULT_CODE_FONT_FAMILY = CODE_FONT_STACKS[0].value

export function getCodeFontSize(): number {
  try {
    const n = Number(localStorage.getItem(KEY_CODE_FONT_SIZE))
    return CODE_FONT_SIZES.some((x) => x === n) ? n : DEFAULT_CODE_FONT_SIZE
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
 * 应用启动时调一次（`main.tsx`），改设置时再调一次 ⇒ 已打开的代码窗口即时刷新。
 */
export function applyCodePrefs(): void {
  const root = document.documentElement
  root.style.setProperty('--code-font-size', `${getCodeFontSize()}px`)
  root.style.setProperty('--code-font-family', getCodeFontFamily())
}

export function setCodeFontSize(px: number): void {
  try {
    localStorage.setItem(KEY_CODE_FONT_SIZE, String(px))
  } catch {
    /* 存不了就用本次会话的值 */
  }
  applyCodePrefs()
}

export function setCodeFontFamily(stack: string): void {
  try {
    localStorage.setItem(KEY_CODE_FONT_FAMILY, stack)
  } catch {
    /* 存不了就用本次会话的值 */
  }
  applyCodePrefs()
}
