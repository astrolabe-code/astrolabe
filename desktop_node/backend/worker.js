const { scan } = require('./parse/scan')

// 只做 CPU 密集的扫描，不碰数据库；一个任务一条结果消息
process.parentPort.on('message', (event) => {
  let payload
  try {
    payload = { result: scan(event.data.root) }
  } catch (e) {
    payload = { error: String((e && e.message) || e) }
  }
  process.parentPort.postMessage(payload)
})
