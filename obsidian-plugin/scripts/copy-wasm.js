/**
 * 把 npm 装好的 wasm 资源复制到插件 wasm/ 目录。
 * 来源：node_modules/web-tree-sitter 与 desktop_node 的 grammar wasm。
 */
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const dest = path.join(root, 'wasm')
fs.mkdirSync(dest, { recursive: true })

function copy(src, name) {
  if (!fs.existsSync(src)) {
    console.warn(`  跳过（源不存在）: ${src}`)
    return
  }
  fs.copyFileSync(src, path.join(dest, name))
  console.log(`  复制 ${name} (${Math.round(fs.statSync(src).size / 1024)}KB)`)
}

// 运行时 wasm
copy(
  path.join(root, 'node_modules/web-tree-sitter/web-tree-sitter.wasm'),
  'web-tree-sitter.wasm',
)

// grammars：优先当前插件的 node_modules，其次 desktop_node 的现成 wasm
const grammarDirs = [
  path.join(root, 'node_modules/@vscode/tree-sitter-wasm/wasm'),
  '/home/ma/astrolabe/desktop_node/node_modules/@vscode/tree-sitter-wasm/wasm',
  // ⛔ .tree-sitter-wasms 那份是旧 ABI（dylink v19），web-tree-sitter 0.27 加载失败。
  //   只作最后兜底，别放前面。
  '/home/ma/astrolabe/desktop_node/node_modules/.tree-sitter-wasms-6YwmWMjr/out',
]
const grammars = ['c', 'cpp', 'python', 'java']
for (const g of grammars) {
  const name = `tree-sitter-${g}.wasm`
  const found = grammarDirs.map((d) => path.join(d, name)).find((p) => fs.existsSync(p))
  if (found) copy(found, name)
  else console.warn(`  未找到 grammar: ${name}`)
}
