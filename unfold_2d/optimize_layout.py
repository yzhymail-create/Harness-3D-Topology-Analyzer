#!/usr/bin/env python3
"""布局零交叉优化器（v6p1 后处理，不改 v6p1）。

用法：
    python3 optimize_layout.py <layout.json> -o <out_layout.json>
        [--angle-max 45] [--angle-step 5] [--pierce-mm 15]
        [--report <report.json>]

设计（2026-11-18 用户定）：
- 检查先定义好：交叉 / 压着画（共线重叠）/ 穿节点三项硬检查，目标 0；
  间距 <5mm 只报数；长度 1:1 与居中（H1）每次调完重验，居中不许变差。
  穿节点 = 管子离它不连接的节点太近（默认 15mm），与交叉同等处理；
  “不连接”按拓扑判（分支的 pieces 碰到的节点都算连接，见 Checker）。
  节点挨近（默认 20mm，不连同一根管子的两节点）只报告、不计硬问题。
- 主干先定，检查调整按分支层级：0 级主干冻结；自上而下一次调一级，
  调好就冻结，下一级只拿已冻结的当障碍物。单调不恶化。
- 角度 5 度一档：默认当前角度；有干涉时按 +5、-5、+10、-10……转，
  取（硬问题，偏离，节点挨近）字典序最小的；角度搜不到干净的再试换边（镜像）。
  节点挨近只在硬问题与偏离都相同时才起作用，不挡硬问题的减少。
- 移动是刚体变换：整条脊线＋其全部子孙脊线绕附着点旋转（或对父脊线
  做镜像），长度、拓扑、内部形状全不变，只换位置。旋转后只验移动的
  子树对其他所有路径（子树内部关系刚体不变，无需重验）。
- 层级与父子关系直接读 layout.json 的 spines（level/parent/anchor），
  不改 v6p1，不读 topology.json。
"""
import argparse
import json
import math
import sys
import time
from collections import defaultdict

EPS = 1e-9
GRID_CELL = 50.0          # 空间网格边长 mm
H1_MAX_PCT = 5.0          # H1 居中阈值（与 v6p1 清单同口径）
H1_GUARD_PP = 0.1         # H1 已失败时，允许恶化上限（百分点）
NEAR_MM = 5.0             # 间距过近上报阈值（软）


# ---------- 几何 ----------

def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _same_pt(p, q, tol=1e-6):
    # 共用端点判等：不用精确相等。两段共享的节点坐标可能经不同算术路径
    # 得来，浮点差 1e-13 级，精确相等会漏判，把共点误报成间距过近（软统计）。
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def seg_proper_intersect(p1, p2, p3, p4):
    """两线段是否在内点真交叉（端点相接不算）。与 v3 同口径。"""
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    if min(abs(d1), abs(d2), abs(d3), abs(d4)) <= 1e-9:
        return False
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def seg_collinear_overlap(p1, p2, p3, p4):
    """两线段是否共线且重叠一段（重叠长度 > 1e-6 才算）。与 v3 同口径。"""
    if abs(_cross(p1, p2, p3)) > 1e-7 or abs(_cross(p1, p2, p4)) > 1e-7:
        return False
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return False

    def t(p):
        return ((p[0] - p1[0]) * dx + (p[1] - p1[1]) * dy) / L2

    t3, t4 = sorted((t(p3), t(p4)))
    lo, hi = max(0.0, t3), min(1.0, t4)
    return (hi - lo) * math.sqrt(L2) > 1e-6


def pt_seg_dist(p, a, b):
    """点到线段距离。"""
    d, _ = pt_seg_dist_t(p, a, b)
    return d


def pt_seg_dist_t(p, a, b):
    """点到线段距离 + 投影参数 t（0=端点 a，1=端点 b，中间=段中）。

    穿节点判定用 t 区分真穿与邻点假象：最近点落在段中（0<t<1）才是
    管子中途从节点旁擦过；最近点是端点、且该端点是本分支的节点时，
    是管子端头贴着邻点（那是节点挨近的事，不算穿节点）。
    """
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def seg_seg_dist(a, b, c, d):
    """两线段最短距离（相交为 0）。"""
    if seg_proper_intersect(a, b, c, d) or seg_collinear_overlap(a, b, c, d):
        return 0.0
    return min(pt_seg_dist(a, c, d), pt_seg_dist(b, c, d),
               pt_seg_dist(c, a, b), pt_seg_dist(d, a, b))


def rot_point(p, c, cos_a, sin_a):
    x = p[0] - c[0]
    y = p[1] - c[1]
    return (c[0] + x * cos_a - y * sin_a,
            c[1] + x * sin_a + y * cos_a)


def mirror_point(p, c, cos_t, sin_t):
    """点 p 对过 c、方向角为 theta 的直线做镜像。"""
    x = p[0] - c[0]
    y = p[1] - c[1]
    # 转到直线坐标系：x' 沿直线，y' 垂直直线
    xr = x * cos_t + y * sin_t
    yr = -x * sin_t + y * cos_t
    yr = -yr
    x2 = xr * cos_t - yr * sin_t
    y2 = xr * sin_t + yr * cos_t
    return (c[0] + x2, c[1] + y2)


# ---------- 空间网格 ----------

class Grid:
    """均匀网格：bbox 查询返回候选 id。"""

    def __init__(self, cell=GRID_CELL):
        self.cell = cell
        self.buckets = defaultdict(list)

    def _cells(self, x0, y0, x1, y1):
        c = self.cell
        for ix in range(int(math.floor(x0 / c)), int(math.floor(x1 / c)) + 1):
            for iy in range(int(math.floor(y0 / c)),
                            int(math.floor(y1 / c)) + 1):
                yield (ix, iy)

    def add_seg(self, idx, a, b):
        x0, x1 = min(a[0], b[0]), max(a[0], b[0])
        y0, y1 = min(a[1], b[1]), max(a[1], b[1])
        for cell in self._cells(x0, y0, x1, y1):
            self.buckets[cell].append(idx)

    def add_pt(self, idx, p, r=0.0):
        for cell in self._cells(p[0] - r, p[1] - r, p[0] + r, p[1] + r):
            self.buckets[cell].append(idx)

    def query(self, x0, y0, x1, y1):
        out = set()
        for cell in self._cells(x0, y0, x1, y1):
            out.update(self.buckets.get(cell, ()))
        return out


# ---------- 布局 ----------

class Layout:
    def __init__(self, data):
        self.data = data
        self.nodes = {n['code']: [float(n['x']), float(n['y'])]
                      for n in data['nodes']}
        self.node_type = {n['code']: n.get('type', '')
                          for n in data['nodes']}
        self.branches = {}
        for b in data['branches']:
            self.branches[b['key']] = {
                'points': [(float(p[0]), float(p[1])) for p in b['points']],
                # pieces：分段点列（合并器读它，不读 points；必须与 points
                # 同变换，否则合并断言失败——2026-11-18 教训）。
                'pieces': [[(float(p[0]), float(p[1])) for p in pc['pts']]
                           for pc in b.get('pieces', [])],
                'node0': b['node0'], 'node1': b['node1'],
                'len_3d': float(b.get('len_3d', 0.0)),
                'dia': float(b.get('dia', 0.0)),
                'ref': b,
            }
        self.spines = {s['id']: s for s in data['spines']}
        self.branch_spine = {}
        for s in data['spines']:
            for bk in s['branches']:
                self.branch_spine[bk] = s['id']
        # 节点 <-> 分支归属（按 pieces 几何端点 na/nb，不按分支拓扑
        # node0/node1：v6p1 里每段只画一次，分支的 points 只含本脊线上
        # 的段，拓扑端点可能在别的脊线——2026-11-18 实测 14 个分支拓扑
        # 端点够不着，但 pieces 端点全部贴合（仅 stub 远端自由）。
        self.node_branches = defaultdict(set)
        self.branch_nodes = {}
        for b in data['branches']:
            touched = set()
            for pc in b.get('pieces', []):
                if pc.get('na') is not None:
                    touched.add(pc['na'])
                if pc.get('nb') is not None:
                    touched.add(pc['nb'])
            if not touched:  # 无 pieces 的分支（不应发生）：退回拓扑端点
                for code in (b.get('node0'), b.get('node1')):
                    if code is not None:
                        touched.add(code)
            self.branch_nodes[b['key']] = touched
            for code in touched:
                self.node_branches[code].add(b['key'])
        self.children = defaultdict(list)
        for s in data['spines']:
            if s['parent'] is not None:
                self.children[s['parent']].append(s['id'])
        # 节点所属脊线（节点在该脊线的 joints 里）
        self.node_spines = defaultdict(set)
        for s in data['spines']:
            for j in s['joints']:
                self.node_spines[j].add(s['id'])
        self.max_level = max(s['level'] for s in data['spines'])
        self._subtree_cache = {}

    # -- 子树 --
    def subtree_spines(self, sid):
        """脊线 sid 及其全部子孙脊线 id（含自身）。"""
        if sid in self._subtree_cache:
            return self._subtree_cache[sid]
        out = [sid]
        for ch in self.children.get(sid, ()):
            out.extend(self.subtree_spines(ch))
        res = tuple(out)
        self._subtree_cache[sid] = res
        return res

    def moved_sets(self, sid):
        """旋转脊线 sid 时移动的分支与节点（不动点迭代）。

        2026-11-18 教训：脊线的 branches 是整根画的，joints 只含路径
        节点，侧枝远端（如 CON82/CON127）不在任何脊线 joints 里；旧版
        只按 joints 移节点，管子转走了、节点留在原地（偏离 456/234mm）。
        规则（按 pieces 几何端点，不按拓扑 node0/node1）：
        - 节点移动当且仅当它的全部相连分支都移动（锚点除外：锚点是转轴）；
        - 分支移动当且仅当它在子树脊线里，或它碰到的任一节点在移动。
        两条规则互相依赖，迭代到稳定为止（集合只增不减，必终止）。
        返回 (moved_branches, moved_nodes, anchor, locked_reason)；
        locked_reason 非空时该脊线禁止旋转——有移动分支的端点连着
        未移动分支，刚体旋转不可能不断开（如侧枝连到已冻结脊线的关节）。
        """
        sp = self.spines[sid]
        sub = self.subtree_spines(sid)
        anchor = sp['anchor']
        moved_branches = set()
        for s in sub:
            moved_branches.update(self.spines[s]['branches'])
        moved_nodes = set()
        for s in sub:
            moved_nodes.update(self.spines[s]['joints'])
        moved_nodes.discard(anchor)
        changed = True
        while changed:
            changed = False
            for bk, touched in self.branch_nodes.items():
                if bk in moved_branches:
                    continue
                if touched & moved_nodes:
                    moved_branches.add(bk)
                    changed = True
            for bk in list(moved_branches):
                for code in self.branch_nodes.get(bk, ()):
                    if code == anchor or code in moved_nodes:
                        continue
                    if all(bk2 in moved_branches
                           for bk2 in self.node_branches.get(code, ())):
                        moved_nodes.add(code)
                        changed = True
        locked = None
        for bk in moved_branches:
            for code in self.branch_nodes.get(bk, ()):
                if code != anchor and code not in moved_nodes:
                    locked = (f"分支 {bk} 碰到的节点 {code} 连着未移动分支，"
                              f"转了会脱开")
                    break
            if locked:
                break
        return moved_branches, moved_nodes, anchor, locked

    def verify_endpoints(self, branch_keys=None, tol=0.5):
        """闭环检查（§十八式）：每段 pieces 的两端必须贴合其节点坐标。
        自环段（na == nb，如 stub 短线头）只核起点，远端是自由点。
        返回 [(branch_key, seg, 端点, 偏离mm)]，空表为通过。"""
        bad = []
        keys = branch_keys if branch_keys is not None else self.branches
        for bk in keys:
            b = self.branches[bk]['ref']
            br = self.branches[bk]
            for pc_data, pc_pts in zip(b.get('pieces', []), br['pieces']):
                if not pc_pts:
                    continue
                na, nb = pc_data.get('na'), pc_data.get('nb')
                if na is not None and na in self.nodes:
                    d = math.hypot(pc_pts[0][0] - self.nodes[na][0],
                                   pc_pts[0][1] - self.nodes[na][1])
                    if d > tol:
                        bad.append((bk, pc_data.get('seg'), na, round(d, 1)))
                if na == nb:
                    continue  # 自环段：远端自由
                if nb is not None and nb in self.nodes:
                    d = math.hypot(pc_pts[-1][0] - self.nodes[nb][0],
                                   pc_pts[-1][1] - self.nodes[nb][1])
                    if d > tol:
                        bad.append((bk, pc_data.get('seg'), nb, round(d, 1)))
        return bad

    # -- 线段 --
    def segments(self, branch_keys=None):
        """全部（或指定）分支的折线段：(branch_key, seg_idx, p0, p1)。"""
        segs = []
        keys = branch_keys if branch_keys is not None else self.branches
        for bk in keys:
            pts = self.branches[bk]['points']
            for i in range(len(pts) - 1):
                if math.hypot(pts[i + 1][0] - pts[i][0],
                              pts[i + 1][1] - pts[i][1]) < 1e-9:
                    continue
                segs.append((bk, i, pts[i], pts[i + 1]))
        return segs

    # -- H1 居中（与 v6p1 run_checklist 同口径） --
    def trunk_mid(self):
        # 主干 = 0 级脊线里关节最多的那条。不能按 is_main 取第一条：
        # is_main 在 v6p1 里是"该关节的主分支"，地板 140 条脊线里有 107 条
        # 标 is_main（含孤岛分量 spine 1），旧写法纯靠字典顺序取到 spine 0。
        lvl0 = [s for s in self.spines.values() if s.get('level') == 0]
        if lvl0:
            main = max(lvl0, key=lambda s: len(s.get('joints', [])))
        else:
            main = next(s for s in self.spines.values() if s.get('is_main'))
        xs = [self.nodes[j][0] for j in main['joints']]
        ys = [self.nodes[j][1] for j in main['joints']]
        return (min(xs) + max(xs)) / 2.0, sum(ys) / len(ys)

    def bbox(self):
        xs, ys = [], []
        for br in self.branches.values():
            for p in br['points']:
                xs.append(p[0])
                ys.append(p[1])
        return min(xs), min(ys), max(xs), max(ys)

    # -- H9 正交率（与 v6p1 _ortho_check 同口径，按当前节点位置重算） --
    # 优化器旋转脊线后 v6p1 的 ortho 旧值失效，必须重算，否则查看器
    # 页头会显示错误的 100%——2026-11-18 教训。stub_seg 脊线在 layout
    # 里无标记，一律按父脊线锚点走向算（与 v6p1 的 stub 分支略有出入，
    # 实测未优化布局上与 v6p1 的 138/138 一致，见下方验证）。
    def ortho_rate(self):
        checked, bad, dev30 = 0, 0, 0
        for s in self.spines.values():
            if s['level'] == 0:
                continue
            js = s['joints']
            if len(js) < 2:
                continue
            p0 = self.nodes.get(js[0])
            p1 = self.nodes.get(js[1])
            if p0 is None or p1 is None or p0 == p1:
                continue
            child_ang = math.degrees(math.atan2(p1[1] - p0[1],
                                                p1[0] - p0[0]))
            ps = self.spines.get(s['parent'])
            if ps is None:
                continue
            pjs = ps['joints']
            if s['anchor'] not in pjs:
                # stub 脊线：锚点在父脊线某段中间（非关节），v6p1 用该段
                # 尾段方向；layout 无 stub 标记，取父脊线离锚点最近的段。
                ap = self.nodes.get(s['anchor'])
                if ap is None:
                    continue
                best = None
                for bk in ps['branches']:
                    pts = self.branches[bk]['points']
                    for i in range(len(pts) - 1):
                        a, b = pts[i], pts[i + 1]
                        dx, dy = b[0] - a[0], b[1] - a[1]
                        ll = dx * dx + dy * dy
                        if ll < 1e-12:
                            continue
                        t = max(0.0, min(1.0, ((ap[0] - a[0]) * dx +
                                                (ap[1] - a[1]) * dy) / ll))
                        px, py = a[0] + t * dx, a[1] + t * dy
                        dd = (ap[0] - px) ** 2 + (ap[1] - py) ** 2
                        if best is None or dd < best[0]:
                            best = (dd, a, b)
                if best is None:
                    continue
                parent_ang = math.degrees(math.atan2(
                    best[2][1] - best[1][1], best[2][0] - best[1][0]))
                rel = (child_ang - parent_ang) % 180.0
                dev = min(abs(rel - t) for t in (30.0, 60.0, 90.0,
                                                 120.0, 150.0))
                checked += 1
                if dev > 0.5:
                    bad += 1
                elif abs(rel - 90.0) > 0.5:
                    dev30 += 1
                continue
            ai = pjs.index(s['anchor'])
            if ai + 1 < len(pjs):
                q0 = self.nodes.get(pjs[ai])
                q1 = self.nodes.get(pjs[ai + 1])
            elif ai > 0:
                q0 = self.nodes.get(pjs[ai - 1])
                q1 = self.nodes.get(pjs[ai])
            else:
                continue
            if q0 is None or q1 is None or q0 == q1:
                continue
            parent_ang = math.degrees(math.atan2(q1[1] - q0[1],
                                                 q1[0] - q0[0]))
            rel = (child_ang - parent_ang) % 180.0
            dev = min(abs(rel - t) for t in (30.0, 60.0, 90.0,
                                             120.0, 150.0))
            checked += 1
            if dev > 0.5:
                bad += 1
            elif abs(rel - 90.0) > 0.5:
                dev30 += 1
        return checked, checked - bad, dev30

    def h1_dev(self, bbox=None):
        """返回 (dev_x_pct, dev_y_pct)：主干中点相对图纸中心的偏差。"""
        if bbox is None:
            bbox = self.bbox()
        x0, y0, x1, y1 = bbox
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        tx, ty = self.trunk_mid()
        w, h = x1 - x0, y1 - y0
        return (abs(tx - cx) / w * 100.0 if w > 0 else 0.0,
                abs(ty - cy) / h * 100.0 if h > 0 else 0.0)

    def max_len_err(self):
        """H2：每根管 |2D 折线长 - 3D 弧长| 的最大值。"""
        worst = 0.0
        for br in self.branches.values():
            pts = br['points']
            l2 = sum(math.hypot(pts[i + 1][0] - pts[i][0],
                                pts[i + 1][1] - pts[i][1])
                     for i in range(len(pts) - 1))
            worst = max(worst, abs(l2 - br['len_3d']))
        return worst

    # -- 应用变换 --
    def apply_transform(self, moved_branches, moved_nodes, fn):
        for bk in moved_branches:
            br = self.branches[bk]
            br['points'] = [fn(p) for p in br['points']]
            br['pieces'] = [[fn(p) for p in pc] for pc in br['pieces']]
        for code in moved_nodes:
            self.nodes[code] = list(fn(tuple(self.nodes[code])))

    def sync_back(self):
        """把内存里的几何写回 data（分支点、节点坐标、脊线方向）。"""
        for b in self.data['branches']:
            br = self.branches[b['key']]
            b['points'] = [[round(p[0], 2), round(p[1], 2)]
                           for p in br['points']]
            for pc, new_pts in zip(b.get('pieces', []), br['pieces']):
                pc['pts'] = [[round(p[0], 2), round(p[1], 2)]
                             for p in new_pts]
            pts = br['points']
            b['len_2d'] = round(sum(
                math.hypot(pts[i + 1][0] - pts[i][0],
                           pts[i + 1][1] - pts[i][1])
                for i in range(len(pts) - 1)), 1)
        for n in self.data['nodes']:
            n['x'], n['y'] = (round(self.nodes[n['code']][0], 2),
                              round(self.nodes[n['code']][1], 2))
        for s in self.data['spines']:
            cur = self.spines[s['id']]
            s['direction'] = cur['direction']
            s['slot_offset'] = cur['slot_offset']


# ---------- 检查器 ----------

class Checker:
    """对“移动的子树 vs 其余部分”做硬检查。

    硬问题三类（目标 0）：交叉、压着画（共线重叠）、穿节点。
    穿节点 = 管子中途离它不连接的节点太近（默认 15mm），与交叉同等
    处理。两处排除（2026-11-18 实测定规）：
    ① 节点是该分支碰到的节点（按 pieces 几何端点，即拓扑上该分支
    经过该节点——旧版按“同脊线关节”豁免，BN06 在 196.1-40X 管上却
    不在任何脊线 joints 里，被误报为穿节点）；
    ② 最近点落在段的端点、且该端点是本分支的节点：管子端头贴着邻
    点（如 196.1-71X 终点 CLP133 离 CLP123 仅 12.3mm），那是节点挨近
    的事，不算穿节点——旧版拓扑豁免曾把这类全报出来（优化后 17 处
    里 14 处是假象，只 3 处是真穿）。
    另有软指标节点挨近（node_close）：不连在同一根管子上的两个节点
    距离 < node_mm（默认 20mm）——只报告，不计入硬问题（多数是长度
    定死的，优化器清不掉；先让检查器看见，是否变硬以后再定）。
    穿节点按（分支，节点）去重：相邻两段共用一个顶点节点时只计一次
    （旧版 BN06 一处计成两处，报告数 7 与明细 6 对不上）。
    """

    def __init__(self, layout, pierce_mm, node_mm=20.0):
        self.L = layout
        self.pierce_mm = pierce_mm
        self.node_mm = node_mm
        # 每条分支的折线顶点里，哪些是本分支碰到的节点（按顶点下标）。
        # 刚体变换保持重合关系，试算时直接用下标查，不必重算坐标。
        self.vertex_node = {}
        for bk, br in layout.branches.items():
            touched = layout.branch_nodes.get(bk, ())
            vm = {}
            for i, v in enumerate(br['points']):
                for code in touched:
                    if _same_pt(v, tuple(layout.nodes[code])):
                        vm[i] = code
                        break
            self.vertex_node[bk] = vm

    def _endpoint_exempt(self, bk, seg_idx, t):
        """最近点是段端点且该端点是本分支的节点 → 邻点假象，豁免。"""
        vm = self.vertex_node.get(bk, {})
        if t <= 1e-9:
            return seg_idx in vm
        if t >= 1 - 1e-9:
            return (seg_idx + 1) in vm
        return False

    def prepare(self, moved_branches, moved_nodes):
        """为一次脊线调整建索引：其余部分的线段网格＋节点网格。"""
        L = self.L
        rest_segs = L.segments(
            [bk for bk in L.branches if bk not in moved_branches])
        self.rest_segs = rest_segs
        self.seg_grid = Grid()
        for idx, (_, _, a, b) in enumerate(rest_segs):
            self.seg_grid.add_seg(idx, a, b)
        self.rest_nodes = {c: L.nodes[c] for c in L.nodes
                           if c not in moved_nodes}
        self.node_grid = Grid()
        for code, p in self.rest_nodes.items():
            self.node_grid.add_pt(code, p, r=self.pierce_mm)
        # 节点挨近网格（半径 node_mm，与穿节点半径不同，另建）
        self.nc_grid = Grid()
        for code, p in self.rest_nodes.items():
            self.nc_grid.add_pt(code, p, r=self.node_mm)

    def _seg_vs_rest(self, bk, a, b, out):
        """一条移动线段对全部其余线段：交叉/压着画。"""
        x0, x1 = min(a[0], b[0]), max(a[0], b[0])
        y0, y1 = min(a[1], b[1]), max(a[1], b[1])
        for idx in self.seg_grid.query(x0, y0, x1, y1):
            rbk, _, c, d = self.rest_segs[idx]
            if seg_proper_intersect(a, b, c, d):
                out['crossings'].append((bk, rbk))
            elif seg_collinear_overlap(a, b, c, d):
                out['overlaps'].append((bk, rbk))

    def _pierce_seg_vs_nodes(self, bk, seg_idx, a, b, out):
        """移动线段对非移动节点：穿节点。"""
        L = self.L
        br = L.branches[bk]
        touched = L.branch_nodes.get(bk, ())
        x0, x1 = min(a[0], b[0]), max(a[0], b[0])
        y0, y1 = min(a[1], b[1]), max(a[1], b[1])
        m = self.pierce_mm
        for code in self.node_grid.query(x0 - m, y0 - m, x1 + m, y1 + m):
            if code in (br['node0'], br['node1']):
                continue  # 端点是自己的节点
            if code in touched:
                continue  # 该分支拓扑上经过该节点，合法
            d, t = pt_seg_dist_t(self.rest_nodes[code], a, b)
            if d < m and not self._endpoint_exempt(bk, seg_idx, t):
                out['piercings'].append((bk, code))

    def _pierce_nodes_vs_segs(self, moved_nodes, new_pos, out):
        """移动后的节点对非移动线段：穿节点（反向）。"""
        L = self.L
        m = self.pierce_mm
        for code in moved_nodes:
            p = new_pos[code]
            for idx in self.seg_grid.query(p[0] - m, p[1] - m,
                                           p[0] + m, p[1] + m):
                rbk, seg_idx, c, d = self.rest_segs[idx]
                rbr = L.branches[rbk]
                if code in (rbr['node0'], rbr['node1']):
                    continue
                if code in L.branch_nodes.get(rbk, ()):
                    continue
                dist, t = pt_seg_dist_t(p, c, d)
                if dist < m and not self._endpoint_exempt(rbk, seg_idx, t):
                    out['piercings'].append((rbk, code))

    def _node_close_trial(self, moved_nodes, new_pos):
        """试算的节点挨近数（只计移动节点 vs 未移动节点）。

        移动节点之间、未移动节点之间的距离刚体不变，试算时不用重算；
        只有移动 vs 未移动的对数会随变换变，作选移动的次要标准（硬问题
        相同时，挨近少的优先——2026-11-18 教训：只看硬问题时优化器把
        CON121/CON94 压到只剩 4mm，两个圆点糊成一片）。
        """
        L = self.L
        nm = self.node_mm
        n = 0
        for code in moved_nodes:
            p = new_pos[code]
            for oc in self.nc_grid.query(p[0] - nm, p[1] - nm,
                                         p[0] + nm, p[1] + nm):
                op = self.rest_nodes[oc]
                if math.hypot(op[0] - p[0], op[1] - p[1]) >= nm:
                    continue
                if L.node_branches.get(code, set()) & \
                        L.node_branches.get(oc, set()):
                    continue
                n += 1
        return n

    def check_trial(self, moved_branches, moved_nodes, transform):
        """试一次变换（不落地）：返回硬问题。"""
        out = {'crossings': [], 'overlaps': [], 'piercings': []}
        L = self.L
        new_pos = {c: transform(tuple(L.nodes[c])) for c in moved_nodes}
        for bk in moved_branches:
            pts = [transform(p) for p in L.branches[bk]['points']]
            for i in range(len(pts) - 1):
                if math.hypot(pts[i + 1][0] - pts[i][0],
                              pts[i + 1][1] - pts[i][1]) < 1e-9:
                    continue
                self._seg_vs_rest(bk, pts[i], pts[i + 1], out)
                self._pierce_seg_vs_nodes(bk, i, pts[i], pts[i + 1], out)
        self._pierce_nodes_vs_segs(moved_nodes, new_pos, out)
        out['piercings'] = sorted(set(out['piercings']))
        out['node_close'] = self._node_close_trial(moved_nodes, new_pos)
        return out

    def full_check(self):
        """全图硬检查（用于前后对比报告）。"""
        L = self.L
        segs = L.segments()
        grid = Grid()
        for idx, (_, _, a, b) in enumerate(segs):
            grid.add_seg(idx, a, b)
        out = {'crossings': [], 'overlaps': [], 'piercings': [],
               'near_lt_5mm': 0, 'node_close': []}
        for i, (bk, _, a, b) in enumerate(segs):
            x0, x1 = min(a[0], b[0]), max(a[0], b[0])
            y0, y1 = min(a[1], b[1]), max(a[1], b[1])
            for j in grid.query(x0, y0, x1, y1):
                if j <= i:
                    continue
                rbk, _, c, d = segs[j]
                if rbk == bk:
                    continue
                # 共用端点（同一节点）的两段不算干涉
                if (_same_pt(a, c) or _same_pt(a, d) or
                        _same_pt(b, c) or _same_pt(b, d)):
                    continue
                if seg_proper_intersect(a, b, c, d):
                    out['crossings'].append((bk, rbk))
                elif seg_collinear_overlap(a, b, c, d):
                    out['overlaps'].append((bk, rbk))
                elif seg_seg_dist(a, b, c, d) < NEAR_MM:
                    out['near_lt_5mm'] += 1
        # 穿节点：全图节点对非关联线段
        node_grid = Grid()
        for code, p in L.nodes.items():
            node_grid.add_pt(code, p, r=self.pierce_mm)
        for bk, seg_idx, a, b in segs:
            br = L.branches[bk]
            touched = L.branch_nodes.get(bk, ())
            x0, x1 = min(a[0], b[0]), max(a[0], b[0])
            y0, y1 = min(a[1], b[1]), max(a[1], b[1])
            m = self.pierce_mm
            for code in node_grid.query(x0 - m, y0 - m, x1 + m, y1 + m):
                if code in (br['node0'], br['node1']):
                    continue
                if code in touched:
                    continue
                d, t = pt_seg_dist_t(L.nodes[code], a, b)
                if d < m and not self._endpoint_exempt(bk, seg_idx, t):
                    out['piercings'].append((bk, code))
        out['piercings'] = sorted(set(out['piercings']))
        # 节点挨近（软指标，不计入硬问题）：不连在同一根管子上的两个
        # 节点距离 < node_mm。圆点是屏幕恒定的，挨太近缩小时糊成一片，
        # 看着像桥接（2026-11-18 BN05/CLP05 看错的根因）。
        nm = self.node_mm
        ng2 = Grid()
        for code, p in L.nodes.items():
            ng2.add_pt(code, p, r=nm)
        seen_pairs = set()
        for code, p in L.nodes.items():
            for oc in ng2.query(p[0] - nm, p[1] - nm, p[0] + nm, p[1] + nm):
                if oc <= code:
                    continue
                pair = (code, oc)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                d = math.hypot(L.nodes[oc][0] - p[0],
                               L.nodes[oc][1] - p[1])
                if d >= nm:
                    continue
                if L.node_branches.get(code, set()) & \
                        L.node_branches.get(oc, set()):
                    continue  # 同一根管子上的两个点，长度定死的
                out['node_close'].append(
                    (code, oc, round(d, 1)))
        out['node_close'].sort(key=lambda t: t[2])
        return out


def seg_intersection_point(p1, p2, p3, p4):
    """两直线交点（用于真交叉点坐标；平行返回 None）。"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4)
          - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
    py = ((x1 * y2 - y1 * x2) * (y3 - y4)
          - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
    return (px, py)


def hard_count(issues):
    return (len(issues['crossings']) + len(issues['overlaps'])
            + len(issues['piercings']))


# ---------- 优化器 ----------

def optimize(layout, angle_max, angle_step, pierce_mm, max_sweeps, log,
               allow_lateral=False, h1_guard_pp=H1_GUARD_PP,
               h1_relax_zero=False, node_mm=20.0, no_nc_increase=True):
    L = layout
    checker = Checker(L, pierce_mm, node_mm)
    report = {'levels': [], 'moves': [], 'stuck': []}
    h1_before = L.h1_dev()

    angles = []
    a = angle_step
    while a <= angle_max + 1e-9:
        angles.append(a)
        angles.append(-a)
        a += angle_step

    for sweep in range(1, max_sweeps + 1):
        full_start = checker.full_check()
        hard_start = hard_count(full_start)
        if hard_start == 0:
            break
        for level in range(1, L.max_level + 1):
            t0 = time.time()
            # 本级开始前的全图硬问题（用于排序：问题多的脊线先调）
            spines_lv = [s for s in L.spines.values() if s['level'] == level]
            if not spines_lv:
                continue
            full0 = checker.full_check()
            n0 = hard_count(full0)
            # 每条脊线当前涉及的硬问题数（按子树试算 Δ=0）
            scored = []
            for s in spines_lv:
                mb, mn, _, _locked = L.moved_sets(s['id'])
                if not mb:
                    continue
                checker.prepare(mb, mn)
                cur = checker.check_trial(mb, mn, lambda p: p)
                scored.append((hard_count(cur), s['id']))
            scored.sort(key=lambda t: (-t[0], t[1]))
            moved_n = 0
            for _, sid in scored:
                sp = L.spines[sid]
                mb, mn, anchor, locked = L.moved_sets(sid)
                if not mb or anchor not in L.nodes:
                    continue
                if locked:
                    report['stuck'].append({
                        'spine': sid, 'level': level, 'anchor': anchor,
                        'blocked_by': 'locked', 'reason': locked})
                    continue
                checker.prepare(mb, mn)
                cur = checker.check_trial(mb, mn, lambda p: p)
                cur_n = hard_count(cur)
                cur_nc = cur['node_close']
                if cur_n == 0:
                    continue  # 已干净，冻结不动
                c = tuple(L.nodes[anchor])
                # 试角度：+5、-5、+10、-10……取（硬问题，偏离，节点挨近）
                # 字典序最小的——硬问题优先，偏离其次，节点挨近只在前两者
                # 相同时才起作用（±5° 这种对称候选之间选不压点的那个）。
                # 不压点否决（默认开，用户 2026-11-18 定"不许压点"；实验想关掉
                # 时用 --allow-nc-increase）：直接否决让节点挨近变多的候选。
                # 2026-11-18 spine 27 教训：-10° 硬问题最少（2）却把 CON121/
                # CON94 压到 4mm，次选 +5° 硬问题 3 但挨近 0——不压点就得
                # 接受多留硬问题，实测地板开否决硬问题 52→2 不变，挨近 8→2。
                best = None  # (n, dev, nc, deg, transform, kind)
                for deg in angles:
                    r = math.radians(deg)
                    cos_a, sin_a = math.cos(r), math.sin(r)
                    fn = lambda p, ca=cos_a, sa=sin_a: rot_point(p, c, ca, sa)
                    iss = checker.check_trial(mb, mn, fn)
                    n = hard_count(iss)
                    nc = iss['node_close']
                    if no_nc_increase and nc > cur_nc:
                        continue
                    if best is None or (n, abs(deg), nc) < (
                            best[0], best[1], best[2]):
                        best = (n, abs(deg), nc, deg, fn, 'rotate')
                    if n == 0 and nc == 0 and abs(deg) == angle_step:
                        break  # 硬问题与挨近都清零且偏离最小，不必再试
                # 换边：对父脊线镜像。旧版只在旋转无改善时才试（致 0 次
                # 换边，Gemini 2026-11-18 指出触发条件过严）：现改为只要
                # 未清零就试，并在镜像后叠加旋转组合（镜像+±5..±90°）。
                # 偏离按 180+|旋转| 计，纯旋转清零时仍优先（换边是第二招）。
                if best is None or best[0] > 0:
                    parent = L.spines.get(sp['parent'])
                    if parent is not None and parent.get('direction') is not None:
                        th = math.radians(parent['direction'])
                        cos_t, sin_t = math.cos(th), math.sin(th)
                        fn0 = lambda p, ct=cos_t, st=sin_t: mirror_point(
                            p, c, ct, st)
                        for deg2 in [0] + angles:
                            if deg2 == 0:
                                fn, dev, kind2 = fn0, 180.0, 'flip'
                            else:
                                r2 = math.radians(deg2)
                                ca2, sa2 = math.cos(r2), math.sin(r2)
                                fn = (lambda p, f0=fn0, ca=ca2, sa=sa2:
                                      rot_point(f0(p), c, ca, sa))
                                dev, kind2 = 180.0 + abs(deg2), 'flip_rot'
                            iss = checker.check_trial(mb, mn, fn)
                            n = hard_count(iss)
                            nc = iss['node_close']
                            if no_nc_increase and nc > cur_nc:
                                continue
                            if best is None or (n, dev, nc) < (
                                    best[0], best[1], best[2]):
                                best = (n, dev, nc, deg2, fn, kind2)
                # 接受条件：默认严格减少；allow_lateral 时允许平移（硬问题
                # 不增加）——用户规则原文是“交叉不增加”，平移可能为后续
                # 脊线腾出空间。平移不改变硬问题数，单调不恶化仍成立。
                accept = (best is not None and
                          (best[0] < cur_n or
                           (allow_lateral and best[0] == cur_n)))
                if not accept:
                    report['stuck'].append({
                        'spine': sid, 'level': level, 'anchor': anchor,
                        'hard_issues': cur_n,
                        'crossings': len(cur['crossings']),
                        'overlaps': len(cur['overlaps']),
                        'piercings': len(cur['piercings'])})
                    continue
                # H1 守门：居中不许变差（两轴各放宽 0.1 个百分点）。
                # 2026-11-18 实测：放宽到"仍通过 5%"反而更差（62→7 vs 62→6），
                # spine 5 的移动局部好、全局差；严格守门实测更优。
                # h1_relax_zero（Gemini P3 招式 3）：仅当本步能把该脊线
                # 清零（best[0]==0，无新干涉）时，允许 H1 放宽到 5% 上限。
                new_pts = []
                for bk in mb:
                    new_pts.extend(best[4](p) for p in L.branches[bk]['points'])
                rest_pts = [p for bk2, br2 in L.branches.items()
                            if bk2 not in mb for p in br2['points']]
                allx = [p[0] for p in new_pts] + [p[0] for p in rest_pts]
                ally = [p[1] for p in new_pts] + [p[1] for p in rest_pts]
                new_h1 = L.h1_dev((min(allx), min(ally),
                                   max(allx), max(ally)))
                old_h1 = L.h1_dev()
                guard = (H1_MAX_PCT if (h1_relax_zero and best[0] == 0)
                         else h1_guard_pp)
                if (new_h1[0] > old_h1[0] + guard
                        or new_h1[1] > old_h1[1] + guard
                        or new_h1[0] > H1_MAX_PCT or new_h1[1] > H1_MAX_PCT):
                    report['stuck'].append({
                        'spine': sid, 'level': level, 'anchor': anchor,
                        'hard_issues': cur_n, 'blocked_by': 'H1',
                        'h1_before': [round(v, 2) for v in old_h1],
                        'h1_after': [round(v, 2) for v in new_h1]})
                    continue
                # 落地
                L.apply_transform(mb, mn, best[4])
                bad_ep = L.verify_endpoints(mb)
                if bad_ep:
                    raise RuntimeError(
                        f"脊线 {sid} 移动后管端脱开（moved_sets 缺陷）："
                        f"{bad_ep[:5]}")
                for s in L.subtree_spines(sid):
                    cur_sp = L.spines[s]
                    if cur_sp.get('direction') is not None:
                        if best[5] == 'rotate':
                            cur_sp['direction'] = round(
                                (cur_sp['direction'] + best[3]) % 360.0, 1)
                        else:  # flip / flip_rot：镜像后再转 best[3]°
                            th = parent['direction']
                            cur_sp['direction'] = round(
                                (2 * th - cur_sp['direction'] + best[3])
                                % 360.0, 1)
                if best[5] == 'rotate':
                    sp['slot_offset'] = round(sp['slot_offset'] + best[3], 1)
                else:  # flip / flip_rot：槽位取反后再转 best[3]°
                    sp['slot_offset'] = round(-sp['slot_offset'] + best[3], 1)
                moved_n += 1
                report['moves'].append({
                    'spine': sid, 'level': level, 'anchor': anchor,
                    'kind': best[5],
                    'deg': best[3] if best[5] in ('rotate', 'flip_rot') else None,
                    'hard_before': cur_n, 'hard_after': best[0],
                    'branches': len(mb), 'nodes': len(mn)})
            full1 = checker.full_check()
            n1 = hard_count(full1)
            report['levels'].append({
                'sweep': sweep,
                'level': level, 'spines': len(spines_lv),
                'moved': moved_n,
                'hard_before': n0, 'hard_after': n1,
                'crossings': len(full1['crossings']),
                'overlaps': len(full1['overlaps']),
                'piercings': len(full1['piercings']),
                'near_lt_5mm': full1['near_lt_5mm'],
                'node_close': len(full1['node_close']),
                'seconds': round(time.time() - t0, 1)})
            log(f"[优化] {level} 级：{len(spines_lv)} 脊线，动 {moved_n} 条，"
                f"硬问题 {n0}→{n1}（交叉 {len(full1['crossings'])}，"
                f"压着画 {len(full1['overlaps'])}，"
                f"穿节点 {len(full1['piercings'])}），"
                f"{time.time() - t0:.1f}s")

        full_end = checker.full_check()
        hard_end = hard_count(full_end)
        log(f"[扫描] 第 {sweep} 遍：硬问题 {hard_start}→{hard_end}")
        if hard_end == 0 or hard_end >= hard_start:
            break

    h1_after = L.h1_dev()
    report['h1_before_pct'] = [round(v, 2) for v in h1_before]
    report['h1_after_pct'] = [round(v, 2) for v in h1_after]
    report['max_len_err_mm'] = round(L.max_len_err(), 3)
    return report


def main():
    ap = argparse.ArgumentParser(description='布局零交叉优化器（v6p1 后处理）')
    ap.add_argument('layout', help='v6p1 layout.json')
    ap.add_argument('-o', '--out', required=True, help='输出 layout.json')
    ap.add_argument('--angle-max', type=float, default=90.0,
                    help='角度搜索上限（度，默认 90；取偏离最小的，多数仍近 90°）')
    ap.add_argument('--angle-step', type=float, default=5.0,
                    help='角度步长（度，默认 5）')
    ap.add_argument('--pierce-mm', type=float, default=15.0,
                    help='穿节点距离（mm，默认 15）')
    ap.add_argument('--node-mm', type=float, default=20.0,
                    help='节点挨近距离（mm，默认 20；只报告，不计入硬问题）')
    ap.add_argument('--allow-nc-increase', action='store_false',
                    dest='no_nc_increase',
                    help='允许移动让节点挨近变多（默认不许：用户 2026-11-18 定，不许压点）')
    ap.add_argument('--sweeps', type=int, default=3,
                    help='最多扫描遍数（默认 3；某遍无改善或硬问题清零即停）')
    ap.add_argument('--allow-lateral', action='store_true',
                    help='允许平移（硬问题不增加的移动；默认只接受严格减少）')
    ap.add_argument('--h1-guard-pp', type=float, default=H1_GUARD_PP,
                    help='H1 守门放宽（百分点，默认 0.1；绝对上限恒为 5%%）')
    ap.add_argument('--h1-relax-zero', action='store_true',
                    help='能把该脊线清零的移动，H1 允许放宽到 5%% 上限')
    ap.add_argument('--report', help='优化报告 json（默认与输出同目录）')
    args = ap.parse_args()

    def log(msg):
        print(msg, flush=True)

    t0 = time.time()
    with open(args.layout, encoding='utf-8') as f:
        data = json.load(f)
    L = Layout(data)
    checker = Checker(L, args.pierce_mm, args.node_mm)
    full0 = checker.full_check()
    log(f"[检查] 优化前：交叉 {len(full0['crossings'])}，"
        f"压着画 {len(full0['overlaps'])}，"
        f"穿节点 {len(full0['piercings'])}，间距<5mm {full0['near_lt_5mm']} 对，"
        f"节点挨近<{args.node_mm}mm {len(full0['node_close'])} 对；"
        f"脊线 {len(L.spines)} 条，层级 0~{L.max_level}；"
        f"H1 偏差 {tuple(round(v, 2) for v in L.h1_dev())}%")
    pre_ep = L.verify_endpoints()
    if pre_ep:
        log(f"[警告] 输入布局已有 {len(pre_ep)} 处管端脱开（v6p1 问题，"
            f"优化器不修）：{pre_ep[:5]}")
    report = optimize(L, args.angle_max, args.angle_step,
                      args.pierce_mm, args.sweeps, log,
                      allow_lateral=args.allow_lateral,
                      h1_guard_pp=args.h1_guard_pp,
                      h1_relax_zero=args.h1_relax_zero,
                      node_mm=args.node_mm,
                      no_nc_increase=args.no_nc_increase)
    post_ep = L.verify_endpoints()
    if post_ep:
        raise RuntimeError(
            f"优化后 {len(post_ep)} 处管端脱开，不写盘：{post_ep[:5]}")
    full1 = checker.full_check()
    report['before'] = {
        'crossings': len(full0['crossings']),
        'overlaps': len(full0['overlaps']),
        'piercings': len(full0['piercings']),
        'near_lt_5mm': full0['near_lt_5mm'],
        'node_close': len(full0['node_close'])}
    report['after'] = {
        'crossings': len(full1['crossings']),
        'overlaps': len(full1['overlaps']),
        'piercings': len(full1['piercings']),
        'near_lt_5mm': full1['near_lt_5mm'],
        'node_close': len(full1['node_close'])}
    report['seconds'] = round(time.time() - t0, 1)
    report['params'] = {'angle_max': args.angle_max,
                        'angle_step': args.angle_step,
                        'pierce_mm': args.pierce_mm,
                        'node_mm': args.node_mm}
    # 剩余硬问题明细（按分支对去重，截断到 200 条）
    rem = {'crossings': sorted({tuple(sorted(p)) for p in full1['crossings']}),
           'overlaps': sorted({tuple(sorted(p)) for p in full1['overlaps']}),
           'piercings': sorted({(b, n) for b, n in full1['piercings']}),
           'node_close': [list(t) for t in full1['node_close']]}
    report['remaining'] = {k: v[:200] for k, v in rem.items()}

    L.sync_back()
    # 舍入后重算：长度误差（H2）与交叉点列表（带坐标，供查看器画红✕）
    worst = 0.0
    for b in data['branches']:
        pts = b['points']
        l2 = sum(math.hypot(pts[i + 1][0] - pts[i][0],
                            pts[i + 1][1] - pts[i][1])
                 for i in range(len(pts) - 1))
        worst = max(worst, abs(l2 - float(b.get('len_3d', 0.0))))
    report['max_len_err_mm'] = round(worst, 3)
    xings = []
    segs = L.segments()
    grid = Grid()
    for idx, (_, _, a, b) in enumerate(segs):
        grid.add_seg(idx, a, b)
    for i, (bk, _, a, b) in enumerate(segs):
        x0, x1 = min(a[0], b[0]), max(a[0], b[0])
        y0, y1 = min(a[1], b[1]), max(a[1], b[1])
        for j in grid.query(x0, y0, x1, y1):
            if j <= i:
                continue
            rbk, _, c, d = segs[j]
            if rbk == bk:
                continue
            if _same_pt(a, c) or _same_pt(a, d) or _same_pt(b, c) or _same_pt(b, d):
                continue
            if seg_proper_intersect(a, b, c, d):
                pt = seg_intersection_point(a, b, c, d)
                if pt is not None:
                    xings.append({'x': round(pt[0], 2), 'y': round(pt[1], 2),
                                  'branches': sorted([bk, rbk])})
    data['crossings'] = xings
    # 更新 stats（checklist 是 v6p1 的，优化后过期，显式标注）
    st = data['stats']
    st['crossings'] = len(xings)
    st['residual_x_cross'] = len(xings)
    st['residual_collinear_overlap'] = len(full1['overlaps'])
    st['residual_near_lt_clearance'] = full1['near_lt_5mm']
    st['residual_interference_pairs'] = len(full1['crossings']) + \
        len(full1['overlaps']) + len(full1['piercings'])
    st['max_len_err_mm'] = report['max_len_err_mm']
    # 正交率按当前几何重算（H9 旧口径；5° 规则下它不再是目标指标，
    # 但页头显示的必须是真值，不能留 v6p1 的 100%）
    o_checked, o_passed, o_dev30 = L.ortho_rate()
    st['ortho_checked'] = o_checked
    st['ortho_passed'] = o_passed
    st['ortho_rate_pct'] = round(100.0 * o_passed / o_checked, 1) \
        if o_checked else 0.0
    st['ortho_deviated_30'] = o_dev30
    x0, y0, x1, y1 = L.bbox()
    st['bbox'] = [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]
    data['meta']['optimized'] = True
    data['meta']['optimizer'] = {
        'script': 'optimize_layout.py',
        'angle_max': args.angle_max, 'angle_step': args.angle_step,
        'pierce_mm': args.pierce_mm,
        'hard_before': hard_count(full0), 'hard_after': hard_count(full1),
        'moves': len(report['moves']), 'stuck': len(report['stuck'])}
    data['checklist_stale'] = True
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    report_path = args.report or args.out.replace('.json', '_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    log(f"[完成] 硬问题 {hard_count(full0)}→{hard_count(full1)}，"
        f"动 {len(report['moves'])} 条脊线，卡住 {len(report['stuck'])} 条，"
        f"耗时 {report['seconds']}s；输出 {args.out}，报告 {report_path}")


if __name__ == '__main__':
    main()
