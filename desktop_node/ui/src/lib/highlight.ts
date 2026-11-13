/** 轻量、转义安全的代码高亮：代码页与仿写面板共用，零运行时依赖 */

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

type Lang = 'c' | 'python' | 'java' | 'js' | 'plain'

const COMMON = [
  'if', 'else', 'for', 'while', 'return', 'break', 'continue', 'const', 'static',
  'class', 'struct', 'enum', 'union', 'typedef', 'void', 'int', 'char', 'float',
  'double', 'long', 'short', 'unsigned', 'signed', 'public', 'private', 'protected',
  'new', 'delete', 'this', 'try', 'catch', 'finally', 'throw', 'true', 'false',
  'null', 'import', 'from', 'var', 'let', 'function', 'async', 'await', 'in', 'is',
  'not', 'and', 'or', 'with', 'as', 'include', 'define', 'namespace', 'using',
  'template', 'typename', 'interface', 'extends', 'implements', 'super',
]

const EXTRA: Record<Lang, string[]> = {
  c: ['sizeof', 'extern', 'inline', 'register', 'volatile', 'goto', 'switch', 'case', 'default'],
  python: ['def', 'lambda', 'yield', 'pass', 'None', 'True', 'False', 'elif', 'except', 'raise', 'self', 'global', 'nonlocal', 'assert', 'del', 'print'],
  java: ['package', 'final', 'abstract', 'synchronized', 'transient', 'instanceof', 'boolean', 'byte', 'switch', 'case', 'default'],
  js: ['export', 'default', 'typeof', 'instanceof', 'of', 'switch', 'case', 'default', 'undefined'],
  plain: [],
}

const SETS: Record<Lang, Set<string>> = {
  c: new Set([...COMMON, ...EXTRA.c]),
  python: new Set([...COMMON, ...EXTRA.python]),
  java: new Set([...COMMON, ...EXTRA.java]),
  js: new Set([...COMMON, ...EXTRA.js]),
  plain: new Set(COMMON),
}

export function langFromExt(ext: string): Lang {
  const e = ext.toLowerCase().replace(/^\./, '')
  if (['c', 'h', 'cc', 'cpp', 'cxx', 'hpp', 'hh', 'hxx'].includes(e)) return 'c'
  if (['py', 'pyi'].includes(e)) return 'python'
  if (e === 'java') return 'java'
  if (['js', 'jsx', 'mjs', 'cjs', 'ts', 'tsx', 'json', 'vue'].includes(e)) return 'js'
  return 'plain'
}

const TOKEN =
  /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|\b(\d+(?:\.\d+)?)\b|\b([A-Za-z_]\w*)\b/g

/** 先转义再包 span，绝不会把代码当 HTML 执行 */
export function highlightCode(code: string, ext = ''): string {
  const lang = langFromExt(ext)
  const keywords = SETS[lang]
  let out = ''
  let last = 0
  for (const m of code.matchAll(TOKEN)) {
    const at = m.index ?? 0
    out += escapeHtml(code.slice(last, at))
    const token = m[0]
    if (m[1]) {
      const cls = token.startsWith('#') && lang !== 'python' ? 'macro' : 'comment'
      out += `<span class="token ${cls}">${escapeHtml(token)}</span>`
    } else if (m[2]) {
      out += `<span class="token string">${escapeHtml(token)}</span>`
    } else if (m[3]) {
      out += `<span class="token number">${escapeHtml(token)}</span>`
    } else if (keywords.has(m[4])) {
      out += `<span class="token keyword">${escapeHtml(token)}</span>`
    } else if (/^[ \t]*\(/.test(code.slice(at + token.length, at + token.length + 2))) {
      out += `<span class="token function">${escapeHtml(token)}</span>`
    } else {
      out += escapeHtml(token)
    }
    last = at + token.length
  }
  return out + escapeHtml(code.slice(last))
}
