import { useRef } from 'react'
import { Crepe, CrepeFeature } from '@milkdown/crepe'
import { Milkdown, useEditor } from '@milkdown/react'
import { $prose } from '@milkdown/utils'
import type { EditorState } from 'prosemirror-state'
import { Plugin, TextSelection } from 'prosemirror-state'
import type { EditorView } from 'prosemirror-view'
import { Decoration, DecorationSet } from 'prosemirror-view'
// ★ 排版（标题字号 / 段落 / 列表 / 表格…）都在这份里，⚠ 少引它标题就全是同字号
import '@milkdown/crepe/theme/common/style.css'
import '@milkdown/crepe/theme/nord.css'
import '@milkdown/crepe/theme/frame.css'

/** ★ 一个「段」—— 后端 blocks 的一条（* `graph/notes.py::split_blocks`）⚠ */
export interface NoteBlockInfo {
  fingerprint: string
  text: string
  comment_count: number
}

/**
 * ★★ **Markdown 只读渲染 + 段评气泡**（`D108` 第 ② 步 / `B242`）⚠
 *
 * ## ★★ 1. 为什么必须只读
 *
 * ```
 * Milkdown 是「边编辑边展示」的编辑器 ⇒ 谁能编辑，谁就能改正文
 *   · · 阅读页必须只读（* 非作者点进来一个字都不能改）⚠
 *   · · 编辑能力只在 NoteEditor 里开，且由后端 canWrite 把关 ✅
 * ```
 *
 * ## ★★ 2. 气泡怎么挂（* 整篇渲染最大的集成点）
 *
 * ```
 * 旧：每段一个 React 元素，气泡是 trailing 插槽
 *      ⇒ 整篇渲染后段落变成 ProseMirror 节点，塞不进 React 元素 ⚠
 * 新：ProseMirror Decoration.widget —— 在段落节点末尾插 DOM 按钮，
 *     点击通过回调通知 React ✅
 *     B242 之后「后端 block」与「PM 顶层节点」按结构一一对应
 *     ⇒ 优先按序号对齐；对不上再按文本贪婪匹配兜底 ⚠
 * ```
 */
export default function MilkdownView({
  text,
  blocks = [],
  onOpenBlock,
  authed = false,
  onSelection,
}: {
  text: string
  blocks?: NoteBlockInfo[]
  onOpenBlock?: (block: NoteBlockInfo) => void
  /** ★ 是否登录（* 未登录不拦右键菜单）⚠ */
  authed?: boolean
  /**
   * ★★ **选区变化**（* 2026-10-23）：选中文字 ⇒ 回信息，选区没了 ⇒ 回 null ⚠
   *   · · ⛔ 不再用右键菜单 —— 所有者：「不要右键弹出评论按钮了……评论按钮和
   *     原生的浏览器右键弹窗同时出现了」⚠
   */
  onSelection?: (info: SelectionInfo | null) => void
}) {
  // ★ 用 ref 存最新的 blocks / 回调 —— decorations 每次重绘都读它，
  //   这样「新来一条评论」不用重建整个编辑器 ✅
  const blocksRef = useRef<NoteBlockInfo[]>(blocks)
  blocksRef.current = blocks
  const cbRef = useRef(onOpenBlock)
  cbRef.current = onOpenBlock
  const authedRef = useRef(authed)
  authedRef.current = authed
  const selRef = useRef(onSelection)
  selRef.current = onSelection

  useEditor(
    (root) => {
      const crepe = new Crepe({
        root,
        defaultValue: text,
        // ★ 只留渲染需要的特性，编辑态的一概关掉
        //   ⚠ Latex / AI 依赖 CodeMirror ⇒ 必须一起关，否则 create() 直接抛错
        features: {
          // ⚠★ 块操作手柄（悬停出现的「+」和拖拽点，点开是 text / advanced / list 菜单）
          //   * 阅读页绝不能有 —— 那是编辑器的东西，所有者实测发现了 ⚠
          [CrepeFeature.BlockEdit]: false,
          // ⚠★ 图片块容器（占位灰框 + 上传/删除操作按钮）—— 阅读页只要一张图
          //   * 关掉后退化成普通 <img>（commonmark 的 image 节点）⚠
          [CrepeFeature.ImageBlock]: false,
          [CrepeFeature.Toolbar]: false,
          [CrepeFeature.CodeMirror]: false,
          [CrepeFeature.LinkTooltip]: false,
          [CrepeFeature.Latex]: false,
          [CrepeFeature.AI]: false,
          [CrepeFeature.Placeholder]: false,
          [CrepeFeature.Cursor]: false,
          [CrepeFeature.TopBar]: false,
        },
      })
      crepe.setReadonly(true)
      crepe.editor.use(makeBubblePlugin(blocksRef, cbRef, selRef, authedRef))
      return crepe.editor
    },
    [text],
  )

  return <Milkdown />
}

// ---------------------------------------------------------------------------
// 段评气泡插件
// ---------------------------------------------------------------------------

/**
 * ★★ **把选区扩到"段"**（* 顶层块，与后端 `split_blocks` 口径一致）⚠
 *
 * ## ★★★ 所有者原话（逐字）
 *
 * > 「阅读页面下，选中文字后自动扩成最近的一段，跨段就把跨的段全选上。」
 *
 * ## ★ 规则
 *
 * ```
 * 只选了几个字   ⇒ 扩成所在的那一整段
 * 跨了两段以上   ⇒ 从第一段开头到最末段结尾（中间各段全含）
 * 空选区（单击） ⇒ 不动 ⚠
 * ```
 */
function expandToBlocks(view: EditorView): void {
  const state = view.state
  const sel = state.selection
  if (sel.empty) return

  const { $from, $to } = sel
  // ⚠ 顶层块 = doc 的第 1 层（* 列表 / 引用 / 代码块都算一个整块）⚠
  if ($from.depth < 1 || $to.depth < 1) return

  let from: number
  let to: number
  try {
    from = $from.start(1)
    to = $to.end(1)
  } catch {
    return
  }
  if (from === sel.from && to === sel.to) return
  if (to <= from) return

  const tr = state.tr.setSelection(TextSelection.create(state.doc, from, to))
  view.dispatch(tr)
}


/** ★ 右键选中文字后回给外层的信息 ⚠ */
export interface SelectionInfo {
  /** 选中文字所属的那一段（* 找不到就 undefined）⚠ */
  block?: NoteBlockInfo
  /** 选中的原文（* 后端存 quote 快照）⚠ */
  quote: string
  /** 选区在视口里的位置（* 浮动工具条据此定位）⚠ */
  rect: { top: number; left: number; width: number; height: number }
}

/**
 * ★★ **把当前选区上报给外层**（* 浮动工具条据此出现）⚠
 *
 * ```
 * 有选区 ⇒ 算出所属段 + 原文 + 视口矩形
 * 无选区 ⇒ 回 null（工具条收起）
 * ```
 */
function reportSelection(
  view: EditorView,
  cb: ((i: SelectionInfo | null) => void) | undefined,
  list: NoteBlockInfo[],
): void {
  if (!cb) return
  const sel = window.getSelection()
  const text = (sel?.toString() || '').trim()
  if (!sel || !text || sel.rangeCount === 0) {
    cb(null)
    return
  }

  // ★ 选中位置 ⇒ 顶层节点下标 ⇒ 反查段下标
  //   ⚠ 不能爬 DOM：Milkdown 在 .ProseMirror 里还套了一层 div，
  //     爬上去会停在外层容器上（* 实测踩过）⇒ 用 PM 的位置反解 ✅
  let nodeIdx = -1
  try {
    const anchorNode = sel.anchorNode
    if (anchorNode) {
      const pos = view.posAtDOM(anchorNode, 0)
      view.state.doc.forEach((n, offset, index) => {
        if (nodeIdx < 0 && pos >= offset && pos <= offset + n.nodeSize) nodeIdx = index
      })
    }
  } catch {
    nodeIdx = -1
  }

  let block: NoteBlockInfo | undefined
  if (nodeIdx >= 0) {
    const nodes = topNodes(view.state)
    const map = alignBlocks(nodes, list)
    const blockIdx = map.indexOf(nodeIdx)
    if (blockIdx >= 0) block = list[blockIdx]
  }

  const r = sel.getRangeAt(0).getBoundingClientRect()
  cb({
    block,
    quote: text.length > 200 ? `${text.slice(0, 200)}…` : text,
    rect: { top: r.top, left: r.left, width: r.width, height: r.height },
  })
}


/** 顶层节点 + 它在文档里的结束位置 */
interface TopNode {
  end: number
  plain: string
}

/** ① 取出所有顶层节点（* 顺序即文档顺序）⚠ */
function topNodes(state: EditorState): TopNode[] {
  const out: TopNode[] = []
  state.doc.forEach((node, offset) => {
    out.push({ end: offset + node.nodeSize, plain: loose(node.textContent) })
  })
  return out
}

/** ② 决定「第 i 个后端 block」对应哪个顶层节点（* -1 = 挂不上）⚠ */
function alignBlocks(nodes: TopNode[], list: NoteBlockInfo[]): number[] {
  if (nodes.length === list.length) return list.map((_, i) => i)

  // 兜底：按文本贪婪匹配（* 结构对不上时尽力而为）
  const map: number[] = []
  let from = 0
  for (const b of list) {
    const want = loose(b.text)
    let hit = -1
    for (let i = from; i < nodes.length; i++) {
      if (nodes[i].plain === want || nodes[i].plain.includes(want)) {
        hit = i
        break
      }
    }
    if (hit < 0) {
      for (let i = 0; i < from; i++) {
        if (nodes[i].plain === want) hit = i
      }
    }
    map.push(hit)
    if (hit >= 0) from = hit + 1
  }
  return map
}

/** ③ 造一个气泡按钮 DOM ⚠ */
function bubbleButton(b: NoteBlockInfo, cb: () => void): HTMLElement {
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.className = 'block-bubble'
  btn.textContent = `${b.comment_count} 段评`
  btn.title = '查看 / 写段评'
  btn.addEventListener('click', (e) => {
    e.preventDefault()
    e.stopPropagation()
    cb()
  })
  return btn
}

function makeBubblePlugin(
  blocksRef: { current: NoteBlockInfo[] },
  cbRef: { current: ((b: NoteBlockInfo) => void) | undefined },
  selRef: { current: ((i: SelectionInfo | null) => void) | undefined },
  authedRef: { current: boolean },
) {
  return $prose(
    () =>
      new Plugin({
        props: {
          // ★★ 右键：选中了文字 ⇒ 弹「写段评」（* 番茄小说那种）⚠
          //   · · 没选中 / 未登录 ⇒ 放行原生菜单 ✅
          handleDOMEvents: {
            // ★★ 选中文字 ⇒ ① 自动扩到整段 ② 上报选区给外层弹浮动工具条 ⚠
            //   · · 用 setTimeout 0：mouseup 时浏览器还没把选区落到 ProseMirror ⚠
            //   · · 单击（空选区）⇒ 上报 null，工具条收起 ✅
            mouseup: (view) => {
              setTimeout(() => {
                expandToBlocks(view)
                reportSelection(view, selRef.current, blocksRef.current)
              }, 0)
              return false
            },
          },
          decorations: (state: EditorState) => {
            const list = blocksRef.current
            if (!list.length) return DecorationSet.empty

            const nodes = topNodes(state)
            const map = alignBlocks(nodes, list)

            const decos = list.map((b, i) => {
              const n = nodes[map[i]]
              if (!n || map[i] < 0) return null
              // ★ 没有段评的段落不挂气泡（* 与旧口径一致；
              //   要新开一段评 ⇒ 选中文字后右键）⚠
              if (!b.comment_count) return null
              return Decoration.widget(
                n.end - 1,
                () => bubbleButton(b, () => cbRef.current?.(b)),
                { side: 1, key: `bubble-${b.fingerprint}` },
              )
            })
            return DecorationSet.create(
              state.doc,
              decos.filter((d): d is Decoration => d !== null),
            )
          },
        },
      }),
  )
}

/**
 * ★ 粗略归一：去掉空白与 markdown 记号，只比「文字」
 *   · · 只在序号对不上时兜底，* 不需要精确 ✅
 */
function loose(s: string): string {
  return (s || '')
    .replace(/\r\n/g, '\n')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_~#>]/g, '')
    .replace(/^\s*(?:[-+]|\d+[.)])\s+/gm, '')
    .replace(/^\s*(?:---|\*\*\*|___)\s*$/gm, '')
    .replace(/\s+/g, '')
}
