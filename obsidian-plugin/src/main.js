/**
 * Astrolabe Code Graph —— Obsidian 插件（最小验证版）
 *
 * 目标只有一个：验证 WASM tree-sitter 能否在 Obsidian 里解析代码。
 * 命令「Astrolabe: 解析当前 vault 代码」→ 扫描 → Notice 显示结果 →
 * 把 {nodes, edges} 写到 vault 根目录 astrolabe-graph.json。
 */
import { Plugin, Notice } from 'obsidian'
import { scanVault } from './parser'

export default class AstrolabePlugin extends Plugin {
  async onload() {
    console.log('[ASTROLABE] plugin loaded')
    this.addCommand({
      id: 'parse-vault',
      name: '解析当前 vault 代码（Astrolabe）',
      callback: () => this.runParse(),
    })
  }

  onunload() {
    console.log('[ASTROLABE] plugin unloaded')
  }

  async runParse() {
    const notice = new Notice('Astrolabe: 初始化 WASM 解析器…', 0)
    try {
      const t0 = Date.now()
      const result = await scanVault(this.app, this.manifest.dir, {
        maxFiles: 500,
      })
      const ms = Date.now() - t0

      // 把结果写到 vault 根，方便在 Obsidian 里直接打开看
      const out = {
        generatedAt: new Date().toISOString(),
        ms,
        files: result.files,
        scanned: result.scanned,
        nodes: result.nodes,
        edges: result.edges,
        errors: result.errors,
      }
      const target = 'astrolabe-graph.json'
      const existing = this.app.vault.getAbstractFileByPath(target)
      const text = JSON.stringify(out, null, 2)
      if (existing) await this.app.vault.modify(existing, text)
      else await this.app.vault.create(target, text)

      const kinds = {}
      for (const n of result.nodes) kinds[n.kind] = (kinds[n.kind] || 0) + 1
      const summary = `文件 ${result.files}/${result.scanned} · 节点 ${result.nodes.length} · 边 ${result.edges.length} · ${ms}ms\n${Object.entries(kinds).map(([k, v]) => `${k}:${v}`).join(' ')}`
      notice.setMessage(`Astrolabe 解析完成\n${summary}`)
      console.log('[ASTROLABE] parse done', summary, 'errors:', result.errors)
      setTimeout(() => notice.hide(), 12000)
    } catch (e) {
      const msg = String(e && e.message || e)
      notice.setMessage(`Astrolabe 解析失败：${msg}`)
      console.error('[ASTROLABE] parse error', e)
      setTimeout(() => notice.hide(), 15000)
    }
  }
}
