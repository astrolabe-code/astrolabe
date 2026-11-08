#!/usr/bin/env python3
"""Astrolabe 应用图标生成器 —— 定稿（纯标准库，无第三方依赖）。

用法：
    cd /home/ma/astrolabe/desktop && python3 packaging/make_icons.py

产出（全部落在 packaging/，即 electron-builder 的 buildResources）：
    icon.svg             矢量源（由同一套参数生成，可手工编辑）
    icon.png             1024×1024（Linux / BrowserWindow）
    icon.ico             16/24/32/48/64/128/256（Windows，BMP 格式）
    icon-preview.png     定稿预览（大图 + 128/64/32/16 对照，不必入库）

【定稿构成】所有者逐轮审定：
    · 主体 D1  —— 倾斜盘面 + 折面明暗 + 穿心照准尺(alidade) + 轴心铆钉
    · 星链 S3  —— 环外 8 颗星 + 4 段淡连线，三层明暗
    · 层次     —— 亮星 2 / 中星 3 / 暗星 3；亮度同时决定颜色与大小
    · 配色 L1  —— 纯白底 + 深青（贴 ui/public/favicon.svg 的 #0891b2）
    · 端头 T3  —— 底边与尺身平齐的三角箭头（仿射变换下仍可辨为三角形）

配色取自 ui/src/styles/tokens.css 亮色主题：
    --card #ffffff / --accent #0891b2 / --accent-strong #0e7490
"""
import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent
S = 1 << 10  # 主图 1024

# ---------------------------------------------------------------- 调色板（L1）
P = dict(bg_top=(255, 255, 255), bg_bottom=(247, 251, 253),
         edge=(150, 190, 205), edge_a=0.30,
         ring_hi=(56, 174, 202), ring_mid=(14, 116, 144), ring_lo=(8, 78, 102),
         rule_hi=(175, 226, 240), rule_mid=(60, 170, 200), rule_lo=(12, 108, 138),
         hub=(10, 92, 120), hub_core=(240, 251, 254),
         star_deep=(6, 96, 126), star_pale=(196, 224, 233),
         line=(14, 116, 144))

# ---------------------------------------------------------------- 盘面 / 照准尺
ANG = math.radians(-24)       # 盘面倾角
FLAT = 0.80                   # 透视压扁
R, HW = 0.285, 0.086          # 外环半径 / 半宽
RULE_A = math.radians(34)     # 照准尺方向（盘面坐标系）
RULE_LEN = 0.395              # 两端伸出盘外
RULE_C, RULE_S = math.cos(RULE_A), math.sin(RULE_A)
R_AX, R_AY = -RULE_LEN * RULE_C, -RULE_LEN * RULE_S
R_BX, R_BY = RULE_LEN * RULE_C, RULE_LEN * RULE_S
TRI_W, TRI_H = 0.066, 0.088   # T3：底边与尺身同宽、朝外三角

# ---------------------------------------------------------------- 星链（屏幕坐标）
# (cx, cy, 半径, 亮度, 带十字光芒)；亮度高 = 更深更饱和（浅底上反相）
STARS = [
    (0.220, -0.390, 0.0185, 0.94, True),
    (-0.100, 0.405, 0.0155, 0.82, True),
    (-0.060, -0.415, 0.0135, 0.56, False),
    (-0.330, -0.360, 0.0120, 0.47, False),
    (0.190, 0.385, 0.0125, 0.40, False),
    (0.365, -0.295, 0.0090, 0.24, False),
    (0.400, 0.060, 0.0095, 0.20, False),
    (-0.370, 0.300, 0.0085, 0.28, False),
]
# (ax, ay, bx, by, 亮度)：连线始终比星点暗，不抢主体
LINES = [
    (-0.330, -0.360, -0.060, -0.415, 0.15),
    (-0.060, -0.415, 0.220, -0.390, 0.22),
    (0.220, -0.390, 0.365, -0.295, 0.13),
    (-0.100, 0.405, -0.370, 0.300, 0.16),
]


def clamp(v, a=0.0, b=1.0):
    return a if v < a else (b if v > b else v)


def cover(d, size):
    """SDF 距离 → 覆盖率（1 像素宽的解析抗锯齿）"""
    t = clamp(0.5 - d * size)
    return t * t * (3 - 2 * t)


def sd_round(px, py, half=0.468, r=0.212):
    qx = abs(px) - (half - r)
    qy = abs(py) - (half - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def sd_seg(px, py, ax, ay, bx, by):
    pax, pay = px - ax, py - ay
    bax, bay = bx - ax, by - ay
    h = clamp((pax * bax + pay * bay) / (bax * bax + bay * bay))
    return math.hypot(pax - bax * h, pay - bay * h)


def sd_tri(px, py, cx, cy, ex, ey, nx, ny, w, h):
    """底边贴在尺身末端、尖端朝盘外的等腰三角形（盘面坐标系）"""
    dx, dy = px - cx, py - cy
    s = dx * ex + dy * ey
    t = dx * nx + dy * ny
    k = w / (2 * h)
    return max(-(s + 0.012), s - h, abs(t) + k * s - w / 2)


def mix(c, col, a):
    return (c[0] + (col[0] - c[0]) * a,
            c[1] + (col[1] - c[1]) * a,
            c[2] + (col[2] - c[2]) * a)


def metal(px, py, hi, lo):
    """沿左上→右下的方向性渐变，给主体体积感"""
    t = clamp(0.5 - (px + py) / 1.1)
    return tuple(hi[i] * (1 - t) + lo[i] * t for i in range(3))


def star_tint(br):
    """暗星淡青近底色，亮星深饱和青 —— 层次不只靠 alpha"""
    t = clamp((br - 0.18) / 0.76)
    a, b = P['star_pale'], P['star_deep']
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


STAR_TINTS = [star_tint(s[3]) for s in STARS]
# 两端三角箭头的局部基（朝外单位向量 + 法向）
TRI_BASES = []
for _ex, _ey, _out in ((R_AX, R_AY, -1), (R_BX, R_BY, 1)):
    _ux, _uy = RULE_C * _out, RULE_S * _out
    TRI_BASES.append((_ex, _ey, _ux, _uy, -_uy, _ux))


def disk_coords(px, py):
    """屏幕坐标 → 盘面（旋转 + 压扁）坐标"""
    u = px * math.cos(ANG) - py * math.sin(ANG)
    v = px * math.sin(ANG) + py * math.cos(ANG)
    return u, v / FLAT


def star_layer(px, py, size):
    out = []
    for ax, ay, bx, by, la in LINES:
        out.append((cover(sd_seg(px, py, ax, ay, bx, by) - 0.0028, size),
                    star_tint(la + 0.30), la))
    for idx, (cx, cy, r, br, sparkle) in enumerate(STARS):
        tint = STAR_TINTS[idx]
        # 尺寸自适应：小图标里星点至少约一个像素，⛔ 不糊成噪点
        rr = max(r, 0.42 / size)
        if sparkle:
            arm = rr * 2.15
            out.append((cover(sd_seg(px, py, cx - arm, cy, cx + arm, cy) - 0.0020, size),
                        tint, br * 0.42))
            out.append((cover(sd_seg(px, py, cx, cy - arm, cx, cy + arm) - 0.0020, size),
                        tint, br * 0.42))
        out.append((cover(math.hypot(px - cx, py - cy) - rr, size), tint, br))
    return out


def body_layer(px, py, size):
    u, qv = disk_coords(px, py)
    rr = math.hypot(u, qv)
    out = []

    # 外环（limb）：折面明暗
    def ring_color(x, y):
        if u * 0.42 + qv * 0.91 >= 0:
            return metal(x, y, P['ring_hi'], P['ring_mid'])
        return metal(x, y, P['ring_mid'], P['ring_lo'])

    out.append((cover(abs(rr - R) - HW, size), ring_color, 1.0))
    out.append((cover(abs(rr - (R - HW + 0.010)) - 0.005, size), P['rule_hi'], 0.55))

    # 照准尺（alidade）：穿心、两端伸出盘外
    def rule_color(x, y):
        if -u * RULE_S + qv * RULE_C >= 0:
            return metal(x, y, P['rule_hi'], P['rule_mid'])
        return metal(x, y, P['rule_mid'], P['rule_lo'])

    out.append((cover(sd_seg(u, qv, R_AX, R_AY, R_BX, R_BY) - 0.033, size),
                rule_color, 1.0))

    # T3 三角箭头
    tri_color = lambda x, y: metal(x, y, P['rule_hi'], P['rule_mid'])
    for ex, ey, ux, uy, nx, ny in TRI_BASES:
        out.append((cover(sd_tri(u, qv, ex, ey, ux, uy, nx, ny, TRI_W, TRI_H), size),
                    tri_color, 0.98))

    # 轴心铆钉（压住照准尺）
    out.append((cover(rr - 0.052, size), P['hub'], 1.0))
    out.append((cover(rr - 0.036, size), P['hub_core'], 1.0))
    return out


def render(size):
    """返回 RGBA bytes"""
    buf = bytearray(size * size * 4)
    inv = 1.0 / size
    for y in range(size):
        py = (y + 0.5) * inv - 0.5
        t = py + 0.5
        base = tuple(P['bg_top'][i] * (1 - t) + P['bg_bottom'][i] * t for i in range(3))
        row = y * size * 4
        for x in range(size):
            px = (x + 0.5) * inv - 0.5
            outer = cover(sd_round(px, py), size)
            if outer <= 0:
                continue
            c = mix(base, P['edge'],
                    cover(abs(sd_round(px, py) + 0.007) - 0.0025, size) * P['edge_a'])
            for cov, col, alpha in star_layer(px, py, size) + body_layer(px, py, size):
                if cov > 0:
                    c = mix(c, col(px, py) if callable(col) else col, cov * alpha)
            i = row + x * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = int(c[0]), int(c[1]), int(c[2]), int(outer * 255)
    return bytes(buf)


def png_bytes(w, h, rgba):
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))

    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes(raw), 9)) +
            chunk(b'IEND', b''))


def ico_bytes(images):
    """BMP(32bpp BGRA) 格式 ICO，Windows 全版本兼容"""
    n = len(images)
    out = bytearray(struct.pack('<HHH', 0, 1, n))
    offset = 6 + 16 * n
    entries = bytearray()
    blobs = bytearray()
    for size, rgba in images:
        stride = size * 4
        xor = bytearray()
        for y in range(size - 1, -1, -1):  # BMP 自下而上
            for x in range(size):
                i = y * stride + x * 4
                r, g, b, a = rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]
                xor += bytes((b, g, r, a))
        and_row = ((size + 31) // 32) * 4
        and_mask = bytes(and_row * size)  # 全 0 = 不透明（alpha 通道生效）
        dib = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0,
                          len(xor) + len(and_mask), 0, 0, 0, 0)
        blob = dib + bytes(xor) + and_mask
        entries += struct.pack('<BBBBHHII',
                               size if size < 256 else 0,
                               size if size < 256 else 0,
                               0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    return bytes(out + entries + blobs)


# ---------------------------------------------------------------- 矢量源
def hexcol(c):
    return '#%02x%02x%02x' % tuple(int(round(v)) for v in c)


def tri_points(ex, ey, ux, uy, nx, ny):
    """三角箭头三顶点（盘面坐标）：底边贴尺身末端、尖端朝外"""
    bcx, bcy = ex - 0.012 * ux, ey - 0.012 * uy
    hw = TRI_W / 2
    return ((bcx + hw * nx, bcy + hw * ny),
            (bcx - hw * nx, bcy - hw * ny),
            (ex + TRI_H * ux, ey + TRI_H * uy))


def halfplane_clip(cid, nx, ny, k=3.0):
    """法向 (nx,ny) 所指一侧的半平面，用于折面明暗分界"""
    L = math.hypot(nx, ny)
    nx, ny = nx / L, ny / L
    dx, dy = -ny, nx
    pts = [(-k * dx, -k * dy), (k * dx, k * dy),
           (k * dx + k * nx, k * dy + k * ny),
           (-k * dx + k * nx, -k * dy + k * ny)]
    s = ' '.join('%.4f,%.4f' % p for p in pts)
    return (f'    <clipPath id="{cid}" clipPathUnits="userSpaceOnUse">\n'
            f'      <polygon points="{s}"/>\n'
            f'    </clipPath>')


def svg_source():
    """由同一套常量生成 SVG，⛔ 避免矢量源与位图漂移"""
    a = []
    A = a.append
    A('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">')
    A('  <!-- Astrolabe 定稿：L1 浅色 / D1 星盘照准尺 / T3 三角箭头 / S3 三层星链 -->')
    A('  <defs>')
    A('    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">')
    A(f'      <stop offset="0" stop-color="{hexcol(P["bg_top"])}"/>')
    A(f'      <stop offset="1" stop-color="{hexcol(P["bg_bottom"])}"/>')
    A('    </linearGradient>')
    for gid, dark, light in (('ringLit', P['ring_mid'], P['ring_hi']),
                             ('ringDark', P['ring_lo'], P['ring_mid']),
                             ('ruleLit', P['rule_mid'], P['rule_hi']),
                             ('ruleDark', P['rule_lo'], P['rule_mid'])):
        A(f'    <linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">')
        A(f'      <stop offset="0" stop-color="{hexcol(dark)}"/>')
        A(f'      <stop offset="1" stop-color="{hexcol(light)}"/>')
        A('    </linearGradient>')
    A(halfplane_clip('ringHalf', 0.42, 0.91))
    A(halfplane_clip('ruleHalf', -RULE_S, RULE_C))
    A('  </defs>')

    # 圆角方底 + 内缘细边
    A(f'  <rect x="33" y="33" width="958" height="958" rx="217" fill="url(#bg)"/>')
    A(f'  <rect x="33" y="33" width="958" height="958" rx="217" fill="none"')
    A(f'        stroke="{hexcol(P["edge"])}" stroke-opacity="{P["edge_a"]}" stroke-width="5"/>')

    # 星链（屏幕坐标 → SVG 像素）
    def sp(cx, cy):
        return (512 + 1024 * cx, 512 + 1024 * cy)

    A('  <!-- 星链：连线 -->')
    for ax, ay, bx, by, la in LINES:
        x1, y1 = sp(ax, ay)
        x2, y2 = sp(bx, by)
        A(f'  <path d="M{x1:.1f} {y1:.1f} L{x2:.1f} {y2:.1f}" '
          f'stroke="{hexcol(star_tint(la + 0.30))}" stroke-opacity="{la}" '
          f'stroke-width="5.7" stroke-linecap="round"/>')
    A('  <!-- 星链：8 颗星，三层明暗 -->')
    for idx, (cx, cy, r, br, sparkle) in enumerate(STARS):
        tint = hexcol(STAR_TINTS[idx])
        x, y = sp(cx, cy)
        rp = 1024 * r
        if sparkle:
            arm = rp * 2.15
            A(f'  <path d="M{x - arm:.1f} {y:.1f} H{x + arm:.1f} '
              f'M{x:.1f} {y - arm:.1f} V{y + arm:.1f}" stroke="{tint}" '
              f'stroke-opacity="{br * 0.42:.2f}" stroke-width="4.1" stroke-linecap="round"/>')
        A(f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="{rp:.1f}" '
          f'fill="{tint}" fill-opacity="{br}"/>')

    # 盘面：屏幕坐标 [px,py] = R(24°)·[u, FLAT*qv]，缩放 1024
    A('  <!-- 盘面（倾斜 -24° + 透视压扁 0.80） -->')
    A('  <g transform="translate(512 512) scale(1024) rotate(24) scale(1 0.8)">')
    A(f'    <circle r="{R}" fill="none" stroke="url(#ringDark)" stroke-width="{2 * HW}"/>')
    A(f'    <circle r="{R}" fill="none" stroke="url(#ringLit)" stroke-width="{2 * HW}" '
      f'clip-path="url(#ringHalf)"/>')
    A(f'    <circle r="{R - HW + 0.010}" fill="none" '
      f'stroke="{hexcol(P["rule_hi"])}" stroke-opacity="0.55" stroke-width="0.010"/>')
    # 照准尺：先暗后亮（clip 分折面）
    rule = (f'M{R_AX:.4f} {R_AY:.4f} L{R_BX:.4f} {R_BY:.4f}')
    A(f'    <path d="{rule}" stroke="url(#ruleDark)" stroke-width="0.066" '
      f'stroke-linecap="round" fill="none"/>')
    A(f'    <path d="{rule}" stroke="url(#ruleLit)" stroke-width="0.066" '
      f'stroke-linecap="round" fill="none" clip-path="url(#ruleHalf)"/>')
    # 三角箭头
    for ex, ey, ux, uy, nx, ny in TRI_BASES:
        pts = ' '.join('%.4f,%.4f' % p for p in tri_points(ex, ey, ux, uy, nx, ny))
        A(f'    <polygon points="{pts}" fill="url(#ruleLit)" fill-opacity="0.98"/>')
    # 轴心铆钉
    A(f'    <circle r="0.052" fill="{hexcol(P["hub"])}"/>')
    A(f'    <circle r="0.036" fill="{hexcol(P["hub_core"])}"/>')
    A('  </g>')
    A('</svg>')
    return '\n'.join(a) + '\n'


# ---------------------------------------------------------------- 预览
def preview():
    """定稿大图 + 128/64/32/16 小尺寸对照，中灰蓝底衬托白图标"""
    big, pad, gap = 360, 26, 20
    smalls = (128, 64, 32, 16)
    w = big + pad * 2
    h = pad + big + gap + 128 + pad
    bg = (213, 223, 233)
    canvas = bytearray(bytes(bg) * (w * h))

    def blit(src, s, x0, y0):
        for yy in range(s):
            for xx in range(s):
                si = (yy * s + xx) * 4
                al = src[si + 3] / 255.0
                if al <= 0:
                    continue
                di = ((yy + y0) * w + x0 + xx) * 3
                canvas[di] = int(src[si] * al + bg[0] * (1 - al))
                canvas[di + 1] = int(src[si + 1] * al + bg[1] * (1 - al))
                canvas[di + 2] = int(src[si + 2] * al + bg[2] * (1 - al))

    blit(render(big), big, pad, pad)
    y0 = pad + big + gap
    total = sum(smalls) + 24 * (len(smalls) - 1)
    sx = (w - total) // 2
    for s in smalls:
        blit(render(s), s, sx, y0 + 128 - s)
        sx += s + 24

    rgba = bytearray(w * h * 4)
    for i in range(w * h):
        rgba[i * 4:i * 4 + 3] = canvas[i * 3:i * 3 + 3]
        rgba[i * 4 + 3] = 255
    return w, h, bytes(rgba)


def main():
    (OUT / 'icon.svg').write_text(svg_source(), encoding='utf-8')
    print('  icon.svg      定稿矢量源')

    big = render(S)
    (OUT / 'icon.png').write_bytes(png_bytes(S, S, big))
    print('  icon.png      1024×1024')

    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = [(s, render(s)) for s in sizes]
    (OUT / 'icon.ico').write_bytes(ico_bytes(images))
    print('  icon.ico      ' + '/'.join(str(s) for s in sizes))

    w, h, rgba = preview()
    (OUT / 'icon-preview.png').write_bytes(png_bytes(w, h, rgba))
    print(f'  icon-preview.png  {w}x{h}（定稿 + 小尺寸对照）')


if __name__ == '__main__':
    main()
