/**
 * ★★★ **节点类型的显示名 + 颜色**（唯一来源）
 *
 * 所有者原话（2026-10-31）：
 * 「类型不要用中文写呀，用英文，长了，就用看得懂的缩写。还有一种类型对应一种颜色，
 *   鲜艳，好区分就行。左侧列表上的类型徽标也要统一有颜色，现在是灰色的。
 *   还有节点对应什么颜色，图谱上的节点就什么颜色，要统一，这样根据颜色就能判断了。」
 *
 * ## 两条规则
 *
 * ```
 * ① 名字用英文；太长就给缩写（function → func，interface → iface，typedef → alias）
 * ② **一种类型一种颜色**，列表徽标 / 面板徽标 / 图谱节点，全部取自这张表
 * ```
 *
 * ⚠ 颜色只用于"区分"，不承载语义（不是"蓝=好、红=坏"）。
 * ⚠ 新增类型时**必须同时加一行**，否则会落到灰色兜底（见 `colorOf`）。
 */

/** 类型 → 英文显示名（缩写版） */
export const KIND_LABEL: Record<string, string> = {
  file: 'file',
  dir: 'dir',
  function: 'func',
  method: 'method',
  class: 'class',
  interface: 'iface',
  struct: 'struct',
  union: 'union',
  enum: 'enum',
  typedef: 'alias',
  record: 'record',
  macro: 'macro',
  module: 'module',
  package: 'pkg',
  variable: 'var',
  constant: 'const',
  field: 'field',
  type: 'type',
}

/**
 * 类型 → 颜色（鲜艳、彼此区分度大）
 *
 * 取舍：**相邻色相不放在一起**（蓝/青/绿/黄/橙/红/紫交替），
 * 这样即使 4% 的人有轻度色觉差异，也能靠明度差区分。
 */
export const KIND_COLOR: Record<string, string> = {
  file: '#16a34a',      // 绿
  dir: '#78716c',       // **暖灰（石色）**—— 结构件不抢眼，但≠兜底灰
  function: '#2563eb',  // 蓝
  method: '#ec4899',    // 玫红
  class: '#f59e0b',     // 琥珀
  interface: '#8b5cf6', // 紫罗兰
  struct: '#0d9488',    // 青绿
  union: '#b45309',     // 棕
  enum: '#84cc16',      // 黄绿
  typedef: '#0891b2',   // 青
  record: '#d946ef',    // 品红
  macro: '#ef4444',     // 红（预处理器是"另一类东西"，给它最跳的颜色）
  module: '#6366f1',    // 靛蓝
  package: '#6366f1',
  variable: '#14b8a6',  // 蓝绿
  constant: '#eab308',  // 黄
  field: '#0369a1',     // 深蓝
  type: '#d97706',      // 琥珀（旧的合并类型）
}

/**
 * 未登记类型的兜底色
 *
 * ⚠ 用**近黑**而不是灰：灰色已经被 `dir`（暖灰石色）占了，
 *   两个灰放在一起根本分不出"这是目录"还是"这是没登记的类型"。
 *   近黑 + 虚线边框（见 `kindKnown`）⇒ 一眼看出"这个类型有问题"。
 */
export const FALLBACK_COLOR = '#111827'

/** 这个类型登记过吗（没登记 ⇒ 用虚线边框把它标出来） */
export const kindKnown = (kind: string) => kind in KIND_COLOR

export const kindLabel = (kind: string) => KIND_LABEL[kind] || kind

export const kindColor = (kind: string) => KIND_COLOR[kind] || FALLBACK_COLOR
