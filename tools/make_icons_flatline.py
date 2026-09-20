#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成扩展图标 —— 扁平描边风（纯标准库：zlib + struct 手写 PNG，不依赖 Pillow）。

参照用户给的参考图定风格，四个硬约束：
    1. 近黑方圆形底（#1F1F1F），完全扁平 —— 无渐变、无投影、无厚度、无高光
    2. 白色粗描边，圆头圆角（round cap / round join）
    3. 默认**纯黑白**；--accent 可加回一点琥珀橙 #F0A54C（对应参考图那个橙点）
    4. 花括号 { } 作为外框（参考图的签名），「里面」承担表达 JSON 的职责

黑白里怎么区分「键」和「值」：**空心描边 = 键，实心 = 值**。
这是描边风里最经典的手法，不用第二种颜色也能读出键值对。

四套「里面」（都基于参考图的外框，只换内部图形语言）
    kv      键值对   —— 空心胶囊 + 冒号 + 实心胶囊        （最直白的 "key": value）
    rows    多行键值 —— 两行「键 : 值」并逐级缩进          （格式化之后的 JSON）
    arr     嵌套     —— 花括号里再套方括号 [ ] + 实心点    （层级 / 数组）
    tree    节点树   —— 实心根节点 + 分支 + 空心子节点      （参考图同款语义）

和上一版（3D 拟物）是两套完全不同的做法：那版靠"厚度 + 投影"做体积，
这版靠"粗描边的形状本身"说话，所有渲染就是 fill + SDF 覆盖率抗锯齿，没有别的。

用法
    python tools/make_icons_flatline.py --list
    python tools/make_icons_flatline.py --compare                  # 比稿页 + 拼图
    python tools/make_icons_flatline.py --size 128 --variant kv --out x.png
    python tools/make_icons_flatline.py --variant kv --out-dir ../icons   # 写正式图标

不带参数运行**不写任何文件**，正式图标必须显式传 --variant --out-dir。
"""

import argparse
import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "icons")
CAND_DIR = os.path.join(HERE, "..", "docs", "icon-candidates", "flatline")

# ---- 参考图实测取色（tools/_zoom_ref.py 从截图里统计出来的主色） ----
TILE = (31, 31, 31)          # #1F1F1F  参考图底色实测 #202020 / #181818
WHITE = (255, 255, 255)      # 描边（参考图实测 #f8f0f0，即白）
AMBER = (240, 165, 76)       # #F0A54C  参考图实测 #f0b060 / #e8a058

SQUIRCLE_N = 4.0             # 与参考图的方圆形转角一致
SMALL_PX = 20                # <= 此尺寸走小图简化

# 描边粗细：参考图约 6.4% 图宽；这里折中取 0.030，兼顾"够粗"和"内部留得下东西"
STROKE = 0.030

# 花括号的折线（左括号）。参考图的括号是又高又窄、中腰外凸的经典字形。
# 关键：中腰是往**左**凸的，所以 y≈0.5 那一带内部可用宽度比上下两端大得多，
# 内部图形可以放得比"看起来"更大（第一版没利用这点，内容显得小而空）。
BRACE_L = [
    (0.296, 0.212),
    (0.246, 0.236),
    (0.232, 0.306),
    (0.232, 0.432),
    (0.192, 0.500),
    (0.232, 0.568),
    (0.232, 0.694),
    (0.246, 0.764),
    (0.296, 0.788),
]

# 内部可用区：中部 x 0.28~0.72（不受括号臂挤压），上下端 x 0.33~0.67
SAFE_MID = (0.286, 0.714)
SAFE_TALL = (0.328, 0.672)


def mirror(pts):
    return [(1.0 - x, y) for (x, y) in pts]


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
# SDF
# ==========================================================================
def clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def inside_squircle(u, v, n=SQUIRCLE_N):
    x = (u - 0.5) * 2.0
    y = (v - 0.5) * 2.0
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


def sd_ring_box(px, py, cx, cy, hw, hh, r, t):
    """空心圆角矩形（描边框）。t = 描边厚度。"""
    return abs(sd_box(px, py, cx, cy, hw, hh, r)) - t


def sd_ring_circle(px, py, cx, cy, r, t):
    """空心圆环。"""
    return abs(sd_circle(px, py, cx, cy, r)) - t


def sd_polyline(px, py, pts, r):
    """折线（圆头圆角）—— 取所有线段的 min，天然是圆角拐弯，不会出现接缝。"""
    m = 1e9
    for i in range(len(pts) - 1):
        d = sd_capsule(px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], r)
        if d < m:
            m = d
    return m


def sd_of(kind, p, x, y):
    if kind == 0:
        return sd_box(x, y, p[0], p[1], p[2], p[3], p[4])
    if kind == 1:
        return sd_capsule(x, y, p[0], p[1], p[2], p[3], p[4])
    if kind == 2:
        return sd_circle(x, y, p[0], p[1], p[2])
    if kind == 4:
        return sd_ring_box(x, y, p[0], p[1], p[2], p[3], p[4], p[5])
    if kind == 5:
        return sd_ring_circle(x, y, p[0], p[1], p[2], p[3])
    return sd_polyline(x, y, p[0], p[1])


# 简写构造：mk(kind, params, color)
def cap(a, b, r, c):
    return (1, (a[0], a[1], b[0], b[1], r), c)


def dot(cx, cy, r, c):
    return (2, (cx, cy, r), c)


def rbox(cx, cy, hw, hh, r, c):
    return (0, (cx, cy, hw, hh, r), c)


def ring(cx, cy, hw, hh, r, t, c):
    return (4, (cx, cy, hw, hh, r, t), c)


def ringdot(cx, cy, r, t, c):
    return (5, (cx, cy, r, t), c)


def line(pts, r, c):
    return (3, (pts, r), c)


def braces():
    return [line(BRACE_L, STROKE, WHITE), line(mirror(BRACE_L), STROKE, WHITE)]


# ==========================================================================
# 四套「里面」
# ==========================================================================
def build_kv(small, accent):
    """键值对：空心胶囊（键） + 冒号 + 实心胶囊（值）。最直白的 "key": value。

    黑白模式下靠「空心 vs 实心」区分键和值 —— 这是描边风里最经典的做法，
    不用第二种颜色也能一眼读出这是个键值对。
    """
    hh = 0.070 if small else 0.058
    t = 0.034 if small else 0.024
    m = braces()
    # 键做成**扁而宽**的描边胶囊。第一版接近圆形，看起来像个甜甜圈/"8"，
    # 完全读不出是"一段文本"；压扁拉宽之后才是 token 的样子。
    m.append(ring(0.358, 0.500, 0.098, hh, hh, t, WHITE))
    if small:
        # 16px 下两个 0.5px 的点必然糊掉，并成一个更实的点
        m.append(dot(0.496, 0.500, 0.030, WHITE))
    else:
        m.append(dot(0.496, 0.476, 0.020, WHITE))
        m.append(dot(0.496, 0.524, 0.020, WHITE))
    m.append(rbox(0.622, 0.500, 0.078, hh, hh, AMBER if accent else WHITE))
    return m


def build_rows(small, accent):
    """多行键值：两行「键 : 值」并逐级缩进 —— 格式化之后的 JSON 样子。"""
    if small:
        rows = [(0.398, 0.276, 0.414, 0.492, 0.644),
                (0.602, 0.312, 0.450, 0.528, 0.650)]
        hh, t, cr = 0.058, 0.030, 0.026
    else:
        rows = [(0.394, 0.272, 0.424, 0.500, 0.648),
                (0.606, 0.308, 0.460, 0.536, 0.654)]
        hh, t, cr = 0.038, 0.022, 0.019
    m = braces()
    for (cy, kx0, kx1, vx0, vx1) in rows:
        m.append(ring((kx0 + kx1) / 2.0, cy, (kx1 - kx0) / 2.0, hh, hh, t, WHITE))
        if small:
            m.append(dot((kx1 + vx0) / 2.0, cy, cr, WHITE))
        else:
            cx = (kx1 + vx0) / 2.0
            m.append(dot(cx, cy - 0.023, cr, WHITE))
            m.append(dot(cx, cy + 0.023, cr, WHITE))
        m.append(rbox((vx0 + vx1) / 2.0, cy, (vx1 - vx0) / 2.0, hh + 0.004,
                      hh + 0.004, AMBER if accent else WHITE))
    return m


def build_arr(small, accent):
    """嵌套：花括号里再套方括号 [ ]，中间一枚实心点 —— 表达对象套数组的层级。

    坑：方括号的"臂"如果只比竖笔长一点点（第一版 0.036），整个字形会被读成
    两根竖线 | ● |，完全看不出是括号。臂长至少要到描边粗细的 2 倍。
    """
    w = 0.036 if small else 0.030
    bar, arm = (0.344, 0.412) if small else (0.350, 0.414)
    m = braces()
    m.append(line([(arm, 0.312), (bar, 0.312), (bar, 0.688), (arm, 0.688)], w, WHITE))
    m.append(line([(1.0 - arm, 0.312), (1.0 - bar, 0.312),
                   (1.0 - bar, 0.688), (1.0 - arm, 0.688)], w, WHITE))
    m.append(dot(0.500, 0.500, 0.092 if small else 0.080, AMBER if accent else WHITE))
    return m


def build_str(small, accent):
    """字符串：一对引号夹一个实心胶囊 —— "value"，JSON 里最有辨识度的元素之一。

    引号要悬在胶囊**上缘**（x-height 之上），压到同一水平线上就成了 ||▬||。
    """
    w = 0.042 if small else 0.034
    qy0, qy1 = (0.398, 0.498) if small else (0.404, 0.492)
    qx = (0.314, 0.352) if not small else (0.312, 0.354)
    m = braces()
    for x in qx:
        m.append(cap((x, qy0), (x, qy1), w * 0.62, WHITE))
        m.append(cap((1.0 - x, qy0), (1.0 - x, qy1), w * 0.62, WHITE))
    m.append(rbox(0.500, 0.540 if not small else 0.548, 0.098 if not small else 0.094,
                  0.044 if not small else 0.052, 0.044 if not small else 0.052,
                  AMBER if accent else WHITE))
    return m


def build_tree(small, accent):
    """节点树：实心根节点 + 白色分支与两个空心子节点（参考图同款语义）。"""
    if small:
        root = (0.500, 0.334, 0.074)
        kids = [(0.382, 0.652), (0.618, 0.652)]
        kr, t, w, stem = 0.066, 0.028, 0.040, 0.372
    else:
        root = (0.500, 0.334, 0.066)
        kids = [(0.384, 0.650), (0.616, 0.650)]
        kr, t, w, stem = 0.060, 0.024, 0.033, 0.368
    m = braces()
    m.append(cap((0.500, stem), kids[0], w, WHITE))
    m.append(cap((0.500, stem), kids[1], w, WHITE))
    # 枝干画到节点中心，环的镂空会把它露出来 —— 先用底色圆盘把环内部盖掉
    for (kx, ky) in kids:
        m.append(dot(kx, ky, kr - t, TILE))
    for (kx, ky) in kids:
        m.append(ringdot(kx, ky, kr, t, WHITE))
    m.append(dot(root[0], root[1], root[2], AMBER if accent else WHITE))
    return m


VARIANTS = {}


class Variant(object):
    __slots__ = ("key", "title", "build", "note")

    def __init__(self, key, title, build, note=""):
        self.key = key
        self.title = title
        self.build = build
        self.note = note


VARIANTS = {
    "kv": Variant("kv", "键值对", build_kv,
                  "一个「键 : 值」：空心胶囊是键、实心胶囊是值。黑白下也分得清，最直白。"),
    "rows": Variant("rows", "多行键值", build_rows,
                    "两行缩进的「键 : 值」，就是格式化之后的 JSON。元素最多、信息量最大。"),
    "str": Variant("str", "字符串", build_str,
                   "一对引号夹一个实心胶囊，就是 value。引号是 JSON 里最抓眼的元素。"),
    "arr": Variant("arr", "嵌套数组", build_arr,
                   "花括号里再套一对方括号，中间一枚实心点：对象里套数组的层级。"),
    "tree": Variant("tree", "节点树", build_tree,
                    "参考图同款语义：实心根节点 + 分支 + 空心子节点。不看 JSON 也认得出是数据。"),
}


# ==========================================================================
# 渲染
# ==========================================================================
def render(size, variant_key, ss=3, accent=False):
    var = VARIANTS[variant_key]
    marks = var.build(size <= SMALL_PX, accent)
    hi = size * ss
    pm = 1.0 / hi
    acc = [[[0.0, 0.0, 0.0, 0.0] for _ in range(size)] for _ in range(size)]

    tr, tg, tb = TILE
    for hy in range(hi):
        v = (hy + 0.5) / hi
        row = acc[hy // ss if hy // ss < size else size - 1]
        for hx in range(hi):
            u = (hx + 0.5) / hi
            if not inside_squircle(u, v):
                continue
            col = [float(tr), float(tg), float(tb)]
            for (kind, p, c) in marks:
                d = sd_of(kind, p, u, v)
                cov = 0.5 - d / pm
                if cov <= 0.0:
                    continue
                if cov > 1.0:
                    cov = 1.0
                col[0] += (c[0] - col[0]) * cov
                col[1] += (c[1] - col[1]) * cov
                col[2] += (c[2] - col[2]) * cov
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
# 极简 5x7 点阵字（只为了在拼图上打标签，免得看图还得对着 HTML 找名字）
# ==========================================================================
# 5x7 点阵：每个字形写成 **7 行 x 5 列** 的字符串列表。
# 早期版本写成一整条 35 字符，结果有多个字形长度不对（31~37），画出来是乱码 ——
# 用「按行拆开 + 渲染时 pad」就不会再犯。
FONT = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "J": ["....#", "....#", "....#", "....#", "#...#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": [".###.", "#...#", "....#", "..##.", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
}
FONT_W, FONT_H = 5, 7


def fill_rect(buf, W, H, x, y, w, h, rgb):
    for yy in range(y, y + h):
        if yy < 0 or yy >= H:
            continue
        base = (yy * W + x) * 4
        for xx in range(x, x + w):
            if xx < 0 or xx >= W:
                continue
            i = base + (xx - x) * 4
            buf[i] = rgb[0]
            buf[i + 1] = rgb[1]
            buf[i + 2] = rgb[2]
            buf[i + 3] = 255


def draw_text(buf, W, H, x, y, text, scale, rgb):
    cx = x
    for ch in text.upper():
        if ch == " ":
            cx += 4 * scale
            continue
        rows = FONT.get(ch)
        if rows is None:
            cx += (FONT_W + 1) * scale
            continue
        for gy in range(FONT_H):
            row = rows[gy] if gy < len(rows) else ""
            for gx in range(FONT_W):
                if gx < len(row) and row[gx] == "#":
                    fill_rect(buf, W, H, cx + gx * scale, y + gy * scale,
                              scale, scale, rgb)
        cx += (FONT_W + 1) * scale
    return cx


def blit_zoom(dst, dw, dh, src, sw, zoom, ox, oy):
    """最近邻放大（看真实像素用，不要平滑）。"""
    for y in range(sw * zoom):
        for x in range(sw * zoom):
            si = ((y // zoom) * sw + (x // zoom)) * 4
            di = ((oy + y) * dw + ox + x) * 4
            if di < 0 or di + 4 > len(dst):
                continue
            dst[di:di + 3] = src[si:si + 3]
            dst[di + 3] = 255


def load_ref_tile(path, size):
    """把参考图截图裁出来缩到 size*size，用于同图对比。"""
    try:
        import png_read
        img = png_read.read_png(path)
    except Exception:
        return None
    W, H = img.width, img.height
    out = bytearray(size * size * 4)
    px = img.pixels
    for y in range(size):
        sy0 = y * H // size
        sy1 = max(sy0 + 1, (y + 1) * H // size)
        for x in range(size):
            sx0 = x * W // size
            sx1 = max(sx0 + 1, (x + 1) * W // size)
            r = g = b = n = 0
            for yy in range(sy0, sy1):
                row = yy * W
                for xx in range(sx0, sx1):
                    i = (row + xx) * 4
                    r += px[i]
                    g += px[i + 1]
                    b += px[i + 2]
                    n += 1
            o = (y * size + x) * 4
            out[o] = r // n
            out[o + 1] = g // n
            out[o + 2] = b // n
            out[o + 3] = 255
    return bytes(out)


# ==========================================================================
# 比稿页 / 拼图
# ==========================================================================
def build_compare(keys):
    os.makedirs(CAND_DIR, exist_ok=True)
    bufs = {}
    abufs = {}
    for k in keys:
        for size, ss in COMPARE_SIZES:
            b = render(size, k, ss)
            write_png(os.path.join(CAND_DIR, "%s@%d.png" % (k, size)), size, size, b)
            bufs[(k, size)] = b
            a = render(size, k, ss, accent=True)
            write_png(os.path.join(CAND_DIR, "%s-accent@%d.png" % (k, size)),
                      size, size, a)
            abufs[(k, size)] = a
        print("  %-6s ok" % k)

    ref = load_ref_tile(os.path.join(CAND_DIR, "..", "ref-zoom.png"), 128)

    cols = [k for k in keys] + (["REF"] if ref else [])
    cw, pad, lm = 200, 14, 84
    rows_h = [206, 206, 206, 146]
    W = lm + pad * 2 + cw * len(cols)
    H = pad * 2 + sum(rows_h)
    sheet = new_canvas(W, H, (243, 244, 246))
    INK = (24, 26, 30)
    GREY = (120, 126, 136)

    bands = [("LIGHT BG", (252, 252, 252), True, bufs),
             ("DARK BG", (46, 46, 46), True, bufs),
             ("ACCENT", (252, 252, 252), True, abufs),
             ("ZOOM", (252, 252, 252), False, bufs)]

    def tile(key, size, store):
        if key == "REF":
            return ref if size == 128 else None
        return store.get((key, size))

    y0 = pad
    for ri, (label, bg, full, store) in enumerate(bands):
        h = rows_h[ri]
        fill_rect(sheet, W, H, lm + pad, y0, cw * len(cols), h - 6, bg)
        draw_text(sheet, W, H, 12, y0 + (h - 6) // 2 - 7, label, 2,
                  INK if ri != 1 else GREY)
        for ci, key in enumerate(cols):
            x0 = lm + pad + ci * cw
            if full:
                big = tile(key, 128, store)
                if big:
                    blit(sheet, W, H, big, 128, 128, x0 + 36, y0 + 26)
                for sz, ox, oy in ((32, 38, 164), (16, 84, 172)):
                    t = tile(key, sz, store)
                    if t:
                        blit(sheet, W, H, t, sz, sz, x0 + ox, y0 + oy)
            else:
                for sz, zoom, ox in ((16, 6, 8), (32, 3, 104)):
                    t = tile(key, sz, store)
                    if t:
                        blit_zoom(sheet, W, H, t, sz, zoom, x0 + ox, y0 + 30)
                draw_text(sheet, W, H, x0 + 8, y0 + 6, key, 2, INK)
        y0 += h

    # 列头
    for ci, key in enumerate(cols):
        x0 = lm + pad + ci * cw
        draw_text(sheet, W, H, x0 + 10, pad + 6, key, 2,
                  (190, 60, 60) if key == "REF" else INK)

    sheet_path = os.path.join(CAND_DIR, "compare-flatline.png")
    write_png(sheet_path, W, H, bytes(sheet))

    cells = []
    for k in keys:
        cells.append(
            '<div class="cell"><div class="light"><img src="%s@128.png" alt=""></div>'
            '<div class="dark"><img src="%s@128.png" alt=""></div>'
            '<div class="accent"><img src="%s-accent@128.png" alt=""></div>'
            '<div class="sm"><img src="%s@32.png" width="32" height="32" alt="">'
            '<img src="%s@16.png" width="16" height="16" alt=""></div>'
            '<h3>%s</h3><p>%s</p></div>'
            % (k, k, k, k, k, VARIANTS[k].title, VARIANTS[k].note))
    refcard = ""
    if ref is not None:
        refcard = ('<div class="cell ref"><div class="light">'
                   '<img src="../ref-zoom.png" alt=""></div>'
                   '<h3>参考图</h3><p>用户给的截图（放大后的原始像素）。'
                   '四套都保留它的外框与配色，只换里面的图形语言。</p></div>')
    html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>图标比稿 · 扁平描边</title>
<style>
:root{color-scheme:light}
body{margin:0;padding:28px 32px 60px;background:#F7F8FA;color:#111827;
 font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
h1{margin:0 0 6px;font-size:22px;letter-spacing:-.01em}
.sub{color:#6B7280;margin:0 0 22px;max-width:860px}
.row{display:grid;grid-template-columns:repeat(%d,1fr);gap:16px;align-items:start}
.cell{background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:14px;
 box-shadow:0 1px 2px rgba(16,24,40,.04)}
.cell.ref{border-color:#FCA5A5;background:#FFFBFB}
.light{background:#FBFBFB;border-radius:12px 12px 0 0;padding:10px;text-align:center;line-height:0}
.dark{background:#2E2E2E;border-radius:0 0 12px 12px;padding:10px;text-align:center;line-height:0}
.accent{background:#FBFBFB;border-radius:12px;margin-top:8px;padding:10px;text-align:center;line-height:0}
.light img,.dark img,.accent img{width:128px;height:128px}
.cell.ref .light img{width:150px;height:150px;border-radius:6px}
.sm{margin-top:10px;display:flex;align-items:flex-end;gap:8px;justify-content:center}
.sm img{display:block}
h3{margin:8px 0 2px;font-size:13.5px;font-weight:600}
p{margin:0;font-size:12px;color:#6B7280;line-height:1.5}
code{background:#F3F4F6;padding:1px 4px;border-radius:4px;font-size:11.5px}
</style></head><body>
<h1>图标比稿 · 扁平描边（黑白）</h1>
<p class="sub">按你说的改成<b>黑白色</b>：近黑方圆形底 <code>#1F1F1F</code> + 白色粗圆头描边，
全扁平 —— 没有渐变、没有投影、没有厚度。四套共用参考图的花括号外框，<b>只换「里面」</b>，
并且都加了能表达 JSON 的元素（冒号、键值对、缩进行、方括号）；
黑白里靠「空心 = 键 / 实心 = 值」区分，第三行是保留一点琥珀橙的版本（跟参考图那个橙点对应）。</p>
<div class="row">%s</div>
</body></html>""" % (len(keys) + (1 if ref else 0), "".join(cells) + refcard)
    html_path = os.path.join(CAND_DIR, "compare.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return sheet_path, html_path


# ==========================================================================
# CLI
# ==========================================================================
def main():
    ap = argparse.ArgumentParser(prog="make_icons_flatline.py",
                                description="生成扩展图标（扁平描边风）")
    ap.add_argument("--variant", default=None,
                    help="内部图形：%s" % ", ".join(sorted(VARIANTS)))
    ap.add_argument("--accent", action="store_true",
                    help="加一点琥珀橙（默认纯黑白）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--out-dir")
    ap.add_argument("--size", type=int)
    ap.add_argument("--out")
    ap.add_argument("--ss", type=int, default=3)
    args = ap.parse_args()

    if args.list:
        for k in sorted(VARIANTS):
            print("  %-6s %s" % (k, VARIANTS[k].title))
            print("         %s" % VARIANTS[k].note)
        return

    if args.compare:
        keys = [args.variant] if args.variant else sorted(VARIANTS)
        print("比稿：%s" % ",".join(keys))
        sheet, html = build_compare(keys)
        print("拼图：%s" % sheet)
        print("比稿页：%s" % html)
        return

    if args.size:
        if not args.variant:
            raise SystemExit("--size 模式必须给 --variant")
        out_path = args.out or ("icon%d.png" % args.size)
        b = render(args.size, args.variant, args.ss, args.accent)
        kb = write_png(out_path, args.size, args.size, b) / 1024.0
        print("wrote %s (%dx%d, %.1f KB) [%s%s]"
              % (out_path, args.size, args.size, kb,
                 VARIANTS[args.variant].title, " +accent" if args.accent else ""))
        return

    if args.out_dir:
        if not args.variant:
            raise SystemExit("--out-dir 模式必须给 --variant（防止误覆盖）")
        out_dir = os.path.abspath(args.out_dir)
        os.makedirs(out_dir, exist_ok=True)
        for size, ss, name in OFFICIAL:
            b = render(size, args.variant, ss, args.accent)
            kb = write_png(os.path.join(out_dir, name), size, size, b) / 1024.0
            print("wrote %s (%dx%d, %.1f KB)" % (name, size, size, kb))
        print("内部图形 %s%s" % (VARIANTS[args.variant].title,
                                 " +accent" if args.accent else ""))
        return

    ap.print_help()
    print("\n提示：不带参数不会写任何文件。先 --compare 看比稿，再 --out-dir 落正式图标。")


if __name__ == "__main__":
    main()
