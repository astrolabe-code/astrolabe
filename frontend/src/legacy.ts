/**
 * ★ SPA 内部链接表（B163 重写）
 *
 * ## ⚠★ 与原版（`/home/webapp/demo/frontend/src/legacy.ts`）的差别
 *
 * ★ 原版叫 `legacy.js`，用途是 **「迁移期降级」**：
 *   SPA 尚未实现的页面，**跳回旧站**对应 URL（`D33`），
 *   首页 CTA 也暂指旧站（`D23`）—— ⚠ 因为那个项目**与旧站并存**。
 *
 * ★★★ **本项目没有旧站** ⇒ ★ 那些路径（`/login/` · `/register/` · `/manuals/`
 *   · `/feedback/` · `/tools/code/` · `/manage/settings/` · `/me/`）
 *   **全是死的** ⚠ ⇒ ★ 已**整体删除**，只保留 **SPA 自己的路由**。
 *
 * ★ 用户裁定（`B163`）：★「**不用一定与以前一样，那是初稿**」✅
 *
 * ## ★ `legacyUrlFor()` 也一并删除
 *
 * ★ 它原本给 `App.tsx` 的 `LegacyRedirect` 用（★ 未匹配路由 ⇒ 跳旧站）。
 * ★★ 本项目**无处可跳** ⇒ ★ 未匹配路由**直接回首页**（见 `App.tsx`）。
 */

/** ★ SPA 内部路径 —— ⚠ 一律带 `/app` 前缀（`D26`：SPA 固定挂 `/app/`，不占用 `/`） */
export const SPA_LINKS = {
  home: '/app/',
  workspace: '/app/workspace',
  login: '/app/login',
} as const
