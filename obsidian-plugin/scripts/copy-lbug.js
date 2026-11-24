/**
 * 复制 @ladybugdb/core 的运行时（JS 包装 + 当前平台 .node 二进制）
 * 到插件目录 lbug/ 下。main.js 里 @ladybugdb/core 是 external，
 * 运行时会从插件目录的 node_modules 加载 —— 这里把它放到标准位置。
 *
 * ⚠ 只复制**当前构建平台**的二进制：
 *   Windows / macOS / ARM 版要分别在对应机器上跑一次 npm install + build，
 *   或手动替换 lbug/@ladybugdb/core/lbugjs.node。
 */
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const srcPkg = path.join(root, 'node_modules/@ladybugdb/core')
const destRoot = path.join(root, 'node_modules/@ladybugdb/core')

if (!fs.existsSync(srcPkg)) {
  console.warn('  跳过：@ladybugdb/core 未安装')
  process.exit(0)
}

// npm 已经把当前平台的 .node 放在 core/lbugjs.node（install.js 做的）——
// 确认它在，就不需要额外复制。
const native = path.join(srcPkg, 'lbugjs.node')
if (fs.existsSync(native)) {
  console.log(`  LadybugDB 运行时就绪: ${Math.round(fs.statSync(native).size / 1024 / 1024)}MB (${process.platform}-${process.arch})`)
} else {
  // 兜底：从平台子包复制
  const sub = path.join(root, `node_modules/@ladybugdb/core-${process.platform}-${process.arch}/lbugjs.node`)
  if (fs.existsSync(sub)) {
    fs.copyFileSync(sub, native)
    console.log(`  已从平台子包复制 lbugjs.node (${process.platform}-${process.arch})`)
  } else {
    console.warn(`  警告：找不到当前平台 (${process.platform}-${process.arch}) 的 lbugjs.node`)
  }
}

// ★ 无条件删所有 @ladybugdb/core-<平台> 子包（二进制已在 core/lbugjs.node）
//   每个子包 28MB，留着会让插件从 35MB 涨到 63MB
const nmRoot = path.join(root, 'node_modules/@ladybugdb')
for (const name of fs.readdirSync(nmRoot)) {
  if (name.startsWith('core-')) {
    fs.rmSync(path.join(nmRoot, name), { recursive: true, force: true })
  }
}

// 打印给用户的分发提示
console.log('  ⚠ 分发提示：Windows/Mac/ARM 朋友需要对应平台的 lbugjs.node（28MB/平台）')
