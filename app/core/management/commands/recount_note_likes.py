"""Astrolabe · 管理命令：**重算笔记点赞计数**（★ `B211`② · `B212`①）

★★★ **这是点赞计数的「自我纠错」入口** ⚠

## ★★ 为什么需要它（对应 B站架构的一句话）

> 「为了保证点赞状态的正确性，且同时让程序拥有**自我纠错**的能力……」

★ `Note.like_count` 是**缓存**，* `core_note_like` 的**行**才是真相（* `B146` 纪律）⚠
  · · ★ 正常路径都同事务维护它（* 赞 / 取消 / realign 删段）✅
  · · ★★ 但缓存迟早会和真相漂移（* 历史上的 SET_NULL 失锚赞、* 手工修数据、
    进程在两次写之间挂掉）⇒* 必须有一条**按真相重写缓存**的路 ⚠

## ★★ 用法

```bash
# 全量重算（* 一篇一篇来，* ❌ 不写一条巨型 SQL —— 那会长时间锁表）
python manage.py recount_note_likes

# 只重算一篇（* 修完数据后定点校正）
python manage.py recount_note_likes --note 123
```

## ⚠★ 为什么不写「一条 UPDATE ... SET like_count = (SELECT COUNT(*))」

```
★★ 巨型相关子查询会**长时间持锁** ⇒* 点赞全卡住 ⚠
   （* 而点赞是本平台最高频的写之一）⚠
★★ 逐篇 UPDATE 每次只锁一行 ⇒* 影响面可预期 ✅
```

⚠ 本命令**只修缓存**，* ❌ 不动 `core_note_like` 的行（* 那是真相）⚠
"""

from django.core.management.base import BaseCommand

from graph.notes import recount_likes


class Command(BaseCommand):
    help = "按 core_note_like 明细表重写 Note.like_count（自我纠错，B211②）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--note",
            type=int,
            default=None,
            help="只重算这一篇（note id）；不给则全量",
        )

    def handle(self, *args, **options):
        from core.models import Note

        note_id = options.get("note")
        if note_id is not None:
            note = Note.objects.filter(pk=note_id).first()
            if note is None:
                self.stderr.write(f"笔记 {note_id} 不存在")
                return
            before = note.like_count
            recount_likes(note)
            after = Note.objects.filter(pk=note_id).values_list("like_count", flat=True).first()
            self.stdout.write(f"笔记 {note_id}：{before} ⇒ {after}"
                              + ("" if before == after else "  （已校正）"))
            return

        fixed = 0
        total = 0
        # ★★ 逐篇来（* ❌ 不写巨型 SQL ——* 见模块文档的锁说明）⚠
        for note in Note.objects.all().only("pk", "like_count").iterator():
            total += 1
            before = note.like_count
            recount_likes(note)
            after = Note.objects.filter(pk=note.pk).values_list("like_count", flat=True).first()
            if before != after:
                fixed += 1
                self.stdout.write(f"  {note.pk}: {before} ⇒ {after}")
        self.stdout.write(f"共扫 {total} 篇，校正 {fixed} 篇"
                          + ("（全部一致）" if fixed == 0 else ""))
