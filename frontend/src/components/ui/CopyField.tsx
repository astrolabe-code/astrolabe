import { useRef, useState } from 'react'
import { Check, Copy, TriangleAlert } from 'lucide-react'
import Button from './Button'

/**
 * ★★★ 复制文本 —— **含「非 HTTPS 也能用」的兜底**（`B172`）
 *
 * ## ⚠★★ 为什么必须有兜底（★ 这是实测出来的，不是保险起见）
 *
 * ★ 所有者从 `http://192.168.3.91:5173` 访问 —— ★★ **那不是安全上下文**
 * （★ 非 HTTPS，★ 且不是 `localhost`）⇒ ★★★ **`navigator.clipboard` 在那里是 `undefined`** ⚠
 *
 * ⇒ ★ 改之前那段代码的 `catch` 分支**必然触发**，★ 而它调的是 `window.prompt` ——
 *   ⚠★ 浏览器原生弹窗**会把整条 URL 显示在标题栏**（★ **含服务器 IP**）⚠
 *   ★★ 这也正是所有者提的第 ④ 条：「显示注册邀请连接的弹窗是浏览器自带的，把我服务器IP地址都显示了」
 *
 * ## ★★ 三级降级（★ 从上往下试）
 *
 * | 顺序 | 手段 | 覆盖 |
 * |---|---|---|
 * | ① | `navigator.clipboard.writeText` | ★ HTTPS / `localhost` |
 * | ② | `<textarea>` + `document.execCommand('copy')` | ★★ **明文 HTTP 也能用** ✅ |
 * | ③ | 都不行 ⇒ 返回 `false` ⇒ ★ 由界面**选中文本**并提示"按 Ctrl+C" | ⚠ 最后兜底 |
 *
 * ⚠★ 注意 ③：★ 它**不再弹任何东西** —— ★ 只是把文本选中 ✅
 */
export async function copyText(text: string): Promise<boolean> {
  // ① 现代 API（★ 只在安全上下文里存在）
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // ★ 落到 ② —— ⚠ 不直接 return：★ 有些浏览器是"对象在、但权限被拒"
  }

  // ② 老办法 —— ★★ 关键：它**不看安全上下文** ✅
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    // ⚠★ 必须"在视口内且可见"才选得中 —— ★ 所以用 fixed + `opacity:0`，
    //   ❌ 不能用 `display:none` / `visibility:hidden`（★ 那样 `select()` 无效）
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '0'
    ta.style.width = '1px'
    ta.style.height = '1px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, ta.value.length)
    const done = document.execCommand('copy')
    document.body.removeChild(ta)
    if (done) return true
  } catch {
    // ★ 落到 ③
  }

  return false
}

interface CopyFieldProps {
  /** ★ 要复制的文本（★ 也是输入框里显示的那份） */
  value: string
  /** ★ 标题（★ 可省略） */
  label?: string
  /** ★ 下面那句小字说明 */
  hint?: string
}

/**
 * ★ 一行「只读文本 + 复制按钮」（`B172`）
 *
 * ★★ **抽成组件而不是各写一遍** —— 所有者原话：
 * 「你应该自己写一个弹窗，**这样以后弹窗可以通用**」⚠
 * ⇒ ★ 本项目**凡是"给个链接"的地方**都用它（★ 邀请链接 · 将来的仓库地址 / API 凭证）✅
 */
export default function CopyField({ value, label, hint }: CopyFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [state, setState] = useState<'idle' | 'ok' | 'fail'>('idle')

  async function onCopy() {
    const done = await copyText(value)
    if (done) {
      setState('ok')
    } else {
      // ★ ③ 兜底：★ 帮用户**选中** —— 他只要按 Ctrl+C（⚠ 不再弹 prompt）
      setState('fail')
      inputRef.current?.focus()
      inputRef.current?.select()
    }
    window.setTimeout(() => setState('idle'), 2500)
  }

  return (
    <div>
      {label && (
        <div className="mb-2" style={{ fontSize: 12.5, color: 'var(--text-sub)' }}>
          {label}
        </div>
      )}
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          className="input"
          readOnly
          value={value}
          aria-label={label || '待复制的文本'}
          // ★ 点一下**自动全选** —— ★ 就算按钮不好使，★ 用户也能直接 Ctrl+C ✅
          onFocus={(e) => e.currentTarget.select()}
          style={{ fontSize: 12.5, fontFamily: 'var(--font-mono, monospace)' }}
        />
        <Button
          type="button"
          variant={state === 'ok' ? 'primary' : 'ghost'}
          onClick={onCopy}
          icon={state === 'ok' ? <Check size={14} /> : <Copy size={14} />}
        >
          {state === 'ok' ? '已复制' : '复制'}
        </Button>
      </div>
      {state === 'fail' && (
        <p className="m-0 mt-2 flex items-center gap-1.5" style={{ fontSize: 12, color: 'var(--warn, var(--err))' }}>
          <TriangleAlert size={13} />
          这个浏览器不让网页自动复制 —— ★ **已经帮你选中了，按 Ctrl+C 即可**。
        </p>
      )}
      {hint && state !== 'fail' && (
        <p className="text-text-faint m-0 mt-2" style={{ fontSize: 12, lineHeight: 1.7 }}>
          {hint}
        </p>
      )}
    </div>
  )
}
