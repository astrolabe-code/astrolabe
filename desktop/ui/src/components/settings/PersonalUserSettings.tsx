/**
 * ★★★ **个人版 · 用户设置**
 *
 * 社区版这一页有「个人资料 / 图谱外观 / 存储 / 账号」四栏 —— 个人版全都没有对象：
 * 没有头像昵称、没有云端存储、没有账号。
 *
 * 所以这一页只说实话：
 *
 * ```\n * 版本            你装的是哪一版\n * 数据在哪         程序和清单的位置（笔记不在这，在各自的项目目录里）\n * 笔记在哪         指向「项目设置」—— 每个项目的笔记位置都不一样\n * 许可证           第三方组件声明（合规要求）\n * ```\n */

import { useEffect, useState } from 'react'
import { ExternalLink, FolderOpen } from 'lucide-react'

import {
  getMeteors,
  setMeteors as saveMeteors,
  getCodeFontSize,
  setCodeFontSize as saveCodeFontSize,
  getCodeFontFamily,
  setCodeFontFamily as saveCodeFontFamily,
  CODE_FONT_SIZES,
  CODE_FONT_STACKS,
} from '../../lib/uiPrefs'

interface Info {
  version: string
  dataDir: string
  packaged: boolean
  notices?: string
}

export default function PersonalUserSettings() {
  // ★ 外观偏好（流星）—— 与图谱页共用 lib/uiPrefs
  const [meteors, setMeteors] = useState(getMeteors)
  // ★ 代码外观（字号 / 字体）—— 改完写 CSS 变量，已打开的代码窗口即时生效
  const [codeFontSize, setCodeFontSize] = useState(getCodeFontSize)
  const [codeFontFamily, setCodeFontFamily] = useState(getCodeFontFamily)
  const [info, setInfo] = useState<Info | null>(null)
  const api = (
    window as unknown as {
      astrolabe?: { info?: () => Promise<Info>; openPath?: (p: string) => Promise<boolean> }
    }
  ).astrolabe

  useEffect(() => {
    api?.info?.().then(setInfo).catch(() => {})
  }, [api])

  const row: React.CSSProperties = {
    display: 'flex',
    alignItems: 'baseline',
    gap: 10,
    padding: '8px 0',
    borderBottom: '1px dashed var(--card-border)',
    fontSize: 12.5,
  }
  const key: React.CSSProperties = { width: 88, color: 'var(--text-faint)', flex: 'none' }
  const mono: React.CSSProperties = {
    fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
    fontSize: 11.5,
    wordBreak: 'break-all',
  }
  const link: React.CSSProperties = {
    marginLeft: 'auto',
    border: '1px solid var(--card-border)',
    background: 'transparent',
    borderRadius: 6,
    padding: '2px 8px',
    fontSize: 11.5,
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    flex: 'none',
  }

  if (!info) return <div className="faint" style={{ fontSize: 13 }}>加载中…</div>

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="card" style={{ padding: '14px 16px' }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 6 }}>关于</div>
        <div style={row}>
          <span style={key}>版本</span>
          <span>{info.version}{info.packaged ? '' : '（开发模式）'}</span>
        </div>
        <div style={row}>
          <span style={key}>数据目录</span>
          <span style={mono}>{info.dataDir}</span>
          <button type="button" onClick={() => void api?.openPath?.(info.dataDir)} style={link}>
            <FolderOpen size={11} /> 打开
          </button>
        </div>
        <div style={{ ...row, borderBottom: 'none' }}>
          <span style={key}>第三方声明</span>
          <span className="faint" style={{ fontSize: 12 }}>
            安装目录里的 THIRD-PARTY-NOTICES.txt
          </span>
          {info.notices && (
            <button type="button" onClick={() => void api?.openPath?.(info.notices!)} style={link}>
              <ExternalLink size={11} /> 打开
            </button>
          )}
        </div>
      </div>

      <div className="card" style={{ padding: '14px 16px', marginTop: 12 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 6 }}>笔记存在哪里</div>
        <div style={{ fontSize: 12.5, lineHeight: 2, color: 'var(--text-sub)' }}>
          笔记跟着项目走 —— 每个项目都有自己的位置：
          <div style={{ marginTop: 6, ...mono }}>
            源码项目 ⇒ &lt;源码目录&gt;/.astrolabe/notes/
            <br />
            手动结构 ⇒ &lt;你选的目录&gt;/.astrolabe/notes/
          </div>
          <div style={{ marginTop: 8 }}>
            具体某个项目存在哪，去那个项目的 <b>设置</b> 里看（那一页有个「打开」按钮）。
          </div>
        </div>
      </div>

      {/* ★★★ 2026-11-05：外观（流星）—— 所有者：「流星这个应该在设置页面出现」 */}
      <div className="card" style={{ padding: '14px 16px', marginTop: 12 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 6 }}>外观</div>
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 12.5,
            color: 'var(--text-sub)',
            cursor: 'pointer',
            lineHeight: 1.8,
          }}
        >
          <input
            type="checkbox"
            checked={meteors}
            onChange={(e) => {
              setMeteors(e.target.checked)
              saveMeteors(e.target.checked)
            }}
          />
          流星特效
          <span className="faint" style={{ fontSize: 11.5 }}>
            图谱里节点之间飞过的流光（关掉更快、更安静）
          </span>
        </label>

        {/* ★★★ 2026-11-06：代码字号 / 字体
            所有者：「字号能不能调整？就把这个按钮放在设置页，
                    要是还能换几个没版权限制的字体，就好了」 */}
        <div style={{ ...row, display: 'flex', alignItems: 'center', marginTop: 10 }}>
          <span style={key}>代码字号</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {CODE_FONT_SIZES.map((px) => (
              <button
                key={px}
                type="button"
                onClick={() => {
                  setCodeFontSize(px)
                  saveCodeFontSize(px)
                }}
                style={{
                  padding: '3px 10px',
                  fontSize: 11.5,
                  borderRadius: 6,
                  cursor: 'pointer',
                  border: `1px solid ${codeFontSize === px ? 'var(--accent)' : 'var(--card-border)'}`,
                  background: codeFontSize === px ? 'var(--accent-dim)' : 'transparent',
                  color: codeFontSize === px ? 'var(--accent)' : 'var(--text-sub)',
                }}
              >
                {px}
              </button>
            ))}
          </div>
        </div>
        <div style={{ ...row, display: 'flex', alignItems: 'center' }}>
          <span style={key}>代码字体</span>
          <select
            className="input"
            style={{ fontSize: 12.5, maxWidth: 340, fontFamily: codeFontFamily }}
            value={codeFontFamily}
            onChange={(e) => {
              setCodeFontFamily(e.target.value)
              saveCodeFontFamily(e.target.value)
            }}
          >
            {CODE_FONT_STACKS.map((f) => (
              <option key={f.label} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
        <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.8 }}>
          这些都是系统自带或开源自由许可（OFL 等）的等宽字体，软件不随附字体文件 ——
          用本机已装的那一个，没装会自动回退到系统等宽字体。改完立即生效，已打开的代码窗口也会跟着变。
        </div>
        <div
          style={{
            marginTop: 10,
            padding: '10px 12px',
            borderRadius: 8,
            background: 'var(--code-bg, #f6f8fa)',
            border: '1px solid var(--card-border)',
            fontFamily: codeFontFamily,
            fontSize: codeFontSize,
            lineHeight: 1.8,
            color: 'var(--code-text, #24292f)',
            overflowX: 'auto',
            whiteSpace: 'pre',
          }}
        >
          <span style={{ color: '#c026d3', fontWeight: 600 }}>def</span>{' '}
          <span style={{ color: '#1d4ed8' }}>greet</span>(name):
{'\n    '}<span style={{ color: '#7c3aed', fontWeight: 600 }}>return</span>{' '}
          <span style={{ color: '#0a7d47' }}>f&quot;hi, {'{name}'}&quot;</span>
        </div>
      </div>

      <div className="card" style={{ padding: '14px 16px', marginTop: 12 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 6 }}>账号</div>
        <div style={{ fontSize: 12.5, lineHeight: 2, color: 'var(--text-sub)' }}>
          个人版只有你一个人，没有登录、没有账号、没有云端同步。
          <br />
          所有数据都在你自己的磁盘上，拷走文件夹就是搬家。
        </div>
      </div>
    </div>
  )
}
