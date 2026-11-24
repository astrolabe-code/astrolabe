/**
 * Astrolabe Code Graph —— Obsidian 插件
 *
 * 架构：
 *   存储  → <vault>/astrolabe/graph.json（持久化，跨会话、可看可同步）
 *   查询  → WASM LadybugDB 内存库（Cypher，Obsidian 重启后从 JSON 重建）
 *
 * 命令：
 *   1. 解析当前 vault 代码 → 写 JSON + 灌内存库
 *   2. Cypher 查询 → 在内存库上跑
 *   3. 从 graph.json 重建图库 → 手动触发（通常自动加载）
 *
 * ★ 导出方式：CJS module.exports = PluginClass（Obsidian 官方口径）
 */
const { Plugin, Notice, Modal, Setting } = require('obsidian')
const { scanVault } = require('./parser')
// graphdb 内部是懒加载（首次 openGraph 才初始化 WASM），不会拖垮插件加载
const { openGraph, writeGraph, readGraph, runQuery, closeGraph } = require('./graphdb')

const GRAPH_JSON = 'astrolabe/graph.json'

/** Cypher 查询弹窗 */
class CypherModal extends Modal {
  constructor(app, plugin) {
    super(app)
    this.plugin = plugin
  }

  onOpen() {
    const { contentEl } = this
    contentEl.createEl('h3', { text: 'Cypher 查询' })

    const ta = contentEl.createEl('textarea', {
      attr: { rows: '5', placeholder: 'MATCH (a:Code)-[:Rel]->(b:Code) RETURN a.name, b.name LIMIT 20' },
    })
    ta.style.width = '100%'
    ta.style.fontFamily = 'monospace'
    ta.style.fontSize = '12px'
    ta.value = 'MATCH (c:Code) RETURN c.kind AS kind, count(*) AS n ORDER BY n DESC'

    const out = contentEl.createEl('pre')
    out.style.marginTop = '10px'
    out.style.maxHeight = '320px'
    out.style.overflow = 'auto'
    out.style.fontSize = '11px'
    out.setText('（结果会显示在这里）')

    const btn = contentEl.createEl('button', { text: '执行' })
    btn.style.marginTop = '8px'
    btn.onclick = async () => {
      out.setText('执行中…')
      try {
        const { columns, rows, elapsedMs } = await this.plugin.query(ta.value)
        if (!rows.length) {
          out.setText(`（0 行，${elapsedMs}ms）`)
          return
        }
        const head = columns.join(' | ')
        const body = rows
          .slice(0, 200)
          .map((r) => columns.map((c) => String(r[c] ?? '')).join(' | '))
          .join('\n')
        const more = rows.length > 200 ? `\n… 还有 ${rows.length - 200} 行` : ''
        out.setText(`${head}\n${'-'.repeat(Math.min(80, head.length))}\n${body}${more}\n\n（${rows.length} 行，${elapsedMs}ms）`)
      } catch (e) {
        out.setText(`错误：${String(e && e.message || e)}`)
      }
    }
    // Ctrl+Enter 执行
    ta.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault()
        btn.click()
      }
    })
    ta.focus()
  }

  onClose() {
    this.contentEl.empty()
  }
}

class AstrolabePlugin extends Plugin {
  async onload() {
    console.log('[ASTROLABE] plugin loaded')
    /** 常驻的内存图库 { db, conn, dbPath } */
    this.graph = null

    this.addCommand({
      id: 'parse-vault',
      name: '解析当前 vault 代码（写入 graph.json + 图库）',
      callback: () => this.runParse(),
    })
    this.addCommand({
      id: 'cypher-query',
      name: 'Cypher 查询',
      callback: () => new CypherModal(this.app, this).open(),
    })
    this.addCommand({
      id: 'reload-graph',
      name: '从 graph.json 重建图库',
      callback: () => this.reloadFromJson(),
    })

    // 启动后异步加载已有 graph.json（不阻塞 Obsidian 启动）
    this.app.workspace.onLayoutReady(() => {
      void this.reloadFromJson({ silent: true })
    })
  }

  async onunload() {
    console.log('[ASTROLABE] plugin unloaded')
    if (this.graph) {
      try { await closeGraph(this.graph) } catch { /* 忽略 */ }
      this.graph = null
    }
  }

  /** 写 JSON 到 vault（目录不存在时先建） */
  async saveJson(payload) {
    const adapter = this.app.vault.adapter
    const dir = 'astrolabe'
    if (!(await adapter.exists(dir))) await adapter.mkdir(dir)
    await adapter.write(GRAPH_JSON, JSON.stringify(payload))
  }

  /** 从 graph.json 重建内存图库 */
  async reloadFromJson({ silent = false } = {}) {
    const adapter = this.app.vault.adapter
    if (!(await adapter.exists(GRAPH_JSON))) {
      if (!silent) new Notice('没有找到 astrolabe/graph.json，先运行「解析当前 vault 代码」')
      return false
    }
    try {
      const text = await adapter.read(GRAPH_JSON)
      const data = JSON.parse(text)
      if (this.graph) {
        try { await closeGraph(this.graph) } catch { /* 忽略 */ }
        this.graph = null
      }
      const project = (this.app.vault.getName() || 'vault').replace(/[^\w\u4e00-\u9fa5-]/g, '_')
      const g = await openGraph(project)
      await writeGraph(g.conn, data.nodes || [], data.edges || [])
      this.graph = g
      if (!silent) {
        new Notice(`图库已重建：${(data.nodes || []).length} 节点 / ${(data.edges || []).length} 边`)
      }
      console.log('[ASTROLABE] reloaded from json', g.dbPath)
      return true
    } catch (e) {
      console.error('[ASTROLABE] reload failed', e)
      if (!silent) new Notice(`重建失败：${String(e && e.message || e)}`)
      return false
    }
  }

  /** 确保内存库可用（没有就从 JSON 建） */
  async ensureGraph() {
    if (this.graph) return this.graph
    const ok = await this.reloadFromJson({ silent: true })
    if (!ok) throw new Error('图库未就绪，请先运行「解析当前 vault 代码」')
    return this.graph
  }

  /** 执行 Cypher */
  async query(cypher) {
    const g = await this.ensureGraph()
    return runQuery(g.conn, cypher)
  }

  async runParse() {
    const notice = new Notice('Astrolabe: 初始化 WASM 解析器…', 0)
    try {
      const t0 = Date.now()

      // ① 解析
      const result = await scanVault(this.app, this.manifest.dir, { maxFiles: 500 })

      // ② 持久化到 vault（JSON：跨会话、可看、可同步）
      notice.setMessage('Astrolabe: 写入 astrolabe/graph.json …')
      await this.saveJson({
        generatedAt: new Date().toISOString(),
        files: result.files,
        scanned: result.scanned,
        nodes: result.nodes,
        edges: result.edges,
      })

      // ③ 灌进内存图库（查询引擎）
      notice.setMessage('Astrolabe: 构建图库 …')
      if (this.graph) {
        try { await closeGraph(this.graph) } catch { /* 忽略 */ }
        this.graph = null
      }
      const project = (this.app.vault.getName() || 'vault').replace(/[^\w\u4e00-\u9fa5-]/g, '_')
      const g = await openGraph(project)
      await writeGraph(g.conn, result.nodes, result.edges)
      this.graph = g

      const ms = Date.now() - t0
      const kinds = {}
      for (const n of result.nodes) kinds[n.kind] = (kinds[n.kind] || 0) + 1
      const summary = `文件 ${result.files}/${result.scanned} · 节点 ${result.nodes.length} · 边 ${result.edges.length} · ${ms}ms\n${Object.entries(kinds).map(([k, v]) => `${k}:${v}`).join(' ')}\n存档: ${GRAPH_JSON}`
      notice.setMessage(`Astrolabe 解析完成\n${summary}`)
      console.log('[ASTROLABE] parse done', summary)
      setTimeout(() => notice.hide(), 20000)
    } catch (e) {
      const msg = String(e && e.message || e)
      notice.setMessage(`Astrolabe 解析失败：${msg}`)
      console.error('[ASTROLABE] parse error', e)
      setTimeout(() => notice.hide(), 20000)
    }
  }
}

module.exports = AstrolabePlugin
