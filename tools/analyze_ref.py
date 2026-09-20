#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析参考截图：识别 JSON 每个 token 的配色，用于精确复刻视觉风格。"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from png_read import read_png, hex_of  # noqa: E402

IMG = r"C:\Users\X\.workbuddy\clipboard-images\clipboard-2026-09-20T03-24-42-809Z-127fbf05.png"

img = read_png(IMG)
W, H = img.width, img.height
RIGHT = 880


def cls(rgb):
    r, g, b = rgb[:3]
    if b > g + 45 and b > r + 25:
        return 'BLUE'
    if g > r + 45 and g > b + 25:
        return 'GREEN'
    if g > r + 45 and b > r + 25:
        return 'TEAL'
    if abs(int(r) - int(b)) <= 55 and r > g + 45 and b > g + 45:
        return 'PURPLE'
    if r > g + 55 and r > b + 55:
        return 'CORAL'
    if max(r, g, b) - min(r, g, b) < 30:
        return 'gray'
    return '?'


def bands():
    out = []
    cur = None
    for y in range(60, H):
        has = False
        for x in range(RIGHT, W - 4, 2):
            r, g, b, a = img.px(x, y)
            if a > 60 and (r < 232 or g < 232 or b < 232):
                has = True
                break
        if has:
            cur = [y, y] if cur is None else [cur[0], y]
        elif cur is not None:
            if cur[1] - cur[0] >= 5:
                out.append(tuple(cur))
            cur = None
    return out


def runs_of(y0, y1):
    res = []
    cur = None
    for x in range(RIGHT, W - 2):
        hit = False
        for y in range(y0, y1 + 1):
            r, g, b, a = img.px(x, y)
            if a > 60 and (r < 232 or g < 232 or b < 232):
                hit = True
                break
        if hit:
            cur = [x, x] if cur is None else [cur[0], x]
        elif cur is not None:
            if cur[1] - cur[0] >= 2:
                res.append(tuple(cur))
            cur = None
    if cur is not None:
        res.append(tuple(cur))

    merged = []
    for r_ in res:
        if merged and r_[0] - merged[-1][1] <= 8:
            merged[-1] = (merged[-1][0], r_[1])
        else:
            merged.append(r_)
    return merged


def color_of(x0, x1, y0, y1):
    c = Counter()
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            r, g, b, a = img.px(x, y)
            if a > 60 and max(r, g, b) - min(r, g, b) >= 34:
                c[(r // 8 * 8, g // 8 * 8, b // 8 * 8)] += 1
    if not c:
        return 'gray', (110, 110, 110)
    rep = c.most_common(1)[0][0]
    return cls(rep), rep


bs = bands()
print("=== 每行 token 配色（右侧面板）===\n")
for i, (y0, y1) in enumerate(bs[:24], 1):
    parts = []
    for (x0, x1) in runs_of(y0, y1):
        k, rep = color_of(x0, x1, y0, y1)
        if x1 - x0 < 3 and k == 'gray':
            continue
        parts.append('%s%s@%d' % (k[:2], hex_of(rep) if k != 'gray' else '', x0))
    print("  #%02d y%3d: %s" % (i, y0, '  '.join(parts)))

print("\n=== 值列（x>1040）的颜色统计 ===")
c = Counter()
for y in range(60, H):
    for x in range(1040, W - 2):
        r, g, b, a = img.px(x, y)
        if a > 60 and max(r, g, b) - min(r, g, b) >= 34:
            c[(r // 6 * 6, g // 6 * 6, b // 6 * 6)] += 1
groups = []
for rgb, n in c.most_common():
    for g_ in groups:
        if all(abs(rgb[i] - g_['rep'][i]) <= 22 for i in range(3)):
            g_['n'] += n
            break
    else:
        groups.append({'rep': rgb, 'n': n})
groups.sort(key=lambda x: -x['n'])
for g_ in groups[:8]:
    print("  %-9s %-8s %6d px" % (hex_of(g_['rep']), cls(g_['rep']), g_['n']))

print("\n=== 键列（880<=x<1040）的颜色统计 ===")
c2 = Counter()
for y in range(60, H):
    for x in range(880, 1040):
        r, g, b, a = img.px(x, y)
        if a > 60 and max(r, g, b) - min(r, g, b) >= 34:
            c2[(r // 6 * 6, g // 6 * 6, b // 6 * 6)] += 1
groups2 = []
for rgb, n in c2.most_common():
    for g_ in groups2:
        if all(abs(rgb[i] - g_['rep'][i]) <= 22 for i in range(3)):
            g_['n'] += n
            break
    else:
        groups2.append({'rep': rgb, 'n': n})
groups2.sort(key=lambda x: -x['n'])
for g_ in groups2[:8]:
    print("  %-9s %-8s %6d px" % (hex_of(g_['rep']), cls(g_['rep']), g_['n']))

print("\n=== 背景与行距 ===")
bg = Counter()
for y in range(60, H, 2):
    for x in range(RIGHT, W, 2):
        r, g, b, a = img.px(x, y)
        if a > 200:
            bg[(r // 2 * 2, g // 2 * 2, b // 2 * 2)] += 1
print("  背景 Top2:", ', '.join('%s(%d)' % (hex_of(k), v) for k, v in bg.most_common(2)))
if len(bs) > 6:
    gaps = [bs[i + 1][0] - bs[i][0] for i in range(min(14, len(bs) - 1))]
    print("  相邻行基线间距:", gaps)
