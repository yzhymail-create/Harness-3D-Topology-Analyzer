#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拓扑结构自检（2026-11-18 用户令：提取的拓扑数据要有办法自检自查）。
用法：python3 topology_audit.py <topology.json> [layout.json]
只读 topology.json（+可选 layout.json），不改任何数据。

检查项（硬规则任一失败则退出码 1）：
  A1 物理可能：每根管子的端点直线距 <= 弧长（直线距 > 弧长 = 这根管子根本连不上这两点）
  A2 度数规则：连接器 degree=1、接头 degree=2、分支点 degree>=3、卡扣 degree>=2
  A3 连通分量：段级生成树分量数与规模（信息项，供核对“几个分量”）
  A4 节点簇：同一节点内，管子端面圆心分成几簇（簇间距 >6mm 即两个接点被并成一个节点）
  A5 自环清查：na==nb 的线段数；单段分支的管子端到端距离（真自环应 ~0mm）
  A6 悬空点：非连接器节点 degree<=1（分支点/接头不应悬空）
  A7 画长核对（需 layout.json）：2D 画长 vs 3D 弧长，误差 >0.1mm 的列出
"""
import json
import math
import re
import sys
from collections import Counter, defaultdict


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def audit(topo_path, layout_path=None):
    d = json.load(open(topo_path, encoding='utf-8'))
    nodes = {n['code']: n for n in d['nodes']}
    branches = {b['key']: b for b in d['branches']}
    out = []
    hard_fail = []

    # ---- A1: chord <= length ----
    bad = []
    for b in d['branches']:
        chord = dist(b['p0'], b['p1'])
        if chord > b['length'] + 0.5:
            bad.append((b['key'], round(chord, 1), b['length']))
    out.append(f"A1 物理可能：{len(d['branches'])} 根管子，直线距>弧长 {len(bad)} 处")
    if bad:
        hard_fail.append(f"A1：{len(bad)} 根管子端点直线距超过弧长（物理不可能）")
        for k, c, l in bad[:10]:
            out.append(f"    {k[-40:]} 直线 {c}mm > 弧长 {l}mm")

    # ---- A2: degree rules ----
    deg_bad = []
    for n in d['nodes']:
        t, dg = n['type'], n['degree']
        if t == 'connector' and dg != 1:
            deg_bad.append((n['code'], t, dg, '连接器应为 1'))
        elif t == 'joint' and dg != 2:
            deg_bad.append((n['code'], t, dg, '接头应为 2'))
        elif t == 'fork' and dg < 3:
            deg_bad.append((n['code'], t, dg, '分支点应 >=3'))
        elif t == 'clamp' and dg < 2:
            deg_bad.append((n['code'], t, dg, '卡扣应 >=2'))
    out.append(f"A2 度数规则：{len(d['nodes'])} 个节点，违规 {len(deg_bad)} 处")
    if deg_bad:
        hard_fail.append(f"A2：{len(deg_bad)} 个节点度数违规")
        for c, t, dg, why in deg_bad[:10]:
            out.append(f"    {c} {t} degree={dg}（{why}）")

    # ---- A3: connected components (segment level) ----
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for s in d['segments']:
        union(s['na'], s['nb'])
    comp = Counter(find(n) for n in nodes)
    sizes = sorted(comp.values(), reverse=True)
    out.append(f"A3 连通分量（段级）：{len(sizes)} 个，规模 {sizes}")

    # ---- A4: node endpoint clusters ----
    multi = []
    for n in d['nodes']:
        ends = []
        for b in d['branches']:
            if b.get('node0') == n['code']:
                ends.append(b['p0'])
            if b.get('node1') == n['code']:
                ends.append(b['p1'])
        clusters = []
        for p in ends:
            for c in clusters:
                if dist(p, c[0]) <= 6.0:
                    c.append(p)
                    break
            else:
                clusters.append([p])
        if len(clusters) > 1:
            spread = max(dist(a[0], b[0]) for a in clusters for b in clusters)
            multi.append((n['code'], n['type'], len(clusters), round(spread, 1)))
    out.append(f"A4 节点簇：{len(multi)} 个节点内管子端点分成多簇（>6mm，两个接点被并成一点）")
    for c, t, k, sp in sorted(multi, key=lambda x: -x[3])[:10]:
        out.append(f"    {c}（{t}）{k} 簇，簇间距 {sp}mm")

    # ---- A5: self-loop inventory ----
    loops = [s for s in d['segments'] if s['na'] == s['nb']]
    single = [(s, branches[s['branch']]) for s in loops
              if len(branches[s['branch']]['segs']) == 1]
    buckets = Counter()
    for s, br in single:
        dd = dist(br['p0'], br['p1'])
        buckets['<0.1mm 真自环' if dd < 0.1 else
                '0.1-6mm' if dd <= 6 else
                '6-25mm' if dd <= 25 else
                '25-50mm' if dd <= 50 else '>50mm'] += 1
    out.append(f"A5 自环：{len(loops)} 条线段（单段分支 {len(single)} 条，多段分支 "
               f"{len(loops) - len(single)} 条）；单段分支端到端距离 {dict(buckets)}")

    # ---- A6: hanging non-connector nodes ----
    hang = [(n['code'], n['type'], n['degree']) for n in d['nodes']
            if n['type'] in ('fork', 'joint') and n['degree'] <= 1]
    out.append(f"A6 悬空点：分支点/接头 degree<=1 共 {len(hang)} 处")
    if hang:
        hard_fail.append(f"A6：{len(hang)} 个分支点/接头悬空")
        for c, t, dg in hang[:10]:
            out.append(f"    {c}（{t}）degree={dg}")

    # ---- A7: 2D vs 3D length (optional layout.json) ----
    # 自环段按 v6p2 画成小环符号，len_2d 不计其长度：先把自环段长度加回再比，
    # 剩下的才是真正的画长误差（不含自环符号的账）。
    if layout_path:
        lj = json.load(open(layout_path, encoding='utf-8'))
        seg_len = {s['seg']: s.get('length', 0) for s in d['segments']}
        seg_loop = {s['seg']: (s['na'] == s['nb']) for s in d['segments']}
        errs = []
        ring_only = 0
        for br in lj['branches']:
            l3 = br.get('len_3d', br.get('length_3d', 0))
            l2 = br.get('len_2d', br.get('length_2d', 0))
            loop_len = sum(seg_len.get(pc.get('seg'), 0) for pc in br.get('pieces', [])
                           if seg_loop.get(pc.get('seg')))
            adj_err = abs((l2 + loop_len) - l3)
            if abs(l2 - l3) > 0.1 and adj_err <= 0.1:
                ring_only += 1
            elif adj_err > 0.1:
                errs.append((br['key'], l3, l2, round(l2 - l3, 1)))
        out.append(f"A7 画长核对：扣掉自环符号长度后，真正画长误差 >0.1mm 共 {len(errs)} 根"
                   f"（另 {ring_only} 根的误差全是自环符号，按设计不计）")
        for k, l3, l2, e in sorted(errs, key=lambda x: -abs(x[3]))[:10]:
            out.append(f"    {k[-40:]} 3D {l3}mm -> 2D {l2}mm，误差 {e:+.1f}mm")

    print('\n'.join(out))
    if hard_fail:
        print('\n硬规则失败：' + '；'.join(hard_fail))
        return 1
    print('\n硬规则全过（A1/A2/A6）；A3/A4/A5/A7 为信息项，需人工复核。')
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(audit(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
