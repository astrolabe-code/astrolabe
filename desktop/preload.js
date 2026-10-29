/**
 * ★ 预加载：**只暴露"事实"，不暴露能力**
 *
 * ```\n * ⛔ 不给渲染进程 fs / child_process / ipcRenderer 原件\n * ✅ 只给一个只读对象（版本、数据目录、是不是桌面版）\n * ```\n *
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
  /** 用系统文件管理器打开数据目录（备份用） */
  openDataDir: () => ipcRenderer.invoke('app:open-data-dir'),
})
