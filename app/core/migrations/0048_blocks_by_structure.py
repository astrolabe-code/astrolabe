# ★ 切段口径改为「按 markdown 结构」（`B242` · 2026-10-23）
#
# 所有者原话：「改后端切段口径，跟前端一样的切法。」
#
# ⚠ 为什么要迁移：`fingerprint = blake2b(段文本)`，段边界变了 ⇒ 指纹变
#   ⇒ 老段评会全部失锚。本迁移把**老指纹重挂到包含它的新段**上，
#     找不到归属的才失锚（fingerprint=""，降级为章评）。
import re

from django.db import migrations

_BLANK_RUN = re.compile(r"\n\s*\n\s*")


def _fp(text: str) -> str:
    import hashlib

    return hashlib.blake2b(text.strip().encode(), digest_size=8).hexdigest()[:16]


def _old_split(body: str) -> list[str]:
    """★ 旧口径：两个空行之间就是一段（代码块内也切）⚠"""
    if not body:
        return []
    parts = _BLANK_RUN.split(body.replace("\r\n", "\n").replace("\r", "\n"))
    return [p.strip() for p in parts if p.strip()]


def _new_split(body: str) -> list[str]:
    """★ 新口径：按 markdown 顶层块切（与前端 Milkdown 节点对应）✅"""
    if not body:
        return []
    from markdown_it import MarkdownIt

    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out: list[str] = []
    for tok in MarkdownIt("commonmark").parse(text):
        if tok.level != 0 or not tok.map:
            continue
        start, end = tok.map
        chunk = "\n".join(lines[start:end]).strip()
        if chunk:
            out.append(chunk)
    return out


def remap(apps, schema_editor):
    Note = apps.get_model("core", "Note")
    NoteComment = apps.get_model("core", "NoteComment")

    remapped = detached = 0
    for note in Note.objects.all():
        body = note.body or ""
        old_blocks = _old_split(body)
        new_blocks = _new_split(body)
        old_fps = [_fp(t) for t in old_blocks]
        new_fps = [_fp(t) for t in new_blocks]
        if set(old_fps) == set(new_fps):
            continue  # 这篇没变 ⇒ 不用碰

        # ★ 旧段文本 ⇒ 新段（* 包含关系：代码块被切两半的情况靠这个合上）⚠
        mapping: dict[str, str] = {}
        for text, fp in zip(old_blocks, old_fps):
            for k, new_text in enumerate(new_blocks):
                if text in new_text or new_text in text:
                    mapping[fp] = new_fps[k]
                    break

        dirty = []
        for c in NoteComment.objects.filter(note=note, is_paragraph=True).exclude(
            fingerprint=""
        ):
            new_fp = mapping.get(c.fingerprint)
            if new_fp is None:
                # ★ 找不到归属 ⇒ 失锚，降级为章评（* 后端已有策略）⚠
                c.fingerprint = ""
                detached += 1
            elif new_fp != c.fingerprint:
                c.fingerprint = new_fp
                remapped += 1
            else:
                continue
            c.ordinal = new_fps.index(new_fp) if new_fp else c.ordinal
            dirty.append(c)

        if dirty:
            NoteComment.objects.bulk_update(dirty, ["fingerprint", "ordinal"])

    if remapped or detached:
        print(f"  段评重挂 {remapped} 条 · 失锚 {detached} 条")


class Migration(migrations.Migration):
    dependencies = [("core", "0047_project_counts_repo")]

    operations = [migrations.RunPython(remap, migrations.RunPython.noop)]
