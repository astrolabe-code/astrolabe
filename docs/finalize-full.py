#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finalize-full.py —— 把「评审稿」清洗成「施工图纸」风格的定稿正文。

用法:  python3 finalize-full.py < in.md > out.md
只作用于**生成物**（backend-design-full.md）；源文件保持可追溯，不受影响。

清洗内容:
  1) 版本 / 评审项标注        （v27、v19 P1-10、S-P0-4、P2-14 …）
  2) 已删除功能的登记行        （表格行首格整格删除线 / 删除线列表项）
  3) 行内删除线片段            （去掉 ~~…~~ 包裹、保留正文）
  4) 「已裁定 / 已改判」等过程措辞
  5) 清理删除后残留的悬空标点

安全约束（**由一次真实事故得出，勿删**）:
  - **不做**任何缩进/空白压缩（会破坏代码块与嵌套列表）；
  - **代码围栏内**只做行内清洗，不做整行删除（避免误删代码行）；
  - ⚠ **禁止用「行首加粗标签以 vNN 开头」当整行删除判据** —— 大量活口径行
    长这样（`> **v28 会话态定位**:…`、`- **v19-1 · 解析 Worker 池**：…`、
    `| **⚠ v27 删除进度载体** | … |`），整行删除会**丢正文**。
    版本/评审项标注一律走 RE_INLINE：**只去标签、保留正文**。
  - 每次删除的行都会写入 `delete-audit.log`（**删除必须可审计**）。
"""
import io
import re
import sys

FENCE = re.compile(r'^\s*(```|~~~)')

# ---------- 1) 整行删除（仅围栏外；只保留「明确是已删功能登记」） ----------
LINE_DROP = [
    re.compile(r'^\|\s*~~[^|]*~~\s*\|'),            # 表格：首格为删除线（“某表/某字段已删”）
    re.compile(r'^\s*\d+\.\s*~~'),                  # 编号列表项以删除线开头
    # 文档流程说明（**逐行精确**，勿改成块删除，见下方注释）
    re.compile(r'^\s*>\s*\*\*约定\*\*\s*[:：]\s*附录标题'),   # “**约定**:附录标题只跟评审轮次…”
]

# 纯过程说明行：**仅当关键词出现在「行首的加粗标签」内**时才整行删除。
#   ⚠ 绝不能改成「行内命中即删」—— 曾因此误删:
#       · 章节标题 `### 4.4 `project_ref` 规范(…;本项为用户追加,非评审轮次产生)`
#       · 夹带活内容的行 `> **⚠ 阶段重排(先读)**:…;后置项 = `cursor` 分片 / …`
#   ⚠ 也不能用「行首加粗标签以 vNN 开头」当判据（见文件头「安全约束」）。
LINE_DROP_KW = re.compile(
    r'^\s*[>|]?\s*(?:[-*+]\s+)?\*\*[^*]{0,40}?'
    r'(两条版本线|本稿状态|修订轨迹|评审轮次|历史轨迹|写入纪律'
    r'|文档头部版本号|编辑插入顺序)[^*]{0,40}?\*\*')
# ⚠ 已移除 `概念一致性范围` / `口径收敛说明`：这两行夹带**活约束**
#   （「六处一致」要求；「生成/存储/读/裁决」四层拆分），删了会丢内容。

# ⚠ 已试过「整块删除（连带后续 `>` 行）」并**撤销**：主文文首那几行属于**同一个大引用块**
#   （文件名说明 → 本文档用途 → 概念一致性范围 → 写入纪律 → 本稿状态 连成一块），
#   块删除会连带吃掉夹带活约束的 `概念一致性范围`（「六处一致」）→ **只允许逐行精确删除**。

# ---------- 2) 括号标注：整体删除 ----------
RE_PAREN = [
    re.compile(r'[（(]\s*(?:v\d+\s*)?(?:S-|A-)?P\d\s*-\s*\d+[^（()）]*[)）]'),
    re.compile(r'[（(]\s*v\d+[^（()）]{0,90}[)）]'),
]

# ---------- 3) 行内替换（只去标签 / 保留正文） ----------
RE_INLINE = [
    (re.compile(r'\*\*v\d+[^*]{0,60}?\*\*'), ''),                     # **v25 P0-12 修正**（去标签）
    (re.compile(r'\*\*(?:S-|A-)?P\d\s*-\s*\d+[^*]{0,40}?\*\*'), ''),
    (re.compile(r'~~([^~]*)~~'), r'\1'),                              # 去删除线包裹
    (re.compile(r'\*\*\s*⚠\s*v\d+\s+'), '**⚠ '),                      # **⚠ v27 删除进度载体** → **⚠ 删除进度载体**
    (re.compile(r'^v[0-9]+\s+'), ''),                                 # 行首裸版本号（正文保留）
    (re.compile(r'评审稿\s*v?\d+\s*[·、]?\s*'), ''),                   # “评审稿 v28 · ”（须先于裸版本号）
    # —— 单/双位「版本号 + 轨迹词」（含 v1–v9；须先于裸版本号，且保护 `anon_rule_v` 枚举）——
    (re.compile(r'v[0-9]+\s*(?:新增|补充|修正|删除|改判|起)\s*[:：]?'), ''),
    (re.compile(r'[（(]随主文\s*·\s*初版\s*v[0-9][^)）]*[)）]'), ''),       # “(随主文 · 初版 v3 · …)”
    (re.compile(r'[（(]评审后修正\s*[,，]\s*v[0-9][^)）]*[)）]'), ''),      # “(评审后修正,v1 过于乐观)”
    (re.compile(r'[（(]替代\s*v[0-9]\s*的[^)）]*[)）]'), ''),             # “(替代 v1 的…未对齐)”
    (re.compile(r'[（(]即\s*v[0-9]\s*方案[)）]'), ''),                     # “(即 v1 方案)”
    (re.compile(r'[（(]主文\s*v[\d.]+\s*[)）]'), ''),                     # “(主文 v3.42)”
    (re.compile(r'[（(][^（()）]{0,30}?非评审轮次[^（()）]{0,20}?[)）]'), ''),  # 标题内“本项为用户追加,非评审轮次产生”
    (re.compile(r'自\s*v[0-9]\s*之后'), ''),                             # “自 v6 之后”
    (re.compile(r'v[0-9]\s*设想的'), '设想中的'),
    (re.compile(r'v[0-9]\s*含糊的'), ''),
    (re.compile(r'v[0-9]\s*(?:按|这两句|允许|只写了)'), ''),
    (re.compile(r'[,，;；]\s*(?:新增|改判)\s*[,，]\s*原名[^)）]*[)）]'), ')'),   # 长括号内“改名沿革”
    (re.compile(r'[:：]\s*及之前\s*[,，]\s*'), '：'),                          # “:v21 及之前,”
    (re.compile(r'及之前\s*[,，]?\s*'), ''),                                    # 兜底
    (re.compile(r'(?:v\d+(?:\s*[–—-]\s*v\d+)?\s*)?(?:S-|A-)?P\d\s*-\s*\d+'
                r'(?:\s*[/、,，]\s*(?:v\d+\s*)?(?:S-|A-)?P\d\s*-\s*\d+)*\s*[:：]?'), ''),  # 裸评审项 ID(含 / 分隔列表)
    (re.compile(r'(?<![\w.`])v(?:1[0-9]|2[0-9])(?![\d.`])\s*[:：]?'), ''),                   # 裸版本号
    (re.compile(r'v\d+\s*已删除'), '不在本方案内'),
    (re.compile(r'v\d+\s*已改判'), '改判'),
    (re.compile(r'已裁定'), '定稿'),
    (re.compile(r'(?:S-|A-)?P\d\s*\d+\s*项'), ''),                     # “P0 12 项”
]

# ---------- 4) 悬空标点清理（安全子集；按 TIDY_PASSES 遍执行） ----------
RE_TIDY = [
    (re.compile(r'\*\*\*\*'), ''),                       # 真·空强调
    (re.compile(r'[（(]\s*[)）]'), ''),
    (re.compile(r'^>\s*[:：]\s*'), '> '),                # 版本标签去掉后留下的 “> ：”
    (re.compile(r'⚠\s*[:：]\s*'), '⚠ '),
    (re.compile(r'([，,。;；、])\s*[:：]'), r'\1'),
    (re.compile(r'([，,。;；、])\s*([，,。;；、])'), r'\1'),   # 先折叠成对标点
    (re.compile(r'[，,、;；]\s*([)）])'), r'\1'),             # 再去掉括号前的残留标点
    (re.compile(r'([（(])\s*[，,、]\s*'), r'\1'),
    (re.compile(r'^(\s*[-*+])\s*[:：]\s*'), r'\1 '),   # 仅行首孤立列表符号（勿误伤 **加粗**：）
    (re.compile(r'[·、]\s*([」）」)|])'), r'\1'),          # “v3.33 · 」”→“v3.33」”
    (re.compile(r'([（(「])\s*[·、]\s*'), r'\1'),
    (re.compile(r'⚠\s*/\s*'), '⚠ '),                      # 标注删除后遗留的 “⚠ /”
    (re.compile(r'\s*/\s*([)）])'), r'\1'),                # 遗留的 “ /)”
    (re.compile(r'[（(]\s*/\s*'), '（'),                    # 遗留的 “(/”
    (re.compile(r'[ \t]*[·、][ \t]*$'), ''),              # 行尾悬空 “·”
    (re.compile(r'的?[「『]\s*v[\d.]+\s*[」』]'), ''),     # “（主文 …「v3.33 」）”
    (re.compile(r'(?<=\S)[ \t]{2,}'), ' '),
    (re.compile(r'[ \t]+([，,。;；、）)])'), r'\1'),
]
TIDY_PASSES = 2
# 标注规则需多遍：前一条删除后可能才出现后一条的形态（如先删 v27 才出现“随主文 · 初版”）
INLINE_PASSES = 2
# 外层需交替“标注 ↔ 标点清理”：标点清理会造出新形态（如 “(主文 v3.42 · )” → “(主文 v3.42)”）
OUTER_PASSES = 2


def clean(text, audit=None):
    """audit: 传入 list 时记录被整行删除的行（源行号 + 内容），使删除可审计。"""
    out, stats = [], {'drop': 0, 'paren': 0, 'inline': 0}
    in_fence = False
    for lineno, line in enumerate(text.split('\n'), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and (any(rx.match(line) for rx in LINE_DROP)
                             or LINE_DROP_KW.search(line)):
            stats['drop'] += 1
            if audit is not None:
                audit.append('%d\t%s' % (lineno, line[:160]))
            continue
        for _ in range(OUTER_PASSES):
            for _ in range(INLINE_PASSES):
                for rx in RE_PAREN:
                    line, n = rx.subn('', line)
                    stats['paren'] += n
                for rx, rep in RE_INLINE:
                    line, n = rx.subn(rep, line)
                    stats['inline'] += n
            for _ in range(TIDY_PASSES):
                for rx, rep in RE_TIDY:
                    line = rx.sub(rep, line)
        out.append(line)
    return '\n'.join(out), stats


def main():
    src = io.open(sys.stdin.fileno(), encoding='utf-8', newline='').read()
    audit = []
    dst, stats = clean(src, audit)
    sys.stdout.write(dst)
    sys.stderr.write('finalize: 删登记行 %d · 括号标注 %d · 行内标注 %d\n'
                     % (stats['drop'], stats['paren'], stats['inline']))
    with io.open('delete-audit.log', 'w', encoding='utf-8') as f:
        f.write('# 被整行删除的行（源行号 <TAB> 内容前 160 字）\n')
        if audit:
            f.write('\n'.join(audit) + '\n')
    sys.stderr.write('finalize: 删行清单 -> delete-audit.log（%d 行）\n' % len(audit))


if __name__ == '__main__':
    main()
