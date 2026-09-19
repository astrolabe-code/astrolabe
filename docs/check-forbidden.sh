#!/usr/bin/env bash
# docs/check-forbidden.sh — 已删除机制的「禁用词」扫描/断言
#   用法: bash check-forbidden.sh            # 只报告(扫描 9 份源文件)
#         bash check-forbidden.sh --assert   # 断言模式:有残留则非 0 退出(供 build 调用)
#   白名单:含「删除声明标记」的行视为"已删除说明",不算残留
set -uo pipefail
cd "$(dirname "$0")"

MODE="${1:-report}"

# 用法:bash check-forbidden.sh              → 扫 9 份源文件(报告)
#      bash check-forbidden.sh --assert     → 扫 9 份源文件 + 断言
#      bash check-forbidden.sh --assert F   → 只扫指定文件(供 build 扫生成物)
if [ -n "${2:-}" ]; then
  FILES=("$2")
else
  FILES=(
    backend-design.md backend-modular-architecture.md backend-contract-detail.md
    backend-authority-matrix.md backend-tenancy-security.md backend-observability-dr.md
    backend-data-lifecycle.md backend-ecosystem-refs.md frontend-contract.md
    backend-strategy-plan.md
  )
fi

# —— 禁用词(已删除的机制 / 表 / 字段 / 术语) ——
PATTERN='nebula|Nebula|ProjectDeletion|ProjectWriterLease|DeviceSession|ProjectSyncState|lease_epoch|writer_token|stale_baseline|stale_writer|no_write_lease|base_graph_rev|base_file_rev|file_rev|hash_algo|vid_type|CREATE SPACE|FIXED_STRING|partition_num|replica_factor|两把锁|active_fence|diverged|relocated|needs_review|pending_repair|inconsistent|graph_outbox|graph_node_ref|nebula_graph_rev|vid_op_rev|snapshot_hash|outbox_stale_dropped|when_guard_semantics'

# —— 白名单:这些行「本身就在说"它已被删除/不允许出现"」,不算活引用 ——
#    判据:含删除/否定动词,或含历史版本标记,或为墓碑行(~~)
ALLOW='删除|移除|作废|已删|被删|删 |不再|不需要|不涉及|不适用|不引入|原|~~|历史改名|v[0-9]|全清|已收敛|PERMITTED|不提供|不出现|现状|目标改判|目标口径|无租约|无两把锁|无客户端写者|无写者|同上'

total=0
for f in "${FILES[@]}"; do
  [ -s "$f" ] || { echo "!! 源文件缺失: $f"; exit 1; }
  hits=$(grep -nE "$PATTERN" "$f" 2>/dev/null | grep -vE "$ALLOW" || true)
  if [ -n "$hits" ]; then
    n=$(printf '%s\n' "$hits" | wc -l)
    total=$((total + n))
    echo "=== $f （$n 处）==="
    printf '%s\n' "$hits" | cut -c1-155
    echo
  fi
done

echo "───────────────"
echo "残留合计: $total 处（已排除删除声明行）"

if [ "$MODE" = "--assert" ] && [ "$total" != "0" ]; then
  echo "断言失败:存在已删除机制的活引用" >&2
  exit 1
fi
exit 0
