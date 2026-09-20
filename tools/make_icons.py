#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成扩展图标 —— 3D 拟物质感（纯标准库：zlib + struct 手写 PNG，不依赖 Pillow）。

上一版是"扁平方块 + 叠几层材质渐变"，被否了：不够立体、太小气、配色普通、
跟一堆同类插件图标糊在一起。这一版换成**真做体积**：

    厚度 thickness
        沿光照反方向（右下）把同一个 SDF 反复偏移绘制 N 次，画出侧壁。
        越靠近顶面的那一层越亮（近似环境光反射），越远越暗；
        比"画两个错位方块"像实体得多，边缘也不会出现半透明接缝。
    投影 shadow
        两层：大范围低透明的环境阴影 + 贴边小范围的接地阴影。
    顶面 face
        方向渐变 + 内缘轮廓光（左上亮 / 右下压暗）+ 镜面高光条。
    地基 tile
        方圆形：对角渐变 + 左上聚光 + 底部暗角 + 边沿倒角。

配色 4 套（拉开色相差，不再都是蓝紫渐变）
    ocean     深蓝海水玻璃
    gold      香槟金 / 黄铜
    graphite  石墨钛银
    emerald   翡翠墨绿

形制 2 套
    slab      厚玻璃砖 —— 正面内嵌三条数据条（最"产品"，小尺寸最稳）
    cube      等距玻璃立方 —— 三个面受光不同，面内嵌等距数据条（最"立体"）

用法
    python tools/make_icons.py --list
    python tools/make_icons.py --compare                 # 生成 8 套比稿页 + 对比拼图
    python tools/make_icons.py --size 128 --palette ocean --concept slab --out x.png
    python tools/make_icons.py --palette ocean --concept slab --out-dir ../icons   # 写正式图标

注意：不带参数运行时**不会**写 icons/ 目录，避免误覆盖线上图标。
"""

import argparse
import math
import os
import struct
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "icons")
CAND_DIR = os.path.join(HERE, "..", "docs", "icon-candidates", "3d")

WHITE = (255.0, 255.0, 255.0)
INK = (3.0, 5.0, 10.0)
SQUIRCLE_N = 4.0

SMALL_PX = 20          # <= 这个尺寸走"小图简化"（条更粗更少）


# ==========================================================================
# PNG
# ==========================================================================
def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path, width, height, rgba):
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]
    data = (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


def new_canvas(w, h, rgb):
    buf = bytearray(w * h * 4)
    r, g, b = rgb
    for i in range(0, len(buf), 4):
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b
        buf[i + 3] = 255
    return buf


def blit(dst, dw, dh, src, sw, sh, ox, oy):
    """把 src(RGBA) alpha 合成到 dst(RGBA) 的 (ox, oy)。"""
    for y in range(sh):
        dy = oy + y
        if dy < 0 or dy >= dh:
            continue
        srow = y * sw * 4
        drow = dy * dw * 4
        for x in range(sw):
            dx = ox + x
            if dx < 0 or dx >= dw:
                continue
            si = srow + x * 4
            sa = src[si + 3]
            if sa == 0:
                continue
            di = drow + dx * 4
            if sa == 255:
                dst[di] = src[si]
                dst[di + 1] = src[si + 1]
                dst[di + 2] = src[si + 2]
            else:
                a = sa / 255.0
                inv = 1.0 - a
                dst[di] = int(round(src[si] * a + dst[di] * inv))
                dst[di + 1] = int(round(src[si + 1] * a + dst[di + 1] * inv))
                dst[di + 2] = int(round(src[si + 2] * a + dst[di + 2] * inv))
            dst[di + 3] = 255
    return dst


# ==========================================================================
# 数学 / SDF
# ==========================================================================
def clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def lerp(a, b, t):
    if t <= 0.0:
        return (float(a[0]), float(a[1]), float(a[2]))
    if t >= 1.0:
        return (float(b[0]), float(b[1]), float(b[2]))
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def hexc(s):
    return (float(int(s[0:2], 16)), float(int(s[2:4], 16)), float(int(s[4:6], 16)))


def softcov(d, feather):
    """距离 -> 软覆盖。feather 为 0 时退化成硬边（调用方需自行处理）。"""
    t = (feather - d) / feather
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def inside_squircle(u, v, inset=0.0, n=SQUIRCLE_N):
    s = 1.0 - inset
    if s <= 0.0:
        return False
    x = (u - 0.5) * 2.0 / s
    y = (v - 0.5) * 2.0 / s
    return (abs(x) ** n + abs(y) ** n) <= 1.0


def sd_box(px, py, cx, cy, hw, hh, r):
    if r > hw:
        r = hw
    if r > hh:
        r = hh
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    ax = qx if qx > 0.0 else 0.0
    ay = qy if qy > 0.0 else 0.0
    m = qx if qx > qy else qy
    if m > 0.0:
        m = 0.0
    return math.sqrt(ax * ax + ay * ay) + m - r


def sd_capsule(px, py, ax, ay, bx, by, r):
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2) - r
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    qx = px - (ax + t * dx)
    qy = py - (ay + t * dy)
    return math.sqrt(qx * qx + qy * qy) - r


def sd_circle(px, py, cx, cy, r):
    return math.sqrt((px - cx) ** 2 + (py - cy) ** 2) - r


def poly_planes(pts):
    """凸多边形 -> 单位外法线半平面列表 [(nx, ny, c)]，内部满足 n·p <= c。"""
    n = len(pts)
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    if area < 0.0:
        pts = list(reversed(pts))
    out = []
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        ex = x2 - x1
        ey = y2 - y1
        L = math.sqrt(ex * ex + ey * ey)
        if L == 0.0:
            continue
        nx = ey / L
        ny = -ex / L
        out.append((nx, ny, nx * x1 + ny * y1))
    return out


def paral(origin, bu, bw, u0, u1, w0, w1):
    """在 (u, w) 基底里取一块平行四边形。"""
    ox, oy = origin
    ux, uy = bu
    wx, wy = bw
    return [
        (ox + u0 * ux + w0 * wx, oy + u0 * uy + w0 * wy),
        (ox + u1 * ux + w0 * wx, oy + u1 * uy + w0 * wy),
        (ox + u1 * ux + w1 * wx, oy + u1 * uy + w1 * wy),
        (ox + u0 * ux + w1 * wx, oy + u0 * uy + w1 * wy),
    ]


def mk_shape(kind, p):
    """把 (kind, params) 预编译成可复用结构。"""
    if kind == 2:
        pl = poly_planes(p)
        x0 = min(q[0] for q in p)
        y0 = min(q[1] for q in p)
        x1 = max(q[0] for q in p)
        y1 = max(q[1] for q in p)
        return {"kind": 2, "planes": pl, "box": (x0, y0, x1, y1)}
    if kind == 1:
        ax, ay, bx, by, r = p
        return {"kind": 1, "p": p,
                "box": (min(ax, bx) - r, min(ay, by) - r,
                        max(ax, bx) + r, max(ay, by) + r)}
    cx, cy, hw, hh, r = p
    return {"kind": 0, "p": p, "box": (cx - hw, cy - hh, cx + hw, cy + hh)}


def sd_of(sh, x, y):
    k = sh["kind"]
    if k == 0:
        p = sh["p"]
        return sd_box(x, y, p[0], p[1], p[2], p[3], p[4])
    if k == 1:
        p = sh["p"]
        return sd_capsule(x, y, p[0], p[1], p[2], p[3], p[4])
    m = -1e9
    for nx, ny, c in sh["planes"]:
        t = nx * x + ny * y - c
        if t > m:
            m = t
    return m


# ==========================================================================
# 配色
# ==========================================================================
class Palette(object):
    __slots__ = ("key", "title", "bg0", "bg1", "glow", "glow_a", "vig", "rim",
                 "face0", "face1", "wall_near", "wall_far", "bars", "bars_hi",
                 "shadow", "note")

    def __init__(self, key, title, bg0, bg1, glow, glow_a, vig, rim,
                 face0, face1, wall_near, wall_far, bars, bars_hi, shadow, note=""):
        self.key = key
        self.title = title
        self.bg0 = bg0              # 左上受光
        self.bg1 = bg1              # 右下压暗
        self.glow = glow
        self.glow_a = glow_a
        self.vig = vig
        self.rim = rim
        self.face0 = face0          # 顶面左上
        self.face1 = face1          # 顶面右下
        self.wall_near = wall_near  # 侧壁靠顶面
        self.wall_far = wall_far    # 侧壁远端
        self.bars = bars            # 浅色面上的深色数据条
        self.bars_hi = bars_hi      # 深色面上的亮色数据条
        self.shadow = shadow
        self.note = note


PALETTES = {
    "ocean": Palette(
        "ocean", "深蓝海水",
        hexc("14527E"), hexc("03111A"), hexc("5DC8FF"), 0.30,
        hexc("010C16"), hexc("C6EEFF"),
        hexc("EAF6FF"), hexc("8FBBD9"), hexc("3E7CA6"), hexc("082A40"),
        [hexc("0E7490"), hexc("1D4ED8"), hexc("0F766E")],
        [hexc("38BDF8"), hexc("818CF8"), hexc("2DD4BF")], hexc("02131F"),
        "冷海水玻璃。蓝青系里最显贵的一档，跟市面上的紫蓝渐变明显区分。",
    ),
    "gold": Palette(
        "gold", "香槟金",
        hexc("6A3E10"), hexc("1C0F03"), hexc("FFC45C"), 0.32,
        hexc("0E0802"), hexc("FFEFC9"),
        hexc("FFF7E4"), hexc("DBB783"), hexc("A87B34"), hexc("332006"),
        [hexc("B45309"), hexc("92400E"), hexc("D97706")],
        [hexc("FBBF24"), hexc("FCD34D"), hexc("F59E0B")], hexc("0C0601"),
        "暖调香槟金。工具栏里最容易一眼跳出来，也最容易被记住。",
    ),
    "graphite": Palette(
        "graphite", "石墨钛银",
        hexc("3A465A"), hexc("07090D"), hexc("9FB6D0"), 0.26,
        hexc("04060A"), hexc("DCE9F7"),
        hexc("F4F7FB"), hexc("B4C0CF"), hexc("6E7B8C"), hexc("12161C"),
        [hexc("4F46E5"), hexc("0E7490"), hexc("334155")],
        [hexc("A5B4FC"), hexc("38BDF8"), hexc("CBD5E1")], hexc("030508"),
        "中性钛银加一点靛蓝。最耐看、最像个工具，但个性最弱。",
    ),
    "emerald": Palette(
        "emerald", "翡翠墨绿",
        hexc("0C5742"), hexc("02140F"), hexc("5EE6AF"), 0.28,
        hexc("010F0B"), hexc("CDFFE9"),
        hexc("EFFFF8"), hexc("9CCDB9"), hexc("3D8C6E"), hexc("04231A"),
        [hexc("047857"), hexc("0F766E"), hexc("065F46")],
        [hexc("34D399"), hexc("10B981"), hexc("6EE7B7")], hexc("01120D"),
        "翡翠墨绿。深色底加浅绿玻璃面，层次拉得最开，最不像默认图标。",
    ),
}


# ==========================================================================
# 元素
# ==========================================================================
def aabb_of(sh, ex, ey, shadows):
    x0, y0, x1, y1 = sh["box"]
    e = abs(ex) if abs(ex) > abs(ey) else abs(ey)
    x0 -= e
    y0 -= e
    x1 += e
    y1 += e
    for s in shadows:
        if not s:
            continue
        dx, dy, spread, feather, _a = s
        x0 = min(x0, x0 - 0.5 + dx - spread - feather)   # 保守放宽
        y0 = min(y0, y0 - 0.5 + dy - spread - feather)
        x1 = max(x1, x1 + 0.5 + dx + spread + feather)
        y1 = max(y1, y1 + 0.5 + dy + spread + feather)
    pad = 0.03
    if ex > 0:
        x1 += ex
    else:
        x0 += ex
    if ey > 0:
        y1 += ey
    else:
        y0 += ey
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def mk_elem(kind, p, ex=0.0, ey=0.0, steps=12, face0=None, face1=None,
            gdir=(0.35, 0.85), wall_near=None, wall_far=None,
            shadow=None, shadow2=None, rim=None, sheens=(), overlays=(),
            mark=None):
    sh = mk_shape(kind, p)
    return {
        "sh": sh,
        "ex": ex, "ey": ey, "steps": steps,
        "face0": face0, "face1": face1, "gdir": gdir,
        "wall_near": wall_near, "wall_far": wall_far,
        "shadow": shadow, "shadow2": shadow2,
        "rim": rim, "sheens": sheens, "overlays": overlays,
        "mark": mark,
        "aabb": aabb_of(sh, ex, ey, (shadow, shadow2)),
    }


def mk_mark(kind, p, color, alpha, feather=0.0):
    sh = mk_shape(kind, p)
    return {
        "sh": sh, "ex": 0.0, "ey": 0.0, "steps": 0,
        "face0": None, "face1": None, "gdir": (0.0, 0.0),
        "wall_near": None, "wall_far": None,
        "shadow": None, "shadow2": None, "rim": None,
        "sheens": (), "overlays": (),
        "mark": (color, alpha, feather),
        "aabb": aabb_of(sh, 0.0, 0.0, (None, None)),
    }


def sh_shift(kind, p, dx, dy, dr=0.0):
    """按形状类型平移（可选缩半径）。poly 不做。"""
    if kind == 1:
        return (p[0] + dx, p[1] + dy, p[2] + dx, p[3] + dy, p[4] + dr)
    if kind == 0:
        return (p[0] + dx, p[1] + dy, p[2], p[3], p[4] + dr)
    return p


# ==========================================================================
# 形制一：slab 厚玻璃砖
# ==========================================================================
def build_slab(pal, small):
    E = []
    ex, ey = 0.050, 0.054
    # 光路是"右下有厚度 + 右下有投影"，所以砖块要往左上让一点，
    # 否则重心会掉到右下角（第一版就是这样，看着歪）。
    cx, cy, hw, hh, r = 0.475, 0.468, 0.316, 0.310, 0.106

    if small:
        bars = [
            (1, (0.276, 0.392, 0.636, 0.392, 0.042), pal.bars[0]),
            (1, (0.276, 0.556, 0.564, 0.556, 0.042), pal.bars[1]),
        ]
    else:
        bars = [
            (1, (0.264, 0.360, 0.686, 0.360, 0.031), pal.bars[0]),
            (1, (0.354, 0.474, 0.654, 0.474, 0.029), pal.bars[1]),
            (1, (0.354, 0.588, 0.562, 0.588, 0.029), pal.bars[2]),
        ]

    ov = []
    for kind, p, col in bars:
        ov.append((kind, sh_shift(kind, p, 0.014, 0.016), pal.wall_far, 0.40))
        ov.append((kind, p, col, 1.0))
        ov.append((kind, sh_shift(kind, p, -0.007, -0.012, -0.016), WHITE, 0.34))

    sheens = [
        # 大面柔光带（玻璃本身的反光）
        (1, (0.205, 0.597, 0.540, 0.127, 0.082), WHITE, 0.11, 0.075),
        # 锐利镜面条
        (1, (0.228, 0.300, 0.523, 0.110, 0.019), WHITE, 0.50, 0.0),
        # 左上热斑
        (0, (0.267, 0.196, 0.108, 0.052, 0.052), WHITE, 0.16, 0.062),
        # 底部回弹光（侧壁把光弹回顶面下缘）
        (1, (0.220, 0.754, 0.665, 0.782, 0.014), pal.face0, 0.26, 0.030),
    ]

    E.append(mk_elem(
        0, (cx, cy, hw, hh, r), ex, ey, steps=13,
        face0=pal.face0, face1=pal.face1, gdir=(0.30, 0.88),
        wall_near=pal.wall_near, wall_far=pal.wall_far,
        shadow=(0.030, 0.036, 0.024, 0.115, 0.52),
        shadow2=(0.012, 0.016, 0.004, 0.030, 0.50),
        rim=(WHITE, 0.26, 0.017),
        sheens=tuple(sheens), overlays=tuple(ov),
    ))
    return E


# ==========================================================================
# 形制二：cube 等距玻璃立方
# ==========================================================================
def build_cube(pal, small):
    E = []
    cx, cy = 0.502, 0.414
    h, v, H = 0.326, 0.188, 0.362

    A = (cx, cy - v)
    B = (cx + h, cy - v * 0.5)
    C = (cx, cy)
    D = (cx - h, cy - v * 0.5)
    Ed = (cx, cy + H)
    F = (D[0], D[1] + H)
    G = (B[0], B[1] + H)

    # 接地阴影（先画，压在整个立方下面）
    E.append(mk_elem(
        0, (0.520, 0.784, 0.288, 0.042, 0.042), steps=0,
        shadow=(0.012, 0.018, 0.040, 0.135, 0.62),
        shadow2=(0.002, 0.008, 0.012, 0.030, 0.55),
    ))

    top_f0 = pal.face0
    top_f1 = pal.face1
    left_f0 = lerp(pal.face1, pal.wall_near, 0.34)
    left_f1 = lerp(pal.wall_near, pal.wall_far, 0.40)
    # 右面不能压太暗：底色本身是深的，压狠了整块silhouette就烂进背景里，
    # 看着就不像个立方体了（第一版就栽在这）。
    right_f0 = lerp(pal.wall_near, pal.wall_far, 0.28)
    right_f1 = lerp(pal.wall_near, pal.wall_far, 0.72)

    # 顶面
    E.append(mk_elem(
        2, [A, B, C, D], steps=0,
        face0=top_f0, face1=top_f1, gdir=(0.22, 0.94),
        sheens=(
            (0, (0.392, 0.318, 0.090, 0.055, 0.052), WHITE, 0.18, 0.075),
            (1, (0.325, 0.352, 0.487, 0.295, 0.012), WHITE, 0.48, 0.0),
            (1, (0.278, 0.376, 0.382, 0.344, 0.006), WHITE, 0.32, 0.0),
        ),
    ))

    # 左面（受光面，放数据条）
    if small:
        ubars = [(0.16, 0.86, 0.22, 0.46), (0.16, 0.66, 0.56, 0.80)]
    else:
        ubars = [(0.13, 0.88, 0.14, 0.29),
                 (0.13, 0.65, 0.39, 0.54),
                 (0.13, 0.77, 0.64, 0.79)]
    ov = []
    origin = D
    bu = (C[0] - D[0], C[1] - D[1])
    bw = (0.0, H)
    for i, (u0, u1, w0, w1) in enumerate(ubars):
        pts = paral(origin, bu, bw, u0, u1, w0, w1)
        ov.append((2, [(x + 0.011, y + 0.013) for (x, y) in pts], pal.wall_far, 0.42))
        ov.append((2, pts, pal.bars_hi[i % len(pal.bars_hi)], 1.0))

    E.append(mk_elem(
        2, [D, C, Ed, F], steps=0,
        face0=left_f0, face1=left_f1, gdir=(0.05, 0.95),
        sheens=((1, (0.262, 0.560, 0.298, 0.740, 0.008), WHITE, 0.10, 0.020),),
        overlays=tuple(ov),
    ))

    # 右面（背光面）
    E.append(mk_elem(
        2, [C, B, G, Ed], steps=0,
        face0=right_f0, face1=right_f1, gdir=(0.92, 0.38),
        sheens=((1, (0.660, 0.480, 0.775, 0.660, 0.007), WHITE, 0.08, 0.020),),
    ))

    # 棱线：上棱最亮，左轮廓次之，右下用回弹光把 silhouette 从背景里拉出来
    w = 0.012 if not small else 0.016
    E.append(mk_mark(1, (A[0], A[1], B[0], B[1], w), WHITE, 0.60))
    E.append(mk_mark(1, (A[0], A[1], D[0], D[1], w), WHITE, 0.50))
    E.append(mk_mark(1, (D[0], D[1], F[0], F[1], w * 0.8), WHITE, 0.32))
    E.append(mk_mark(1, (B[0], B[1], G[0], G[1], w * 0.7), pal.face0, 0.34))
    E.append(mk_mark(1, (C[0], C[1], Ed[0], Ed[1], w * 0.7), pal.face0, 0.28))
    E.append(mk_mark(1, (F[0], F[1], Ed[0], Ed[1], w * 0.7), pal.face0, 0.22))
    E.append(mk_mark(1, (Ed[0], Ed[1], G[0], G[1], w * 0.7), pal.face0, 0.26))
    return E


class Shape(object):
    __slots__ = ("key", "title", "build", "note")

    def __init__(self, key, title, build, note=""):
        self.key = key
        self.title = title
        self.build = build
        self.note = note


SHAPES = {
    "slab": Shape("slab", "厚玻璃砖", build_slab,
                  "一块有厚度的玻璃砖，正面内嵌三条数据条。最稳，小尺寸最清楚。"),
    "cube": Shape("cube", "等距立方", build_cube,
                  "等距投影立方体，三面受光不同 + 左面数据条。最立体，最不像同类图标。"),
}


# ==========================================================================
# 渲染
# ==========================================================================
def bg_color(pal, u, v):
    t = clamp01((u - 0.5) * 0.50 + (v - 0.5) * 0.86 + 0.5)
    col = lerp(pal.bg0, pal.bg1, t)

    dx = u - 0.245
    dy = v - 0.155
    d = math.sqrt(dx * dx + dy * dy)
    g = 1.0 - d / 0.92
    if g > 0.0:
        col = lerp(col, pal.glow, (g * g) * pal.glow_a)

    col = lerp(col, pal.vig, (clamp01((v - 0.44) / 0.56) ** 1.7) * 0.27)

    # 边沿倒角：左上提亮 / 右下压暗，让"地基"本身有体积
    if not inside_squircle(u, v, inset=0.034):
        if (u + v) < 0.98:
            col = lerp(col, pal.rim, 0.20)
        else:
            col = lerp(col, pal.vig, 0.40)
    if not inside_squircle(u, v, inset=0.013):
        col = lerp(col, pal.rim, 0.30 if (u + v) < 0.98 else 0.08)
    return col


def shade(e, u, v, col, pal, pm):
    m = e["mark"]
    if m is not None:
        d = sd_of(e["sh"], u, v)
        cov = softcov(d, m[2]) if m[2] > 0.0 else clamp01(0.5 - d / pm)
        if cov > 0.0:
            col = lerp(col, m[0], cov * m[1])
        return col

    x0, y0, x1, y1 = e["aabb"]
    if u < x0 or u > x1 or v < y0 or v > y1:
        return col

    sh = e["sh"]
    sd = sd_of

    # --- 投影 ---
    s1 = e["shadow"]
    if s1:
        d = sd(sh, u - s1[0], v - s1[1]) - s1[2]
        c = softcov(d, s1[3])
        if c > 0.0:
            col = lerp(col, pal.shadow, c * s1[4])
    s2 = e["shadow2"]
    if s2:
        d = sd(sh, u - s2[0], v - s2[1]) - s2[2]
        c = softcov(d, s2[3])
        if c > 0.0:
            col = lerp(col, pal.shadow, c * s2[4])

    ex = e["ex"]
    ey = e["ey"]
    steps = e["steps"]

    # --- 侧壁：远端先画，越靠顶面越亮，最后一层赢 ---
    if steps > 0:
        wn = e["wall_near"]
        wf = e["wall_far"]
        for i in range(steps):
            t = 1.0 - i / float(steps)
            d = sd(sh, u + t * ex, v + t * ey)
            c = 0.5 - d / pm
            if c <= 0.0:
                continue
            col = lerp(col, lerp(wn, wf, t), c if c < 1.0 else 1.0)

    # --- 顶面 ---
    face0 = e["face0"]
    if face0 is None:
        return col
    d = sd(sh, u, v)
    cov = clamp01(0.5 - d / pm)
    if cov <= 0.0:
        return col

    gd = e["gdir"]
    col = lerp(col, lerp(face0, e["face1"], clamp01(u * gd[0] + v * gd[1])), cov)

    rim = e["rim"]
    if rim and d > -rim[2]:
        edge = clamp01((d + rim[2]) / rim[2])
        col = lerp(col, rim[0], edge * rim[1] * cov * (1.0 if (u + v) < 1.0 else 0.30))

    for sk, sp, sc, sa, sfe in e["sheens"]:
        d2 = sd_of(mk_shape(sk, sp), u, v)
        c2 = softcov(d2, sfe) if sfe > 0.0 else clamp01(0.5 - d2 / pm)
        if c2 > 0.0:
            col = lerp(col, sc, c2 * sa * cov)

    for ok, op, oc, oa in e["overlays"]:
        d3 = sd_of(mk_shape(ok, op), u, v)
        c3 = clamp01(0.5 - d3 / pm)
        if c3 > 0.0:
            col = lerp(col, oc, c3 * oa * cov)
    return col


def render(size, pal_key, shape_key, ss=3):
    pal = PALETTES[pal_key]
    shape = SHAPES[shape_key]
    elems = shape.build(pal, size <= SMALL_PX)

    hi = size * ss
    pm = 1.0 / hi
    acc = [[[0.0, 0.0, 0.0, 0.0] for _ in range(size)] for _ in range(size)]

    for hy in range(hi):
        v = (hy + 0.5) / hi
        row = acc[hy // ss if hy // ss < size else size - 1]
        for hx in range(hi):
            u = (hx + 0.5) / hi
            if not inside_squircle(u, v):
                continue
            col = bg_color(pal, u, v)
            for e in elems:
                col = shade(e, u, v, col, pal, pm)
            cell = row[hx // ss if hx // ss < size else size - 1]
            cell[0] += col[0]
            cell[1] += col[1]
            cell[2] += col[2]
            cell[3] += 1.0

    total = float(ss * ss)
    out = bytearray()
    for y in range(size):
        for x in range(size):
            r, g, b, a = acc[y][x]
            if a <= 0.0:
                out += b"\x00\x00\x00\x00"
                continue
            alpha = a / total
            out += bytes((
                max(0, min(255, int(round(r / a)))),
                max(0, min(255, int(round(g / a)))),
                max(0, min(255, int(round(b / a)))),
                max(0, min(255, int(round(alpha * 255.0)))),
            ))
    return bytes(out)


OFFICIAL = [
    (16, 5, "icon16.png"),
    (32, 4, "icon32.png"),
    (48, 4, "icon48.png"),
    (128, 3, "icon128.png"),
    (300, 2, "store-icon-300.png"),
]

COMPARE_SIZES = [(128, 3), (32, 4), (16, 5)]


# ==========================================================================
# 比稿页 / 拼图
# ==========================================================================
def build_compare(pal_keys, shape_keys):
    os.makedirs(CAND_DIR, exist_ok=True)
    bufs = {}
    for sk in shape_keys:
        for pk in pal_keys:
            for size, ss in COMPARE_SIZES:
                t0 = time.time()
                b = render(size, pk, sk, ss)
                write_png(os.path.join(CAND_DIR, "%s-%s@%d.png" % (pk, sk, size)),
                          size, size, b)
                bufs[(pk, sk, size)] = b
                print("  %-9s %-5s @%-4d ss=%d  %.1fs"
                      % (pk, sk, size, ss, time.time() - t0))

    # --- 拼图 ---
    cw, ch, pad = 182, 190, 14
    W = pad * 2 + cw * len(pal_keys)
    H = pad * 2 + ch * len(shape_keys)
    sheet = new_canvas(W, H, (238, 241, 245))
    for ri, sk in enumerate(shape_keys):
        for ci, pk in enumerate(pal_keys):
            x0 = pad + ci * cw
            y0 = pad + ri * ch
            for y in range(y0 + 1, y0 + ch - 1):
                base = (y * W + x0 + 1) * 4
                for x in range(cw - 2):
                    i = base + x * 4
                    sheet[i] = 255
                    sheet[i + 1] = 255
                    sheet[i + 2] = 255
            blit(sheet, W, H, bufs[(pk, sk, 128)], 128, 128, x0 + 27, y0 + 10)
            blit(sheet, W, H, bufs[(pk, sk, 32)], 32, 32, x0 + 28, y0 + 146)
            blit(sheet, W, H, bufs[(pk, sk, 16)], 16, 16, x0 + 76, y0 + 154)
            blit(sheet, W, H, bufs[(pk, sk, 128)], 128, 128, x0 + 27, y0 + 10)
    sheet_path = os.path.join(CAND_DIR, "compare-3d.png")
    write_png(sheet_path, W, H, bytes(sheet))

    # --- HTML ---
    rows = []
    for sk in shape_keys:
        cells = []
        for pk in pal_keys:
            p = PALETTES[pk]
            cells.append(
                '<div class="cell">'
                '<div class="shot"><img src="%s-%s@128.png" width="128" height="128" alt="">'
                '<div class="sm"><img src="%s-%s@32.png" width="32" height="32" alt="">'
                '<img src="%s-%s@16.png" width="16" height="16" alt=""></div></div>'
                '<h3>%s · %s</h3><p>%s</p>'
                '</div>' % (pk, sk, pk, sk, pk, sk, p.title, SHAPES[sk].title, p.note))
        rows.append('<div class="row">%s</div>' % "".join(cells))
    html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>图标比稿 · 3D 拟物</title>
<style>
:root{color-scheme:light}
body{margin:0;padding:28px 32px 60px;background:#F7F8FA;color:#111827;
 font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
h1{margin:0 0 6px;font-size:22px;letter-spacing:-.01em}
.sub{color:#6B7280;margin:0 0 22px}
.shapehdr{margin:26px 0 10px;font-size:15px;font-weight:600;color:#374151;
 border-left:3px solid #111827;padding-left:9px}
.shapehdr span{font-weight:400;color:#6B7280;font-size:13px;margin-left:8px}
.row{display:grid;grid-template-columns:repeat(%d,1fr);gap:16px}
.cell{background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:14px 14px 12px;
 box-shadow:0 1px 2px rgba(16,24,40,.04)}
.shot{position:relative;display:flex;justify-content:center;align-items:flex-start;
 padding:6px 0 4px}
.sm{position:absolute;right:4px;bottom:0;display:flex;align-items:flex-end;gap:7px}
.sm img{image-rendering:-webkit-optimize-contrast;display:block}
h3{margin:6px 0 2px;font-size:13.5px;font-weight:600}
p{margin:0;font-size:12px;color:#6B7280;line-height:1.5}
</style></head><body>
<h1>图标比稿 · 3D 拟物质感</h1>
<p class="sub">同一个光路：光从左上来 → 顶面亮、厚度在右下、投影落在右下。共 %d 套，每套给出 128 / 32 / 16 三个尺寸。</p>
%s
</body></html>""" % (len(pal_keys), len(pal_keys), "".join(
        '<div class="shapehdr" style="margin-top:%dpx">%s<span>%s</span></div>%s'
        % (0 if i == 0 else 26, SHAPES[sk].title, SHAPES[sk].note, rows[i])
        for i, sk in enumerate(shape_keys)))
    html_path = os.path.join(CAND_DIR, "compare.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return sheet_path, html_path


# ==========================================================================
# CLI
# ==========================================================================
def main():
    ap = argparse.ArgumentParser(prog="make_icons.py", description="生成扩展图标（3D 拟物）")
    ap.add_argument("--palette", default=None, help="配色：%s" % ", ".join(sorted(PALETTES)))
    ap.add_argument("--concept", dest="concept", default=None,
                    help="形制：%s" % ", ".join(sorted(SHAPES)))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--compare", action="store_true", help="生成 8 套比稿页 + 拼图")
    ap.add_argument("--out-dir")
    ap.add_argument("--size", type=int)
    ap.add_argument("--out")
    ap.add_argument("--ss", type=int, default=3)
    args = ap.parse_args()

    if args.list:
        print("配色：")
        for k in sorted(PALETTES):
            print("  %-9s %s" % (k, PALETTES[k].title))
            print("            %s" % PALETTES[k].note)
        print("形制：")
        for k in sorted(SHAPES):
            print("  %-9s %s" % (k, SHAPES[k].title))
            print("            %s" % SHAPES[k].note)
        return

    if args.compare:
        pal_keys = [args.palette] if args.palette else sorted(PALETTES)
        shape_keys = [args.concept] if args.concept else sorted(SHAPES)
        print("比稿：%s x %s" % (",".join(pal_keys), ",".join(shape_keys)))
        sheet, html = build_compare(pal_keys, shape_keys)
        print("拼图：%s" % sheet)
        print("比稿页：%s" % html)
        return

    if args.size:
        if not (args.palette and args.concept):
            raise SystemExit("--size 模式必须同时给 --palette 与 --concept")
        out_path = args.out or ("icon%d.png" % args.size)
        b = render(args.size, args.palette, args.concept, args.ss)
        kb = write_png(out_path, args.size, args.size, b) / 1024.0
        print("wrote %s (%dx%d, %.1f KB) [%s / %s]"
              % (out_path, args.size, args.size, kb,
                 PALETTES[args.palette].title, SHAPES[args.concept].title))
        return

    if args.out_dir:
        if not (args.palette and args.concept):
            raise SystemExit("--out-dir 模式必须同时给 --palette 与 --concept（防止误覆盖）")
        out_dir = os.path.abspath(args.out_dir)
        os.makedirs(out_dir, exist_ok=True)
        for size, ss, name in OFFICIAL:
            b = render(size, args.palette, args.concept, ss)
            kb = write_png(os.path.join(out_dir, name), size, size, b) / 1024.0
            print("wrote %s (%dx%d, %.1f KB)" % (name, size, size, kb))
        print("配色 %s / 形制 %s" % (PALETTES[args.palette].title,
                                     SHAPES[args.concept].title))
        return

    ap.print_help()
    print("\n提示：不带参数不会写任何文件。先跑 --compare 看比稿，再 --out-dir 落正式图标。")


if __name__ == "__main__":
    main()
