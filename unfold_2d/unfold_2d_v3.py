#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3D拓扑 → 2D展开图（v3，按 unfold_2d/需求说明.md）

规则摘要（v3，2026-11-16 语音定稿；v2 未被修改部分继续有效）：
- 长度 1:1：每根管子（分支）2D 折线总长 = 3D 中心线真实弧长
- 主干 = 最长分支，水平放置
- 长度数组逐个剥离：按长度从大到小，依次放置已有已放置节点的分支
- 有环先完整画环（圆上弦多边形，不剪口）；无环直接取最长管作主干
- 同点分支：第一根 90° 垂直，第二根夹 30°（60°），其后 ±30° 交替展开
- 干涉中途拐弯：在上一段结束点拐弯，拐到刚好避开（5° 步进，最大 45°）
- 多连通分量同图排列；放置失败不丢分支（兜底放置并记警告）
- DXF 用 BLOCK/INSERT：每根管子、每个连接器、每个卡扣一个块
- 干涉定义：真交叉、共线重叠、或间距 < CLEARANCE（默认 5mm，见需求 §十一问题3，暂定值）

模型说明：
- 画图单位是分支（一根管子）。分支由若干线段（segments）按 node0→node1 链式组成，
  每段在 2D 上是一条直线（段长 = 3D 段长），段与段之间在关节处连接；整根分支的
  2D 折线总长 = 分支 3D 弧长。无干涉时各段共线（即 v2 的"画成直线"）。
- 自环线段（na==nb，如 IP 的 SEG12/SEG21/SEG32）：画成等边三角形小环，
  周长 = 段长，起止都在同一节点上，不剪口不断开。
- 平行线段（两段同起止节点）：先画的一段把弦长定为两者较短者（较长者中部打折），
  后画的一段走直线，两段长度都保真。

用法：
  python3 unfold_2d_v3.py topology.json -o out_dir [--clearance 5]
输出：unfold_v3.dxf / unfold_v3.xlsx / layout.json
"""

import json, math, os, sys, argparse
from collections import defaultdict, deque

CLEARANCE_DEFAULT = 5.0   # 干涉判定最小间距 mm（需求 §十一问题3 未决，暂定 5mm）
BEND_MAX = 45.0           # 拐弯最大角度
BEND_STEP = 5.0           # 拐弯步进
# 同点分支偏移序列（相对垂直方向）：第1根 0°，第2根 -30°，第3根 +30°，…
ANGLE_OFFSETS = [0, -30, 30, -60, 60, -15, 15, -45, 45, -75, 75]
TOL = 1e-6
COMP_GAP = 200.0          # 连通分量之间的间距 mm

# ---------------------------------------------------------------- 几何工具

def pt_eq(a, b, tol=1e-6):
    return abs(a[0]-b[0]) < tol and abs(a[1]-b[1]) < tol

def _cross(o, a, b):
    return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

def _on_seg(p, a, b, tol=1e-9):
    return (min(a[0], b[0])-tol <= p[0] <= max(a[0], b[0])+tol and
            min(a[1], b[1])-tol <= p[1] <= max(a[1], b[1])+tol and
            abs(_cross(a, b, p)) < 1e-7)

def seg_proper_intersect(p1, p2, p3, p4):
    """两线段是否在内点真交叉（端点相接不算）。"""
    d1 = _cross(p3, p4, p1); d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3); d4 = _cross(p1, p2, p4)
    if min(abs(d1), abs(d2), abs(d3), abs(d4)) <= 1e-9:
        return False
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))

def seg_collinear_overlap(p1, p2, p3, p4):
    """两线段是否共线且重叠一段（重叠长度 > 1e-6 才算）。"""
    if abs(_cross(p1, p2, p3)) > 1e-7 or abs(_cross(p1, p2, p4)) > 1e-7:
        return False
    # 投影到 p1p2 方向
    dx, dy = p2[0]-p1[0], p2[1]-p1[1]
    L2 = dx*dx + dy*dy
    if L2 < 1e-12:
        return False
    def t(p):
        return ((p[0]-p1[0])*dx + (p[1]-p1[1])*dy) / L2
    t3, t4 = sorted((t(p3), t(p4)))
    lo, hi = max(0.0, t3), min(1.0, t4)
    return (hi - lo) * math.sqrt(L2) > 1e-6

def pt_seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx-ax, by-ay
    L2 = dx*dx + dy*dy
    if L2 < 1e-12:
        return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / L2))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

def seg_seg_dist(p1, p2, p3, p4):
    if seg_proper_intersect(p1, p2, p3, p4):
        return 0.0
    return min(pt_seg_dist(p1, p3, p4), pt_seg_dist(p2, p3, p4),
               pt_seg_dist(p3, p1, p2), pt_seg_dist(p4, p1, p2))

def pieces_interfere(a1, a2, b1, b2, clearance, skip_dist=False):
    """两条已画线段是否干涉：真交叉 / 共线重叠 / 间距 < clearance。
    共享端点的两段只查共线重叠（在同一节点分叉的两根管子根部必然靠近）。"""
    if pt_eq(a1, b1) or pt_eq(a1, b2) or pt_eq(a2, b1) or pt_eq(a2, b2):
        return seg_collinear_overlap(a1, a2, b1, b2)
    if seg_proper_intersect(a1, a2, b1, b2):
        return True
    if seg_collinear_overlap(a1, a2, b1, b2):
        return True
    if skip_dist:
        return False
    return seg_seg_dist(a1, a2, b1, b2) < clearance

def unit_from_angle(deg):
    r = math.radians(deg)
    return (math.cos(r), math.sin(r))

def add_pt(p, u, L):
    return (p[0] + u[0]*L, p[1] + u[1]*L)

def dist(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

def angle_of(a, b):
    return math.degrees(math.atan2(b[1]-a[1], b[0]-a[0]))

def rot_pt(p, deg, origin=(0.0, 0.0)):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    x, y = p[0]-origin[0], p[1]-origin[1]
    return (origin[0] + x*c - y*s, origin[1] + x*s + y*c)

# ---------------------------------------------------------------- 拓扑加载

class Topo:
    """四步管线 topology.json 的读取与图结构。"""

    def __init__(self, path):
        with open(path, encoding='utf-8') as f:
            self.raw = json.load(f)
        self.branches = {}   # key -> {length, dia, node0, node1, pieces}
        self.segs = {}       # seg -> {branch, na, nb, length, dia}
        self.nodes = {}      # code -> {type, name_3d, xyz}
        for n in self.raw.get('nodes', []):
            self.nodes[n['code']] = {
                'type': n.get('type', '?'),
                'name_3d': n.get('name_3d', ''),
                'xyz': n.get('xyz'),
            }
        for s in self.raw.get('segments', []):
            self.segs[s['seg']] = {
                'branch': s.get('branch'), 'na': s.get('na'), 'nb': s.get('nb'),
                'length': float(s.get('length', 0)), 'dia': float(s.get('dia', 0)),
                'stub': bool(s.get('stub', False)),  # §十八：退化短管标记
            }
        for b in self.raw.get('branches', []):
            key = b.get('key') or b.get('occ')
            pieces = []
            for sg in b.get('segs', []) or []:
                if sg in self.segs:
                    s = self.segs[sg]
                    pieces.append({'seg': sg, 'na': s['na'], 'nb': s['nb'],
                                   'length': s['length'], 'dia': s['dia'],
                                   'stub': s.get('stub', False)})
            if not pieces:
                # 无 segs 列表的分支：整根当一段（端点 node0/node1）
                pieces.append({'seg': key, 'na': b.get('node0'), 'nb': b.get('node1'),
                               'length': float(b.get('length', 0)),
                               'dia': float(b.get('dia', 0))})
            self.branches[key] = {
                'length': float(b.get('length', 0)), 'dia': float(b.get('dia', 0)),
                'node0': b.get('node0'), 'node1': b.get('node1'),
                'pieces': pieces,
            }
        self.dropped_branches = []   # §二十二 drop_branches() 删掉的分支 key（按原顺序）
        self._build_indices()

    def _build_indices(self):
        """节点->分支、分支邻接索引（__init__ 与 drop_branches() 共用，
        抽出来保证两处建的索引完全一致）。"""
        # 节点 -> 分支
        self.node_branches = defaultdict(set)
        for key, b in self.branches.items():
            for pc in b['pieces']:
                self.node_branches[pc['na']].add(key)
                self.node_branches[pc['nb']].add(key)
        # 分支邻接（共享任一节点）
        self.branch_adj = defaultdict(set)
        for n, ks in self.node_branches.items():
            ks = list(ks)
            for i in range(len(ks)):
                for j in range(i+1, len(ks)):
                    self.branch_adj[ks[i]].add(ks[j])
                    self.branch_adj[ks[j]].add(ks[i])

    def drop_branches(self, keys):
        """§二十二：删掉指定分支（过孔零件等非路径件）及只属于它们的线段
        与节点，并重建索引。返回实际删掉的分支 key 列表（按拓扑原顺序；
        清单里没有的分支静默跳过）。拓扑文件本身不动，只改内存里的对象；
        被删记录在 self.dropped_branches，供布局 meta 与清单引用。"""
        drop = [k for k in self.branches if k in keys]
        if not drop:
            self.dropped_branches = []
            return []
        drop_set = set(drop)
        drop_segs = {sg for sg, s in self.segs.items()
                     if s['branch'] in drop_set}
        keep_nodes = set()
        for k, b in self.branches.items():
            if k in drop_set:
                continue
            for pc in b['pieces']:
                keep_nodes.add(pc['na'])
                keep_nodes.add(pc['nb'])
        drop_nodes = {c for c in self.nodes if c not in keep_nodes}
        for k in drop:
            del self.branches[k]
        for sg in drop_segs:
            del self.segs[sg]
        for c in drop_nodes:
            del self.nodes[c]
        # raw 同步（下游不读 raw，但对象内不留残留）
        self.raw['branches'] = [
            b for b in self.raw.get('branches', [])
            if (b.get('key') or b.get('occ')) not in drop_set]
        self.raw['segments'] = [
            s for s in self.raw.get('segments', [])
            if s.get('seg') not in drop_segs]
        self.raw['nodes'] = [
            n for n in self.raw.get('nodes', [])
            if n.get('code') not in drop_nodes]
        self._build_indices()
        self.dropped_branches = drop
        return drop

    def branch_nodes(self, key):
        """分支上的关节节点（node0→node1 顺序，去重保序）。"""
        b = self.branches[key]
        joints = [b['pieces'][0]['na']] + [pc['nb'] for pc in b['pieces']]
        return joints

    def components(self):
        """分支图的连通分量（按分量内最长分支长度降序）。"""
        seen, comps = set(), []
        for k in self.branches:
            if k in seen:
                continue
            q = deque([k]); seen.add(k); comp = []
            while q:
                x = q.popleft(); comp.append(x)
                for y in sorted(self.branch_adj[x]):
                    if y not in seen:
                        seen.add(y); q.append(y)
            comps.append(sorted(comp))
        comps.sort(key=lambda c: (-max(self.branches[k]['length'] for k in c),
                                  c[0]))
        return comps

    def find_cycles(self, comp_keys):
        """在节点-线段图上找环（生成树 + 非树边），分类：
        - 自环：线段 na==nb
        - 平行对：两条线段同起止节点
        - 真环：>=3 个不同节点的环
        返回 (rings, self_loops, parallel_pairs)；rings 为线段列表的列表。"""
        comp = set(comp_keys)
        segset = [sg for sg, s in self.segs.items() if s['branch'] in comp]
        adj = defaultdict(list)
        for sg in segset:
            s = self.segs[sg]
            if s['na'] == s['nb']:
                continue  # 自环不进邻接表，单独处理
            adj[s['na']].append((s['nb'], sg))
            adj[s['nb']].append((s['na'], sg))
        parent, parent_seg, depth = {}, {}, {}
        for start in adj:
            if start in depth:
                continue
            stack = [(start, None, None, 0)]
            while stack:
                u, p, ps, d = stack.pop()
                if u in depth:
                    continue
                parent[u] = p; parent_seg[u] = ps; depth[u] = d
                for v, sg in adj[u]:
                    if v not in depth:
                        stack.append((v, u, sg, d+1))
        tree_segs = set(s for s in parent_seg.values() if s)
        self_loops = [sg for sg in segset if self.segs[sg]['na'] == self.segs[sg]['nb']]
        rings, parallel_pairs = [], []
        for sg in segset:
            if sg in tree_segs or sg in self_loops:
                continue
            s = self.segs[sg]
            a, b = s['na'], s['nb']
            # 树上路径 a→b
            def path_to_root(x):
                p = []
                while x is not None:
                    p.append(x); x = parent.get(x)
                return p
            pa, pb = path_to_root(a), path_to_root(b)
            sa = set(pa)
            lca = next((x for x in pb if x in sa), None)
            if lca is None:
                continue
            path_segs = []
            x = a
            while x != lca:
                path_segs.append(parent_seg[x]); x = parent[x]
            x = b
            while x != lca:
                path_segs.append(parent_seg[x]); x = parent[x]
            cyc_segs = [sg] + path_segs
            cyc_nodes = set()
            for cs in cyc_segs:
                cyc_nodes.add(self.segs[cs]['na']); cyc_nodes.add(self.segs[cs]['nb'])
            if len(path_segs) == 1 and len(cyc_nodes) == 2:
                parallel_pairs.append((sg, path_segs[0]))
            elif len(cyc_nodes) >= 3:
                rings.append(cyc_segs)
        return rings, self_loops, parallel_pairs

# ---------------------------------------------------------------- 布局引擎

class Layout:
    """v3 展开布局：剥离顺序 + 角度规则 + 干涉拐弯 + 环/自环/平行特殊处理。"""

    def __init__(self, topo, clearance=CLEARANCE_DEFAULT):
        self.topo = topo
        self.clearance = clearance
        self.node_pos = {}          # code -> (x, y)
        self.node_parent_dir = {}   # code -> 到达该节点的线段方向（度，指向节点）
        self.node_children = defaultdict(list)  # code -> 从该节点锚定画出的分支
        self.placed = {}            # branch -> {points, pieces{seg:(p1,p2)}, bends, joint_pos}
        self.placed_pieces = []     # (p1, p2, branch, seg, skip_dist)
        self.piece_pos = {}         # seg -> (p1, p2)（含环预置线段）
        self.warnings = []          # 字符串
        self.bends = []             # {branch, seg, at, delta}
        self.length_errors = []     # {branch, seg, err_mm}
        self.rings_drawn = []       # {segs, nodes}
        self.parallel_sib = defaultdict(list)  # seg -> 平行兄弟 seg 列表
        self.self_loop_segs = set()
        self.cycle_info = {}        # 分量 -> {rings, self_loops, parallel_pairs}
        self.comp_boxes = []        # [(xmin, ymin, xmax, ymax)]

    # ---- 干涉检查 ----

    def piece_conflicts(self, p1, p2, extra_pieces, skip_dist=False):
        """候选线段是否与已画线段干涉。extra_pieces 为本分支试算中已 laid 的段。"""
        for (q1, q2, _b, _s, sd) in self.placed_pieces:
            if pieces_interfere(p1, p2, q1, q2, self.clearance,
                                skip_dist=(skip_dist or sd)):
                return True
        for (q1, q2, sd) in extra_pieces:
            if pieces_interfere(p1, p2, q1, q2, self.clearance,
                                skip_dist=(skip_dist or sd)):
                return True
        return False

    def piece_overlaps(self, p1, p2, extra_pieces):
        """候选线段是否与已画线段共线重叠（压着画，v2 明文禁止）。"""
        for (q1, q2, _b, _s, _sd) in self.placed_pieces:
            if seg_collinear_overlap(p1, p2, q1, q2):
                return True
        for (q1, q2, _sd) in extra_pieces:
            if seg_collinear_overlap(p1, p2, q1, q2):
                return True
        return False

    # ---- 基础图形：三角形自环、折线段 ----

    def triangle_loop(self, p, direction_deg, length):
        """等边三角形小环：从 p 出发、回到 p，周长 = length。
        返回子线段点列 [p, p1, p2, p]。"""
        s = length / 3.0
        p1 = add_pt(p, unit_from_angle(direction_deg), s)
        p2 = add_pt(p1, unit_from_angle(direction_deg + 120.0), s)
        return [p, p1, p2, p]

    def _tick_best(self, p, base_angle, length, check_subs):
        """§十八：退化短管画直线短线头（不是环）。24 朝向 15° 步进试选，
        取干涉最少者；平局取先试到的（确定性）。返回 ([p, far], bad)。"""
        best, bad = None, None
        for k in range(24):
            far = add_pt(p, unit_from_angle(base_angle + 15.0 * k), length)
            b = check_subs([(p, far)], skip_dist=True)
            if bad is None or b < bad:
                best, bad = [p, far], b
                if b == 0:
                    break
        return best, bad

    def kink_points(self, a, b, length, side=1):
        """A→B 两点间、总长 length 的单折点：返回 [a, kink, b]。
        length >= |AB| 时成立；side=+1 折点在前进方向左侧，-1 在右侧。"""
        d = dist(a, b)
        if length <= d + 1e-9:
            return [a, b]
        mx, my = (a[0]+b[0])/2.0, (a[1]+b[1])/2.0
        half = length / 2.0
        h = math.sqrt(max(0.0, half*half - (d/2.0)**2))
        base = math.radians(angle_of(a, b) + 90.0*side)
        return [a, (mx + math.cos(base)*h, my + math.sin(base)*h), b]

    # ---- 环形：圆上弦多边形 ----

    def ring_polygon(self, lengths):
        """给定各边长，解圆半径 R 使弦多边形闭合，返回顶点（质心在原点）。
        若最长边 >= 其余边之和则无法闭合，返回 None。"""
        if max(lengths) >= sum(lengths) - max(lengths):
            return None
        lo = max(lengths) / 2.0 * 1.000001
        hi = 1e7
        for _ in range(200):
            mid = (lo + hi) / 2.0
            s = sum(2.0*math.asin(min(1.0, L/(2.0*mid))) for L in lengths)
            if s > 2.0*math.pi:
                lo = mid
            else:
                hi = mid
        R = (lo + hi) / 2.0
        pts, ang = [], 0.0
        for L in lengths:
            pts.append((R*math.cos(ang), R*math.sin(ang)))
            ang += 2.0*math.asin(L/(2.0*R))
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        return [(p[0]-cx, p[1]-cy) for p in pts]

    def place_ring(self, ring_segs, origin):
        """把一个真环画成闭合多边形（不剪口）。ring_segs 须已按环顺序排列。"""
        # 环线段排序：沿 na/nb 链式排列
        segs = self.topo.segs
        ordered = [ring_segs[0]]
        used = {ring_segs[0]}
        cur = segs[ring_segs[0]]['nb']
        while len(ordered) < len(ring_segs):
            nxt = None
            for sg in ring_segs:
                if sg in used:
                    continue
                if segs[sg]['na'] == cur:
                    nxt = sg; cur = segs[sg]['nb']; break
                if segs[sg]['nb'] == cur:
                    nxt = sg; cur = segs[sg]['na']; break
            if nxt is None:
                break
            ordered.append(nxt); used.add(nxt)
        lengths = [segs[sg]['length'] for sg in ordered]
        poly = self.ring_polygon(lengths)
        if poly is None:
            self.warnings.append(f"环 {ordered} 最长边过长无法闭合多边形，改走剥离放置")
            return False
        # 顶点对应节点：顶点 i 是 ordered[i] 的起点
        ring_nodes = []
        for i, sg in enumerate(ordered):
            s = segs[sg]
            # 确定该段的起点（链式顺序下是上一段的终点）
            if i == 0:
                start_node = s['na']
            else:
                start_node = ring_nodes[-1][1]  # 上一段的终点
            # 该段的方向：起点 -> 终点
            if s['na'] == start_node:
                end_node = s['nb']
            else:
                end_node = s['na']
            ring_nodes.append((start_node, end_node))
        ox, oy = origin
        for i, sg in enumerate(ordered):
            p1 = (poly[i][0]+ox, poly[i][1]+oy)
            p2 = (poly[(i+1) % len(poly)][0]+ox, poly[(i+1) % len(poly)][1]+oy)
            n1, n2 = ring_nodes[i]
            self.node_pos[n1] = p1
            self.node_pos[n2] = p2
            self.node_parent_dir[n2] = angle_of(p1, p2)
            self.piece_pos[sg] = (p1, p2)
            self.placed_pieces.append((p1, p2, segs[sg]['branch'], sg, False))
        self.node_parent_dir[ring_nodes[0][0]] = angle_of(
            (poly[-1][0]+ox, poly[-1][1]+oy), (poly[0][0]+ox, poly[0][1]+oy))
        self.rings_drawn.append({'segs': ordered,
                                 'nodes': [n for n, _ in ring_nodes]})
        return True

    # ---- 分支试算 ----

    def _joints(self, key):
        return self.topo.branch_nodes(key)

    def layout_branch(self, key, run_angles):
        """试算一个分支的布局（不提交全局状态）。
        run_angles: {关节下标: 该自由延伸段的起始角度}。
        返回 dict(points, pieces{seg:(p1,p2)}, joint_pos{idx:(x,y)},
                  bends, warnings, n_bad)；失败返回 None。"""
        topo = self.topo
        b = topo.branches[key]
        pieces = b['pieces']
        joints = self._joints(key)
        n = len(pieces)
        placed_j = [i for i in range(n+1) if joints[i] in self.node_pos]
        if not placed_j:
            return None
        joint_pos = {i: self.node_pos[joints[i]] for i in placed_j}
        seg_pts = {}    # seg -> 该段的 2D 点列
        bends, warnings = [], []
        n_bad = 0
        trial_subs = []  # 本次试算中已 laid 的子段 [(p1, p2, skip_dist)]

        def check_subs(subs, skip_dist=False):
            """检查一组子线段是否干涉（对已提交段 + 本次试算已 laid 段）。
            权重：共线重叠（压着画，v2 明文禁止）计 10，交叉/过近计 1，
            让算法优先避开压着画，宁可多一次 X 交叉（v2 允许）。"""
            bad = 0
            for (q1, q2) in subs:
                if self.piece_overlaps(q1, q2, trial_subs):
                    bad += 10
                elif self.piece_conflicts(q1, q2, trial_subs, skip_dist=skip_dist):
                    bad += 1
            return bad

        def accept_subs(subs, skip_dist=False):
            for (q1, q2) in subs:
                trial_subs.append((q1, q2, skip_dist))

        def lay_constrained(i0, i1):
            """关节 i0→i1 之间的线段（两端关节已定），返回该段的点列与关节位置。
            含自环段时：自环画三角形，其余段组成 A→B 路径。"""
            nonlocal n_bad
            A, B = joint_pos[i0], joint_pos[i1]
            run = pieces[i0:i1]
            loops = [pc for pc in run if pc['na'] == pc['nb']]
            straights = [pc for pc in run if pc['na'] != pc['nb']]
            d = dist(A, B)
            L = sum(pc['length'] for pc in straights)
            # 路径点列（不含自环三角）
            if not straights:
                path = [A, B]  # 只有自环段：A==B，路径退化
            elif L <= d + 1e-9:
                if L < d - 0.01:
                    # 长度不够：拉直并记误差
                    self.length_errors.append({'branch': key, 'seg': run[0]['seg'],
                                               'err_mm': round(d - L, 2)})
                    warnings.append(f"{key} 受约束段长度 {L:.1f} < 两端距离 {d:.1f}，"
                                    f"拉直误差 {d-L:.1f}mm")
                    n_bad += 1
                path = [A, B]
            else:
                path = self.kink_points(A, B, L)
                bends.append({'branch': key, 'seg': run[0]['seg'],
                              'at': joints[i0], 'delta': 'kink',
                              'note': f'受约束段 {L:.1f}>{d:.1f} 中部打折'})
            # 沿路径按弧长定关节位置
            # 路径弧长与各段累积长度的对应
            cum = [0.0]
            for pc in run:
                if pc['na'] != pc['nb']:
                    cum.append(cum[-1] + pc['length'])
            total = cum[-1] if cum[-1] > 0 else 1.0
            # 路径各子段长度
            path_lens = [dist(path[k], path[k+1]) for k in range(len(path)-1)]
            path_total = sum(path_lens) or 1.0

            def point_at(s):
                """沿路径走 s（按比例换算到路径总长）处的点。"""
                target = s / total * path_total
                acc = 0.0
                for k in range(len(path)-1):
                    if acc + path_lens[k] >= target - 1e-9:
                        t = 0.0 if path_lens[k] < 1e-9 else (target-acc)/path_lens[k]
                        t = max(0.0, min(1.0, t))
                        return (path[k][0] + t*(path[k+1][0]-path[k][0]),
                                path[k][1] + t*(path[k+1][1]-path[k][1]))
                    acc += path_lens[k]
                return path[-1]

            # 各关节位置与各段点列
            pts_out = [A]
            s_acc = 0.0
            for idx, pc in enumerate(run):
                j = i0 + idx  # 该段起点关节下标
                if pc['na'] == pc['nb']:
                    # §十八：退化短管画直线短线头（不是环）；真环画小三角
                    jp = joint_pos.get(j)
                    if jp is None:
                        jp = point_at(s_acc)
                        joint_pos[j] = jp
                    tang = angle_of(path[0], path[-1])
                    if pc.get('stub'):
                        tick, bad = self._tick_best(
                            jp, tang, pc['length'], check_subs)
                        seg_pts[pc['seg']] = tick
                        pts_out += tick[1:]
                        joint_pos[j+1] = jp
                        continue
                    tri, bad = None, None
                    for k in range(24):
                        t = self.triangle_loop(jp, tang + 15.0*k, pc['length'])
                        s = [(t[m], t[m+1]) for m in range(3)]
                        b = check_subs(s, skip_dist=True)
                        if bad is None or b < bad:
                            tri, bad = t, b
                            if b == 0:
                                break
                    seg_pts[pc['seg']] = tri
                    pts_out += tri[1:]
                    joint_pos[j+1] = jp
                else:
                    p_start = joint_pos.get(j)
                    if p_start is None:
                        p_start = point_at(s_acc)
                        joint_pos[j] = p_start
                    s_acc += pc['length']
                    p_end = B if j+1 == i1 else point_at(s_acc)
                    joint_pos[j+1] = p_end
                    # 该段在路径上的子点列：取路径上 p_start→p_end 之间的点
                    seg_pts[pc['seg']] = self._subpath(path, p_start, p_end)
                    pts_out += seg_pts[pc['seg']][1:]
            # 干涉检查（受约束段无法改角，只能记警告）
            for pc in run:
                pts = seg_pts[pc['seg']]
                subs = [(pts[k], pts[k+1]) for k in range(len(pts)-1)]
                sd = (pc['na'] == pc['nb'])
                bad = check_subs(subs, skip_dist=sd)
                accept_subs(subs, skip_dist=sd)
                n_bad += bad
                if bad:
                    warnings.append(f"{key}/{pc['seg']} 受约束段与已画线干涉 {bad} 处")
            return pts_out

        def lay_free(anchor_j, direction, base_angle):
            """从锚点关节向 direction（+1 朝 node1 / -1 朝 node0）自由延伸。
            返回该方向的点列（从锚点向外）。"""
            nonlocal n_bad
            pts_out = [joint_pos[anchor_j]]
            cur = joint_pos[anchor_j]
            ang = base_angle
            rng = range(anchor_j, n) if direction > 0 else range(anchor_j-1, -1, -1)
            for i in rng:
                pc = pieces[i]
                j_next = i+1 if direction > 0 else i
                if pc['na'] == pc['nb']:
                    # §十八：退化短管画直线短线头（不是环）；真环画小三角
                    if pc.get('stub'):
                        tick, bad = self._tick_best(
                            cur, ang, pc['length'], check_subs)
                        seg_pts[pc['seg']] = tick if direction > 0 \
                            else tick[::-1]
                        accept_subs([(tick[0], tick[1])], skip_dist=True)
                        if bad:
                            n_bad += bad
                            warnings.append(
                                f"{key}/{pc['seg']} 短线头与已画线干涉")
                        pts_out += tick[1:]
                        joint_pos[j_next] = cur
                        continue
                    # 自环三角：试 24 个朝向（15° 步进），取干涉最少的
                    tri, bad = None, None
                    for k in range(24):
                        t = self.triangle_loop(cur, ang + 15.0*k, pc['length'])
                        s = [(t[m], t[m+1]) for m in range(3)]
                        b = check_subs(s, skip_dist=True)
                        if bad is None or b < bad:
                            tri, bad = t, b
                            if b == 0:
                                break
                    # 按 node0→node1 规范顺序存（后向段需反转）
                    seg_pts[pc['seg']] = tri if direction > 0 else tri[::-1]
                    subs = [(tri[m], tri[m+1]) for m in range(3)]
                    accept_subs(subs, skip_dist=True)
                    if bad:
                        n_bad += bad
                        warnings.append(f"{key}/{pc['seg']} 自环三角与已画线干涉")
                    pts_out += tri[1:]
                    joint_pos[j_next] = cur
                    continue
                # 平行预折：远端关节未定、且有更短的未放置平行兄弟时，弦长取较短者
                chord = None
                for sib in self.parallel_sib.get(pc['seg'], []):
                    if sib in self.piece_pos:
                        continue
                    sl = self.topo.segs[sib]['length']
                    if sl < pc['length'] - 1e-9:
                        chord = sl if chord is None else min(chord, sl)
                # 逐段试放：1) 直行+关节拐弯 2) 有弦长约束时打折两侧都试
                #    3) 中部打折（无弦长约束时，单段分支的拐弯办法）
                placed_seg = False
                bend_deltas = [0.0] + [d for pair in
                                       zip([BEND_STEP*k for k in range(1, int(BEND_MAX/BEND_STEP)+1)],
                                           [-BEND_STEP*k for k in range(1, int(BEND_MAX/BEND_STEP)+1)])
                                       for d in pair]
                cands = []  # (end, subs, new_ang, bend_info)
                for delta in bend_deltas:
                    a2 = ang + delta
                    if chord is None:
                        end = add_pt(cur, unit_from_angle(a2), pc['length'])
                        cands.append((end, [(cur, end)], a2, ('joint', delta)))
                    else:
                        end = add_pt(cur, unit_from_angle(a2), chord)
                        for side in (1, -1):
                            kp = self.kink_points(cur, end, pc['length'], side)
                            cands.append((end, [(kp[0], kp[1]), (kp[1], kp[2])],
                                          a2, ('kink', delta, side)))
                if chord is None:
                    for frac in (0.5, 0.33, 0.67):
                        for kd in (10.0, -10.0, 20.0, -20.0, 30.0, -30.0):
                            pm = add_pt(cur, unit_from_angle(ang),
                                        pc['length']*frac)
                            end = add_pt(pm, unit_from_angle(ang+kd),
                                         pc['length']*(1-frac))
                            cands.append((end, [(cur, pm), (pm, end)], ang+kd,
                                          ('midkink', kd, frac)))
                best_cand, best_bad = None, None
                for (end, subs, new_ang, info) in cands:
                    bad = check_subs(subs)
                    if best_bad is None or bad < best_bad:
                        best_cand, best_bad = (end, subs, new_ang, info), bad
                    if bad == 0:
                        pts = [subs[0][0]] + [s[1] for s in subs]
                        # 按 node0→node1 规范顺序存（后向段需反转）
                        seg_pts[pc['seg']] = pts if direction > 0 else pts[::-1]
                        accept_subs(subs)
                        pts_out += [s[1] for s in subs]
                        if chord is not None:
                            bends.append({'branch': key, 'seg': pc['seg'],
                                          'at': joints[anchor_j], 'delta': 'kink',
                                          'note': f'平行预折：弦 {chord:.1f} < 段长 {pc["length"]:.1f}'})
                        if info[0] == 'joint' and abs(info[1]) > 1e-9:
                            bends.append({'branch': key, 'seg': pc['seg'],
                                          'at': joints[j_next] if direction > 0 else joints[anchor_j],
                                          'delta': info[1], 'note': '干涉拐弯'})
                        elif info[0] == 'midkink':
                            bends.append({'branch': key, 'seg': pc['seg'],
                                          'at': joints[j_next] if direction > 0 else joints[anchor_j],
                                          'delta': info[1],
                                          'note': f'中部打折（{info[2]*100:.0f}%处）'})
                        ang = new_ang
                        joint_pos[j_next] = end
                        cur = end
                        placed_seg = True
                        break
                if not placed_seg:
                    # 兜底：取干涉最少的候选（加权分，共线重叠计 10），而非直行基准角
                    (end, subs, new_ang, info) = best_cand
                    if chord is not None and info[0] == 'kink':
                        bends.append({'branch': key, 'seg': pc['seg'],
                                      'at': joints[anchor_j], 'delta': 'kink',
                                      'note': f'平行预折（兜底）：弦 {chord:.1f} < 段长 {pc["length"]:.1f}'})
                    if info[0] == 'joint' and abs(info[1]) > 1e-9:
                        bends.append({'branch': key, 'seg': pc['seg'],
                                      'at': joints[j_next] if direction > 0 else joints[anchor_j],
                                      'delta': info[1], 'note': '干涉拐弯（兜底取最少干涉）'})
                    elif info[0] == 'midkink':
                        bends.append({'branch': key, 'seg': pc['seg'],
                                      'at': joints[j_next] if direction > 0 else joints[anchor_j],
                                      'delta': info[1],
                                      'note': f'中部打折（{info[2]*100:.0f}%处，兜底）'})
                    pts = [subs[0][0]] + [s[1] for s in subs]
                    seg_pts[pc['seg']] = pts if direction > 0 else pts[::-1]
                    accept_subs(subs)
                    pts_out += [s[1] for s in subs]
                    joint_pos[j_next] = end
                    cur = end
                    ang = new_ang
                    n_bad += best_bad
                    warnings.append(f"{key}/{pc['seg']} 试放全部干涉，兜底取最少干涉方案")
            return pts_out

        # ---- 组装：受约束段 + 自由延伸段 ----
        first_p, last_p = placed_j[0], placed_j[-1]
        # 受约束段（相邻已放置关节之间）
        for a, b_ in zip(placed_j, placed_j[1:]):
            if b_ > a:
                lay_constrained(a, b_)
        # 自由延伸段
        if first_p > 0:
            ang = run_angles.get(first_p, 90.0)
            lay_free(first_p, -1, ang + 180.0)
        if last_p < n:
            ang = run_angles.get(last_p, 90.0)
            lay_free(last_p, +1, ang)
        # 特殊情况：整根分支只有一个已放置关节且在中间——两自由段共线
        # （上面已处理：后向段角度 = 前向角 + 180°，同一条直线）

        # 组装整根点列（按关节顺序）
        points = []
        for i, pc in enumerate(pieces):
            pts = seg_pts.get(pc['seg'])
            if pts is None:
                return None
            if not points:
                points += pts
            else:
                points += pts[1:]
        if len(points) < 2:
            return None
        return {'points': points, 'pieces': {sg: (pts[0], pts[-1])
                                             for sg, pts in seg_pts.items()},
                'seg_pts': seg_pts, 'joint_pos': dict(joint_pos),
                'bends': bends, 'warnings': warnings, 'n_bad': n_bad}

    def _subpath(self, path, p_start, p_end):
        """取折线 path 上 p_start→p_end 之间的子点列（含两端与中间拐点）。"""
        # 在路径上定位两点（按最近点投影）
        def locate(p):
            best, bestd = 0.0, 1e18
            acc = 0.0
            for k in range(len(path)-1):
                d = pt_seg_dist(p, path[k], path[k+1])
                if d < bestd:
                    bestd = d
                    # 沿路径弧长
                    dx, dy = path[k+1][0]-path[k][0], path[k+1][1]-path[k][1]
                    L2 = dx*dx+dy*dy
                    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0,
                        ((p[0]-path[k][0])*dx + (p[1]-path[k][1])*dy)/L2))
                    best = acc + t*math.sqrt(L2)
                acc += dist(path[k], path[k+1])
            return best
        s0, s1 = locate(p_start), locate(p_end)
        if s1 < s0:
            s0, s1 = s1, s0
        out = [p_start]
        acc = 0.0
        for k in range(len(path)-1):
            L = dist(path[k], path[k+1])
            if s0 < acc + L - 1e-9 and acc < s1 - 1e-9:
                if acc + L > s0 + 1e-9 and acc + L < s1 - 1e-9:
                    out.append(path[k+1])
            acc += L
        out.append(p_end)
        # 去重连续重复点
        ded = [out[0]]
        for p in out[1:]:
            if not pt_eq(p, ded[-1]):
                ded.append(p)
        return ded

    # ---- 分支放置（候选试算 + 提交） ----

    def _free_runs(self, key):
        """返回自由延伸段列表 [(锚点关节下标, 方向)]。"""
        joints = self._joints(key)
        n = len(self.topo.branches[key]['pieces'])
        placed_j = [i for i in range(n+1) if joints[i] in self.node_pos]
        if not placed_j:
            return []
        runs = []
        if placed_j[0] > 0:
            runs.append((placed_j[0], -1))
        if placed_j[-1] < n:
            runs.append((placed_j[-1], +1))
        return runs

    def _base_angle(self, node):
        """某节点上新分支的基准角：父方向 + 90° + 同点偏移。"""
        k = len(self.node_children[node])
        off = ANGLE_OFFSETS[min(k, len(ANGLE_OFFSETS)-1)]
        return self.node_parent_dir.get(node, 0.0) + 90.0 + off

    def place_branch_best(self, key):
        """试算多个候选角度，选干涉最少的提交；都不行也兜底放置。
        候选优先级：规则角度（90°/60°/…+翻转）→ 全圆扫掠（15°步进，找干净方向）。"""
        runs = self._free_runs(key)
        joints = self._joints(key)
        if not runs:
            # 全段受约束（两端都已定）：直接试算
            res = self.layout_branch(key, {})
            if res is not None:
                self._commit(key, res)
                return True
            return False
        # 各自由段的规则角度选项
        opts = []
        for (j, d) in runs:
            base = self._base_angle(joints[j])
            opts.append([base, base+180.0, base+30.0, base-30.0,
                         base+60.0, base-60.0])
        same_anchor = len(runs) == 2 and runs[0][0] == runs[1][0]
        combos = []
        if same_anchor or len(runs) == 1:
            for a0 in opts[0]:
                combos.append({runs[0][0]: a0})
        else:
            for a0 in opts[0][:3]:
                for a1 in opts[1][:3]:
                    combos.append({runs[0][0]: a0, runs[1][0]: a1})
        best, best_score = None, None

        def score_of(res):
            return (res['n_bad'], len(res['warnings']),
                    sum(abs(b['delta']) for b in res['bends']
                        if isinstance(b['delta'], (int, float))))

        for angles in combos:
            res = self.layout_branch(key, angles)
            if res is None:
                continue
            sc = score_of(res)
            if best_score is None or sc < best_score:
                best, best_score = res, sc
                if sc[0] == 0 and sc[1] == 0:
                    break
        if best is None:
            return False
        if best_score[0] > 0:
            self.warnings.append(f"{key} 所有候选角度均有干涉，取最少干涉方案")
        self._commit(key, best)
        return True

    def _commit(self, key, res):
        """把试算结果写入全局状态。"""
        joints = self._joints(key)
        b = self.topo.branches[key]
        # 先算自由段锚点（用提交前的 node_pos 状态，用于同点子分支计数）
        free_anchors = self._free_runs(key)
        for idx, pos in res['joint_pos'].items():
            node = joints[idx]
            if node not in self.node_pos:
                self.node_pos[node] = pos
                # 到达方向：该关节相邻段的方向（指向该关节）
                if idx > 0:
                    p_prev = res['joint_pos'].get(idx-1)
                    if p_prev is not None and not pt_eq(p_prev, pos):
                        self.node_parent_dir[node] = angle_of(p_prev, pos)
                elif idx < len(b['pieces']):
                    p_next = res['joint_pos'].get(idx+1)
                    if p_next is not None and not pt_eq(p_next, pos):
                        self.node_parent_dir[node] = angle_of(pos, p_next) + 180.0
        for sg, (p1, p2) in res['pieces'].items():
            self.piece_pos[sg] = (p1, p2)
        for sg, pts in res['seg_pts'].items():
            for k in range(len(pts)-1):
                skip = (self.topo.segs[sg]['na'] == self.topo.segs[sg]['nb'])
                self.placed_pieces.append((pts[k], pts[k+1], key, sg, skip))
        for (j, _d) in free_anchors:
            node = joints[j]
            if key not in self.node_children[node]:
                self.node_children[node].append(key)
        self.placed[key] = res
        self.bends.extend(res['bends'])
        self.warnings.extend(res['warnings'])

    # ---- 主干 / 分量 / 整体 ----

    def next_origin(self):
        """下一个主干/分量的起点（当前包围盒右侧 + 间隙）。"""
        if not self.node_pos:
            return (0.0, 0.0)
        xs = [p[0] for p in self.node_pos.values()]
        return (max(xs) + COMP_GAP, 0.0)

    def place_trunk(self, key, origin):
        """最长分支水平放置为主干。"""
        joints = self._joints(key)
        self.node_pos[joints[0]] = origin
        self.node_parent_dir[joints[0]] = 0.0
        res = self.layout_branch(key, {0: 0.0})
        if res is None:
            self.warnings.append(f"主干 {key} 试算失败")
            return False
        self._commit(key, res)
        return True

    def layout_component(self, comp_keys, origin):
        """一个连通分量的展开：先环后剥离。"""
        comp = set(comp_keys)
        rings, self_loops, parallels = self.topo.find_cycles(comp_keys)
        self.cycle_info[len(self.cycle_info)] = {'rings': rings, 'self_loops': self_loops,
                                                 'parallel_pairs': parallels}
        for sg in self_loops:
            self.self_loop_segs.add(sg)
        for (a, b_) in parallels:
            self.parallel_sib[a].append(b_)
            self.parallel_sib[b_].append(a)
        started = False
        if rings:
            # 画最大的真环（其余环由剥离时的受约束段处理）
            ring = max(rings, key=len)
            if self.place_ring(ring, origin):
                started = True
            if len(rings) > 1:
                self.warnings.append(f"本分量有 {len(rings)} 个真环，只单独画了最大的"
                                     f"（{len(ring)} 段），其余由剥离处理")
        if not started:
            trunk = sorted(comp_keys,
                           key=lambda k: (-self.topo.branches[k]['length'], k))[0]
            self.place_trunk(trunk, origin)
        # 剥离：反复取"已有已放置节点的最长未放置分支"
        remaining = set(comp_keys) - set(self.placed)
        guard = 0
        while remaining:
            guard += 1
            if guard > len(comp_keys) + 10:
                self.warnings.append("剥离循环保护触发，剩余分支强制放置")
                break
            cands = [k for k in remaining
                     if any(n in self.node_pos for n in self._joints(k))]
            if not cands:
                # 无可连接分支（不应发生）：取最长者另起主干
                k = sorted(remaining,
                           key=lambda kk: (-self.topo.branches[kk]['length'], kk))[0]
                self.warnings.append(f"{k} 与已放置部分无连接节点，另起主干放置")
                self.place_trunk(k, self.next_origin())
                remaining.discard(k)
                continue
            k = sorted(cands,
                       key=lambda kk: (-self.topo.branches[kk]['length'], kk))[0]
            if not self.place_branch_best(k):
                self.warnings.append(f"{k} 放置失败，强制另起主干")
                self.place_trunk(k, self.next_origin())
            remaining.discard(k)

    def run(self):
        comps = self.topo.components()
        origin = (0.0, 0.0)
        for comp in comps:
            before = set(self.placed)
            self.layout_component(comp, origin)
            # 本分量包围盒（只计本分量新放置的分支）
            xs, ys = [], []
            for k in set(self.placed) - before:
                for (x, y) in self.placed[k]['points']:
                    xs.append(x); ys.append(y)
            if xs:
                self.comp_boxes.append((min(xs), min(ys), max(xs), max(ys)))
                origin = (max(xs) + COMP_GAP, 0.0)
        return self

    # ---- 验证 ----

    def bbox(self):
        xs = [p[0] for p in self.node_pos.values()]
        ys = [p[1] for p in self.node_pos.values()]
        for res in self.placed.values():
            for (x, y) in res['points']:
                xs.append(x); ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys))

    def validate(self):
        """自测：画出数、长度误差、残留干涉。返回 stats 字典。"""
        topo = self.topo
        total_len_3d = sum(b['length'] for b in topo.branches.values())
        len_errs = []
        for key, b in topo.branches.items():
            if key not in self.placed:
                continue
            pts = self.placed[key]['points']
            l2 = sum(dist(pts[i], pts[i+1]) for i in range(len(pts)-1))
            len_errs.append((key, b['length'], l2, l2 - b['length']))
        max_err = max((abs(e[3]) for e in len_errs), default=0.0)
        # 残留干涉复查（全量两两检查）
        left = 0
        pp = self.placed_pieces
        for i in range(len(pp)):
            for j in range(i+1, len(pp)):
                if pp[i][2] == pp[j][2] and pp[i][3] == pp[j][3]:
                    continue  # 同一段的子段
                if pieces_interfere(pp[i][0], pp[i][1], pp[j][0], pp[j][1],
                                    self.clearance,
                                    skip_dist=(pp[i][4] or pp[j][4])):
                    left += 1
        return {
            'branches_total': len(topo.branches),
            'branches_placed': len(self.placed),
            'nodes_total': len(topo.nodes),
            'nodes_placed': len(self.node_pos),
            'total_len_3d': round(total_len_3d, 1),
            'max_len_err_mm': round(max_err, 2),
            'len_errs': [(k, round(a, 1), round(c, 1), round(e, 2))
                         for (k, a, c, e) in len_errs if abs(e) > 0.05],
            'residual_interference_pairs': left,
            'bends': len(self.bends),
            'warnings': len(self.warnings),
            'rings_drawn': len(self.rings_drawn),
            'components': len(self.topo.components()),
            'bbox': [round(v, 1) for v in self.bbox()],
        }

# ---------------------------------------------------------------- 输出

def sanitize_block_name(name):
    return ''.join(c if (c.isalnum() or c == '_') else '_' for c in name)

def arc_midpoint(points):
    """折线按弧长取中点。"""
    total = sum(dist(points[i], points[i+1]) for i in range(len(points)-1))
    if total < 1e-9:
        return points[0]
    acc, target = 0.0, total / 2.0
    for i in range(len(points)-1):
        L = dist(points[i], points[i+1])
        if acc + L >= target - 1e-9:
            t = 0.0 if L < 1e-9 else (target-acc)/L
            t = max(0.0, min(1.0, t))
            return (points[i][0] + t*(points[i+1][0]-points[i][0]),
                    points[i][1] + t*(points[i+1][1]-points[i][1]))
        acc += L
    return points[-1]

def write_dxf(layout, out_path):
    """DXF 输出：每根管子/连接器/卡扣一个 BLOCK，模型空间只放 INSERT。"""
    import ezdxf
    from ezdxf.enums import TextEntityAlignment
    topo = layout.topo
    doc = ezdxf.new('R2010')
    doc.units = ezdxf.units.MM
    doc.layers.add('TUBE', color=5)
    doc.layers.add('CONN', color=1)
    doc.layers.add('CLAMP', color=3)
    doc.layers.add('NODE', color=8)
    doc.layers.add('LABEL', color=7)
    msp = doc.modelspace()

    # --- 管子块 ---
    for key, res in layout.placed.items():
        b = topo.branches[key]
        pts = res['points']
        origin = pts[0]
        rot = angle_of(pts[0], pts[1]) if len(pts) > 1 else 0.0
        # 局部坐标 = 相对 origin 的坐标再转 -rot（2026-11-17 修：原代码只转
        # -rot 未减 origin，局部坐标仍是绝对坐标，INSERT 再加一次 insert
        # 点导致整根管子位移 R(rot)·origin——IP 实测 Body.123 被推出近 1 米；
        # v3/v4 的 DXF 都有此问题，查看器读 layout.json 不受影响）
        local = [(q[0] - origin[0], q[1] - origin[1])
                 for q in (rot_pt(p, -rot, origin) for p in pts)]
        blk_name = sanitize_block_name('TUBE_' + key)
        blk = doc.blocks.new(name=blk_name)
        blk.add_lwpolyline(local, dxfattribs={'layer': 'TUBE'})
        mid = arc_midpoint(local)
        label = f"{key} Φ{b['dia']:.1f} L={b['length']:.1f}"
        # 文字方向补偿：保证插入后文字不倒置
        text_rot = 0.0 if -90.0 < rot <= 90.0 else 180.0
        txt = blk.add_text(label, height=8.0,
                           dxfattribs={'layer': 'LABEL', 'rotation': text_rot})
        txt.set_placement((mid[0], mid[1] + 6), align=TextEntityAlignment.MIDDLE_CENTER)
        msp.add_blockref(blk_name, insert=origin,
                         dxfattribs={'rotation': rot, 'layer': 'TUBE'})

    # --- 连接器 / 卡扣块（每个节点一个） ---
    for code, pos in layout.node_pos.items():
        nd = topo.nodes.get(code, {})
        t = nd.get('type', '?')
        if t == 'connector':
            blk_name = sanitize_block_name('CON_' + code)
            blk = doc.blocks.new(name=blk_name)
            blk.add_circle((0, 0), 8.0, dxfattribs={'layer': 'CONN'})
            txt = blk.add_text(code, height=6.0, dxfattribs={'layer': 'LABEL'})
            txt.set_placement((0, 12), align=TextEntityAlignment.MIDDLE_CENTER)
            msp.add_blockref(blk_name, insert=pos, dxfattribs={'layer': 'CONN'})
        elif t == 'clamp':
            blk_name = sanitize_block_name('CLP_' + code)
            blk = doc.blocks.new(name=blk_name)
            blk.add_circle((0, 0), 5.0, dxfattribs={'layer': 'CLAMP'})
            txt = blk.add_text(code, height=6.0, dxfattribs={'layer': 'LABEL'})
            txt.set_placement((0, 9), align=TextEntityAlignment.MIDDLE_CENTER)
            msp.add_blockref(blk_name, insert=pos, dxfattribs={'layer': 'CLAMP'})
        else:
            # 分叉/接头节点：非设备，直接画圆+编号（不做块）
            msp.add_circle(pos, 3.0, dxfattribs={'layer': 'NODE'})
            txt = msp.add_text(code, height=6.0, dxfattribs={'layer': 'LABEL'})
            txt.set_placement((pos[0]+5, pos[1]+5))
    doc.saveas(out_path)
    return out_path

def write_excel(layout, out_path):
    import openpyxl
    topo = layout.topo
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = '2D管子'
    ws.append(['分支', '起点X', '起点Y', '终点X', '终点Y',
               '3D弧长(mm)', '2D长度(mm)', '误差(mm)', '直径(mm)', '段数', '拐弯数'])
    for key, res in sorted(layout.placed.items()):
        b = topo.branches[key]
        pts = res['points']
        l2 = sum(dist(pts[i], pts[i+1]) for i in range(len(pts)-1))
        nb = sum(1 for bd in res['bends'] if bd['branch'] == key)
        ws.append([key, round(pts[0][0], 2), round(pts[0][1], 2),
                   round(pts[-1][0], 2), round(pts[-1][1], 2),
                   round(b['length'], 1), round(l2, 1), round(l2-b['length'], 2),
                   round(b['dia'], 1), len(b['pieces']), nb])
    ws2 = wb.create_sheet('2D线段')
    ws2.append(['SEG', '分支', '起点节点', '终点节点', '起点X', '起点Y',
                '终点X', '终点Y', '长度(mm)', '直径(mm)'])
    for key, res in sorted(layout.placed.items()):
        for sg, pts in res['seg_pts'].items():
            s = topo.segs[sg]
            ws2.append([sg, key, s['na'], s['nb'],
                        round(pts[0][0], 2), round(pts[0][1], 2),
                        round(pts[-1][0], 2), round(pts[-1][1], 2),
                        round(s['length'], 1), round(s['dia'], 1)])
    ws3 = wb.create_sheet('2D节点')
    ws3.append(['节点', '类型', '实例全名', 'X', 'Y'])
    for code in sorted(layout.node_pos):
        nd = topo.nodes.get(code, {})
        x, y = layout.node_pos[code]
        ws3.append([code, nd.get('type', '?'), nd.get('name_3d', ''),
                    round(x, 2), round(y, 2)])
    ws4 = wb.create_sheet('验证')
    st = layout.validate()
    ws4.append(['项目', '数值'])
    for k, v in st.items():
        if k in ('len_errs',):
            continue
        ws4.append([k, str(v)])
    if st['len_errs']:
        ws4.append([])
        ws4.append(['长度误差>0.05mm 的分支', '3D长', '2D长', '误差'])
        for row in st['len_errs']:
            ws4.append(list(row))
    if layout.bends:
        ws4.append([])
        ws4.append(['拐弯记录', '线段', '位置', '角度', '说明'])
        for bd in layout.bends:
            ws4.append([bd['branch'], bd['seg'], bd['at'], bd['delta'], bd.get('note', '')])
    if layout.warnings:
        ws4.append([])
        ws4.append(['警告'])
        for w in layout.warnings:
            ws4.append([w])
    wb.save(out_path)
    return out_path

def write_layout_json(layout, out_path):
    topo = layout.topo
    data = {
        'meta': {'source': 'unfold_2d_v3.py', 'clearance_mm': layout.clearance},
        'stats': layout.validate(),
        'cycles': {str(k): {'rings': v['rings'], 'self_loops': v['self_loops'],
                            'parallel_pairs': v['parallel_pairs']}
                   for k, v in layout.cycle_info.items()},
        'branches': [],
        'nodes': [],
        'bends': layout.bends,
        'warnings': layout.warnings,
        'length_errors': layout.length_errors,
    }
    for key, res in sorted(layout.placed.items()):
        b = topo.branches[key]
        pts = res['points']
        l2 = sum(dist(pts[i], pts[i+1]) for i in range(len(pts)-1))
        data['branches'].append({
            'key': key, 'dia': round(b['dia'], 2),
            'len_3d': round(b['length'], 1), 'len_2d': round(l2, 1),
            'node0': b['node0'], 'node1': b['node1'],
            'points': [[round(x, 2), round(y, 2)] for (x, y) in pts],
            'pieces': [{'seg': sg, 'na': topo.segs[sg]['na'], 'nb': topo.segs[sg]['nb'],
                        'pts': [[round(x, 2), round(y, 2)] for (x, y) in p]}
                       for sg, p in res['seg_pts'].items()],
        })
    for code in sorted(layout.node_pos):
        nd = topo.nodes.get(code, {})
        x, y = layout.node_pos[code]
        data['nodes'].append({'code': code, 'type': nd.get('type', '?'),
                              'name_3d': nd.get('name_3d', ''),
                              'x': round(x, 2), 'y': round(y, 2)})
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return out_path

# ---------------------------------------------------------------- 主入口

def main():
    ap = argparse.ArgumentParser(description='3D拓扑 → 2D展开图（v3）')
    ap.add_argument('topo_json')
    ap.add_argument('-o', '--out', default='.')
    ap.add_argument('--clearance', type=float, default=CLEARANCE_DEFAULT)
    args = ap.parse_args()

    topo = Topo(args.topo_json)
    print(f"输入：分支 {len(topo.branches)} / 节点 {len(topo.nodes)} / "
          f"线段 {len(topo.segs)}")
    comps = topo.components()
    print(f"连通分量：{len(comps)} 个，规模 {[len(c) for c in comps]}")
    for i, c in enumerate(comps):
        rings, sl, pp = topo.find_cycles(c)
        print(f"  分量{i+1}：真环 {len(rings)} 个，自环线段 {len(sl)} 条，"
              f"平行对 {len(pp)} 对")
        for r in rings:
            print(f"    真环：{len(r)} 段 {r}")
        for (a, b_) in pp:
            sa, sb = topo.segs[a], topo.segs[b_]
            print(f"    平行对：{a}({sa['branch']} {sa['length']:.1f}) / "
                  f"{b_}({sb['branch']} {sb['length']:.1f}) "
                  f"{sa['na']}-{sa['nb']}")
        for sg in sl:
            s = topo.segs[sg]
            print(f"    自环：{sg}({s['branch']} {s['length']:.1f}) @ {s['na']}")

    layout = Layout(topo, clearance=args.clearance).run()
    st = layout.validate()
    print(f"2D分支：{st['branches_placed']} / {st['branches_total']}")
    print(f"2D节点：{st['nodes_placed']} / {st['nodes_total']}")
    print(f"总长 3D：{st['total_len_3d']} mm")
    print(f"最大长度误差：{st['max_len_err_mm']} mm")
    print(f"拐弯：{st['bends']} 次，警告：{st['warnings']} 条，"
          f"残留干涉对数：{st['residual_interference_pairs']}")
    print(f"画环：{st['rings_drawn']} 个")
    bb = st['bbox']
    print(f"图纸尺寸：{bb[2]-bb[0]:.1f} x {bb[3]-bb[1]:.1f} mm "
          f"(x {bb[0]:.1f}~{bb[2]:.1f}, y {bb[1]:.1f}~{bb[3]:.1f})")
    for w in layout.warnings[:20]:
        print(f"  警告：{w}")
    if len(layout.warnings) > 20:
        print(f"  ...还有 {len(layout.warnings)-20} 条警告")

    os.makedirs(args.out, exist_ok=True)
    dxf = write_dxf(layout, os.path.join(args.out, 'unfold_v3.dxf'))
    print(f"DXF: {dxf}")
    xlsx = write_excel(layout, os.path.join(args.out, 'unfold_v3.xlsx'))
    print(f"Excel: {xlsx}")
    js = write_layout_json(layout, os.path.join(args.out, 'layout.json'))
    print(f"layout.json: {js}")

    if st['branches_placed'] < st['branches_total']:
        print('错误：有分支未画出')
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
