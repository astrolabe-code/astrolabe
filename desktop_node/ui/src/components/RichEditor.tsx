import { useEffect, useRef, type ReactNode } from 'react'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import { Bold, Code2, Heading2, Italic, List, ListOrdered, Minus, Quote } from 'lucide-react'
import { marked } from 'marked'
import TurndownService from 'turndown'

const turndown = new TurndownService({
  headingStyle: 'atx',
  codeBlockStyle: 'fenced',
  bulletListMarker: '-',
  emDelimiter: '*',
})

export function mdToHtml(md: string): string {
  return marked.parse(md || '', { async: false }) as string
}

export function htmlToMd(html: string): string {
  // turndown 默认给列表项留 3 个空格，归一化成常见的「- 内容」
  return turndown
    .turndown(html)
    .replace(/^(\s*)([-*+]|\d+\.)\s{3}/gm, '$1$2 ')
    .trim()
}

interface Props {
  initialMarkdown: string
  editable: boolean
  onChange: (markdown: string) => void
}

function Toolbar({ editor }: { editor: Editor }) {
  const tool = (label: string, active: boolean, onClick: () => void, icon: ReactNode) => (
    <button
      type="button"
      title={label}
      className={`rich-tool${active ? ' active' : ''}`}
      onClick={onClick}
    >
      {icon}
    </button>
  )
  return (
    <div className="rich-toolbar">
      {tool('粗体', editor.isActive('bold'), () => editor.chain().focus().toggleBold().run(), <Bold size={13} />)}
      {tool('斜体', editor.isActive('italic'), () => editor.chain().focus().toggleItalic().run(), <Italic size={13} />)}
      {tool('标题', editor.isActive('heading', { level: 2 }), () => editor.chain().focus().toggleHeading({ level: 2 }).run(), <Heading2 size={13} />)}
      {tool('无序列表', editor.isActive('bulletList'), () => editor.chain().focus().toggleBulletList().run(), <List size={13} />)}
      {tool('有序列表', editor.isActive('orderedList'), () => editor.chain().focus().toggleOrderedList().run(), <ListOrdered size={13} />)}
      {tool('引用', editor.isActive('blockquote'), () => editor.chain().focus().toggleBlockquote().run(), <Quote size={13} />)}
      {tool('代码块', editor.isActive('codeBlock'), () => editor.chain().focus().toggleCodeBlock().run(), <Code2 size={13} />)}
      {tool('分隔线', false, () => editor.chain().focus().setHorizontalRule().run(), <Minus size={13} />)}
    </div>
  )
}

/** Markdown 所见即所得：值以 Markdown 出入，内部是 TipTap 文档 */
export default function RichEditor({ initialMarkdown, editable, onChange }: Props) {
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  const editor = useEditor({
    extensions: [StarterKit, Placeholder.configure({ placeholder: '用 Markdown 写点什么…' })],
    content: mdToHtml(initialMarkdown),
    editable,
    onUpdate: ({ editor: e }) => onChangeRef.current(htmlToMd(e.getHTML())),
  })

  useEffect(() => {
    editor?.setEditable(editable)
  }, [editor, editable])

  return (
    <div className="rich-editor">
      {editable && editor && <Toolbar editor={editor} />}
      <EditorContent editor={editor} className="rich-content" />
    </div>
  )
}
