const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  invoke: (method, ...args) => ipcRenderer.invoke('invoke', method, args),
})
