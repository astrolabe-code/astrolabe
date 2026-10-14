# `B184` 第二步：**给 `request_url` 加 CHECK 正则**
#
# ★★ 所有者原话（逐字）：
#   「**所以，基图里这个字段只有唯一合法的样式，且不能为空**」
#
# ## 为什么单独一个迁移（★ 与 0012 拆开）
#
# ```
# ★ PostgreSQL 把「加约束」的校验**推迟到事务提交时**执行 ⚠
#   ⇒ ★ 若与 0012 的删数据合在一个迁移里：
#     · 删掉的那 15 行在事务内已不存在 ⇒ ★ 按理不会撞 ⚠
#     · ★★ 但 `AddConstraint` 在 PG 上会走 "pending trigger events" 路径
#       （★ 同一个坑，`0005`/`0006` 与 `0009`–`0011` 都踩过）⚠
#   ⇒ ★★ 拆开最稳 ✅
# ```
#
# ## 正则的口径（★ 与 `BaseGraph.canonical_url()` 的实现逐字对齐）
#
# ```
# ^https://(github\.com|gitee\.com)/[^/]+/[^/]+/blob/[0-9a-f]{7,64}$
# ```
#
# | 段 | 挡什么 |
# |---|---|
# | ★★ `^https://` | ★★ **`file://` / `legacy://` / 空串全部挡掉** ⚠ |
# | ★ `(github\.com\|gitee\.com)` | ★ 只认这两个平台（★ 与 `_HOSTS` 一致）⚠ |
# | ★ `[^/]+/[^/]+` | ★ `owner/repo` |
# | ★ `/blob/` | ★ 必须是 blob 形态（★ 与 `canonical_url()` 拼的一致）⚠ |
# | ★ `[0-9a-f]{7,64}` | ★★ **必须是 hex**（★ 小写，★ 7–64 位）⚠ |
#
# ⚠★ 为什么下界是 **7** 而不是 40：★ GitHub 也允许**短 sha**（★ 7 位起）⚠
#   ★★ 而上界 64：★ sha-1 是 40、★ 将来若换 sha-256 是 64 ⚠

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('graph', '0012_b184_remote_only_identity'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='basegraph',
            constraint=models.CheckConstraint(
                check=models.Q(
                    request_url__regex=r'^https://(github\.com|gitee\.com)/[^/]+/[^/]+/blob/[0-9a-f]{7,64}$'
                ),
                name='chk_basegraph_request_url_remote',
            ),
        ),
    ]
