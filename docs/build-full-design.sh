#!/usr/bin/env bash
# docs/build-full-design.sh — 生成「送审定稿」backend-design-full.md（幂等、可重复执行）
#   用法: bash docs/build-full-design.sh
#   特性: ① 锚点式清洗(禁行号) ② 按阅读顺序重排 9 部分 ③ 每部分导读 + 唯一锚点
#         ④ 章节级目录自动汇总 ⑤ 断言失败即退出,先写临时文件再原子替换(不产半成品)
set -euo pipefail
cd "$(dirname "$0")"
OUT=backend-design-full.md
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT

# ---------- 清洗规则(锚点式) ----------
f_strip_trail(){ awk '/^> \*\*修订轨迹\*\*:/{f=1} /^> \*\*概念一致性范围/{f=0} !f' "$1"; }
f_strip_a6(){ sed '/^## A6 /,$d' "$1"; }
f_strip_b8(){ awk '/^## B8 /{f=1} /^## B9 /{f=0} !f' "$1"; }
f_strip_c6(){ awk '/^## C6 /{f=1} /^## C8 /{f=0} !f' "$1"; }
f_strip_m15(){ sed '/^## 15\. /,$d' "$1"; }   # 模块化 §15「与 v27 减法的一致性核对」= 纯过程记录
f_pass(){ cat "$1"; }

# ---------- 阅读顺序(下标即部分号-1) ----------
NAMES=(
 "后端设计主文"
 "后端模块化架构（12 模块 + 4 张 P0 表）"
 "附录 D · 数据契约细则"
 "附录 A · 权威矩阵与写者租约"
 "附录 B · 权限强制注入与安全规范"
 "附录 F · 可观测、容灾与测试"
 "附录 G · 数据导出与删除（GDPR）"
 "附录 C · 生态对标与引用核实"
 "前端对接契约（v3.35 · 评审稿 v27）"
)
FILES=(
 backend-design.md backend-modular-architecture.md backend-contract-detail.md
 backend-authority-matrix.md backend-tenancy-security.md backend-observability-dr.md
 backend-data-lifecycle.md backend-ecosystem-refs.md frontend-contract.md
)
FILTERS=( f_strip_trail f_strip_m15 f_pass f_strip_a6 f_strip_b8 f_pass f_pass f_strip_c6 f_pass )
INTROS=(
 '**本部分看点**：① §0.0 术语与命名(先读) ② §2 目标架构 / **§2.3 读懂体验(L0–L11:锚定 / 阅读路径 / 图不可变 / 快照共享 / 媒体整合 / 发现层)** ③ §4 数据落位(三存储 + 加速器) ④ §5 同步设计 ⑤ **§6.0 发布许可核验(Gate 0/1/2 三车道)** ⑥ §9 落地节奏 ⑦ §11 待拍板决策'
 '**本部分看点**：① §3 模块清单(**12 模块**) ② §7 共享内核 ③ §8 实施路径 ④ **§10 表归属矩阵** ⑤ §11 事件契约 ⑥ §12 降级矩阵 ⑦ §13 错误码契约'
 '**本部分看点**：① D1 VID 编码(固定 `sha256_16`、两端 bit-exact) ② D3 `CodeAnalysis` 唯一写者 ③ D5 `parse_hash` 幂等与快照标识 ④ D6 字段级合并 ⑤ D7 请求体字段清单 ⑥ D8 读路径统一契约 / D9 派生预计算'
 '**本部分看点**：① A1 四种权威分层 ② A2 权威矩阵(生成/存储/读/裁决四层) ③ A5 检索索引同步(`search_outbox`,单目标三态) —— ★ 原 A3(写者租约)/ A4(文件级版本向量)**已随「图不可变」删除**'
 '**本部分看点**：① B1 威胁模型 / B2 三条强制规则 ② B3 逐接口注入清单 ③ B4 OpenSearch 专项 / B5 图数据隔离 ④ B7 审计与可观测 ⑤ B11 错误码矩阵(含越权统一 404)'
 '**本部分看点**：① F1 监控指标(含审计三条阈值) ② F2 备份与容灾(含逐表处置) ③ F3 测试策略与用例集'
 '**本部分看点**：① G1 数据分类与逐表处置 ② G2 导出(含许可与署名) ③ G3 删除执行顺序(九步 + `Job` 记进度) ④ G5 审计保留期 ⑤ G4 验收断言'
 '**本部分看点**：① C1 引用核实与 **C1.4 产品类竞品与不可替代性** ② C2 浏览器解析能力分档 ③ C3 阈值依据(2000 文件 / 100MB) ④ C7 供应链安全 ⑤ C8 效率对标'
 '**本部分看点**：① §1–§13 现状实测契约 ② §14 版本化与弃用登记 ③ **§15 限流统一契约(429 + `Retry-After`)** ④ §16 合约协商 ↔ §17 写路径契约 ⑤ §18 读路径 / §19 客户端义务 / **§20 读懂体验(解释 / 阅读路径 / 进度 / 发布审批 / 媒体整合 / 发现层 / 创作者认证)**'
)

# ---------- 1) 逐部分过滤 + 注入锚点 + 汇总目录 ----------
: > "$W/body.md"; : > "$W/toc.md"

# ---- 1a) 第 0 部分：战略与授权规划（先读）----
#   为什么置 0 号：本部分面向「平台方 / 资助方 / 收购方」，是唯一对外的战略章节；
#   其余 9 部分面向实施团队。放最前面 = 打开即可见（用户要求）。
{
  part0="$W/p0.md"
  f_pass backend-strategy-plan.md > "$part0"
  awk -v p="0" '/^## /{c++; sub(/[ \t]+$/,""); print $0 " {#p0-" c "}"; next} {print}' "$part0" > "$part0.a" && mv "$part0.a" "$part0"
  awk -v p="0" '/^## /{c++; h=$0; sub(/^## /,"",h); print "- [" h "](#p0-" c ")"}' "$part0" >> "$W/toc.md"
  printf -- '---\n\n# 【第 0 部分】%s\n\n' "战略与授权规划（先读）"
  printf -- '> **来源**：`docs/backend-strategy-plan.md`\n>\n'
  printf -- '> **本部分看点**：① ★ 开源 / 商业核心边界清单（可开源 10 项 · 商业核心 10 项 · 三条判据）② 三层授权结构（开源 / 商业 / 商标）③ 功能开关表（可授权 vs 不可授权）④ 递进路线 ⑤ ★ 三条底线\n\n'
  cat "$part0"; printf '\n'
} >> "$W/body.md"

for i in "${!FILES[@]}"; do
  n=$((i+1)); part="$W/p$n.md"
  "${FILTERS[$i]}" "${FILES[$i]}" > "$part"
  awk -v p="$n" '/^## /{c++; sub(/[ \t]+$/,""); print $0 " {#p" p "-" c "}"; next} {print}' "$part" > "$part.a" && mv "$part.a" "$part"
  awk -v p="$n" '/^## /{c++; h=$0; sub(/^## /,"",h); print "- [" h "](#p" p "-" c ")"}' "$part" >> "$W/toc.md"
  {
    printf -- '---\n\n# 【第 %d 部分】%s\n\n' "$n" "${NAMES[$i]}"
    printf -- '> **来源**：`docs/%s`\n>\n' "${FILES[$i]}"
    printf -- '> %s\n\n' "${INTROS[$i]}"
    cat "$part"; printf '\n'
  } >> "$W/body.md"
done

# ---------- 2) 卷首(含自动汇总的章节级目录) ----------
{
cat <<'HEAD'
# 方案完整设计（定稿 · 施工图纸）

> **这份文档是什么**：**完整的最终设计** —— 一份可以照着施工的说明书，按阅读顺序编排，**只讲「最终是什么」，不讲「改过什么」**。
> **权威**：以各源文件为准；本文件由 **10 份源文档**合并生成，**生成物勿手改**。
> **重新生成**：`bash docs/build-full-design.sh`（幂等）。
> **先读**：**第 0 部分 · 战略与授权规划**（开源 / 商业边界 · 授权结构 · 功能开关表），再读主文 **§0.0 术语与命名**。

## 0. 给平台方 / 资助方 / 收购方（先读这一节）

| 你想知道的 | 看哪里 |
|---|---|
| **哪些可以开源、哪些是商业核心** | **【第 0 部分】S2 边界清单**（可开源 10 项 · 商业核心 10 项 · 三条判据） |
| **怎么授权、怎么收钱** | **【第 0 部分】S3 三层授权结构** |
| **我买下来能开哪些商业空间** | ★ **【第 0 部分】S4 功能开关表**（A 组可授权 · B 组授权不了） |
| **这个项目的独特能力是什么** | 【第 8 部分】附录 C（竞品与不可替代性）· 主文 **§2.3**（锚定与解释层） |
| **法律风险干不干净** | 【第 5 部分】附录 B · 【第 1 部分】**§6.0 发布许可核验** · **§2.3.14** |
| **能不能接手（可交接性）** | **【第 0 部分】S7** · 【第 2 部分】模块化架构 |
| **创始人会要什么** | **【第 0 部分】S6 三条底线**（署名 / 商标 / 付费关系） |

## 1. 一句话概览

**以「读懂陌生开源项目」为核心目标的代码图谱学习平台**：浏览器解压即解析 → 图谱提供**导航**、**锚点解释**提供说明、**阅读路径**提供阅读顺序；服务端只托管用户「显式公开」且通过**许可核验**的内容（正常**自动放行**，人工只兜存疑）；**私有内容永不上行、永不可公开**（其长期学习走桌面客户端）。

## 2. 技术组成

| 存储 | 角色 | 权威性 |
|---|---|---|
| **PostgreSQL** | 唯一权威：元数据 / `Job` / 权限 / **图节点·边** / 分析 / 审计 / `search_outbox` | 权威 |
| **OpenSearch** | 检索索引（含全站公开搜索） | 可重建、非权威、最终一致 |
| **Redis** | 限流 / 队列 / 热点邻域缓存 | 非权威、可随时重建 |
| **Neo4j Community（共享池）** | **按需图计算加速器**（>2 跳 / 图算法，用完释放） | 非权威、可随时重建 |

> **完整口径见【第 1 部分】§2 / §4.2 / §4.5 / §5.5** —— 该处为唯一权威定义；本节仅为速览。

## 3. 阅读顺序（本文件编排）

| # | 部分 | 源文件 | 定位 |
|---|---|---|---|
| **0** | ★ **战略与授权规划（先读）** | `backend-strategy-plan.md` | **唯一对外的战略章节**：开源 / 商业边界清单 · 三层授权结构 · 功能开关表 · 递进路线 · 三条底线 |
| 1 | 后端设计主文 | `backend-design.md` | 总体设计（目标架构、读懂体验与解释层、本地优先与发布合规、落地节奏、待拍板决策） |
| 2 | 后端模块化架构 | `backend-modular-architecture.md` | 13 模块 + 4 张 P0 表（表归属/事件/降级/错误码） |
| 3 | 附录 D · 数据契约细则 | `backend-contract-detail.md` | VID 编码、版本向量、fencing、请求体清单 |
| 4 | 附录 A · 权威矩阵与写者租约 | `backend-authority-matrix.md` | 权威四层、租约、outbox 状态机 |
| 5 | 附录 B · 权限注入与安全 | `backend-tenancy-security.md` | 威胁模型、注入清单、审计、错误码 |
| 6 | 附录 F · 可观测与容灾 | `backend-observability-dr.md` | 指标阈值、备份恢复、测试策略 |
| 7 | 附录 G · 导出与删除 | `backend-data-lifecycle.md` | 数据分类、导出、删除九步、验收 |
| 8 | 附录 C · 生态对标 | `backend-ecosystem-refs.md` | 引用核实、产品类竞品、浏览器分档、阈值依据 |
| 9 | 前端对接契约 | `frontend-contract.md` | 现状契约（§1–§13）+ 目标契约（§14–§20） |

**未收录**：附录 E（历史归档）、两份决策登记、4 份参考料。

## 4. 全文章节目录（可跳转）

HEAD
cat "$W/toc.md"
cat <<'TAIL'

---

**门禁状态**：✅ **可开工** —— 检查器与「文档自检清单」已取消，**文档定稿即通过**。

---

TAIL
} > "$W/head.md"

# ---------- 2b) 定稿化清洗（只作用于生成物；源文件保持可追溯） ----------
#   注意：必须清洗**拼装后的整份**（含卷首自动生成的目录），否则目录与正文标题会不一致。
cat "$W/head.md" "$W/body.md" > "$W/out.raw.md"
python3 finalize-full.py < "$W/out.raw.md" > "$W/out.md"

# ---------- 3) 断言(失败即退出,不替换目标) ----------
fail(){ echo "断言失败: $*" >&2; exit 1; }
[ "$(grep -c '^# 【第' "$W/out.md")" = 10 ] || fail "部分数 != 10（含第 0 部分·战略与授权规划）"
[ "$(grep -c '本部分看点' "$W/out.md")" = 10 ] || fail "导读数 != 10"
[ "$(grep -c '^# 【第 0 部分】战略与授权规划' "$W/out.md")" = 1 ] || fail "第 0 部分（战略与授权规划）缺失或不在最前"
h_cnt=$(grep -c '^## .*{#' "$W/out.md"); t_cnt=$(grep -c '^- \[' "$W/out.md")
[ "$h_cnt" = "$t_cnt" ] || fail "锚点数($h_cnt) != 目录条目数($t_cnt)"
[ "$(grep -c "三存储 + 加速器(先读)" "$W/out.md")" = 1 ] || fail "三存储权威定义不唯一"
[ "$(grep -c '^## .*遗留待评审' "$W/out.md")" = 0 ] || fail "残留「遗留待评审」小节"
[ "$(grep -c '本轮 v27 变更摘要' "$W/out.md")" = 0 ] || fail "残留卷尾摘要"
# —— 定稿化(施工图纸口径)断言：不得残留版本 / 评审项 / 删除线标注 ——
clean_assert(){
  local n; n=$(grep -cE "$1" "$W/out.md" || true)
  if [ "$n" != 0 ]; then
    echo "--- 命中样本($n 处) ---" >&2
    grep -nE "$1" "$W/out.md" | head -8 | cut -c1-150 >&2
    fail "$2"
  fi
}
clean_assert '\*\*v[0-9]+|（v[0-9]+' "残留版本标注"
clean_assert '(S-|A-)?P[0-9]-[0-9]+' "残留评审项标注"
clean_assert '~~' "残留删除线登记"
clean_assert '修订轨迹|评审轮次|本稿状态' "残留历史轨迹措辞"

# —— 内容存在性断言（防「清洗过度」；比「无残留」更重要）——
#    背景：曾用「行首加粗标签以 vNN 开头」当整行删除判据，误删约 20 行活内容。
#    每次重建后请同时查看 delete-audit.log 复核被删的行。
for k in '浏览器不做持久化' '六处一致' '生成/存储/读/裁决' '删除进度 = `Job`' \
         '图与元数据' 'graph_analysis.completed' '后置项' '缺实现时' '池大小' '取消发布'; do
  [ "$(grep -c "$k" "$W/out.md" || true)" -ge 1 ] || fail "内容缺失(疑似清洗过度): $k"
done
for f in backend-design.md backend-authority-matrix.md backend-tenancy-security.md backend-ecosystem-refs.md backend-contract-detail.md backend-observability-dr.md backend-data-lifecycle.md backend-modular-architecture.md frontend-contract.md; do
  [ -s "$f" ] || fail "源文件缺失: $f"
done

# —— 禁用词断言(第7类:已删除机制不得留下活引用;见 check-forbidden.sh) ——
#    背景:多轮"删机制"后曾残留 nebula / ProjectDeletion / FIXED_STRING / 两把锁 等活引用,
#    仅靠人工扫描无法根治 → 改为机械断言。
#    两道:①扫 10 份源文件 ②扫**生成物**(封住"构建脚本导读 / finalize 产物"等盲区)。
bash check-forbidden.sh --assert >/dev/null || fail "源文件存在已删除机制的活引用 —— 运行 \`bash check-forbidden.sh\` 查看明细"
bash check-forbidden.sh --assert "$W/out.md" >/dev/null || fail "生成物存在已删除机制的活引用 —— 运行 \`bash check-forbidden.sh --assert <生成物>\` 查看明细"

mv "$W/out.md" "$OUT"
echo "已生成 $OUT : $(wc -l < "$OUT") 行 · 部分 $(grep -c '^# 【第' "$OUT") · 锚点 $h_cnt / 目录 $t_cnt"
