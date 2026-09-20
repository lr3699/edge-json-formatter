#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成扩展图标（纯标准库：zlib + struct 手写 PNG，不依赖 Pillow）。

设计取向：**不用花括号**。扩展名里的 "{}" 是上一版的思路，
这里改用更能表达"结构化数据 / 排版"的图形语言，四套概念并行比稿。

四套概念
    card      代码卡片   —— 一张带亮边的卡，内含三条语法色横条
    tree      数据树     —— 根节点 + 分支 + 子节点，表达可折叠树结构
    stack     层叠光片   —— 三层错位方片，表达"分层 / 规整化"
    angle     尖括号数据 —— < > 夹一枚节点，表达代码与结构化数据

材质系统（让它"贵"起来的关键，而不是单纯叠一个渐变）
    - 方圆形 tile：超椭圆 |x|^n + |y|^n <= 1，转角过渡连续
    - 左上高光 specular：单侧光源，玻璃质感
    - 顶部玻璃带 glass：上缘柔光，产生"面"而非"片"
    - 底部暗角 vignette：压住下半部，增加厚重
    - 内缘轮廓光 rim：外沿细亮边，深浅背景都不糊
所有图形用 SDF + 超采样抗锯齿，小尺寸下依然干净。

用法
    python tools/make_icons.py                       # 默认方案，生成官方一套
    python tools/make_icons.py --concept tree        # 指定概念
    python tools/make_icons.py --concept card --size 128 --out x.png
    python tools/make_icons.py --list
"""

import argparse
import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "icons")

WHITE = (255, 255, 255)
INK = (8, 8, 24)
SQUIRCLE_N = 4.0


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# 数学 / SDF
# --------------------------------------------------------------------------
def clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def lerp(a, b, t):
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def hexc(s):
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def inside_squircle(u, v, inset=0.0, n=SQUIRCLE_N):
    s = 1.0 - inset
    if s <= 0.0:
        return False
    x = (u - 0.5) * 2.0 / s
    y = (v - 0.5) * 2.0 / s
    return (abs(x) ** n + abs(y) ** n) <= 1.0


def sd_box(px, py, cx, cy, hw, hh, r):
    r = min(r, hw, hh)
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def sd_circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


def sd_capsule(px, py, ax, ay, bx, by, r):
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay) - r
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) - r


def sdf(kind, a, px, py):
    if kind == "box":
        return sd_box(px, py, a[0], a[1], a[2], a[3], a[4])
    if kind == "dot":
        return sd_circle(px, py, a[0], a[1], a[2])
    return sd_capsule(px, py, a[0], a[1], a[2], a[3], a[4])


# --------------------------------------------------------------------------
# 概念（每个返回 marks 列表；marks = (kind, args, color, alpha)）
# --------------------------------------------------------------------------
PURPLE = hexc("C4B5FD")
BLUE = hexc("7DD3FC")
GREEN = hexc("86EFAC")
MINT = hexc("4ADE80")


def concept_card():
    """代码卡片：深色面板 + 亮边框 + 三条语法色横条。

    面板改用"比底色更深"的填充，而不是半透明白 —— 半透明白会把卡洗成
    灰紫色，廉价感很重（第一版就是这个问题）。
    """
    m = []
    # 外圈亮边 → 再盖深色面板，只留出 1.5% 的一圈亮线
    m.append(("box", (0.500, 0.500, 0.340, 0.310, 0.100), WHITE, 0.34))
    m.append(("box", (0.500, 0.500, 0.316, 0.286, 0.084), hexc("1B1140"), 0.62))
    # 三条横条：宽度递减、第二条缩进，模拟层级
    m.append(("seg", (0.270, 0.390, 0.665, 0.390, 0.027), PURPLE, 1.0))
    m.append(("seg", (0.365, 0.500, 0.620, 0.500, 0.024), BLUE, 1.0))
    m.append(("seg", (0.365, 0.610, 0.540, 0.610, 0.024), GREEN, 1.0))
    return m


def concept_tree():
    """数据树：根节点 → 两个子节点，右子节点用强调色。"""
    m = []
    line = 0.032
    m.append(("seg", (0.500, 0.275, 0.500, 0.450, line), WHITE, 0.50))
    m.append(("seg", (0.240, 0.450, 0.760, 0.450, line), WHITE, 0.50))
    m.append(("seg", (0.240, 0.450, 0.240, 0.610, line), WHITE, 0.50))
    m.append(("seg", (0.760, 0.450, 0.760, 0.610, line), WHITE, 0.50))
    m.append(("dot", (0.500, 0.205, 0.082), WHITE, 1.0))
    m.append(("dot", (0.240, 0.688, 0.072), WHITE, 0.90))
    m.append(("dot", (0.760, 0.688, 0.072), MINT, 1.0))
    return m


def concept_indent():
    """层级缩进：四条逐级右移的横条，直接表达「美化 / 嵌套」。

    这是四套里语义最直给的一套 —— 看到阶梯状缩进就想到格式化后的 JSON。
    """
    m = []
    ys = [0.295, 0.415, 0.535, 0.655]
    xs = [0.215, 0.300, 0.385, 0.470]
    colors = [PURPLE, hexc("A5B4FC"), BLUE, GREEN]
    for y, x, c in zip(ys, xs, colors):
        m.append(("seg", (x, y, x + 0.360, y, 0.029), c, 1.0))
    return m


def concept_angle():
    """尖括号数据：< > 夹一枚节点。"""
    m = []
    w = 0.040
    m.append(("seg", (0.385, 0.245, 0.205, 0.500, w), WHITE, 0.96))
    m.append(("seg", (0.205, 0.500, 0.385, 0.755, w), WHITE, 0.96))
    m.append(("seg", (0.615, 0.245, 0.795, 0.500, w), WHITE, 0.96))
    m.append(("seg", (0.795, 0.500, 0.615, 0.755, w), WHITE, 0.96))
    m.append(("dot", (0.500, 0.500, 0.092), MINT, 1.0))
    return m


class Concept(object):
    def __init__(self, key, title, build, c0, c1, gdir, spec, glass, vig,
                 rim_color, rim_alpha, note=""):
        self.key = key
        self.title = title
        self.build = build
        self.c0 = c0
        self.c1 = c1
        self.gdir = gdir
        self.spec = spec
        self.glass = glass
        self.vig = vig
        self.rim_color = rim_color
        self.rim_alpha = rim_alpha
        self.note = note


CONCEPTS = {
    "tree": Concept(
        "tree", "数据树", concept_tree,
        hexc("0B1020"), hexc("16213E"), (0.55, 0.45),
        0.14, 0.05, 0.28, hexc("94A3B8"), 0.14,
        "最贴合功能（可折叠树结构）。暗底 + 薄荷绿强调点，终端气质。",
    ),
    "indent": Concept(
        "indent", "层级缩进", concept_indent,
        hexc("312E81"), hexc("6D28D9"), (0.62, 0.38),
        0.30, 0.12, 0.22, WHITE, 0.30,
        "语义最直给：阶梯状缩进 = 格式化后的 JSON。小尺寸下也不糊。",
    ),
    "card": Concept(
        "card", "代码卡片", concept_card,
        hexc("2A1E6E"), hexc("5B21B6"), (0.60, 0.40),
        0.26, 0.10, 0.26, WHITE, 0.28,
        "最有产品感：深色面板 + 亮边 + 语法色横条。",
    ),
    "angle": Concept(
        "angle", "尖括号数据", concept_angle,
        hexc("0F172A"), hexc("1E3A8A"), (0.58, 0.42),
        0.20, 0.07, 0.26, hexc("CBD5E1"), 0.18,
        "仍是代码语义，但轮廓与旧版的 {} 完全不同，不会认错。",
    ),
}

DEFAULT_CONCEPT = "legacy"


def concept_legacy():
    """第一版外观，仅用于回退对比。"""
    m = []
    m.append(("box", (0.500, 0.500, 0.415, 0.415, 0.095), WHITE, 0.34))
    m.append(("seg", (0.300, 0.300, 0.300, 0.700, 0.040), WHITE, 0.0))
    return m


LEGACY = Concept(
    "legacy", "旧版（仅回退用）", concept_legacy,
    hexc("2B7CFF"), hexc("6A4BFF"), (0.50, 0.50),
    0.0, 0.0, 0.0, WHITE, 0.0,
)


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------
def render(size, concept, ss=3):
    hi = size * ss
    pm = 1.0 / hi                     # 一个 hi 像素在归一化坐标下的边长
    marks = concept.build()
    acc = [[[0.0, 0.0, 0.0, 0.0] for _ in range(size)] for _ in range(size)]

    n = concept.gdir
    for hy in range(hi):
        v = (hy + 0.5) / hi
        row = acc[min(hy // ss, size - 1)]
        for hx in range(hi):
            u = (hx + 0.5) / hi
            if not inside_squircle(u, v):
                continue

            # 1) 对角渐变
            col = lerp(concept.c0, concept.c1, clamp01(u * n[0] + v * n[1]))

            # 2) 左上高光
            if concept.spec > 0.0:
                d = math.hypot(u - 0.20, v - 0.10) / 0.95
                col = lerp(col, WHITE, (max(0.0, 1.0 - d) ** 2) * concept.spec)

            # 3) 顶部玻璃带
            if concept.glass > 0.0:
                col = lerp(col, WHITE, (clamp01((0.45 - v) / 0.45) ** 2) * concept.glass)

            # 4) 底部暗角
            if concept.vig > 0.0:
                col = lerp(col, INK, (clamp01((v - 0.42) / 0.58) ** 1.6) * concept.vig)

            # 5) 内缘轮廓光
            if concept.rim_alpha > 0.0 and not inside_squircle(u, v, inset=0.018):
                col = lerp(col, concept.rim_color, concept.rim_alpha)

            # 6) 图形
            # 覆盖率必须换算到"像素"单位：cov = clamp01(0.5 - d_px)。
            # 若直接写 clamp01(0.5*pm - d)，形状内部只会得到 ~0.02 的覆盖，
            # 图形整体透明不可见（这个坑踩过一次）。
            for (kind, a, c, alpha) in marks:
                if alpha <= 0.0:
                    continue
                d = sdf(kind, a, u, v)
                cov = clamp01(0.5 - d / pm)
                if cov > 0.0:
                    col = lerp(col, c, cov * alpha)

            cell = row[min(hx // ss, size - 1)]
            cell[0] += col[0]
            cell[1] += col[1]
            cell[2] += col[2]
            cell[3] += 1.0

    total = float(ss * ss)
    out = bytearray()
    for y in range(size):
        for x in range(size):
            r, g, b, a = acc[y][x]
            alpha = a / total
            if alpha <= 0.0:
                out += bytes((0, 0, 0, 0))
                continue
            out += bytes((
                max(0, min(255, int(round(r / a)))),
                max(0, min(255, int(round(g / a)))),
                max(0, min(255, int(round(b / a)))),
                max(0, min(255, int(round(alpha * 255)))),
            ))
    return bytes(out)


OFFICIAL = [
    (16, 4, "icon16.png"),
    (32, 4, "icon32.png"),
    (48, 3, "icon48.png"),
    (128, 3, "icon128.png"),
    (300, 2, "store-icon-300.png"),
]


def main():
    ap = argparse.ArgumentParser(prog="make_icons.py", description="生成扩展图标")
    ap.add_argument("--concept", default=DEFAULT_CONCEPT,
                    help="概念：%s" % ", ".join(sorted(list(CONCEPTS) + ["legacy"])))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out-dir")
    ap.add_argument("--size", type=int)
    ap.add_argument("--out")
    ap.add_argument("--ss", type=int, default=3)
    args = ap.parse_args()

    if args.list:
        for k in sorted(CONCEPTS):
            c = CONCEPTS[k]
            print("%-6s %s" % (k, c.title))
            print("       %s" % c.note)
        print("legacy 第一版外观（仅回退对比）")
        return

    concept = LEGACY if args.concept == "legacy" else CONCEPTS.get(args.concept)
    if concept is None:
        raise SystemExit("未知概念：%s" % args.concept)

    if args.size:
        out_path = args.out or ("icon%d.png" % args.size)
        rgba = render(args.size, concept, args.ss)
        kb = write_png(out_path, args.size, args.size, rgba) / 1024.0
        print("wrote %s (%dx%d, %.1f KB) [%s]"
              % (out_path, args.size, args.size, kb, concept.title))
        return

    out_dir = os.path.abspath(args.out_dir or OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    for size, ss, name in OFFICIAL:
        rgba = render(size, concept, ss)
        kb = write_png(os.path.join(out_dir, name), size, size, rgba) / 1024.0
        print("wrote %s (%dx%d, %.1f KB)" % (name, size, size, kb))
    print("概念：%s" % concept.title)


if __name__ == "__main__":
    main()
