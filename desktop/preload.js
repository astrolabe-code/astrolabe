/**
 * ★ 预加载：**只暴露"事实"，不暴露能力**
 *
 * ```\n * ⛔ 不给渲染进程 fs / child_process / ipcRenderer 原件\n * ✅ 只给一个只读对象（版本、数据目录、是不是桌面版）\n * ✅ 例外：frame:false 自绘标题栏需要窗口控制，只暴露四个固定动作\n * ```\n *
 * ⚠ 业务数据一律走 `app://local/api/*`（由主进程转给边车），
 *   ⛔ 不要在这里再开一条数据通道 —— 两条路会让"数据从哪来"变得不可追。
 */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('astrolabe', {
  /** ★ 桌面版标记：前端用它切换「绿色版」相关的 UI（比如显示数据目录） */
  isDesktop: true,
  /** 版本 + 数据目录（都是只读事实） */
  info: () => ipcRenderer.invoke('app:info'),
  /** ★ 原生目录选择（返回绝对路径，取消则 null）—— 浏览器做不到 */
  pickDirectory: () => ipcRenderer.invoke('app:pick-dir'),
  /** ★ 打开任意路径（目录或文件） */
  openPath: (target) => ipcRenderer.invoke('app:open-path', target),
  /** 用系统文件管理器打开数据目录（备份用） */
  openDataDir: () => ipcRenderer.invoke('app:open-data-dir'),

  /** ★ 自绘标题栏：窗口控制（frame:false 后原生按钮没有了） */
  winMinimize: () => ipcRenderer.invoke('win:minimize'),
  winToggleMaximize: () => ipcRenderer.invoke('win:toggle-maximize'),
  winClose: () => ipcRenderer.invoke('win:close'),
  winIsMaximized: () => ipcRenderer.invoke('win:is-maximized'),
  /** 最大化状态变化订阅，返回取消订阅函数 */
  onWinMaximized: (cb) => {
    const listener = (_e, value) => cb(!!value)
    ipcRenderer.on('win:maximized', listener)
    return () => ipcRenderer.removeListener('win:maximized', listener)
  },
})
