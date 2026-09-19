"""Astrolabe · 冒烟：许可核验（Gate 0 第三道门）

★ 依据 `docs/USERS-AND-AUTH.md` U3.4 / U3.7 · `B143`

用法（在容器里）：
    docker compose exec -T web sh -c "python manage.py shell < /app/scripts/smoke_licensing.py"

★★ 重点验证三类**容易写错**的地方：

1. ★★ **识别顺序** —— `AGPL` 必须排在 `GPL` 之前（特征串是同一个，顺序错了 AGPL 会被认成 GPL）
2. ★★ **BSD-3 vs BSD-2** —— 两者正文都以「Redistribution and use…」开头，靠「Neither the name」区分
3. ★★ **`require_file` 开关的两档行为** —— 关 ⇒ 进审核；开 ⇒ 直接拒绝（`B143` 的松绑）
"""

from core.licensing import (
    DECISION_ALLOW,
    DECISION_REJECT,
    DECISION_REVIEW,
    detect_spdx,
    evaluate,
)

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}: got={got!r} want={want!r}")
    print(f"  {'✅' if ok else '❌'} {label:<58} = {got!r}")


MIT = """MIT License

Copyright (c) 2026 Someone

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction.
"""

APACHE = """                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/
"""

GPL3 = """                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007
"""

AGPL3 = """                    GNU AFFERO GENERAL PUBLIC LICENSE
                       Version 3, 19 November 2007
"""

LGPL3 = """                  GNU LESSER GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007
"""

BSD_BODY = """Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
"""

BSD3 = BSD_BODY + """
    * Neither the name of the copyright holder nor the names of its
      contributors may be used to endorse or promote products derived.
"""

ELASTIC = """                          ELASTIC LICENSE
                            Version 2.0
"""

UNKNOWN_LICENSE = """Copyright (c) 2026 Someone. All rights reserved.
This software is provided for evaluation purposes only under the terms agreed
in the separate written agreement signed by both parties.
"""

# ===========================================================================
print("=" * 80)
print("① 识别（★ 顺序敏感 —— AGPL 必须先于 GPL 被认出）")
print("=" * 80)
check("MIT", detect_spdx("LICENSE", MIT), "MIT")
check("Apache-2.0", detect_spdx("LICENSE", APACHE), "Apache-2.0")
check("GPL-3.0", detect_spdx("COPYING", GPL3), "GPL-3.0")
check("★ AGPL-3.0（不能被认成 GPL）", detect_spdx("LICENSE", AGPL3), "AGPL-3.0")
check("LGPL-3.0", detect_spdx("LICENSE", LGPL3), "LGPL-3.0")
check("★ BSD-3-Clause（靠 Neither the name 区分）", detect_spdx("LICENSE", BSD3), "BSD-3-Clause")
check("★ BSD-2-Clause（无 Neither the name）", detect_spdx("LICENSE", BSD_BODY), "BSD-2-Clause")
check("Elastic-2.0", detect_spdx("LICENSE", ELASTIC), "Elastic-2.0")
check("认不出的许可证 ⇒ None（❌ 不猜）", detect_spdx("LICENSE", UNKNOWN_LICENSE), None)
check("★ 源码头 SPDX 声明优先", detect_spdx("a.py", "# SPDX-License-Identifier: MIT\nx=1"), "MIT")

# ===========================================================================
print()
print("=" * 80)
print("② 判定：宽松 ⇒ 自动放行")
print("=" * 80)
v = evaluate(texts={"LICENSE": MIT})
check("MIT · decision", v.decision, DECISION_ALLOW)
check("MIT · category", v.category, "permissive")
check("MIT · spdx", v.spdx, "MIT")
check("MIT · reason_text 非空（★ U3.7 ①）", bool(v.reason_text), True)
check("MIT · suggestion 非空（★ U3.7 ③）", bool(v.suggestion), True)
check("MIT · evidence 含文件名（★ U3.7 ②）", v.evidence.get("license_files"), ["LICENSE"])

v = evaluate(texts={"LICENSE": APACHE})
check("Apache-2.0 · decision", v.decision, DECISION_ALLOW)

# ===========================================================================
print()
print("=" * 80)
print("③ 判定：传染性 / 限制性 / 认不出 ⇒ 一律人工复核")
print("=" * 80)
v = evaluate(texts={"COPYING": GPL3})
check("GPL-3.0 · decision", v.decision, DECISION_REVIEW)
check("GPL-3.0 · category", v.category, "copyleft")
check("GPL-3.0 · reason_code", v.reason_code, "copyleft")
check("GPL-3.0 · 原因里有「传染性」（★ 人类可读）", "传染性" in v.reason_text, True)
check("GPL-3.0 · ★ 原因是「调用图算不算衍生作品」（这才是真风险）", "衍生" in v.reason_text, True)

v = evaluate(texts={"LICENSE": ELASTIC})
check("Elastic-2.0 · decision", v.decision, DECISION_REVIEW)
check("Elastic-2.0 · category", v.category, "restrictive")
check("Elastic-2.0 · 原因点明「作者可授权给自己」", "版权人" in v.reason_text, True)

v = evaluate(texts={"LICENSE": UNKNOWN_LICENSE})
check("认不出 · decision", v.decision, DECISION_REVIEW)
check("认不出 · category", v.category, "unknown")
check("认不出 · ★ 原因里承认「不假装认识」", "不假装认识" in v.reason_text, True)
check(
    "★★ 「有文件但认不出」必须区别于「没有文件」（★ 冒烟抓出的 bug）",
    v.category != "missing",
    True,
)

# ===========================================================================
print()
print("=" * 80)
print("④ ★★ 无许可证的两档行为（`B143` 松绑的核心）")
print("=" * 80)
v = evaluate(texts={}, require_file=False)
check("无许可证 · require_file=False ⇒ 进审核（★ 现在）", v.decision, DECISION_REVIEW)
check("无许可证 · category", v.category, "missing")
check("无许可证 · ★ 原因是「权利人很可能就是提交者本人」", "提交者本人" in v.reason_text, True)

v = evaluate(texts={}, require_file=True)
check("无许可证 · require_file=True ⇒ 直接拒绝（★ 以后）", v.decision, DECISION_REJECT)

# ===========================================================================
print()
print("=" * 80)
print("⑤ 真实目录扫描")
print("=" * 80)
v = evaluate("/app")
print(f"  /app（本项目自身）: spdx={v.spdx!r} category={v.category!r} decision={v.decision!r}")
print(f"    原因: {v.reason_text}")
print(f"    建议: {v.suggestion}")
print(f"    证据: license_files={v.evidence.get('license_files')}")
check("★ 每个结论都必须能被管理员读懂（reason 非空）", bool(v.reason_text), True)

# ===========================================================================
print()
print("=" * 80)
print("⑥ ★★★ 审核队列：核验结论 → 一条【能独立读懂】的审核项（U3.7 的核心要求）")
print("=" * 80)
from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402

from core.models import Project, ProjectReview  # noqa: E402

U = get_user_model()
admin, _ = U.objects.get_or_create(username="smoke_admin")
admin.is_staff = True
admin.save(update_fields=["is_staff"])

p, _ = Project.objects.get_or_create(
    project_ref="proj_smoke_license_0000000000000",
    defaults={"name": "冒烟·无许可证项目"},
)
p.reviews.all().delete()

v = evaluate(texts={}, require_file=False)
p.license_spdx = v.spdx
p.license_category = v.category
p.license_exception = v.decision != DECISION_ALLOW
p.license_evidence = v.evidence
p.review_state = Project.REVIEW_PENDING
p.save()

rv = ProjectReview.objects.create(
    project=p,
    reason_code=v.reason_code,
    reason_text=v.reason_text,
    evidence=v.evidence,
    suggestion=v.suggestion,
)

print("  ★★ 管理员在后台会看到这样一条（★ 必须能独立读懂，不必翻代码）:")
print(f"     项目       : {p.name}")
print(f"     进审核原因  : [{rv.reason_code}] {rv.reason_text}")
print(f"     检测证据   : {v.evidence.get('license_files') or '（未找到任何许可证文件）'}")
print(f"     系统建议   : {rv.suggestion}")
print(f"     当前决定   : {rv.decision}（⚠ 待管理员裁决 —— 系统只给依据与建议）")
print()

check("审核项已建", ProjectReview.objects.filter(project=p).count(), 1)
check("项目状态 = 待审核", p.review_state, Project.REVIEW_PENDING)
check("★ 标了 license_exception（便于将来批量收回）", p.license_exception, True)
check("reason_text 长度适合后台直接显示（≤400）", len(rv.reason_text) <= 400, True)
check("evidence 落库（★「我们凭什么这么判」的留痕）", bool(rv.evidence), True)

# ---- 管理员裁决（★ 决定权在人，❌ 不在系统）----
rv.decision = ProjectReview.DECISION_APPROVED
rv.decided_by = admin
rv.decided_at = timezone.now()
rv.decision_note = "提交者即权利人本人，前期测试阶段放行"
rv.save()
p.review_state = Project.REVIEW_APPROVED
p.save(update_fields=["review_state"])

check("裁决后项目状态", p.review_state, Project.REVIEW_APPROVED)
check("★ 决定人已记录（可追责，U2.5 纪律 1）", rv.decided_by_id, admin.pk)

# ===========================================================================
print()
print("=" * 80)
if FAILED:
    print(f"❌ 失败 {len(FAILED)} 项：")
    for f in FAILED:
        print(f"   - {f}")
else:
    print("✅ 全部通过")
print("=" * 80)
