# ★ 一次性迁移：把存量笔记正文规范成 **Milkdown 编辑器的序列化形式**（`D108` 第 ③ 步）
#
# 所有者（2026-10-23，逐字）：「继续吧，做一次性迁移就行」
#
# ⚠ 为什么需要：* 编辑器（Milkdown）保存时会把它自己的序列化写回正文，
#   而存量正文是手写的 ⇒ 两者有差异（实测：补尾换行 · 把不成标题的 `#` 转义）
#   ⇒ 不迁移的话，* 每次编辑都会改掉这几处 ⇒ 段文本变 ⇒ 指纹变 ⇒ 段评失锚 ⚠
#
# ★ 这些规范形**不是 Python 模仿的**，是拿真实编辑器序列化出来的：
#   · 用 `?mddebug=1` 调试钩子取 `crepe.getMarkdown()`，逐篇比对 ✅
#   · 迁移后正文与编辑器输出一致 ⇒ 之后再保存是恒等变换，* 指纹不再变 ✅
#
# ⚠ 只用 `.update()` 写 body：* `save()` 会触发 `realign`，
#   而默认策略是 `hide` ⇒ 段评会被当场摘掉；* 这里自己按序号重挂 ⚠

from django.db import migrations

#: 笔记 pk ⇒ 规范形正文（* 由真实 Milkdown 序列化产出，* 见文件头）⚠
CANONICAL_BODIES = {
    189: "只在版本一可见\n",
    190: "\\#好好\n说\n",
    191: "反反复复\n",
    192: "# 火红色\n\n还记得我等你\n我去你家帮我\n\n和我的充电器拿两件\n",
}


def forwards(apps, schema_editor):
    Note = apps.get_model('core', 'Note')
    NoteComment = apps.get_model('core', 'NoteComment')

    import hashlib

    def fp(text):
        return hashlib.blake2b(text.strip().encode(), digest_size=8).hexdigest()[:16]

    changed = 0
    repinned = 0
    for pk, body in CANONICAL_BODIES.items():
        note = Note.objects.filter(pk=pk).first()
        if note is None or note.body == body:
            continue

        # ① 旧段 / 新段（* 规范化只改文字，* 不改段数与顺序）⚠
        from graph.notes import split_blocks

        old_blocks = split_blocks(note.body or '')
        new_blocks = split_blocks(body)

        # ② 写正文（* update ⇒ 不触发 realign）⚠
        Note.objects.filter(pk=pk).update(body=body)
        changed += 1

        # ③ 段评按**序号**重挂（* 段数没变 ⇒ 序号即对应关系）⚠
        new_fps = [fp(t) for t in new_blocks]
        first_at = {}
        for i, f in enumerate(new_fps):
            first_at.setdefault(f, i)
        for c in NoteComment.objects.filter(note_id=pk, is_paragraph=True).exclude(fingerprint=''):
            if c.fingerprint in first_at:
                continue          # 本来就还对得上
            if 0 <= c.ordinal < len(new_fps):
                c.fingerprint = new_fps[c.ordinal]
                c.ordinal = first_at[c.fingerprint]
                c.save(update_fields=['fingerprint', 'ordinal'])
                repinned += 1
            else:
                c.fingerprint = ''   # 序号也对不上 ⇒ 失锚
                c.save(update_fields=['fingerprint'])

    if changed or repinned:
        print(f'  正文规范化 {changed} 篇 · 段评重挂 {repinned} 条')


class Migration(migrations.Migration):
    dependencies = [('core', '0048_blocks_by_structure')]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
