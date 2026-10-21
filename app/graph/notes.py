"""Astrolabe · **笔记的段落切分与锚点对齐**（★ `B188` · 2026-10-15）

★★★ **本模块只做一件事**：

> ★★ **把一篇 markdown 笔记切成段，* 并让老段评继续挂在原来的段上** ⚠

---

# ★★★ 为什么必须单独一个模块

```
★★ 段评的锚点是**段落指纹**（`B235`），* 而段落会随正文编辑**增删改** ⚠
   ⇒ ★★ 若不认真对齐，* 段评会【静默地】挂到别的段落上 ⚠
     （* 没人会发现，* 评论就这么错位了）⚠
   ⇒ ★ 所以对齐算法**只在这里实现一次**，* ❌ 不让每个视图各写一遍 ⚠
```

# ★★★ 三条口径（★ 全是所有者定的）

| # | 口径 | 依据 |
|---|---|---|
| ① | ★★ **段落 = 空行分隔的块** | ★ 所有者原话（A20）：「**都是markdown笔记了，段落不是很容易看出来吗？还需要问？**」⚠ |
| ② | ★★ **只有「完全相同」才续用原锚点** | ★ 所有者原话（A5）：「**我查了番茄小说的机制，他也是哪怕改一个字，段评就没了的**」⚠ |
| ③ | ★★ **改一个字 ⇒ 该段评论掉锚** | ★ 同上 ⇒ ★ 掉锚后按 `note.orphan_comment_policy` 处置 ✅ |

---

# ⚠★ 一个必须说的边界（★ 不用现在答，* 但要知道）

```
★★ markdown 里有特殊结构时，*「空行分隔」与「眼睛看到的段」会差一点 ⚠
   · ★ 列表项之间的空行 · ★ 引用块 `>` · ★ 代码块 ``` 内的空行 ⚠
   · ★★ 而现在按纯空行切 ⇒ ★ 代码块会被切成好几段 ⚠
   ⇒ ★ **显示层必须按同一口径切**（* 否则"评论挂的段"与"看到的段"不一致）⚠
   ⇒ ★ 更稳的做法是前端也按同一函数切（* 或后端把 ordinal 一并返回 ✅）
```

"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

# ⚠★ 2026-10-16（`B209`③）：**`project_of` 已移入 `core/access.py`** ⚠
#   · ★ 它回答"这篇笔记是谁的"，* 本质是**访问判定** ⇒* 该住访问内核 ⚠
#   · ★★ 而从内核 import（* graph → core 是允许方向，* `ARCHITECTURE.md` A3）✅
from core.access import project_of

if TYPE_CHECKING:  # pragma: no cover
    from django.db.models import QuerySet

    from core.models import Note

# ===========================================================================
# ① 切段
# ===========================================================================

#: ★ 空行分隔（★ 一个或多个空行都算一段的边界）
_BLANK_RUN = re.compile(r"\n\s*\n\s*")


def split_blocks(body: str) -> list[str]:
    """★★ **把正文切成段**（★ 空行分隔）✅

    ★ 返回**去掉首尾空白**的段列表（* 空段丢掉）✅

    ⚠★ 不解析 markdown 结构（* 列表 / 引用 / 代码块一律按空行切）——
      ★★ 这是所有者定的口径（* 见模块文档的边界说明）⚠
    """
    if not body:
        return []
    parts = _BLANK_RUN.split(body.replace("\r\n", "\n").replace("\r", "\n"))
    return [p.strip() for p in parts if p.strip()]


# ===========================================================================
# ② 指纹
# ===========================================================================

def fingerprint(text: str) -> str:
    """★★ **一段文本的指纹**（★ `B235` · 2026-10-21 重新定义）⚠

    ## ★★★ 所有者原话（逐字）

    > 「**分段不要改小写，但分段后的文本还要去掉两端的空白字符，比如\n \t空格之类的字符。**」
    > 「**不要区压内部空白，多一步处理，还没啥收益。**」

    ## ★ 现在只做一件事

    ```python
    段文本 = text.strip()        # 去两端 \n / \t / 空格
    指纹   = blake2b(段文本, 8 字节).hex()[:16]
    ```

    ⚠★ 与原实现的差别（* 两步被**有意去掉**）：
    ```
    ① ⛔ 不压缩内部连续空白 —— 「多一步处理，还没啥收益」
    ② ⛔ 不转小写        —— 「分段不要改小写」
    ```

    ## ⚠ 由此产生的取舍（如实记，`B235`④）

    ```
    · ★ 只改大小写（Hello → hello）      ⇒ 指纹变化 ⇒ 走失锚策略 ⚠
    · ★ 行内多打一个空格（a  b → a b）  ⇒ 指纹变化 ⇒ 走失锚策略 ⚠
    ```
    """
    return hashlib.blake2b((text or "").strip().encode("utf-8"), digest_size=8).hexdigest()


# ===========================================================================
# ③ 对齐（★★ 本模块的核心）
# ===========================================================================

def realign(note: "Note") -> list[dict]:
    """★★★ **按新正文重算段落，并按项目策略处置失锚评论**（* `B235` 重写）⚠

    ## ★★★ 所有者原话（逐字）

    > 「**代码块里也是一样，只要是两个\n之间的内容，就是一段，就可以计算指纹，
    > 挂段评。就这样简单处理，这样，渲染后，视觉上分段的内容，就都可以挂段评了，
    > 分割算法还简单。**」

    ## ★★ 数据形态（2026-10-21 起）

    ```
    ⛔ 不再有 `core_noteblock` 行 —— 段落是**算出来的**，不是存出来的 ✅
    段评的锚点 = `NoteComment.fingerprint`（+ `ordinal` 记位置）✅
    ```

    ## ★★ 算法

    ```python
    ① 按空行切段 ⇒ texts / fps
    ② 重复段**合并到第一次出现**（* 内容一样，* 所有者裁定都挂第一个）✅
    ③ 段评的指纹还在 ⇒ 把 ordinal 更新到新位置（* 段落挪了位置，* 评论跟着走）✅
    ④ 指纹没了（段被改 / 被删）⇒ 按项目策略：
         attach_to_new   ⇒ 重钉到**同 ordinal 的新段**
         move_to_chapter ⇒ 失锚（fingerprint=""），章评区可见
         hide（默认）     ⇒ 失锚（fingerprint=""），默认列表不显示
    ⑤ **已经失锚的**（fingerprint=""）⛔ 不再二次重钉 —— 否则它们会被
        "复活"到后写入的任意段上（* 旧的 realign 也只处理**本次**失效的）⚠
    ```

    Returns:
        ★ 段落列表 `[{ordinal, fingerprint, text}]`（* 调用方直接序列化发前端）✅
    """
    from django.db import transaction

    from core import settings_table as st
    from core.models import NoteComment

    texts = split_blocks(note.body or "")
    fps = [fingerprint(t) for t in texts]

    # ② 重复段合并到第一次出现
    first_at: dict[str, int] = {}
    for i, fp in enumerate(fps):
        first_at.setdefault(fp, i)

    policy = st.get("note.orphan_comment_policy", project=project_of(note))

    dirty: list[NoteComment] = []
    for c in NoteComment.objects.filter(note=note, is_paragraph=True):
        fp = c.fingerprint or ""

        if fp and fp in first_at:
            # ③ 指纹还在 ⇒ 位置可能变了
            new_ord = first_at[fp]
            if c.ordinal != new_ord:
                c.ordinal = new_ord
                dirty.append(c)
            continue

        if not fp:
            # ⑤ 早就失锚了 ⇒ 不复活
            continue

        # ④ 本次才失锚
        if policy == "attach_to_new" and 0 <= c.ordinal < len(fps):
            c.fingerprint = fps[c.ordinal]
            c.ordinal = first_at[c.fingerprint]
        else:
            c.fingerprint = ""
        dirty.append(c)

    if dirty:
        with transaction.atomic():
            NoteComment.objects.bulk_update(dirty, ["fingerprint", "ordinal"])

    return [
        {"ordinal": i, "fingerprint": fp, "text": text}
        for i, (text, fp) in enumerate(zip(texts, fps))
    ]
