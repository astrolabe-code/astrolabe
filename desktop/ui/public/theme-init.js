// 主题初始化(防闪变):在 CSS 解析前同步设置 data-theme
// 与旧站 assets/static/js/theme-init.js 保持同 key(theme)、同取值(light|dark)、同元素(<html data-theme>)
// 外置脚本以满足 CSP script-src 'self'
;(function () {
  try {
    var t = localStorage.getItem('theme')
    if (t === 'dark' || t === 'light') {
      document.documentElement.setAttribute('data-theme', t)
    }
  } catch (e) {
    /* 隐私模式忽略 */
  }
})()
