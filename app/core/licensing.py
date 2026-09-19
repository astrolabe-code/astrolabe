"""Astrolabe · 共享内核：许可证核验（Gate 0 的**第三道门**）

★ 依据 `USERS-AND-AUTH.md` **U3.4**（许可核验）+ **`B109`**（许可分级）+ **`B143`**（松绑）。

---

# 为什么判据是「能不能公开衍生结果」，而不是「能不能解析」

★★ `U3.4` 立的核心判断：

| 行为 | 需要什么 |
|---|---|
| ★ **在本地解析**（读源码、生成图） | ★ **基本都允许**（技术处理） |
| ★★ **把「图」公开到网站** | ★★ **需要许可证允许「再分发」+「制作衍生作品」** |

⇒ ★★ 因为 ★ **图是源码的衍生结果**。
★ 所以本模块判的是**后者**。

---

# 三档处理（`B143` 松绑后的口径）

| 类别 | 处理 | 为什么 |
|---|---|---|
| **宽松**（MIT / Apache / BSD …） | ✅ **自动放行** | ★ 明确允许再分发与衍生 |
| **传染性**（GPL / AGPL / LGPL） | ⚠ **人工复核** | ★★ **调用图算不算衍生作品，业界无统一结论** —— 若算 ⇒ **图数据要按 GPL 发布**（传染整个平台） |
| **限制性**（Elastic / PolyForm / BSL） | ⚠ **人工复核** | ★ 作者**是版权人、可以授权给自己** ⇒ 可放行；⚠ 但平台是**"明知条款存在"** |
| **无许可证文件** | ⚠ **人工复核**（★ `B143`） | ★★ **"无许可证" ≠ "侵权"** —— ★ **权利人很可能就是提交者本人**（⚠ 用户自己的项目大多没许可证） |
| **有文件但认不出** | ⚠ **人工复核** | ⚠ 不认识就不假装认识 |

⚠★ **`require_file=True` 时，无许可证才直接拒绝** ——
   ★ 这个开关由 `AppSetting.license_require_file` 控制（★ **现在关**，便于前期测试；**以后打开即收紧**）。

---

★★★ **审核必须给出「为什么」**（`U3.7`）——
   每一条判定都带 `reason_text`（**人类可读**）+ `evidence`（**检测证据**）+ `suggestion`（**系统建议**）。
   ★ 因为 ★★ **"人工审核通过" ≠ "平台背书版权"** ——
   它只表示「在已知信息下，未发现明显问题」⇒ **依据必须留痕**。

⚠ 分层纪律：本模块属于**共享内核** —— ① ② 都要用；★ 只依赖标准库，❌ 不 import Django 模型。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

# ===========================================================================
# 类别判定表
# ===========================================================================

#: ✅ **宽松许可** —— 明确允许再分发与衍生 ⇒ 自动放行
PERMISSIVE: frozenset[str] = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "Unlicense",
        "0BSD",
        "MPL-2.0",       # ⚠ 文件级 copyleft，但对"引用/衍生"足够宽松
        "CC0-1.0",
        "Zlib",
        "BSL-1.0",       # ⚠ Boost，★ 不是 Business Source License（后者在 RESTRICTIVE）
    }
)

#: ⚠ **传染性许可** —— ★★ GPL 的「调用图算不算衍生作品」**业界无统一结论**
COPYLEFT: frozenset[str] = frozenset(
    {"GPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0", "GPL-3.0-only",
     "GPL-3.0-or-later", "AGPL-3.0", "AGPL-3.0-only", "LGPL-2.1", "LGPL-3.0"}
)

#: ⚠ **限制性许可** —— 明确禁止再分发 / 托管服务
RESTRICTIVE: frozenset[str] = frozenset(
    {
        "Elastic-2.0",
        "PolyForm-Strict-1.0.0",
        "PolyForm-Noncommercial-1.0.0",
        "PolyForm-Free-Trial-1.0.0",
        "BUSL-1.1",
        "SSPL-1.0",
    }
)

#: 判定的三种去向
DECISION_ALLOW = "allow"       # ✅ 自动放行
DECISION_REVIEW = "review"     # ⚠ 人工复核
DECISION_REJECT = "reject"     # ❌ 直接拒绝（⚠ 只有 require_file=True 且无许可证时）

CATEGORY_MISSING = "missing"
CATEGORY_UNKNOWN = "unknown"


# ===========================================================================
# 识别
# ===========================================================================

#: ★ **许可证文件名候选**（⚠ 只认这些名字 —— ❌ 不把 `README.md` 当许可证）
LICENSE_FILENAMES: tuple[str, ...] = (
    "LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE.rst",
    "LICENCE", "LICENCE.txt", "LICENCE.md",
    "COPYING", "COPYING.txt", "COPYING.md",
    "LICENSE-MIT", "LICENSE-APACHE", "LICENSE-GPL", "UNLICENSE",
    "COPYRIGHT",
)

#: ★ SPDX 特征串 —— **顺序敏感**（★ 先具体后宽泛：`AGPL` 必须在 `GPL` 之前）
_SPDX_PATTERNS: tuple[tuple[str, str], ...] = (
    # ---- 传染性（★ 必须先判，否则 AGPL 会被 GPL 吃掉）----
    ("AGPL-3.0", "GNU AFFERO GENERAL PUBLIC LICENSE"),
    ("LGPL-3.0", "GNU LESSER GENERAL PUBLIC LICENSE"),
    ("LGPL-2.1", "GNU LESSER GENERAL PUBLIC LICENSE"),
    ("GPL-3.0", "GNU GENERAL PUBLIC LICENSE"),
    ("GPL-2.0", "GNU GENERAL PUBLIC LICENSE"),
    # ---- 限制性 ----
    ("Elastic-2.0", "ELASTIC LICENSE"),
    ("BUSL-1.1", "BUSINESS SOURCE LICENSE"),
    ("SSPL-1.0", "SERVER SIDE PUBLIC LICENSE"),
    ("PolyForm-Strict-1.0.0", "POLYFORM STRICT"),
    ("PolyForm-Noncommercial-1.0.0", "POLYFORM NONCOMMERCIAL"),
    # ---- 宽松 ----
    ("Apache-2.0", "APACHE LICENSE"),
    ("MPL-2.0", "MOZILLA PUBLIC LICENSE"),
    ("Unlicense", "FREE AND UNENCUMBERED SOFTWARE RELEASED INTO THE PUBLIC DOMAIN"),
    ("MIT", "PERMISSION IS HEREBY GRANTED, FREE OF CHARGE"),
    ("BSD-3-Clause", "NEITHER THE NAME"),
    ("BSD-2-Clause", "REDISTRIBUTION AND USE IN SOURCE AND BINARY FORMS"),
    ("ISC", "PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE"),
    ("Zlib", "'AS-IS' AND WITH ALL FAULTS"),
)

#: ★ 源码文件头里的 SPDX 声明（GitHub 的现代做法）
_SPDX_HEADER_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)")

#: GNU 版本号（用来区分 GPL-2.0 / GPL-3.0）
_GNU_VERSION_RE = re.compile(r"version\s+([23])", re.IGNORECASE)


def detect_spdx(filename: str, text: str) -> str | None:
    """从一个文件的内容里识别 SPDX 标识（⚠ 认不出返回 `None`，❌ 不猜）。"""
    # ★ 优先看显式的 SPDX 声明（最可靠）
    m = _SPDX_HEADER_RE.search(text)
    if m:
        return m.group(1).strip()

    upper = text.upper()
    for spdx, needle in _SPDX_PATTERNS:
        if needle in upper:
            # ★ GPL 系要再分版本（特征串一样）
            if spdx in ("GPL-2.0", "GPL-3.0"):
                vm = _GNU_VERSION_RE.search(text)
                if vm:
                    return f"GPL-{vm.group(1)}.0"
            return spdx

    # ★ 文件名本身就带语义（如 `LICENSE-APACHE`）—— 兜底
    base = os.path.basename(filename).upper()
    if "APACHE" in base:
        return "Apache-2.0"
    if "MIT" in base:
        return "MIT"
    return None


def find_license_files(root: str, *, max_depth: int = 2, max_bytes: int = 64 * 1024) -> list[tuple[str, str]]:
    """在仓库里找许可证文件。

    ★ 只扫**根目录 + 有限层子目录** —— ⚠ 许可证**几乎总在根目录**，
      ❌ 不做全库扫描（那会白读几千个文件）。

    Returns: `[(相对路径, 文本内容), …]`
    """
    found: list[tuple[str, str]] = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []            # ★ 不再往下走
        # ⚠ 跳过明显的噪音目录（它们里的 "LICENSE" 通常是第三方依赖的）
        dirnames[:] = [
            d for d in dirnames
            if d not in (".git", "node_modules", "vendor", "third_party", ".venv", "venv", "__pycache__")
        ]
        for name in filenames:
            if name in LICENSE_FILENAMES or name.upper().startswith(("LICENSE", "LICENCE", "COPYING")):
                path = os.path.join(dirpath, name)
                try:
                    if os.path.getsize(path) > max_bytes:
                        continue
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        found.append((os.path.relpath(path, root), fh.read(max_bytes)))
                except OSError:
                    continue
    return found


# ===========================================================================
# 判定
# ===========================================================================

@dataclass
class LicenseVerdict:
    """★ 许可核验结论 —— ★★ **自带「为什么」**（`U3.7`）。

    ⚠★ 这四样必须都有，否则审核队列就没法用：

    | 字段 | 对应 `U3.7` |
    |---|---|
    | `reason_text` | ① **进审核的原因（人类可读）** |
    | `evidence` | ② **系统检测到的证据** |
    | `suggestion` | ③ **系统的建议** |
    | `decided_by` | ④ 由**管理员**最终决定（❌ 系统不代替判断） |
    """

    spdx: str = ""
    category: str = CATEGORY_MISSING
    decision: str = DECISION_REVIEW
    reason_code: str = "no_license"
    reason_text: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""
    #: ★★ **给用户（提交者）看的说法** —— ⚠ 与 `reason_text` **不是同一件事**：
    #:   · `reason_text` 给**管理员** —— 含证据、含"该不该放行"的判断要点
    #:   · `user_message` 给**提交者** —— 说清**状态** + **该做什么**，
    #:     ❌ 不暴露内部判断细节（★ 如"权利人可能就是你"这种话不该让用户看见）
    user_message: str = ""

    @property
    def auto_allowed(self) -> bool:
        return self.decision == DECISION_ALLOW

    @property
    def needs_review(self) -> bool:
        return self.decision == DECISION_REVIEW

    def to_dict(self) -> dict[str, Any]:
        return {
            "spdx": self.spdx,
            "category": self.category,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "reason_text": self.reason_text,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
            "user_message": self.user_message,
        }


#: ★★ 「**尚未核验**」的原因码 —— ⚠ 与 `missing`（"**看了、没有**"）**是两件事**
CODE_PENDING = "license_pending"


def deferred() -> LicenseVerdict:
    """★★ **「尚未核验」** —— ★ 发布时源码还没拉下来，许可当然还没看。

    ⚠★ 为什么必须有这个态，❌ 不能拿 `missing` 顶替：

    | 原因码 | 说的是什么 |
    |---|---|
    | `missing` | ★ **看了，这个仓库没有许可证文件** |
    | ★ `license_pending` | ★ **还没看** |

    ⚠★ 混用会**给管理员错误的原因** —— ★ 而这正是 `U3.7` / `U3.8` 一路在防的东西
      （★ 与 `B146` 抓出的「有文件但认不出」被归成 `missing` 是**同一类错误**）。

    ★ 作业层拉完源码后会调用 `submission.resolve_license()` **就地把这条改成真结论**
      —— ★ 管理员最终看到的是**真原因**，❌ 不是"待核验"这个中间态。
    """
    return LicenseVerdict(
        spdx="",
        category=CATEGORY_MISSING,
        decision=DECISION_REVIEW,
        reason_code=CODE_PENDING,
        reason_text="许可核验尚未进行 —— 会在拉取源码后立即核验，届时这条记录会被更新。",
        evidence={"deferred": True},
        suggestion="等待核验结果，通常无需人工处理",
        user_message="你的项目已受理，正在拉取源码并核验许可证，请稍候。",
    )


def classify(spdx: str | None) -> str:
    """SPDX 标识 → 类别（⚠ 认不出按 `unknown`，❌ 不默认当宽松）。"""
    if not spdx:
        return CATEGORY_MISSING
    if spdx in PERMISSIVE:
        return "permissive"
    if spdx in COPYLEFT:
        return "copyleft"
    if spdx in RESTRICTIVE:
        return "restrictive"
    return CATEGORY_UNKNOWN


def evaluate(
    root: str | None = None,
    *,
    texts: Mapping[str, str] | None = None,
    require_file: bool | None = None,
) -> LicenseVerdict:
    """★ 核验一个项目。

    Args:
        root: 源码目录（会从中找许可证文件）
        texts: 直接给 `{文件名: 内容}`（★ 便于单测；⚠ 与 `root` 二选一）
        require_file: ★ 覆盖开关（`None` = 读 `AppSetting.license_require_file`）

    ⚠★ **无论结论如何都要返回 `LicenseVerdict`**（❌ 不抛异常）——
      ★ 因为"没许可证"是**正常的业务情况**，不是程序错误。
    """
    if require_file is None:
        require_file = _require_file_setting()

    files: list[tuple[str, str]]
    if texts is not None:
        files = list(texts.items())
    elif root is not None:
        files = find_license_files(root)
    else:
        files = []

    # ---- 逐文件识别，取第一个认出来的（★ 根目录优先）----
    hits: list[dict[str, str]] = []
    spdx = ""
    for relpath, text in sorted(files, key=lambda p: (p[0].count(os.sep), p[0])):
        got = detect_spdx(relpath, text)
        head = " ".join(text.split())[:160]
        hits.append({"path": relpath, "spdx": got or "（未识别）", "head": head})
        if got and not spdx:
            spdx = got

    evidence: dict[str, Any] = {
        "license_files": [p for p, _ in files],
        "detections": hits[:5],          # ⚠ 只留样本，❌ 不全量塞库
        "require_file": bool(require_file),
    }

    if not files:
        return _verdict_missing(evidence, require_file=bool(require_file))

    # ★★ `category` 必须区分两件【不同】的事（★ 这是冒烟测试抓出来的 bug）：
    #    · 文件**不存在** ⇒ `missing`  （"没有许可证文件"）
    #    · 文件存在但**认不出** ⇒ `unknown`（"有这个文件，但读不懂它"）
    #  ⚠ 混为一谈会**给管理员错误的原因** —— 而这正是 `U3.7` 要防的东西。
    category = classify(spdx) if spdx else CATEGORY_UNKNOWN
    if category == "permissive":
        return LicenseVerdict(
            spdx=spdx,
            category=category,
            decision=DECISION_ALLOW,
            reason_code="permissive",
            reason_text=f"许可证为 {spdx}（宽松许可，允许再分发与衍生）",
            evidence=evidence,
            suggestion="建议放行",
            user_message=f"已自动核验通过（识别到许可证 {spdx}）。",
        )

    if category == "copyleft":
        return LicenseVerdict(
            spdx=spdx,
            category=category,
            decision=DECISION_REVIEW,
            reason_code="copyleft",
            reason_text=(
                f"许可证为 {spdx}（传染性许可）。「调用图算不算衍生作品」业界没有统一结论，"
                "若算，图数据就需按该许可发布，需要人工判断"
            ),
            evidence=evidence,
            suggestion="建议人工确认后再放行（不要自动放行）",
            user_message=(
                f"你的项目使用 {spdx} 许可证，这类许可证需要人工确认后才能上线。"
                "我们审核后会通知你，你也可以在项目页查看进度。"
            ),
        )

    if category == "restrictive":
        return LicenseVerdict(
            spdx=spdx,
            category=category,
            decision=DECISION_REVIEW,
            reason_code="restrictive",
            reason_text=(
                f"许可证为 {spdx}（明确限制条款）。作者作为版权人可以授权给自己，"
                "但平台属于「明知条款存在」，需要人工确认"
            ),
            evidence=evidence,
            suggestion="建议向提交者确认其权利人身份后再放行",
            user_message=(
                f"你的项目使用 {spdx} 许可证，其中包含使用限制条款，需要人工确认后才能上线。"
                "如果这个项目是你自己的，审核时会向你确认。"
            ),
        )

    if category == CATEGORY_UNKNOWN:
        return LicenseVerdict(
            spdx=spdx,
            category=category,
            decision=DECISION_REVIEW,
            reason_code="unknown_license",
            reason_text=(
                "仓库里有许可证文件，但无法识别为已知的 SPDX 标识。"
                "系统不假装认识，需要人工阅读后判断"
            ),
            evidence=evidence,
            suggestion="建议人工阅读许可证原文后再决定",
            user_message=(
                "你的仓库里有许可证文件，但我们无法自动识别它的类型，已转人工审核。"
                "如果你想加快处理，可以在项目页补充说明许可证名称。"
            ),
        )

    # ⚠ 理论上到不了这里（files 非空 ⇒ category 是四类之一）
    return LicenseVerdict(
        spdx=spdx,
        category=category,
        decision=DECISION_REVIEW,
        reason_code="unexpected",
        reason_text="许可核验出现未预期的情况，需要人工确认",
        evidence=evidence,
        suggestion="建议人工确认",
        user_message="你的项目已转人工审核，我们会尽快处理。",
    )


def _verdict_missing(evidence: dict[str, Any], *, require_file: bool) -> LicenseVerdict:
    """★ **无许可证文件** —— 这是 `B143` 专门松绑过的一格。

    ★★ `B143` 的理由（用户原话）：
      「**没有许可证的不要立即驳回，依然是管理员审核** —— 这是方便我**前期测试**的手段，
       我**很多 github 项目也没有许可证**，我就不能测试我自己的库了。」

    ⇒ ★ 两种行为**由开关决定**：
      · `require_file=False`（★ **现在**）⇒ ⚠ **进人工复核**（★ 便于测试）
      · `require_file=True`（★ **以后**）⇒ ❌ **直接拒绝**
    """
    if require_file:
        return LicenseVerdict(
            spdx="",
            category=CATEGORY_MISSING,
            decision=DECISION_REJECT,
            reason_code="no_license",
            reason_text="未找到许可证文件（当前配置为「无许可证一律拒绝」）",
            evidence=evidence,
            suggestion="拒绝 —— 请作者补充许可证后重新提交",
            user_message=(
                "你的项目没有找到许可证文件，暂时无法上线。"
                "请在仓库里加上许可证文件（例如 MIT）后重新提交，本次提交不占用你的上传额度。"
            ),
        )
    return LicenseVerdict(
        spdx="",
        category=CATEGORY_MISSING,
        decision=DECISION_REVIEW,
        reason_code="no_license",
        reason_text=(
            "未找到许可证文件。无许可证即默认「保留所有权利」，"
            "但权利人很可能就是提交者本人（他不需要自己的授权），需要人工判断"
        ),
        evidence=evidence,
        suggestion="建议人工确认提交者身份后放行（当前处于前期测试阶段）",
        user_message=(
            "你的项目没有找到许可证文件，已转人工审核。"
            "如果项目是你自己写的，通常可以直接通过；审核结果会在项目页显示。"
        ),
    )


def _require_file_setting() -> bool:
    """★ 读开关（⚠ 延迟 import，避免共享内核在 Django 未就绪时被导入）。"""
    try:
        from core import appsettings

        return bool(appsettings.get("license_require_file"))
    except Exception:  # noqa: BLE001 —— ⚠ 读不到开关时**取保守值**（要求许可证）
        return True
