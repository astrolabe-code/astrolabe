import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FolderOpen, Settings } from 'lucide-react'

import Button from './ui/Button'

interface DesktopApi {
  isDesktop?: boolean
  info?: () => Promise<{ version: string; dataDir: string }>
  openDataDir?: () => Promise<boolean>
}

/**
 * ★★★ **两个全局动作：设置 / 打开数据目录**（2026-11-05）
 *
 * 所有者：「除了搜索按钮，把其他按钮都移到左边，能合为一类的合为一类，并折叠」
 *
 * ## 为什么单独抽一个组件
 *
 * ```
 * 原来它们平铺在**顶栏右侧**（搜索 / 设置 / 数据 三个并排）
 * 现在顶栏右侧只留「搜索 Ctrl+K」
 * ⇒ 这两个动作进"工具"菜单（顶栏左边那个折叠项）
 * ⇒ 菜单在页面里渲染、动作属于全局 ⇒ 抽成组件，两边都能用
 * ```
 */
export default function AppMenuItems() {
  const nav = useNavigate()
  const [dataDir, setDataDir] = useState('')
  const api = (window as unknown as { astrolabe?: DesktopApi }).astrolabe

  useEffect(() => {
    // ★ 只在桌面版里有；浏览器里打开就什么都不显示（不报错）
    api?.info?.().then((i) => setDataDir(i.dataDir)).catch(() => {})
  }, [api])

  return (
    <>
      <Button icon={<Settings size={13} />} onClick={() => nav('/me/settings')} title="设置">
        设置
      </Button>
      {dataDir && (
        <Button
          icon={<FolderOpen size={13} />}
          onClick={() => void api?.openDataDir?.()}
          title={dataDir}
        >
          打开数据目录
        </Button>
      )}
    </>
  )
}
