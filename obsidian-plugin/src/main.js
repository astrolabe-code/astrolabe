/**
 * Astrolabe Code Graph —— Obsidian 插件
 *
 * 命令「解析当前 vault 代码」：
 *   扫描 vault 内代码 → WASM tree-sitter 解析 → 写入
 *   <vault>/astrolabe/graphs/<项目名>.lbug（LadybugDB）
 */
import { Plugin, Notice } from 'obsidian'
import { scanVault } from './parser'
import { openGraph, writeGraph, closeGraph } from './graphdb'

export default class AstrolabePlugin extends Plugin {
  async onload() {
    console.log('[ASTROLABE] plugin loaded')
    this.addCommand({
      id: 'parse-vault',
      name: '解析当前 vault 代码 → LadybugDB',
      callback: () => this.runParse(),
    })
  }

  onunload() {
    console.log('[ASTROLABE] plugin unloaded')
  }

  async runParse() {
    const notice = new Notice('Astrolabe: 初始化 WASM 解析器…', 0)
    let graph = null
    try {
      const t0 = Date.now()

      // ① 解析
      const result = await scanVault(this.app, this.manifest.dir, { maxFiles: 500 })

      // ② 拿到 vault 的磁盘路径（LadybugDB 要真实文件路径）
      //    ⚠ 桌面端 Obsidian 才有 adapter.getFullPath（移动端本插件不支持）
      const adapter = this.app.vault.adapter
      if (typeof adapter.getFullPath !== 'function') {
        throw new Error('当前环境不支持 LadybugDB（需要桌面端 Obsidian）')
      }
      const vaultPath = adapter.getFullPath('')
      const dir = `${vaultPath}/astrolabe/graphs`
      // ★ Obsidian 桌面端用 window.require('fs')，不用 import('node:fs')
      const req = (typeof window !== 'undefined' && window.require)
        || (0, eval)('typeof require === "function" ? require : null')
      if (!req) throw new Error('当前环境没有 Node require（LadybugDB 仅支持桌面端）')
      const fs = req('node:fs') || req('fs')
      fs.mkdirSync(dir, { recursive: true })

      // 项目名：取 vault 文件夹名
      const project = (vaultPath.split(/[\\/]/).filter(Boolean).pop() || 'vault')
        .replace(/[^\w\u4e00-\u9fa5-]/g, '_')
      const dbPath = `${dir}/${project}.lbug`

      // ③ 写入图库
      notice.setMessage(`Astrolabe: 写入图库 ${project}.lbug …`)
      graph = await openGraph(dbPath)
      await writeGraph(graph.conn, result.nodes, result.edges)

      const ms = Date.now() - t0
      const kinds = {}
      for (const n of result.nodes) kinds[n.kind] = (kinds[n.kind] || 0) + 1
      const summary = `文件 ${result.files}/${result.scanned} · 节点 ${result.nodes.length} · 边 ${result.edges.length} · ${ms}ms\n${Object.entries(kinds).map(([k, v]) => `${k}:${v}`).join(' ')}\n图库: astrolabe/graphs/${project}.lbug`
      notice.setMessage(`Astrolabe 解析完成\n${summary}`)
      console.log('[ASTROLABE] parse done', summary, 'errors:', result.errors)
      setTimeout(() => notice.hide(), 15000)
    } catch (e) {
      const msg = String(e && e.message || e)
      notice.setMessage(`Astrolabe 解析失败：${msg}`)
      console.error('[ASTROLABE] parse error', e)
      setTimeout(() => notice.hide(), 15000)
    } finally {
      if (graph) {
        try { await closeGraph(graph) } catch { /* 忽略 */ }
      }
    }
  }
}
