#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 GitHub Social preview 图（1280x640 · 无水印 · 可复现）。

- 输出：reports/social-preview.png
- 纯几何绘制（星空 + 星盘 + 文字），随机种子固定，重复执行结果一致
- 依赖：项目自带 venv 里的 Pillow

用法：
    /home/webapp/demo/venv/bin/python docs/make-social-preview.py
"""
from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

# ---------- 基本参数 ----------
W, H = 1280, 640          # GitHub social preview 要求 2:1
S = 4                     # 超采样倍数（先放大画，再缩小 → 抗锯齿）
CW, CH = W * S, H * S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "social-preview.png")

GOLD = (198, 160, 62)
GOLD_LIGHT = (226, 192, 104)
STAR = (235, 240, 255)

FONT_LATIN_BOLD = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_CJK = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

# 布局（以 1280x640 的逻辑坐标为准，绘制时统一乘 S）
CX_L, CY_L, R_L = 640, 215, 175
TITLE_TOP = 428           # ASTROLABE 文字顶部
SUB_TOP = 512             # 中文副标顶部


def load_font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    raise SystemExit("找不到可用字体，尝试过：" + " / ".join(paths))


def mix(c1, c2, t):
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


def main() -> None:
    random.seed(20260918)

    # ---------- 1. 背景：垂直渐变 ----------
    top, bot = (7, 10, 18), (15, 22, 38)
    base = Image.new("RGB", (CW, CH))
    bd = ImageDraw.Draw(base)
    for y in range(CH):
        bd.line([(0, y), (CW, y)], fill=mix(top, bot, y / CH))
    base = base.convert("RGBA")

    # ---------- 2. 叠加层 ----------
    ov = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    cx, cy = CX_L * S, CY_L * S
    RR = R_L * S

    # 2.1 中心光晕（由大到小、由淡到浓）
    for i in range(46):
        r = (R_L + 150 - i * 4.2) * S
        a = int(3 + 9 * (i / 46))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD + (a,))

    # 2.2 星点（避开星盘所在区域）
    for _ in range(150):
        x, y = random.uniform(0, W), random.uniform(0, H)
        if math.hypot(x - CX_L, y - CY_L) < R_L * 1.2:
            continue
        r = random.uniform(0.6, 1.9) * S
        a = random.randint(70, 235)
        d.ellipse([x * S - r, y * S - r, x * S + r, y * S + r], fill=STAR + (a,))

    # 2.3 星座连线
    for group in (
        [(300, 84), (372, 126), (330, 196)],
        [(918, 96), (996, 152), (944, 226), (1024, 258)],
        [(262, 388), (330, 452), (296, 512)],
    ):
        pts = [(x * S, y * S) for x, y in group]
        d.line(pts, fill=(150, 180, 235, 70), width=max(1, S // 2))
        for x, y in pts:
            rr = 2.6 * S
            d.ellipse([x * S - rr, y * S - rr, x * S + rr, y * S + rr],
                      fill=(200, 220, 255, 170))

    # 2.4 星盘：同心圈
    def ring(r_log: float, width: float, alpha: int) -> None:
        r = r_log * S
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=GOLD + (alpha,), width=max(1, int(width * S)))

    ring(R_L, 2.6, 235)
    ring(R_L - 15, 1.0, 120)
    ring(R_L - 48, 0.9, 95)
    ring(R_L - 99, 0.9, 75)
    ring(52, 1.6, 150)
    ring(14, 1.2, 190)

    # 2.5 刻度（每 2° 一根，30° / 10° 加长）
    for deg in range(0, 360, 2):
        rad = math.radians(deg)
        if deg % 30 == 0:
            length, alpha, w = 19, 235, 2
        elif deg % 10 == 0:
            length, alpha, w = 11, 150, 1
        else:
            length, alpha, w = 6, 85, 1
        r0, r1 = (R_L - 15) * S, (R_L - 15 - length) * S
        d.line([cx + r0 * math.cos(rad), cy + r0 * math.sin(rad),
                cx + r1 * math.cos(rad), cy + r1 * math.sin(rad)],
               fill=GOLD + (alpha,), width=max(1, w * S))

    # 2.6 指针 + 中心
    for deg, length, w, alpha in ((-55, 118, 3, 240), (128, 74, 2, 150)):
        rad = math.radians(deg)
        d.line([cx, cy,
                cx + length * S * math.cos(rad),
                cy + length * S * math.sin(rad)],
               fill=GOLD + (alpha,), width=max(1, w * S))
    rr = 6 * S
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=GOLD_LIGHT + (255,))

    # ---------- 3. 文字 ----------
    f_title = load_font(FONT_LATIN_BOLD, 58 * S)
    f_sub = load_font(FONT_CJK, 25 * S)

    def draw_tracked(text: str, font, fill, top: int, tracking: float) -> None:
        total = (sum(d.textlength(ch, font=font) for ch in text)
                 + tracking * (len(text) - 1))
        x = (CW - total) / 2
        for ch in text:
            d.text((x, top), ch, font=font, fill=fill)
            x += d.textlength(ch, font=font) + tracking

    draw_tracked("ASTROLABE", f_title, (243, 240, 232, 255), TITLE_TOP * S, 9 * S)
    draw_tracked("读懂代码的坐标系", f_sub, (154, 166, 191, 255), SUB_TOP * S, 3 * S)

    # ---------- 4. 合成 + 输出 ----------
    img = Image.alpha_composite(base, ov).convert("RGB")
    img = img.resize((W, H), Image.LANCZOS)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print("已生成:", OUT, img.size)


if __name__ == "__main__":
    main()
