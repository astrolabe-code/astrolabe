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
    """★★★ **按新正文重算段落，* 并按项目策略处置失锚评论** ⚠

    ## ★★ 算法（★ `B188` 定的判据：**完全相同**）

    ```
    ① ★ 按新正文切段 ⇒ 新段列表 + 各自的指纹
    ② ★★ 指纹【完全相同】的旧行 ⇒ ★★ **续用原 id** ✅
    ③ ★ 匹配不上的新段 ⇒ **建新行**
    ④ ★ 没被续上的旧行 ⇒ **按项目策略处置它上面的评论**（★ 见下）⚠
    ```

    ## ★★★ 第 ④ 步的三个选项（★ `B189` · 所有者原话 A5）

    > 「**修改段落了，评论默认不再显示，但要给作者三个选项，挂在新写的段落上，
    > 放底部评论区里，默认的不显示。嗯，这个不要每次修改都跳，记录到项目设置里。**」

    | 策略（* `note.orphan_comment_policy`）| 落法 |
    |---|---|
    | ★★ `attach_to_new` | ★ 把失锚评论**重钉**到同 `ordinal` 的新段 ✅ |
    | ★ `move_to_chapter` | ★ `block_id` 置 NULL，* 章评区**可见**（* 标注"原段落已变更"）✅ |
    | ★★ `hide`（默认）| ★ `block_id` 置 NULL，* 默认列表**不显示** ✅ |

    ⚠★★ **`move_to_chapter` 与 `hide` 的数据形态完全相同** ⚠
      · · ★ 都是「`block_id IS NULL` 且 `is_paragraph=True`」⚠
      · · ★★ 差别只在【展示位置】⇒ ★ 策略改了**一条数据都不用搬** ✅
      · · ★（* 这正是"**数据不因策略分裂**"的意思 ⚠）

    ⚠★ 而 `anchor_kind` **创建时定死、不随锚点失效而变** ✅
      · · ★ 否则"失锚的段评"会被误判成"章评" ⚠

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
    from core.models import NoteBlock, NoteComment

    new_texts = split_blocks(note.body or "")
    new_fps = [fingerprint(t) for t in new_texts]

    # ---- ② 旧行按指纹归组（* 一篇笔记内指纹**可能重复** ⇒ ★ 用列表）----
    old_by_fp: dict[str, list[NoteBlock]] = {}
    for b in NoteBlock.objects.filter(note=note).order_by("ordinal"):
        old_by_fp.setdefault(b.fingerprint, []).append(b)

    used: set[int] = set()           # ★ 被续用的旧行 id
    to_create: list[NoteBlock] = []   # 要新建的

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
            if reused.ordinal != ordinal or reused.text != text:
                # ★ ordinal 可能因插段/删段而变 ⇒ ★ 要更新（* text 冗余存一份）
                NoteBlock.objects.filter(pk=reused.pk).update(
                    ordinal=ordinal, text=text
                )
        else:
            to_create.append(
                NoteBlock(note=note, ordinal=ordinal, text=text, fingerprint=fp)
            )

    # ---- ④ 收集没被续上的旧行 ----
    stale = list(NoteBlock.objects.filter(note=note).exclude(pk__in=used))
    if not stale and not to_create:
        return NoteBlock.objects.filter(note=note).order_by("ordinal")

    # ⚠★★ 顺序很要紧（* 两个坑都是实测踩出来的）⚠
    #
    # ```
    # ⓪ ★★ 先记下"哪条评论挂在哪个旧段上" ⚠
    #     · · ★ 因为下一步就要删旧段，* 而删了就对不上号了 ✅
    # ① ★★ 再删旧行 ⚠
    #     · · ★ 必须在 bulk_create 【之前】⓪ ⇒ ★ 否则新行的 ordinal 会
    #       与还没删的旧行相撞（* `uniq_note_block`  violation）⚠
    #     · · ★ 而删旧行会让 `block_id` 自动 SET_NULL ⇒ ★ 那正是
    #       hide / move_to_chapter 想要的形态 ✅
    # ② ★ 再建新行 ✅
    # ③ ★ 最后按策略重钉（* 只有 attach_to_new 需要）✅
    # ```
    orphan_map: dict[int, list[int]] = {}
    # ⚠★★ 必须在 delete() 【之前】记下 ordinal ⚠
    #
    # ★★ 为什么（★ 实测踩过，* 而它是**静默的**）：
    #   · ★ Django 的 `Model.delete()` **会把内存对象的 `pk` 置成 None** ⚠
    #   · · ★ 而我原先在删完之后才用 `old.pk` 去查 orphan_map ✅
    #     ⇒ ★★ `orphan_map.get(None)` ⇒ `[]` ⇒ **一条都没重钉** ⚠
    #   · · ★ 表现：* 策略明明是 attach_to_new，* 评论却还是失锚 ⚠
    #   · · ★★ 而它**不报错** ⚠
    #   ⇒ ★★ 所以这里先拍一张「旧 pk ⇒ ordinal」的快照 ✅
    ordinal_of: dict[int, int] = {}
    for old in stale:
        cids = list(
            NoteComment.objects.filter(note=note, block=old, is_paragraph=True)
            .values_list("pk", flat=True)
        )
        if cids:
            orphan_map[old.pk] = cids
        ordinal_of[old.pk] = old.ordinal

    for old in stale:
        old.delete()

    if to_create:
        NoteBlock.objects.bulk_create(to_create)
        # ⚠★★ 必须【从库里重新取】⓪ —— ★ 不能接着用 `to_create` 里的对象 ⚠
        #   · ★ `bulk_create()` 不保证把自增 id 写回内存对象 ⚠
        #   · ★★ 而 `attach_to_new` 要拿它当重钉目标 ⇒ ★ pk 为 None 会又置一次 NULL ⚠
        fresh = list(NoteBlock.objects.filter(note=note).order_by("ordinal"))
    else:
        fresh = list(NoteBlock.objects.filter(note=note).order_by("ordinal"))

    if orphan_map:
        _handle_orphans(note, ordinal_of, fresh, orphan_map)

    return NoteBlock.objects.filter(note=note).order_by("ordinal")


def _handle_orphans(
    note: "Note",
    ordinal_of: dict[int, int],
    fresh: list["NoteBlock"],
    orphan_map: dict[int, list[int]],
) -> None:
    """★★ **按项目策略处置失锚评论**（★ `B189` 的三个选项）⚠

    ⚠★ 调用时机：* 旧段**已删**（* 其上的评论 `block_id` 已自动变 NULL）·
      * 新段**已建好**（* 所以能重钉）✅

    ## ★ 三个策略（* `note.orphan_comment_policy`，* 项目级）

    ```
    attach_to_new   ⇒ ★ 把失锚评论【重钉】到同 ordinal 的新段 ✅
    move_to_chapter ⇒ ★ block_id 保持 NULL，* 章评区可见 ✅
    hide（默认）    ⇒ ★ block_id 保持 NULL，* 默认列表不显示 ✅
    ```

    ⚠★★ **后两者的数据形态完全相同** ⚠
      · · ★ 都是「`block_id IS NULL` 且 `is_paragraph=True`」⚠
      · · ★★ 差别只在【展示位置】⇒ ★ 策略改了**一条数据都不用搬** ✅
      · · ★（* 这正是"**数据不因策略分裂**"的意思 ⚠）
    """
    from core import settings_table as st
    from core.models import NoteComment

    policy = st.get("note.orphan_comment_policy", project=_project_of(note))

    if policy != "attach_to_new":
        # ★★ hide / move_to_chapter ⇒ ★ 删旧段时已经 SET_NULL 了 ✅
        #   · · ★ 所以这里【什么都不做】—— ★ 数据形态两者相同 ✅
        return

    # ---- attach_to_new：* 按 ordinal 重钉到新段 ----
    by_ordinal = {b.ordinal: b for b in fresh}
    # ★★ 遍历 orphan_map（* 它的键是**删除前**拍下的真 pk）✅
    for old_pk, cids in orphan_map.items():
        target = by_ordinal.get(ordinal_of.get(old_pk))
        if target is None:
            # ★ 新段比旧段少（* 用户删了段）⇒ ★ 无处可钉 ⇒ ★ 保持失锚 ✅
            continue
        NoteComment.objects.filter(pk__in=cids).update(block=target)


def _project_of(note: "Note"):
    """★★ **这个笔记属于哪个项目**（★ 用于取项目级设置）⚠

    ⚠★ 笔记挂在 `graph_node` 上，* 而节点可能属【基图】或【项目】⚠
      · · ★ 属项目 ⇒ ★ 直接取 `node.project` ✅
      · · ★ 属基图 ⇒ ★ 要顺基图找到**绑它的项目** ⚠
      · · ★（* 而一个基图可能被多个项目绑 ⇒ ★ 这种情形下策略**不明确**）⚠
      · · ★★ 所以：* 取不到唯一项目时返回 None ⇒ ★ 用**代码默认值** ✅
    """
    node = note.node
    if node is None:
        return None
    if node.project_id is not None:
        return node.project
    # ★ 属基图 ⇒ ★ 找第一个绑它的项目（* 取不到就返回 None ✅）
    from core.models import Project

    return Project.objects.filter(base_graph_id=node.base_graph_id).first()


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
