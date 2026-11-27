import { EditorState, StateEffect, StateField, type Extension } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  type DecorationSet,
  drawSelection,
  dropCursor,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search'
import {
  HighlightStyle,
  bracketMatching,
  foldGutter,
  indentOnInput,
  syntaxHighlighting,
} from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

/**
 * ★★ CodeMirror 6 的只读配置（代码展示用）
 *
 * ⚠ 这些包**本来就在依赖树里**（Milkdown 的代码块就是 CM6 渲染的），
 *   现在只是显式声明后直接使用；以后做「仿写」只需把 readOnly/editable 去掉。
 *
 * ⚠ 语言包**按需动态 import** ⇒ 不把十几种解析器塞进首屏
 */

/** 语法配色：接到站点 CSS 变量上（沿用 MilkdownEditor 里那套 `--code-*` 口径） */
const codeHighlight = HighlightStyle.define([
  // ★★★ 关键字**按语义分色**（所有者：「关键字都是一个颜色，没有区分，看着很单调」）
  //   ⚠ @lezer/highlight 里这些都是 t.keyword 的子 tag，语言包打了哪个就用哪个色；
  //     只打通用 keyword 的语法走最后那条兜底。
  //   ⚠ 放在数组最前：后面 t.bool / t.null 等更具体的规则仍能覆盖它们。
  { tag: t.controlKeyword,    color: 'var(--code-kw-control, #7c3aed)',  fontWeight: '600' }, // if/else/for/return/try
  { tag: t.definitionKeyword, color: 'var(--code-kw-define, #c026d3)',   fontWeight: '600' }, // def/class/struct/func
  { tag: t.moduleKeyword,     color: 'var(--code-kw-module, #0891b2)',   fontWeight: '600' }, // import/from/export/use
  { tag: t.operatorKeyword,   color: 'var(--code-kw-operator, #c2410c)', fontWeight: '600' }, // and/or/not/is/in/as
  { tag: t.modifier,          color: 'var(--code-kw-modifier, #4f46e5)', fontWeight: '600' }, // public/static/const/async
  { tag: t.keyword,           color: 'var(--code-kw, #7c3aed)',          fontWeight: '600' }, // 兜底：未细分的关键字
  { tag: [t.string, t.special(t.string)], color: 'var(--code-str, #0a7d47)' },
  { tag: t.comment, color: 'var(--code-comment, #94a3b8)', fontStyle: 'italic' },
  { tag: [t.number, t.bool, t.null], color: 'var(--code-num, #b45309)' },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: 'var(--code-fn, #1d4ed8)' },
  { tag: [t.definition(t.variableName), t.className, t.typeName], color: 'var(--code-type, #0369a1)' },
  { tag: t.operator, color: 'var(--text-sub, #64748b)' },
  { tag: t.invalid, color: 'var(--err, #dc2626)' },
])

/** 外观：透明底、跟随站点变量；目标行用一条淡色底 + 左侧竖线 */
const codeTheme = EditorView.theme(
  {
    '&': {
      height: '100%',
      backgroundColor: 'transparent',
      color: 'var(--text-main, #1f2937)',
      // ★ 设置 → 外观 可调（lib/uiPrefs 下发 CSS 变量，改完立刻生效）
      fontSize: 'var(--code-font-size, 12.5px)',
    },
    '.cm-scroller': {
      overflow: 'auto',
      fontFamily:
        'var(--code-font-family, ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace)',
      lineHeight: '1.65',
    },
    '.cm-content': { caretColor: 'transparent', padding: '8px 0' },
    '.cm-gutters': {
      backgroundColor: 'transparent',
      border: 'none',
      color: 'var(--text-faint, #94a3b8)',
      minWidth: '44px',
    },
    '.cm-activeLine': { backgroundColor: 'rgba(37,99,235,.045)' },
    '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--text-sub)' },
    '.cm-cmFocusLine': {
      backgroundColor: 'rgba(37,99,235,.10)',
      boxShadow: 'inset 3px 0 0 var(--accent, #2563eb)',
    },
    '.cm-selectionBackground, &.cm-focused .cm-selectionBackground':
      { backgroundColor: 'rgba(37,99,235,.18)' },
    '&.cm-focused': { outline: 'none' },
  },
  { dark: false },
)

/** ★ 把「当前节点所在行」做成可更新的 decoration */
export const setFocusLine = StateEffect.define<number | null>()

const focusLineField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    let next = value.map(tr.changes)
    for (const e of tr.effects) {
      if (!e.is(setFocusLine)) continue
      if (e.value == null) {
        next = Decoration.none
        continue
      }
      const doc = tr.state.doc
      const n = Math.max(1, Math.min(doc.lines, e.value))
      const from = doc.line(n).from
      next = Decoration.set([
        Decoration.line({ class: 'cm-cmFocusLine' }).range(from),
      ])
    }
    return next
  },
  provide: (f) => EditorView.decorations.from(f),
})

/** 滚到某行并把它高亮（行号从 1 开始） */
export function focusLine(view: EditorView, line: number | null) {
  if (!line || line < 1) {
    view.dispatch({ effects: setFocusLine.of(null) })
    return
  }
  const doc = view.state.doc
  const n = Math.max(1, Math.min(doc.lines, line))
  const pos = doc.line(n).from
  view.dispatch({
    effects: [
      setFocusLine.of(n),
      EditorView.scrollIntoView(pos, { y: 'center' }),
    ],
    selection: { anchor: pos },
  })
}

/** 基础扩展（不含语言包）；`readOnly: false` 即可编辑（仿写用） */
export function baseExtensions({ readOnly = true }: { readOnly?: boolean } = {}): Extension[] {
  return [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightSpecialChars(),
    history(),
    foldGutter(),
    drawSelection(),
    dropCursor(),
    EditorState.allowMultipleSelections.of(true),
    indentOnInput(),
    bracketMatching(),
    syntaxHighlighting(codeHighlight),
    highlightActiveLine(),
    highlightSelectionMatches(),
    focusLineField,
    keymap.of([
      ...defaultKeymap,
      ...searchKeymap,
      ...historyKeymap,
      indentWithTab,
    ]),
    codeTheme,
    // ★★ 只读 / 可编辑：仿写传 readOnly:false，其余配置完全复用
    ...(readOnly ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : []),
  ]
}

type LangLoader = () => Promise<Extension>

/** 语言包按需加载；认不出的语言就用纯文本（照样能看、能搜、能复制） */
const loaders: Record<string, LangLoader> = {
  python: async () => (await import('@codemirror/lang-python')).python(),
  javascript: async () => (await import('@codemirror/lang-javascript')).javascript(),
  typescript: async () =>
    (await import('@codemirror/lang-javascript')).javascript({ typescript: true, jsx: true }),
  java: async () => (await import('@codemirror/lang-java')).java(),
  c: async () => (await import('@codemirror/lang-cpp')).cpp(),
  cpp: async () => (await import('@codemirror/lang-cpp')).cpp(),
  go: async () => (await import('@codemirror/lang-go')).go(),
  rust: async () => (await import('@codemirror/lang-rust')).rust(),
  sql: async () => (await import('@codemirror/lang-sql')).sql(),
  json: async () => (await import('@codemirror/lang-json')).json(),
  markdown: async () => (await import('@codemirror/lang-markdown')).markdown(),
  yaml: async () => (await import('@codemirror/lang-yaml')).yaml(),
  html: async () => (await import('@codemirror/lang-html')).html(),
  css: async () => (await import('@codemirror/lang-css')).css(),
}

export async function loadLanguage(lang: string): Promise<Extension | null> {
  const loader = loaders[lang]
  if (!loader) return null
  try {
    return await loader()
  } catch {
    return null // 某个语言包加载失败 ⇒ 退化为纯文本，不阻断看代码
  }
}
