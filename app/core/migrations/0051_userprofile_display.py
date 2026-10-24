# ★ 用户空间：昵称 + 一句话签名（2026-10-24）
#
# 所有者原话（逐字）：
#   「关注/粉丝要做，不过我现在还没有精力做，等我把项目完善一点了，再加上。昵称/签名要加。
#     私有内容在自己的空间里要显示」
#
# ⚠ 昵称**不唯一**（唯一的是 username）；为空 ⇒ 全站回落 username，* 存量无需回填 ⚠
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0050_note_ref")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="display_name",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="bio",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
