/** @type {import('tailwindcss').Config} */
// D20:Tailwind 只做布局工具类,颜色/字体/圆角全部映射现站 CSS 变量(D18),
// 因此不重写外观,视觉与旧站 1:1
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        'bg-deep': 'var(--bg-deep)',
        card: 'var(--card)',
        'card-border': 'var(--card-border)',
        'text-main': 'var(--text-main)',
        'text-sub': 'var(--text-sub)',
        'text-faint': 'var(--text-faint)',
        accent: 'var(--accent)',
        'accent-strong': 'var(--accent-strong)',
        'accent-dim': 'var(--accent-dim)',
        ok: 'var(--ok)',
        warn: 'var(--warn)',
        err: 'var(--err)',
        'code-bg': 'var(--code-bg)',
        'code-bar': 'var(--code-bar)',
        'code-border': 'var(--code-border)',
        'code-text': 'var(--code-text)',
        'code-dim': 'var(--code-dim)',
      },
      fontFamily: {
        ui: 'var(--font-ui)',
        mono: 'var(--font-mono)',
      },
      borderRadius: {
        card: 'var(--radius)',
        ctl: 'var(--radius-sm)',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        'card-hover': 'var(--shadow-card-hover)',
        dlg: 'var(--shadow-dlg)',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
