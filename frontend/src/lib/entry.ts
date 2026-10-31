/**
 * ★★ **入口识别**（路标，不是流程图）
 *
 * 所有者原话（2026-10-31）：
 * 「入口还有点用，流程图感觉没有用。我这不是图谱工具，不需要看流程，
 *   我这只要用户知道从哪里开始，再去学习代码，自然就知道流程是如何了，
 *   而不是 gitnexus 那样给专家掌握全局的工具。」
 *
 * ## 只做一件事
 *
 * ```
 * 告诉用户"从这几行开始读"，然后他自己顺着调用边走
 * ⛔ 不算执行流、不画路径、不猜"哪个函数更重要"
 * ```
 *
 * ## 规则（有限枚举 · 认不出就不标）
 *
 * ```
 * 函数名 main / __main__            C / Java / Python 的常规入口
 * 文件名叫 main.*（main.c/main.py…） 入口常驻文件，单独标出来
 * ```
 *
 * ⚠ 认不出（比如库项目没有 main）就**一个都不标**，让用户自己找——
 *   乱标比不标更糟：它会让人从错误的地方开始读。
 */

import type { GraphNode } from './mergeGraph'

/** 函数名口径 */
const ENTRY_FUNCS = new Set(['main', '__main__'])

/** 文件名口径（`main.c` / `Main.java` / `main.py`） */
const ENTRY_FILE = /^main\.[A-Za-z0-9]+$/i

export function isEntryNode(n: Pick<GraphNode, 'kind' | 'name'>): boolean {
  if (n.kind === 'function' || n.kind === 'method') {
    return ENTRY_FUNCS.has((n.name || '').trim())
  }
  if (n.kind === 'file') {
    return ENTRY_FILE.test((n.name || '').trim())
  }
  return false
}

/** 把入口节点排到最前（其余保持原顺序，稳定排序） */
export function entriesFirst<T extends Pick<GraphNode, 'kind' | 'name'>>(items: T[]): T[] {
  const head: T[] = []
  const tail: T[] = []
  for (const n of items) (isEntryNode(n) ? head : tail).push(n)
  return head.length ? [...head, ...tail] : items
}
