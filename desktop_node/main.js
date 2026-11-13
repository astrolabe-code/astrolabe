const { app, BrowserWindow, protocol, ipcMain } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const backend = require('./backend')

const DIST = path.join(__dirname, 'ui', 'dist')
const DATA_DIR = app.isPackaged
  ? path.join(path.dirname(app.getPath('exe')), 'data')
  : path.join(__dirname, 'data')

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
])

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2',
  '.ico': 'image/x-icon',
}

function registerProtocol() {
  protocol.handle('app', (req) => {
    const rel = decodeURIComponent(new URL(req.url).pathname)
    let file = path.resolve(DIST, '.' + rel)
    if (!file.startsWith(DIST)) return new Response('forbidden', { status: 403 })
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, 'index.html')
    const buf = fs.readFileSync(file)
    return new Response(new Uint8Array(buf), {
      headers: { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' },
    })
  })
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    frame: false,
    backgroundColor: '#ffffff',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  const built = fs.existsSync(path.join(DIST, 'index.html'))
  win.loadURL(process.env.ASTROLABE_DEV_URL || (built ? 'app://local/' : 'http://localhost:5173'))
  if (process.env.ASTROLABE_DEVTOOLS === '1') win.webContents.openDevTools()
}

const windowHandlers = {
  'window.minimize': () => BrowserWindow.getFocusedWindow()?.minimize(),
  'window.toggleMaximize': () => {
    const w = BrowserWindow.getFocusedWindow()
    if (!w) return
    if (w.isMaximized()) w.unmaximize()
    else w.maximize()
  },
  'window.close': () => BrowserWindow.getFocusedWindow()?.close(),
}

const handlers = { ...backend.handlers, ...windowHandlers }

ipcMain.handle('invoke', async (_event, method, args = []) => {
  const fn = handlers[method]
  if (typeof fn !== 'function') throw new Error(`未知方法：${method}`)
  return fn(...args)
})

app.whenReady().then(() => {
  backend.init(DATA_DIR)
  registerProtocol()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
