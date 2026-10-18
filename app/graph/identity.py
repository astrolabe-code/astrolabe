"""★★★ 节点身份（`stable_vid`）的**唯一实现** —— `B219` · 2026-10-18

## ★★★ 所有者原话（逐字）

> 「**vid 的计算要重新计划一下。github 上的代码版本和 sha 之类的项目和基图
> 已经记录了。那重要的就是文件路径，函数名，起始行与结束行编写成一个 vid，
> 你觉得怎么样？**」
>
> 「**加 kind 也行……还有起始结束行号，有些情况可能没有，你直接规定一个
> 确定值，比如 -1 就行。这样哈希计算出来的数据比较规整**」

## ★★ 口径

```
stable_vid = BLAKE2b-64( "kind|file_path|name|line|line_end" ) 的低 53 位
   · · ★ 缺失行号一律 -1（* 不用 NULL / 0 —— 哈希输入必须规整）⚠
   · · ★★ 53 位 = JS 安全整数上限（`2^53-1`）—— 60 位会被前端截断成错值 ⚠
   · · ★ 同一版本重解析 ⇒ 必然相同（* 内容一样，* 串一样）✅
```

⚠★ **撞车（~5e-7）**：* 同一仓库内按规范串排序，* 依次以 `|1`、`|2`… 重哈希
  （* 顺序确定 ⇒* 重解析结果一致）✅ —— ⛔ 不静默合并 ⚠
"""

from __future__ import annotations

import hashlib

from graph import kinds

#: ★ 53 位掩码（`2^53 - 1`）——* JS 的 `Number.MAX_SAFE_INTEGER` ⚠
_MASK = (1 << 53) - 1


def canonical(kind, file_path: str, name: str, line, line_end) -> str:
    """★★ 规范串（* 五个字段 + 四个分隔符，* 缺一不可）⚠"""
    kid = kind if isinstance(kind, int) else kinds.kind_id(str(kind))
    ln = line if isinstance(line, int) and line >= 0 else -1
    end = line_end if isinstance(line_end, int) and line_end >= 0 else -1
    return f"{kid}|{file_path or ''}|{name or ''}|{ln}|{end}"


def hash53(text: str) -> int:
    """★ `BLAKE2b-64` 取低 53 位 ⚠"""
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & _MASK


def assign_vids(canons: list[str]) -> dict[str, int]:
    """★★★ **确定性分配**（* 撞车按排序后的规范串重哈希）⚠"""
    used: dict[int, str] = {}
    out: dict[str, int] = {}
    for canon in sorted(set(canons)):
        vid = hash53(canon)
        n = 0
        while vid in used and used[vid] != canon:
            n += 1
            vid = hash53(f"{canon}|{n}")
        used[vid] = canon
        out[canon] = vid
    return out
