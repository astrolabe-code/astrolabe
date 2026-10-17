import {
  BookOpenCheck,
  CircleHelp,
  Lightbulb,
  ListChecks,
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
}

export const KIND_META: Record<NoteKind, KindMeta> = {
  flash: { label: '灵光一闪', icon: Lightbulb, hint: '突然明白的一件事' },
  question: { label: '质疑', icon: CircleHelp, hint: '这里为什么要这样写？' },
  confuse: { label: '困惑', icon: CircleHelp, hint: '看不懂，先记下来' },
  pitfall: { label: '踩坑', icon: TriangleAlert, hint: '这里容易出错' },
  summary: { label: '小结', icon: ListChecks, hint: '串起一片知识的总结' },
}

/** ★ 兜底：未知 kind 不该出现（后端已校验），真出现了也别崩 ✅ */
export function kindMeta(kind: string): KindMeta {
  return KIND_META[kind as NoteKind] ?? { label: kind || '笔记', icon: BookOpenCheck, hint: '' }
}
