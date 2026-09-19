#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 GitHub 组织头像（512x512 · 无水印 · 可复现）。

- 纯几何绘制（径向渐变底 + 星盘），不经过任何 AI 绘图服务，因此不存在水印
- 设计时已考虑 GitHub 会把头像裁成圆形：所有元素都在圆形安全区内
- 不放文字（头像在列表里只有 20~48px，放字看不清）
- 输出：reports/org-avatar.png

用法：
    /home/webapp/demo/venv/bin/python docs/make-org-avatar.py
"""
from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw

# ---------- 基本参数 ----------
SIZE = 512                # 正方形头像
S = 4                     # 超采样倍数（放大画、再缩小 → 抗锯齿）
CS = SIZE * S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "org-avatar.png")

GOLD = (198, 160, 62)
GOLD_LIGHT = (230, 197, 112)
STAR = (232, 238, 252)

CENTER = SIZE // 2        # 256
R = 172                   # 星盘外圈半径 → 直径 344，圆形裁剪（直径 512）内安全


def mix(c1, c2, t):
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


def main() -> None:
    random.seed(42)

    # ---------- 1. 背景：径向渐变（中心稍亮，边缘沉下去） ----------
    bg = Image.new("RGB", (CS, CS), (7, 10, 18))
    bd = ImageDraw.Draw(bg)
    inner, outer = (17, 24, 42), (7, 10, 18)
    steps = 150
    for i in range(steps, 0, -1):
        t = i / steps
        r = t * (CS * 0.72)
        bd.ellipse([CS / 2 - r, CS / 2 - r, CS / 2 + r, CS / 2 + r],
                   fill=mix(inner, outer, t))

    base = bg.convert("RGBA")
    ov = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    cx = cy = CENTER * S

    # ---------- 2. 星点（只在星盘外侧，避免糊住主体） ----------
    for _ in range(80):
        x, y = random.uniform(0, SIZE), random.uniform(0, SIZE)
        if math.hypot(x - CENTER, y - CENTER) < R * 1.15:
            continue
        r = random.uniform(0.8, 2.4) * S
        a = random.randint(90, 240)
        d.ellipse([x * S - r, y * S - r, x * S + r, y * S + r], fill=STAR + (a,))

    # ---------- 3. 星盘（居中；线宽比社交图更粗，小尺寸才看得见） ----------
    def ring(r_log: float, width: float, alpha: int) -> None:
        r = r_log * S
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=GOLD + (alpha,), width=max(1, int(width * S)))

    ring(R, 3.6, 240)         # 外圈（粗）
    ring(R - 20, 1.3, 120)
    ring(R - 58, 1.1, 90)
    ring(58, 2.0, 150)
    ring(16, 1.4, 190)

    # 刻度：每 10° 一根；每 30° 加长加粗（小尺寸下要能看出「刻度感」）
    for deg in range(0, 360, 10):
        rad = math.radians(deg)
        if deg % 30 == 0:
            length, alpha, w = 26, 240, 2.4
        else:
            length, alpha, w = 14, 140, 1.2
        r0 = (R - 20) * S
        r1 = (R - 20 - length) * S
        d.line([cx + r0 * math.cos(rad), cy + r0 * math.sin(rad),
                cx + r1 * math.cos(rad), cy + r1 * math.sin(rad)],
               fill=GOLD + (alpha,), width=max(1, int(w * S)))

    # 指针（两条，一粗一细）
    for deg, length, w, alpha in ((-58, 128, 3.4, 245), (124, 86, 2.4, 160)):
        rad = math.radians(deg)
        d.line([cx, cy,
                cx + length * S * math.cos(rad),
                cy + length * S * math.sin(rad)],
               fill=GOLD + (alpha,), width=max(1, int(w * S)))

    # 中心轴点
    rr = 8 * S
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=GOLD_LIGHT + (255,))

    # ---------- 4. 合成 + 输出 ----------
    img = Image.alpha_composite(base, ov).convert("RGB")
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print("已生成:", OUT, img.size)


if __name__ == "__main__":
    main()
