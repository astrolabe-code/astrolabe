/**
 * ★★★ Astrolabe 个人版 · 桌面壳（绿色版）
 *
 * ## 为什么是这个架构
 *
 * ```\n * ⛔ 不起 HTTP 服务 —— 用户不会遇到「端口被占」「localhost 被公司策略封」\n * ⛔ 不装任何东西 —— 绿色版，双击 exe 就跑（数据在 exe 同目录）\n * ✅ 前端一行不改 —— 自定义协议 `app://local` 把 /api/* 转给 Python 边车\n * ✅ 后端只保留解析器 —— Django 那套 Web 层不进这个包\n * ```\n *
 * ## 三条关键实现
 *
 * 1. **自定义协议**（`app://local/app/...`）
 *    · 静态文件：映射到 `frontend/dist`
 *    · `/api/*`：转发给 Python 边车（stdio，不走网络）
 *    · 未知路径：回落 index.html（SPA 深链需要）
 *
 * 2. **绿色版**：`userData` 指到 exe 同目录的 `data/`
 *    · 拷走整个文件夹 = 搬家；卸载 = 删文件夹
 *    · ⚠ 必须在 `app.whenReady()` **之前**设置，否则 Electron 已经建好目录了
 *
 * 3. **边车通信**：换行分隔的 JSON（`{"id","method","path","body"}` ↔ `{"id","status","body"}`）
 *    · 不用 HTTP ⇒ 没有端口
 *    · 不用 socket 文件 ⇒ Windows 上不用处理命名管道差异
 */

const { app, BrowserWindow, protocol, ipcMain, shell, dialog } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const { spawn } = require('node:child_process')
const { pathToFileURL } = require('node:url')

// ---------------------------------------------------------------- 路径

const IS_PACKAGED = app.isPackaged
const EXE_DIR = path.dirname(app.getPath('exe'))

/** 前端构建产物目录：打包后在 resources/dist，开发时在 ../frontend/dist */
const DIST = IS_PACKAGED
  ? path.join(process.resourcesPath, 'dist')
  : (() => {
      // ★ 本地开发：个人版产物（dist-personal）优先，没有才退回线上产物
      const personal = path.join(__dirname, '..', 'frontend', 'dist-personal')
      return fs.existsSync(personal) ? personal : path.join(__dirname, '..', 'frontend', 'dist')
    })()

/** 边车：打包后是 resources/sidecar/astrolabe-sidecar(.exe)，开发时是 python 脚本 */
const SIDECAR_CMD = IS_PACKAGED
  ? path.join(process.resourcesPath, 'sidecar', process.platform === 'win32' ? 'astrolabe-sidecar.exe' : 'astrolabe-sidecar')
  : process.platform === 'win32'
    ? 'python'
    : 'python3'
const SIDECAR_ARGS = IS_PACKAGED
  ? []
  : [path.join(__dirname, 'sidecar', 'main.py')]

/**
 * ★★ 绿色版的核心一行（`D…`）——
 * 默认 Electron 把 SQLite/缓存写到 `%APPDATA%/astrolabe-desktop`，
 * 那就不是绿色版了。指到 exe 同目录的 data/，拷走即搬家。
 * ⚠ 必须在 whenReady 之前调用。
 */
const DATA_DIR = path.join(EXE_DIR, 'data')
try {
  fs.mkdirSync(DATA_DIR, { recursive: true })
  app.setPath('userData', DATA_DIR)
} catch (e) {
  // ⚠ 目录不可写（比如放在只读盘）⇒ 退回默认位置，⛔ 不要让程序起不来
  console.error('[astrolabe] userData 设置失败，用默认路径：', e.message)
}

// ---------------------------------------------------------------- 边车

const SMOKE = !!process.env.ASTROLABE_SMOKE
const SMOKE_APIS = new Set()

let sidecar = null
let seq = 0
const pending = new Map()

function startSidecar() {
  sidecar = spawn(SIDECAR_CMD, SIDECAR_ARGS, {
    cwd: EXE_DIR,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, ASTROLABE_DATA_DIR: DATA_DIR, PYTHONIOENCODING: 'utf-8' },
  })

  let buf = ''
  sidecar.stdout.on('data', (chunk) => {
    buf += chunk.toString('utf8')
    let idx
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 1)
      if (!line) continue
      let msg
      try {
        msg = JSON.parse(line)
      } catch {
        console.error('[sidecar] 非 JSON 输出：', line.slice(0, 200))
        continue
      }
      const p = pending.get(msg.id)
      if (p) {
        pending.delete(msg.id)
        p.resolve(msg)
      }
    }
  })

  sidecar.stderr.on('data', (d) => console.error('[sidecar]', d.toString().slice(0, 400)))

  sidecar.on('exit', (code) => {
    // ⚠ 边车挂了 ⇒ 所有挂起的请求都要 reject，否则界面永远转圈
    for (const [, p] of pending) p.reject(new Error(`边车已退出 (code ${code})`))
    pending.clear()
    sidecar = null
  })
}

/** 调一次边车；超时 30s（解析大仓库会慢，但也不能无限等） */
function callSidecar(method, apiPath, body) {
  return new Promise((resolve, reject) => {
    if (!sidecar) {
      reject(new Error('边车未启动'))
      return
    }
    const id = ++seq
    pending.set(id, { resolve, reject })
    sidecar.stdin.write(JSON.stringify({ id, method, path: apiPath, body }) + '\n')
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        reject(new Error('边车超时'))
      }
    }, 30000)
  })
}

// ---------------------------------------------------------------- 协议

protocol.registerSchemesAsPrivileged([
  {
    scheme: 'app',
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
  },
])

const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.woff2': 'font/woff2', '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
}

function serveFile(file) {
  const ext = path.extname(file).toLowerCase()
  return new Response(fs.readFileSync(file), {
    headers: { 'content-type': MIME[ext] || 'application/octet-stream' },
  })
}

function registerProtocol() {
  protocol.handle('app', async (request) => {
    const url = new URL(request.url)
    // ⚠★ 必须带上 query（`?limit=&offset=` 这些参数全在 search 里）——
    //   只传 pathname 的话，边车收到的是"没有参数的路径"，分页/筛选全部失效
    const p = decodeURIComponent(url.pathname || '/') + (url.search || '')

    // ★ /api/* ⇒ 交给边车（⛔ 不走网络，没有端口）
    if (p.startsWith('/api/')) {
      if (SMOKE) SMOKE_APIS.add(`${request.method} ${p}`)
      let body = null
      if (request.method !== 'GET' && request.method !== 'HEAD') {
        try {
          body = JSON.parse(await request.text())
        } catch {
          body = null
        }
      }
      try {
        const r = await callSidecar(request.method, p, body)
        return new Response(JSON.stringify(r.body ?? {}), {
          status: r.status || 200,
          headers: { 'content-type': 'application/json; charset=utf-8' },
        })
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: String(e.message || e) }), {
          status: 500,
          headers: { 'content-type': 'application/json; charset=utf-8' },
        })
      }
    }

    // ★ 静态文件：/app/xxx → dist/xxx
    const rel = p.replace(/^\/app/, '')
    let file = path.join(DIST, rel)
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      // ⚠ SPA 深链（如 /app/p/xxx/notes/y）⇒ 回落 index.html，否则刷新 404
      file = path.join(DIST, 'index.html')
    }
    if (!fs.existsSync(file)) {
      return new Response('前端未构建：请先在 frontend 目录执行 npm run build', {
        status: 503,
        headers: { 'content-type': 'text/plain; charset=utf-8' },
      })
    }
    return serveFile(file)
  })
}

// ---------------------------------------------------------------- 窗口

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#ffffff', // ★ 个人版全白（见 POSITIONING / 主题 plain）
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // ⚠ 沙箱在部分 Linux 环境要关，Windows 上保持默认
      sandbox: false,
    },
  })

  // ★ 外部链接用系统浏览器打开，⛔ 不在应用内导航走
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url)
    return { action: 'deny' }
  })

  win.loadURL('app://local/app/')

  /**
   * ★ 自检模式（`ASTROLABE_SMOKE=1`）——
   *   在无头环境里验证三件事：页面加载、协议映射、边车通道。
   *   ⚠ 只读验证，不改任何数据；打包流水线以后也能直接用它当冒烟。
   */
  if (process.env.ASTROLABE_SMOKE) {
    win.webContents.once('did-finish-load', async () => {
      const probe = `(async () => {
        const r = await fetch('/api/ping')
        const j = await r.json()
        let scan = null
        try {
          const sr = await fetch('/api/fs/scan', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ path: ${JSON.stringify(process.env.ASTROLABE_SMOKE_SCAN || '')} }),
          })
          scan = (await sr.json()).data?.files ?? null
        } catch (e) { scan = 'ERR' }
        const t = document.title
        const root = !!document.querySelector('#root')?.children.length
        return { title: t, apiOk: j.ok === true, pong: j.data?.pong, rootRendered: root,
                 desktopFlag: !!window.astrolabe?.isDesktop,
                 text: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 80),
                 hasTopNav: !!document.querySelector('.topnav'),
                 hasSky: !!document.querySelector('canvas, .skyfx'), scanFiles: scan }
      })()`
      try {
        const out = await win.webContents.executeJavaScript(probe)
        console.log('SMOKE ' + JSON.stringify(out))
      } catch (e) {
        console.log('SMOKE ' + JSON.stringify({ error: String(e.message || e) }))
      }
      /**
       * ★ 自检动作脚本（`ASTROLABE_SMOKE_JS=<文件>`）——
       *   用来驱动真实交互（打字 / 点保存），跑完把结果打回主进程。
       *   ⚠ 仅自检用，普通启动不读这个变量。
       */
      if (process.env.ASTROLABE_SMOKE_JS) {
        const deep = process.env.ASTROLABE_SMOKE_PATH
        if (deep) {
          await win.loadURL('app://local/app' + deep)
          await new Promise((r) => setTimeout(r, 2200))
        }
        try {
          const src = fs.readFileSync(process.env.ASTROLABE_SMOKE_JS, 'utf8')
          const out = await win.webContents.executeJavaScript(src)
          console.log('SMOKE_ACTION ' + JSON.stringify(out))
        } catch (e) {
          console.log('SMOKE_ACTION ' + JSON.stringify({ error: String(e.message || e) }))
        }
      }

      const deepPath = process.env.ASTROLABE_SMOKE_JS ? null : process.env.ASTROLABE_SMOKE_PATH
      if (deepPath) {
        await win.loadURL('app://local/app' + deepPath)
        await new Promise((r) => setTimeout(r, 2500))
        try {
          const info = await win.webContents.executeJavaScript(
            `({ url: location.pathname + location.search,
                text: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,160) })`,
          )
          console.log('SMOKE_PAGE ' + JSON.stringify(info))
        } catch (e) {
          console.log('SMOKE_PAGE ' + JSON.stringify({ error: String(e.message || e) }))
        }
      }
      setTimeout(async () => {
        try {
          const img = await win.webContents.capturePage()
          fs.writeFileSync('/tmp/astrolabe-shell.png', img.toPNG())
        } catch (e) {
          console.log('SMOKE 截图失败 ' + String(e.message || e))
        }
        console.log('SMOKE_APIS ' + JSON.stringify([...SMOKE_APIS].sort()))
        app.quit()
      }, 1200)
    })
  }
  return win
}

// ---------------------------------------------------------------- IPC（只读事实）

ipcMain.handle('app:info', () => ({
  version: app.getVersion(),
  dataDir: DATA_DIR,
  distDir: DIST,
  packaged: IS_PACKAGED,
  // ★ 许可证声明：打包后在 resources/ 下，开发时在仓库根
  notices: IS_PACKAGED
    ? path.join(process.resourcesPath, 'THIRD-PARTY-NOTICES.txt')
    : path.join(__dirname, '..', 'THIRD-PARTY-NOTICES.txt'),
}))

ipcMain.handle('app:pick-dir', async () => {
  // ★ 自检用：`ASTROLABE_SMOKE_PICK` 指定目录就跳过原生对话框
  //   （无头环境点不了系统对话框；⚠ 普通启动不设这个变量）
  if (process.env.ASTROLABE_SMOKE_PICK) return process.env.ASTROLABE_SMOKE_PICK
  // ★ 原生目录对话框 —— 浏览器做不到这件事（安全限制），这也是要壳的原因之一
  const r = await dialog.showOpenDialog({
    title: '选择要读的代码目录',
    properties: ['openDirectory'],
  })
  return r.canceled ? null : r.filePaths[0] || null
})

ipcMain.handle('app:open-path', async (_e, target) => {
  // ★ 打开任意目录/文件（设置页里「打开笔记目录」「看第三方声明」用）
  if (!target || typeof target !== 'string') return false
  await shell.openPath(target)
  return true
})

ipcMain.handle('app:open-data-dir', async () => {
  await shell.openPath(DATA_DIR)
  return true
})

app.whenReady().then(() => {
  startSidecar()
  registerProtocol()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (sidecar) {
    try {
      sidecar.kill()
    } catch {
      /* ignore */
    }
  }
})
