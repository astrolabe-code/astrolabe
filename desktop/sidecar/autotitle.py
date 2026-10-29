#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ **从正文推一个名字**（`D112` 的个人版移植）

## 所有者原话（逐字）

> 「**笔记是想到什么记什么，没有事先想好的标题**」
> 「**笔记每一个要有标题呀，不然以后谁知道这里面写的是什么东西，
>   截几个字到标题，也能分辨呀。**」
> 「**标题25个字差不多了吧？**」

## 规则（与社区版 `web/views/notes.py::_auto_title` 保持一致）

```
① 取第一段（跳过空行）
② 若是 markdown 标题（`# …`）⇒ 先去掉 `#` 号
③ 去掉行内记号（`* ` _ ~`、`[文字](链接)`、HTML 标签）
④ 前 25 字内有标点 ⇒ 断在【最后一个】标点处，**不加省略号**
⑤ 没有标点 ⇒ 硬切 25 字 + `…`
```

⚠ 只影响**名字**（列表/搜索用）；正文原样保留，⛔ 不删任何东西。
⚠ 用户手写了名字就不覆盖；**清空名字 ⇒ 回到自动**（`D124`）。
"""

from __future__ import annotations

import re

TITLE_FALLBACK_MAX = 25

#: ★ 断句用的标点（中英文都要，按"最后一个"取）
TITLE_BREAKS = "。！？；：，、,.!?;:  \t"


def _strip_md(s: str) -> str:
    s = re.sub(r"[*`_~]", "", s)
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def auto_title(body: str) -> str:
    for line in (body or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        raw = raw.lstrip("#>").strip()
        raw = raw.lstrip("-*+").strip()
        raw = re.sub(r"^\d+[.)]\s*", "", raw)
        s = _strip_md(raw)
        if not s:
            continue

        if len(s) <= TITLE_FALLBACK_MAX:
            return s

        window = s[:TITLE_FALLBACK_MAX]
        cut = max(window.rfind(ch) for ch in TITLE_BREAKS)
        if cut > 0:
            head = window[:cut].strip()
            if head:
                return head
        return s[:TITLE_FALLBACK_MAX].rstrip() + "…"

    return ""
