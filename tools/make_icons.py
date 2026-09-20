#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成扩展图标。

纯标准库实现（zlib + struct 手写 PNG 编码），不依赖 Pillow。
图形：蓝色圆角矩形渐变底 + 白色花括号「{ }」，超采样抗锯齿。

用法：
    python tools/make_icons.py
"""

import math
import os
import struct
import zlib

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icons")

# 渐变起止色（与查看器强调色一致）
C0 = (0x2B, 0x7C, 0xFF)
C1 = (0x6A, 0x4B, 0xFF)
WHITE = (255, 255, 255)


# --------------------------------------------------------------------------
# PNG 编码
# --------------------------------------------------------------------------
def _chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path, width, height, rgba):
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        raw += rgba[y * stride:(y + 1) * stride]
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


# --------------------------------------------------------------------------
# 几何
# --------------------------------------------------------------------------
def quad_bezier(p0, p1, p2, steps):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
        y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


# 左花括号的归一化包围盒：x ∈ [0.24, 1.00]（脚架在 0.62，缺口尖端在 0.24）
BRACE_MIN_X = 0.24
BRACE_MAX_X = 1.00


def build_left_brace():
    """归一化坐标系 (0..1) 的左花括号折线，开口朝右、缺口朝左。"""
    pts = []
    pts += quad_bezier((1.00, 0.00), (0.76, 0.00), (0.62, 0.13), 16)
    pts.append((0.62, 0.36))
    pts += quad_bezier((0.62, 0.36), (0.62, 0.45), (0.24, 0.50), 16)
    pts += quad_bezier((0.24, 0.50), (0.62, 0.55), (0.62, 0.64), 16)
    pts.append((0.62, 0.87))
    pts += quad_bezier((0.62, 0.87), (0.76, 1.00), (1.00, 1.00), 16)
    dedup = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - dedup[-1][0]) > 1e-9 or abs(p[1] - dedup[-1][1]) > 1e-9:
            dedup.append(p)
    return dedup


def seg_distance(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def polyline_distance(px, py, pts):
    best = 1e9
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        d = seg_distance(px, py, ax, ay, bx, by)
        if d < best:
            best = d
            if best < 0.4:
                break
    return best


def rounded_rect_alpha(x, y, size, radius):
    """返回 0..1 的圆角矩形内部覆盖率（已按像素中心判定，边缘由超采样处理）。"""
    half = size / 2.0
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    dx = x - cx
    dy = y - cy
    if dx == 0.0 and dy == 0.0:
        return 1.0
    return 1.0 if math.hypot(dx, dy) <= radius else 0.0


def render(size, ss=3):
    """渲染 size x size 的 RGBA 图标。"""
    hi = size * ss
    acc = [[[0.0, 0.0, 0.0, 0.0] for _ in range(size)] for _ in range(size)]

    radius_hi = 0.225 * hi
    stroke_half = 0.078 * hi / 2.0

    height_ratio = 0.52
    brace_h = height_ratio * hi
    box_w = (BRACE_MAX_X - BRACE_MIN_X) / 1.0  # 归一化宽度 = 0.76
    brace_w = box_w * brace_h
    gap = 0.115 * hi
    content_w = 2 * brace_w + gap
    margin_x = (hi - content_w) / 2.0
    top_y = (hi - brace_h) / 2.0

    local = build_left_brace()

    def to_px(u, v):
        x = margin_x + (u - BRACE_MIN_X) / box_w * brace_w
        y = top_y + v * brace_h
        return x, y

    left_pts = [to_px(u, v) for (u, v) in local]
    right_pts = [(hi - x, y) for (x, y) in left_pts]

    # 花括号包围盒（含描边）用于跳过无用像素
    xs = [p[0] for p in left_pts] + [p[0] for p in right_pts]
    ys = [p[1] for p in left_pts] + [p[1] for p in right_pts]
    bx0 = max(0, int(min(xs) - stroke_half - 2))
    bx1 = min(hi, int(max(xs) + stroke_half + 3))
    by0 = max(0, int(min(ys) - stroke_half - 2))
    by1 = min(hi, int(max(ys) + stroke_half + 3))

    for hy in range(hi):
        v = hy + 0.5
        row = acc[min(hy // ss, size - 1)]
        for hx in range(hi):
            u = hx + 0.5
            base = rounded_rect_alpha(u, v, hi, radius_hi)
            if base <= 0.0:
                continue

            t = (u / hi + v / hi) / 2.0
            r = C0[0] + (C1[0] - C0[0]) * t
            g = C0[1] + (C1[1] - C0[1]) * t
            b = C0[2] + (C1[2] - C0[2]) * t

            if bx0 <= hx < bx1 and by0 <= hy < by1:
                d = min(
                    polyline_distance(u, v, left_pts),
                    polyline_distance(u, v, right_pts),
                )
                cov = stroke_half + 0.5 - d
                if cov <= 0.0:
                    cov = 0.0
                elif cov > 1.0:
                    cov = 1.0
                if cov > 0.0:
                    r = r + (WHITE[0] - r) * cov
                    g = g + (WHITE[1] - g) * cov
                    b = b + (WHITE[2] - b) * cov

            cell = row[min(hx // ss, size - 1)]
            cell[0] += r * base
            cell[1] += g * base
            cell[2] += b * base
            cell[3] += base

    n = float(ss * ss)
    out = bytearray()
    for y in range(size):
        for x in range(size):
            r, g, b, a = acc[y][x]
            alpha = a / n
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


def main():
    out_dir = os.path.abspath(OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    targets = [
        (16, 3, "icon16.png"),
        (32, 3, "icon32.png"),
        (48, 3, "icon48.png"),
        (128, 3, "icon128.png"),
        (300, 2, "store-icon-300.png"),
    ]
    for size, ss, name in targets:
        rgba = render(size, ss)
        path = os.path.join(out_dir, name)
        nbytes = write_png(path, size, size, rgba)
        print("wrote %s (%dx%d, %d bytes)" % (name, size, size, nbytes))


if __name__ == "__main__":
    main()
