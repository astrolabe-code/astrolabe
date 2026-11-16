import { Crepe, CrepeFeature } from '@milkdown/crepe'
import { HighlightStyle, LanguageDescription, syntaxHighlighting } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { EditorView } from '@codemirror/view'
import { useRef } from 'react'
import { Milkdown, MilkdownProvider, useEditor } from '@milkdown/react'
import { uploadConfig } from '@milkdown/kit/plugin/upload'
import { $prose } from '@milkdown/utils'
import { Plugin, PluginKey } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet } from '@milkdown/kit/prose/view'
import type { EditorView as PmEditorView } from '@milkdown/kit/prose/view'
// ★ 排版（标题字号 / 段落 / 列表 / 表格…）都在这份里，⚠ 少引它标题就全是同字号
import '@milkdown/crepe/theme/common/style.css'
import '@milkdown/crepe/theme/nord.css'
import '@milkdown/crepe/theme/frame.css'

/** ★ 暴露给外层的句柄（* 保存时读最新正文）⚠ */
export interface MilkdownEditorApi {
  getMarkdown: () => string
  /** 在光标处显示浅色补全（空串 = 清除） */
  setGhost: (text: string) => void
  clearGhost: () => void
  /** 光标前的内容 + 整篇 + 是否在段落末尾（决定要不要请求补全） */
  getContext: () => {
    before: string
    /** 光标前的**全部**文字（换行后当前段落为空时用它兜底） */
    context: string
    doc: string
    atEnd: boolean
    ready: boolean
  }
}

/**
 * ★★ **行内补全（ghost text）**
 *
 * 所有者原话（2026-11-16）：
 * 「我希望是用户自己书写理解，而不是ai帮用户书写。书写的障碍之一是语言表达…
 *   能不能像补全代码一样，在用户书写 markdown 文档时，用浅色字给出接下来的十几个字？」
 *
 * 做法：ProseMirror 的 `Decoration.widget` 在光标处插一段**不可编辑**的浅色文字。
 *   · `Tab` 接受（插入正文）
 *   · `Esc` 忽略
 *   · 继续打字 —— 文档一改就自动消失（`tr.docChanged ⇒ ''`）
 */
const ghostKey = new PluginKey<string>('astrolabe-ghost')
/** 当前编辑器的 PM 视图（插件 view() 里拿，⛔ 不依赖 editorViewCtx） */
let ghostView: PmEditorView | null = null

const ghostPlugin = $prose(
  () =>
    new Plugin<string>({
      key: ghostKey,
      view: (view) => {
        ghostView = view
        return {
          destroy: () => {
            if (ghostView === view) ghostView = null
          },
        }
      },
      state: {
        init: () => '',
        apply(tr, value) {
          const meta = tr.getMeta(ghostKey)
          if (meta !== undefined) return String(meta)
          // ★ 用户一动键盘/一粘贴，提示立刻消失（⛔ 不和他抢字）
          if (tr.docChanged) return ''
          return value
        },
      },
      props: {
        handleKeyDown(view, event) {
          const text = ghostKey.getState(view.state) || ''
          if (!text) return false
          if (event.key === 'Tab') {
            view.dispatch(view.state.tr.insertText(text))
            return true
          }
          if (event.key === 'Escape') {
            view.dispatch(view.state.tr.setMeta(ghostKey, ''))
            return true
          }
          return false
        },
        decorations(state) {
          const text = ghostKey.getState(state) || ''
          if (!text) return null
          const { $from } = state.selection
          if (!$from.parent.isTextblock) return null
          return DecorationSet.create(state.doc, [
            Decoration.widget(
              $from.pos,
              () => {
                const span = document.createElement('span')
                span.className = 'ghost-text'
                span.textContent = text
                return span
              },
              { side: 1 },
            ),
          ])
        },
      },
    }),
)

/**
 * ★★ **Markdown 编辑器**（`D108` 第 ③ 步）⚠
 *
 * ## ★★ 与只读版的区别
 *
 * ```
 * MilkdownView（阅读页）  setReadonly(true)  ⇒ editable: () => false
 * MilkdownEditor（本组件）默认可编辑          ⇒ 工具栏 / 斜杠菜单都在
 * ```
 *
 * ## ★★ 谁能编辑
 *
 * ```
 * ⚠ 前端只是"少一次无用请求"——真正的闸门在后端 canWrite：
 *   · · NoteEditor 这个弹窗本来就只有作者打得开（NotePage 的入口带 canWrite）
 *   · · 后端 PATCH 照样校验权限 ⇒ 前端被绕过也改不了 ✅
 * ```
 *
 * ⚠ 序列化会改原文（`1)`→`1.`、`---`→`***`）⇒ 已做一次性迁移
 *   （`core/migrations/0049_editor_canonical.py`），* 之后保存不再变指纹 ✅
 */
/** ★★★ 代码块语言（* 按需动态加载，⛔ 不一次性打进主包）⚠ */
const CODE_LANGUAGES = [
  LanguageDescription.of({
    name: 'JavaScript',
    alias: ['js', 'jsx'],
    load: () => import('@codemirror/lang-javascript').then((m) => m.javascript({ jsx: true })),
  }),
  LanguageDescription.of({
    name: 'TypeScript',
    alias: ['ts', 'tsx'],
    load: () =>
      import('@codemirror/lang-javascript').then((m) => m.javascript({ typescript: true, jsx: true })),
  }),
  LanguageDescription.of({
    name: 'Python',
    alias: ['py'],
    load: () => import('@codemirror/lang-python').then((m) => m.python()),
  }),
  LanguageDescription.of({
    name: 'Java',
    load: () => import('@codemirror/lang-java').then((m) => m.java()),
  }),
  LanguageDescription.of({
    name: 'C++',
    alias: ['cpp', 'c'],
    load: () => import('@codemirror/lang-cpp').then((m) => m.cpp()),
  }),
  LanguageDescription.of({
    name: 'Go',
    load: () => import('@codemirror/lang-go').then((m) => m.go()),
  }),
  LanguageDescription.of({
    name: 'Rust',
    load: () => import('@codemirror/lang-rust').then((m) => m.rust()),
  }),
  LanguageDescription.of({
    name: 'SQL',
    load: () => import('@codemirror/lang-sql').then((m) => m.sql()),
  }),
  LanguageDescription.of({
    name: 'HTML',
    alias: ['xml'],
    load: () => import('@codemirror/lang-html').then((m) => m.html()),
  }),
  LanguageDescription.of({
    name: 'CSS',
    load: () => import('@codemirror/lang-css').then((m) => m.css()),
  }),
  LanguageDescription.of({
    name: 'JSON',
    load: () => import('@codemirror/lang-json').then((m) => m.json()),
  }),
  LanguageDescription.of({
    name: 'YAML',
    alias: ['yml'],
    load: () => import('@codemirror/lang-yaml').then((m) => m.yaml()),
  }),
  LanguageDescription.of({
    name: 'Markdown',
    alias: ['md'],
    load: () => import('@codemirror/lang-markdown').then((m) => m.markdown()),
  }),
]

/**
 * ★★ **CodeMirror 外观**：透明底 + 站点配色（2026-10-24）⚠
 *
 * ⚠ Crepe 的默认 featureConfigs 里写死了 `theme: oneDark`
 *   ⇒ 代码块是深色底 + 紫色关键字，* 与阅读页完全不是一套 ⚠
 *   ⇒ 传入自己的 theme 顶掉它 ✅
 */
const CODE_THEME = EditorView.theme({
  '&': { backgroundColor: 'transparent', color: 'var(--code-text)' },
  '.cm-content': { caretColor: 'var(--text-main)' },
  '.cm-gutters': {
    backgroundColor: 'transparent',
    color: 'var(--code-dim)',
    border: 'none',
  },
  '.cm-activeLine': { backgroundColor: 'transparent' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent' },
  '.cm-selectionBackground, ::selection': { backgroundColor: 'rgba(77, 184, 214, 0.25)' },
})

/**
 * ★★ **CodeMirror 的配色**：接到站点 `--code-*` 变量上（2026-10-24）⚠
 *
 * ⚠ 不这么做的话 CM 会用自带高亮配色 —— 与阅读页（Prism）不一致 ⚠
 */
const CODE_HIGHLIGHT = syntaxHighlighting(
  HighlightStyle.define([
    {
      tag: [tags.keyword, tags.controlKeyword, tags.definitionKeyword],
      color: 'var(--code-key)',
      fontWeight: '600',
    },
    { tag: [tags.string, tags.special(tags.string), tags.regexp], color: 'var(--code-str)' },
    { tag: [tags.function(tags.variableName), tags.className, tags.typeName], color: 'var(--code-fn)' },
    { tag: [tags.comment, tags.lineComment, tags.blockComment], color: 'var(--code-com)', fontStyle: 'italic' },
    { tag: [tags.number, tags.bool, tags.null, tags.atom], color: 'var(--code-num)' },
    { tag: [tags.propertyName, tags.attributeName, tags.variableName], color: 'var(--code-dec)' },
    { tag: [tags.operator, tags.punctuation, tags.bracket], color: 'var(--code-dim)' },
  ]),
)


export default function MilkdownEditor({
  initial,
  apiRef,
  onRejectUpload,
  onChange,
}: {
  initial: string
  /** ★ 父组件的 ref —— 编辑器就绪后把句柄塞进去（* 保存时读它）⚠ */
  apiRef: React.MutableRefObject<MilkdownEditorApi | null>
  /** ★ 有人拖/粘图片进来时通知外层（* 站点不支持上传）⚠ */
  onRejectUpload?: () => void
  /**
   * ★★ 正文变化时回调（2026-10-27）⚠
   *
   * ⚠⚠ **危险 API，接之前先看这段** ⚠⚠
   *
   * ```\n   * 错误用法（2026-10-27 踩过，表现为「写作页面抖动太厉害」）：\n   *   <MilkdownEditor initial={body} onChange={setBody} />\n   *   ⇒ body 一变 ⇒ initial 变 ⇒ useEditor 的依赖变 ⇒ **编辑器被销毁重建**\n   *   ⇒ 每敲几下抖一次、光标乱跳 ⚠\n   * ```\n
   * ✅ 正确用法：**只在 `initial` 不随 state 变化时**接（例如独立的预览面板）。
   * 需要「正文 → 外层」的场合，改成**保存时读一次** `apiRef.current.getMarkdown()`。
   *
   * 原用途（* 已被上面这条取代）：编辑页「不填名字会叫什么」的实时预览。
   * ⚠ 只在**防抖 300ms** 后触发一次，⛔ 不是每次击键都回调（序列化整篇很贵）⚠
   */
  onChange?: (markdown: string) => void
}) {
  return (
    <MilkdownProvider>
      <Inner
        initial={initial}
        apiRef={apiRef}
        onRejectUpload={onRejectUpload}
        onChange={onChange}
      />
    </MilkdownProvider>
  )
}

function Inner({
  initial,
  apiRef,
  onRejectUpload,
  onChange,
}: {
  initial: string
  apiRef: React.MutableRefObject<MilkdownEditorApi | null>
  onRejectUpload?: () => void
  onChange?: (markdown: string) => void
}) {
  // ⚠ 用 ref 存回调：`useEditor` 的 deps 里只有 `initial`
  //   ⇒ 把 `onChange` 放进依赖会**重建编辑器**（光标丢失）⚠
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  useEditor(
    (root) => {
      const crepe = new Crepe({
        root,
        defaultValue: initial,
        // ★★★ **关掉块手柄**（2026-10-27）⚠
        //   · · 所有者：「正文每段前有个加号和六个点是什么东西？」→「关掉吧，obsidian 都没有这东西。」
        //   · · 那两样是 Crepe 的 `BlockEdit`（`+` 插入块 / `⋮⋮` 拖动排序），
        //     只在光标所在块旁淡入（实测 opacity 0 → 1）⚠
        //   · · ⛔ 读者页（`MilkdownView`）本来就关着它 —— 这里补齐，编辑页也不要 ✅
        features: {
          [CrepeFeature.BlockEdit]: false,
        },
        // ★★★ **编辑器保留 CodeMirror**（2026-10-24）⚠
        //   · · CM 的 `basicSetup` 自带行号（lineNumbers）✅
        //   · · 但默认 `languages: []` ⇒ 没有语法高亮 ⇒ 这里补上语言包
        //   · · 配色再接到站点 `--code-*`，* 与阅读页（Prism）视觉一致 ✅
        featureConfigs: {
          // ★ Crepe 的默认占位文案是英文「Please enter...」——
          //   所有者反复要求「不要整英文呀，用中文写」⇒ 换掉 ⚠
          [CrepeFeature.Placeholder]: {
            text: '写点什么…',
            mode: 'doc',
          },
          [CrepeFeature.CodeMirror]: {
            languages: CODE_LANGUAGES,
            // ★ theme 必须显式给：* 否则用 Crepe 默认的 oneDark ⚠
            theme: CODE_THEME,
            extensions: [CODE_HIGHLIGHT],
          },
        },
      })

      // ★★★ **站点不提供图片上传**（所有者：*「网站不能随便传一些图片上去展示」）⚠
      //   · · Crepe 默认回调是 `URL.createObjectURL(file)` ⇒ 存的是 `blob:` 本地地址，
      //     * 刷新即失效、别人看不到 ⚠
      //   · · 这里把 uploader 改成空实现 ⇒ **什么都不插入** ✅
      crepe.editor.config((ctx) => {
        ctx.update(uploadConfig.key, (prev) => ({ ...prev, uploader: async () => [] }))
      })

      // ⚠★ 这里**不再**挂 `makeHighlightPlugin`（2026-10-24）⚠
      //   · · 编辑器代码块由 CodeMirror 渲染，* PM 装饰器进不去其 DOM，
      //     挂了也只是每次改动白算一遍 Prism ⇒ 已移除 ✅
      //   · · 编辑器的高亮/行号分别来自 CM 语言包与 `basicSetup` ⚠
      // ★ 注册行内补全插件
      crepe.editor.use(ghostPlugin)

      // ★ 句柄直接塞进父组件的 ref（* 不靠回调，* 避免时序问题）⚠
      const setGhost = (text: string) => {
        if (!ghostView) return
        ghostView.dispatch(ghostView.state.tr.setMeta(ghostKey, text || ''))
      }
      apiRef.current = {
        getMarkdown: () => crepe.getMarkdown(),
        setGhost,
        clearGhost: () => setGhost(''),
        getContext: () => {
          if (!ghostView) {
            return { before: '', context: '', doc: '', atEnd: false, ready: false }
          }
          const { $from, from } = ghostView.state.selection
          const before = $from.parent.textBetween(0, $from.parentOffset, '\n', ' ')
          // ★ 刚敲完回车时当前段落是空的 —— 用光标前的全部文字兜底，
          //   否则会误报「上文太短」，而他明明刚写完一整段。
          const context = ghostView.state.doc.textBetween(0, from, '\n', ' ')
          return {
            before,
            context,
            doc: crepe.getMarkdown(),
            atEnd: $from.parentOffset >= $from.parent.content.size,
            ready: true,
          }
        },
      }

      // ★★ 正文变化 ⇒ 防抖 300ms 后回调（2026-10-27）⚠
      //   · · ⛔ 不做防抖的话，每敲一个字都要 `getMarkdown()` 序列化整篇 ⚠
      if (onChangeRef.current) {
        let timer: ReturnType<typeof setTimeout> | null = null
        crepe.on((listener) => {
          listener.markdownUpdated((_ctx, markdown) => {
            if (timer) clearTimeout(timer)
            timer = setTimeout(() => onChangeRef.current?.(markdown), 300)
          })
        })
      }
      return crepe.editor
    },
    [initial],
  )

  // ★ 外层包一层：* 便于给编辑器单独定左右留白（块手柄要位置）⚠
  // ★ 拖拽 / 粘贴图片 ⇒ 拦下来并提示（* uploader 已空，但静默没反应很困惑）⚠
  const guard = (e: React.DragEvent | React.ClipboardEvent) => {
    const files = 'dataTransfer' in e ? e.dataTransfer?.files : (e as React.ClipboardEvent).clipboardData?.files
    if (!files || !files.length) return
    const images = Array.from(files).filter((f) => f.type.startsWith('image/'))
    if (!images.length) return
    e.preventDefault()
    e.stopPropagation()
    onRejectUpload?.()
  }

  return (
    <div className="milkdown-editor" onDropCapture={guard} onPasteCapture={guard}>
      <Milkdown />
    </div>
  )
}
