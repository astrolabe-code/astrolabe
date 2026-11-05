/**
 * 项目图标:后端 `icon_lucide` 是 lucide 的 kebab 名(见 project_service.ICON_EMOJI_MAP),
 * 这里显式登记映射,保证按需 tree-shake,不用 `import * as` 拖进整包。
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import type { ComponentType } from 'react'
import {
  Apple, Book, Brain, ChartColumn, CircleCheck, CircleX, ClipboardList, CodeXml,
  Construction, Download, FileText, Flame, FlaskConical, Folder, FolderOpen,
  Gamepad2, Globe, Hammer, Hourglass, Lightbulb, Lock, Microscope, Monitor,
  Package, Palette, Pencil, Puzzle, RefreshCw, Rocket, Save, Search, Settings,
  Share2, Shell, Smartphone, Star, Terminal, Trash, TrendingDown, TrendingUp,
  Upload, Wrench, Zap,
} from 'lucide-react'

/** 只用到 size/className,放宽为 ComponentType<any> 以兼容 lucide 的 ForwardRef 类型 */
export type LucideLike = ComponentType<any>

const ICONS: Record<string, LucideLike> = {
  'package': Package,
  'folder': Folder,
  'folder-open': FolderOpen,
  'file-text': FileText,
  'book': Book,
  'wrench': Wrench,
  'hammer': Hammer,
  'rocket': Rocket,
  'bar-chart-3': ChartColumn,
  'trending-up': TrendingUp,
  'trending-down': TrendingDown,
  'brain': Brain,
  'zap': Zap,
  'microscope': Microscope,
  'globe': Globe,
  'save': Save,
  'palette': Palette,
  'puzzle': Puzzle,
  'lightbulb': Lightbulb,
  'flame': Flame,
  'star': Star,
  'code-2': CodeXml,
  'share-2': Share2,
  'upload': Upload,
  'download': Download,
  'trash-2': Trash,
  'pencil': Pencil,
  'refresh-cw': RefreshCw,
  'clipboard-list': ClipboardList,
  'gamepad-2': Gamepad2,
  'settings': Settings,
  'lock': Lock,
  'check-circle-2': CircleCheck,
  'x-circle': CircleX,
  'hourglass': Hourglass,
  'construction': Construction,
  'monitor': Monitor,
  'smartphone': Smartphone,
  'search': Search,
  'flask-conical': FlaskConical,
  'terminal': Terminal,
  'apple': Apple,
  'shell': Shell,
}

/** 取项目图标组件;未知名字回退 package(与后端 icon_lucide 兜底一致) */
export function projectIcon(name?: string): LucideLike {
  return ICONS[name || ''] || Package
}
