# ★ 把现有段评的锚点从 `block_id` 迁到 `fingerprint`（* `B235` · 2026-10-21）
#
# ⚠★ 为什么要迁：* 段落不再是表里的行，* 段评锚点改成「段落指纹」。
#   · · ★ 旧指纹是「压空白 + 转小写」算的，* 新指纹只 strip
#     ⇒ ⛔ 不能直接抄 `NoteBlock.fingerprint`，* 必须**按段文本重算** ⚠
#
# ★ 映射规则：
#   · 评论挂在某个旧段上 ⇒ 拿那段文本重算指纹 ⇒ 在**新正文切分结果**里找同指纹的段
#     · · 找到 ⇒ 填 fingerprint + ordinal ✅
#     · · 找不到（正文已变）⇒ fingerprint = ""（* 失锚，* 走原有失锚策略）✅
import hashlib
import re

from django.db import migrations

_BLANK_RUN = re.compile(r"\n\s*\n\s*")


def _split(body: str) -> list[str]:
    if not body:
        return []
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    return [p.strip() for p in _BLANK_RUN.split(body) if p.strip()]


def _fp(text: str) -> str:
    """★ 与 `graph.notes.fingerprint` 完全一致（* 只 strip）⚠"""
    return hashlib.blake2b((text or "").strip().encode("utf-8"), digest_size=8).hexdigest()


def fill(apps, schema_editor):
    Note = apps.get_model("core", "Note")
    NoteBlock = apps.get_model("core", "NoteBlock")
    NoteComment = apps.get_model("core", "NoteComment")

    fixed = 0
    orphaned = 0
    for note in Note.objects.all().iterator():
        segs = _split(note.body or "")
        fs = [_fp(t) for t in segs]
        first_at: dict[str, int] = {}
        for i, f in enumerate(fs):
            first_at.setdefault(f, i)

        for c in NoteComment.objects.filter(note_id=note.pk, is_paragraph=True):
            block = (
                NoteBlock.objects.filter(pk=c.block_id).first()
                if c.block_id
                else None
            )
            if block is None:
                if not c.fingerprint:
                    c.fingerprint = ""
                c.save(update_fields=["fingerprint", "ordinal"])
                continue

            f = _fp(block.text)
            if f in first_at:
                c.fingerprint = f
                c.ordinal = first_at[f]
                fixed += 1
            else:
                c.fingerprint = ""
                c.ordinal = block.ordinal
                orphaned += 1
            c.save(update_fields=["fingerprint", "ordinal"])

    print(f"    段评重钉 {fixed} 条；正文已变而失锚 {orphaned} 条")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0041_comment_fingerprint_anchor"),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
