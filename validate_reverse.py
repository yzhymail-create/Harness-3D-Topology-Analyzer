#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证: 从管状实体反推的中心线 vs 真实 Flexible Curve 中心线, 逐点对比偏差."""
import numpy as np
import harness_topology as H


def resample(pts, n=200):
    pts = np.asarray(pts, float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    if total < 1e-9:
        return np.repeat(pts[:1], n, axis=0)
    out = []
    tgt = np.linspace(0, total, n)
    j = 0
    for t in tgt:
        while j < len(s)-2 and s[j+1] < t:
            j += 1
        f = (t - s[j]) / max(s[j+1]-s[j], 1e-12)
        out.append(pts[j]*(1-f) + pts[j+1]*f)
    return np.array(out)


def dev(a, b, n=200):
    A, B = resample(a, n), resample(b, n)
    d1 = np.linalg.norm(A-B, axis=1)
    B2, A2 = resample(b, n), resample(a, n)
    d2 = np.linalg.norm(B2-A2, axis=1)
    d = np.maximum(d1, d2)  # 双向(防方向相反)
    return d.mean(), d.max()


print("== 正常模式(线框) ==")
r_true = H.analyze("M1E-DRD.stp", 3.0, progress=lambda m: None)
print(f"分支={len(r_true['branches'])} 节点={len(r_true['nodes'])}")
assert len(r_true["branches"]) == 10 and len(r_true["nodes"]) == 15, "回归失败!"

print("== 强制反推模式(仅实体) ==")
r_rev = H.analyze("M1E-DRD.stp", 3.0, progress=lambda m: None, force_reverse=True)
print(f"分支={len(r_rev['branches'])} 节点={len(r_rev['nodes'])}")

T = {b["proto"]: b for b in r_true["branches"]}
print(f"\n{'分支':22s} {'真长mm':>8s} {'反推长mm':>9s} {'平均偏差':>8s} {'最大偏差':>8s} 来源")
all_d = []
for b in r_rev["branches"]:
    t = T[b["proto"]]
    mean, mx = dev(t["polyline"], b["polyline"])
    all_d.append((mean, mx))
    print(f'{b["proto"]:22s} {t["length"]:8.1f} {b["length"]:9.1f} {mean:8.2f} {mx:8.2f} {b["src"]}')
means = [d[0] for d in all_d]; mxs = [d[1] for d in all_d]
print(f"\n总体: 平均偏差 {np.mean(means):.2f}mm, 最大偏差 {np.max(mxs):.2f}mm")
print("结论:", "通过" if np.max(mxs) < 2.0 else "偏差偏大, 需人工复核")
