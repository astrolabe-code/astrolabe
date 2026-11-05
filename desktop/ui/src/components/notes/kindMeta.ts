import {
  BookOpenCheck,
  CircleHelp,
  Lightbulb,
  ListChecks,
  Scale,
  TriangleAlert,
  Zap,
} from 'lucide-react'
import type { NoteKind } from '../../api/types'

/**
 * ★★ **笔记的 5 种「盒子」**（`B201` · 固定枚举）
 *
 * ⚠★ 所有者原话整句：「**可增删最多四五个，你整个表干什么？**」
 *   ⇒ ★ 固定 5 种，❌ 不是用户自定义字段 ✅
 *
 * ⚠★ 本文件是**标签与图标的唯一出处**（列表 / 编辑器 / 徽标共用它）——
 *   ❌ 不在各组件里各写一份（早晚不一致）⚠
 */
export const NOTE_KINDS: readonly NoteKind[] = [
  'flash',
  'question',
  'confuse',
  'pitfall',
  'summary',
]

export interface KindMeta {
  /** 中文标签（UI 显示用） */
  label: string
  /** 图标 */
  icon: typeof Zap
  /** 一句话说明（编辑器里给用户看） */
  hint: string
  /** ★★ 该类型的主题色（* 五个盒子各不同色；卡片标签 / 分组标题 / 编辑器共用）⚠ */
  color: string
}

export const KIND_META: Record<NoteKind, KindMeta> = {
  // ★★★ 五色：* 灵感=琥珀、* 质疑=蓝、* 困惑=紫、* 踩坑=红、* 小结=绿 ⚠
  //   · · ★ 深浅两套主题下都够亮（* 饱和度高、* 不依赖 --accent）✅
  flash: { label: '灵光一闪', icon: Lightbulb, hint: '突然明白的一件事', color: '#f59e0b' },
  // ★★★ 2026-10-27：**质疑 ≠ 困惑**（所有者原话，逐字）⚠
  //   「**质疑是凭什么我这样写代码不行，而困惑是为什么要这样写，我看不懂。**」
  //   ⇒ 差别在**写的人有没有立场**：
  //      · 质疑 = 有立场，能说出更好的写法 ⇒ 要作者**回应/辩护**
  //      · 困惑 = 没立场，只是缺信息   ⇒ 只要作者**解释一句**
  //   ⚠ 旧版两条 hint 都写成「为什么」，图标又都是 CircleHelp
  //     ⇒ 界面上这两类根本分不开（数据里 question 长期 0 篇）⚠
  question: {
    label: '质疑',
    icon: Scale,
    hint: '我觉得这里该那样写 —— 凭什么非要这样？',
    color: '#3b82f6',
  },
  confuse: {
    label: '困惑',
    icon: CircleHelp,
    hint: '这段在干什么 —— 暂时看不懂',
    color: '#a855f7',
  },
  pitfall: { label: '踩坑', icon: TriangleAlert, hint: '这里容易出错', color: '#ef4444' },
  summary: { label: '小结', icon: ListChecks, hint: '串起一片知识的总结', color: '#10b981' },
}

/** ★ 兜底：未知 kind 不该出现（后端已校验），真出现了也别崩 ✅ */
export function kindMeta(kind: string): KindMeta {
  return (
    KIND_META[kind as NoteKind] ?? {
      label: kind || '笔记',
      icon: BookOpenCheck,
      hint: '',
      color: '#94a3b8',
    }
  )
}
