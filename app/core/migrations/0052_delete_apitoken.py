# ★★ 删掉 ApiToken 表（B245 / B246 · 2026-10-25）
#
# 所有者原话（逐字）：
#   「现有的 397 个 ApiToken直接删掉，记住我要做，但不要那么长的时间，
#    一周就差不多了，而且后台应该可调。登录限流不要一起做。」
#
# ## ★ 为什么能直接删
#
#   ① 认证已换成 Django session（`web/auth.py` 重写，Bearer 中间件已删）
#   ② 后台「访问令牌」栏目已撤（`core/admin.py`）
#   ③ ⚠ 删了**不可回滚** —— 已按 B246 的要求额外备份数据库
#
# ## ★ 连带消失的东西
#
#   · `auth.token_ttl_days` / `auth.token_ttl_days_short` 两个参数键作废
#     （换成 `auth.session_ttl_days`，默认 7 天，见 `core/appsettings.py`）
#   · 「登录设备」页从"列令牌"变成"列会话"（`web/views/auth.py::tokens`）
#
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0051_userprofile_display"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ApiToken",
        ),
    ]
