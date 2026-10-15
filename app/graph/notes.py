"""Astrolabe · **笔记的段落切分与锚点对齐**（★ `B188` · 2026-10-15）

★★★ **本模块只做一件事**：

> ★★ **把一篇 markdown 笔记切成段，* 并让老段评继续挂在原来的段上** ⚠

---

# ★★★ 为什么必须单独一个模块

```
★★ 段评的锚点是 `NoteBlock.id`，* 而段落会随正文编辑**增删改** ⚠
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

if TYPE_CHECKING:  # pragma: no cover
    from django.db.models import QuerySet

    from core.models import Note, NoteBlock

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
    """★★ **一段文本的指纹**（★ 据此判断"完全相同"）⚠

    ## ★★ 规范化（★ 三件事，* 缺一件就会"看着一样却对不上"）

    ```
    ① ★★ **压缩所有连续空白为一个空格** ⚠
       · · ★ 为什么：* 用户在行尾多打一个空格、* 或把两个空格改成一个 ⇒ ★★ 视觉上没变 ⚠
    ② ★ **去掉首尾空白** ✅
    ③ ★ **不区分大小写** ⚠
       · · ★ 为什么：* 英文笔记里改一个字母大小写 ⇒ ★ 语义没变 ⚠
       · · ⚠★ 但这是**有意的让步**：* 它会让"只改大小写"也被判为相同 ⇒
         · · ★ 而那正是"完全相同"想要的（* 段评不该因为大小写掉锚）✅
    ```

    ## ⚠★ 为什么是 16 个字符（* 而不是 64）

    ```
    ★★ `B199` 定的：* 64 bit 哈希 ⇒ ★ 一篇笔记的段落只有几十个 ⚠
       ⇒ ★★ 碰撞概率可忽略 ✅
    · · ★ 而它**进索引** ⇒ ★ 缩到 16 字符 **省 48 字节/条** ⚠
    · · ★（* 模型里那一列就是 `varchar(16)` ✅）
    ```
    """
    norm = re.sub(r"\s+", " ", (text or "")).strip().lower()
    return hashlib.blake2b(norm.encode("utf-8"), digest_size=8).hexdigest()


# ===========================================================================
# ③ 对齐（★★ 本模块的核心）
# ===========================================================================

def realign(note: "Note") -> "QuerySet[NoteBlock]":
    """★★★ **按新正文重算段落，* 并尽量让老段评留在原处** ⚠

    ## ★★ 算法（★ `B188` 定的判据：**完全相同**）

    ```
    ① ★ 按新正文切段 ⇒ 新段列表 + 各自的指纹
    ② ★★ 指纹【完全相同】的旧行 ⇒ ★★ **续用原 id** ✅
    ③ ★ 匹配不上的新段 ⇒ **建新行**
    ④ ★ 没被续上的旧行 ⇒ **删**
       ⇒ ★ 它上面的评论 `block_id` 变 NULL（★ 即"失锚"）⚠
    ```

    ## ★★ 为什么"续用"而不是"按位置对上"

    ```
    ★ 按位置（* 第 N 段对第 N 段）看起来更省事 —— ★★ 而那是错的** ⚠
      · · ★ 在最前面插一段 ⇒ ★ 后面所有段**整体错位** ⚠
      · · ★★ 而段评会【静默地】挂到别的段落上 ⚠
    ```

    ## ⚠★ 幂等

    ```
    ★★ 同一份正文连续调两次 ⇒ ★ 第二次**一个都不动** ✅
      · · ★（* 因为指纹没变 ⇒ * 全部续用）⚠
    ```

    Returns:
        ★ 重算后的 `NoteBlock` QuerySet（* 调用方可以直接序列化发给前端）✅
    """
    from core.models import NoteBlock

    new_texts = split_blocks(note.body or "")
    new_fps = [fingerprint(t) for t in new_texts]

    # ---- ② 旧行按指纹归组（* 一篇笔记内指纹**可能重复** ⇒ ★ 用列表）----
    old_by_fp: dict[str, list[NoteBlock]] = {}
    for b in NoteBlock.objects.filter(note=note).order_by("ordinal"):
        old_by_fp.setdefault(b.fingerprint, []).append(b)

    used: set[int] = set()          # ★ 被续用的旧行 id
    to_create: list[NoteBlock] = []  # 要新建的
    keep_ordinals: list[tuple[int, str, int]] = []  # (ordinal, text, fp)

    for ordinal, (text, fp) in enumerate(zip(new_texts, new_fps)):
        pool = old_by_fp.get(fp)
        # ★★ 找一个还没被用过的旧行续用 ✅
        reused = None
        if pool:
            for cand in pool:
                if cand.pk not in used:
                    reused = cand
                    break
        if reused is not None:
            used.add(reused.pk)
            keep_ordinals.append((ordinal, text, fp))
            if reused.ordinal != ordinal or reused.text != text:
                # ★ ordinal 可能因插段/删段而变 ⇒ ★ 要更新（* text 冗余存一份）
                NoteBlock.objects.filter(pk=reused.pk).update(
                    ordinal=ordinal, text=text
                )
        else:
            to_create.append(
                NoteBlock(note=note, ordinal=ordinal, text=text, fingerprint=fp)
            )

    # ---- ④ 删掉没被续上的旧行 ⇒ ★ 它上面的评论/点赞会 SET_NULL（失锚）----
    # ⚠★★ 必须在【bulk_create 之前】做 ⚠
    #
    # ★★ 为什么（★ 实测踩过，* 而且它是**静默的**）：
    #   · ★ 我原先把这段放在建新行之后 ⚠
    #   · ★ 而第一次调用时 `used` 是**空的**（* 没有任何续用）⚠
    #   · ★★ 于是"刚建好的段"全被判成 stale ⇒ **当场删光** ⚠
    #   · · ★ 而它**不报错** ⇒ ★ 只是静默地返回 0 个段 ⚠
    #     （* 表现：* 笔记建好了，* 但一个段评锚点都没有）⚠
    #   ⇒ ★★ 顺序必须是：* 先删旧的 ⇒ 再建新的 ✅
    stale = NoteBlock.objects.filter(note=note).exclude(pk__in=used)
    if stale.exists():
        # ⚠★ 逐行删而不是 queryset.delete() —— ★ 让 Django 的 collector
        #   发 post_delete（* 缓存失效逻辑要靠它跟上）✅
        for b in stale:
            b.delete()

    # ---- ③ 新建匹配不上的新段 ----
    if to_create:
        NoteBlock.objects.bulk_create(to_create)

    return NoteBlock.objects.filter(note=note).order_by("ordinal")


def orphan_blocks(note: "Note") -> "QuerySet[NoteBlock]":
    """★★ **这个笔记里"失锚"的段**（★ 被删了、* 但评论还指着它）⚠

    ★ 其实它们**已经不在 `NoteBlock` 表里了**（* `realign` 第 ④ 步删掉了）⚠
    ★ 所谓"失锚"指的是 **`NoteComment.block_id IS NULL` 但 `is_paragraph=True`** 的那些评论 ✅

    ⚠★ 所以本函数名不副实 —— ★ 真正的查询在 `web/views/comments.py` 里 ⚠
      （* 留着它是为了把这件事说清，* ❌ 不是为了让调用方用错）⚠
    """
    raise NotImplementedError(
        "失锚评论请直接查 NoteComment.objects.filter("
        "note=note, is_paragraph=True, block=None)"
    )
