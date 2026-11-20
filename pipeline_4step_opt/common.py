# -*- coding: utf-8 -*-
"""四步管线通用工具：包围盒数学、计时/内存记录、JSON 读写、名字解码。

本文件只有通用工具，不含任何拓扑判定规则。规则全部在 v7geom 引用
的 v7_final 函数里（第 1/3 步）与 stage2_contacts.py 里（第 2 步）。
"""
import json
import math
import os
import re
import resource
import struct
import time


# ---------------------------------------------------------------- 包围盒
def aabb_from_points(pts):
    """点列的外包盒 -> (xmin, ymin, zmin, xmax, ymax, zmax)。"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def aabb_expand(box, r):
    """包围盒各向外扩 r。"""
    x0, y0, z0, x1, y1, z1 = box
    return (x0 - r, y0 - r, z0 - r, x1 + r, y1 + r, z1 + r)


def aabb_dist(a, b):
    """两轴对齐包围盒之间的最短距离（相交/包含时为 0）。
    这是两实体真实表面距离的下界：若包围盒距离 > 阈值，实体一定不接触，
    可安全跳过；反之只说明“可能是候选”，必须再算精确距离。"""
    dx = max(b[0] - a[3], a[0] - b[3], 0.0)
    dy = max(b[1] - a[4], a[1] - b[4], 0.0)
    dz = max(b[2] - a[5], a[2] - b[5], 0.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def aabb_center(box):
    return ((box[0] + box[3]) / 2.0,
            (box[1] + box[4]) / 2.0,
            (box[2] + box[5]) / 2.0)


def aabb_diag(box):
    return math.sqrt((box[3] - box[0]) ** 2 +
                     (box[4] - box[1]) ** 2 +
                     (box[5] - box[2]) ** 2)


def bbox_c_from_box(box):
    """v7 的 bbox_c 格式：[cx, cy, cz, dx, dy, dz]（中心 + 三向尺寸）。"""
    c = aabb_center(box)
    return [c[0], c[1], c[2],
            box[3] - box[0], box[4] - box[1], box[5] - box[2]]


# ---------------------------------------------------------------- 计时/内存
def peak_rss_mb():
    """当前进程峰值常驻内存（MB）。Linux 上 ru_maxrss 单位是 KB。"""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


class StageTimer:
    """记录一步的耗时与内存峰值（/usr/bin/time 不可用时用 resource 模块）。"""

    def __init__(self, name, log):
        self.name = name
        self.log = log

    def __enter__(self):
        self.t0 = time.time()
        self.rss0 = peak_rss_mb()
        self.log(f"[计时] {self.name} 开始（当前内存 {self.rss0:.0f} MB）")
        return self

    def __exit__(self, *exc):
        dt = time.time() - self.t0
        rss = peak_rss_mb()
        self.log(f"[计时] {self.name} 完成：{dt:.1f}s，峰值内存 {rss:.0f} MB")
        self.dt = dt
        self.rss_peak = rss
        return False


# ---------------------------------------------------------------- JSON
def dump_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 名字解码
def decode_step_name(s):
    """解码 STEP 文本里的 \\X2\\...\\X0\\ 转义与 \\ 转义（与 v7 的 decode_name
    同义，另处理 CATIA 路径里的双反斜杠）。"""
    s = s.replace("\\\\", "\\").replace("''", "'")

    def _x2(m):
        hexs = m.group(1)
        try:
            units = [int(hexs[i:i + 4], 16) for i in range(0, len(hexs), 4)]
            raw = b"".join(struct.pack(">H", u) for u in units)
            return raw.decode("utf-16-be")
        except Exception:
            return m.group(0)

    return re.sub(r"\\X2\\([0-9A-Fa-f]+)\\X0\\", _x2, s)


# ---------------------------------------------------------------- 其他
def timestamp():
    """YYYYMMDD_HHMMSS（交付文件名时间戳，用户硬规则）。"""
    return time.strftime("%Y%m%d_%H%M%S")


def make_log(prefix=""):
    """返回一个带时间戳的 log 函数（同时打印）。"""
    def log(msg):
        print(f"{time.strftime('%H:%M:%S')} {prefix}{msg}", flush=True)
    return log
