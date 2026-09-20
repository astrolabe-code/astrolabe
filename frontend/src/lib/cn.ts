import { twMerge } from 'tailwind-merge'

/** 类名合并:过滤空值 + tailwind-merge 去重(避免冲突工具类) */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return twMerge(parts.filter(Boolean).join(' '))
}
