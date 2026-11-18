#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仪表线束（IP-Harness）3D → 2D 展开 v5。

相对 v4 的唯一根本改动：主干定义纠正（2026-11-17 20:34 用户亲定，
见《需求说明.md》§五）：
  主干 = 连接器到连接器之间找到的最长路径（路径总长 = 沿途各分支 3D
  中心线真实弧长之和），整条路径拉直、水平画在中间。
  v4 把主干理解成最长单根管子 Body.123（191.9mm），用户 20:31 指出图纸
  主干没拉直——单管定义作废。IP 实测主干路径：CON08→CON01，2343.4mm，
  28 根分支（次长 2214.2mm，CON01→CON32）。

其余规则与 v4 相同（§十三正交规则、PCA 投影、环分类、分级干涉、
硬失败门、确定性），全部复用 unfold_2d_v4.py 的机械，只改主干：
  - 主干计算：枚举全部连接器节点（IP 共 32 个），每连接器为源跑一次
    Dijkstra（边权 = 分支 3D 弧长），取两两之间最长的一条。程序算出，
    不许写死；IP 校核值 CON08→CON01 / 2343.4mm / 28 根，算不出来就是 bug。
  - 布局：整条 28 根路径共线水平放置（29 个路径关节 y 恒定），按路径
    顺序、各段按真实弧长排；BFS 树以整条路径为根（每个路径关节是其
    侧枝子树的根），其余分支按 §十三 正交规则挂接。
  - H1 改为路径主干三查：(a)29 个路径关节共线（max|y−y主干| ≤0.01mm）、
    (b)水平 0°、(c)横竖两方向居中（路径中点与图纸中心偏差均 ≤5%）。
    教训：清单必须量用户眼睛看得到的东西——整条路径的直，
    不是某一根管子（v4 的 H1 只查一根管子，全过但图还是错的）。

六个阶段与 v4 相同（①读取校验 ②拓扑分析 ③PCA 投影 ④结构化布局
⑤干涉优化 ⑥工程输出），阶段 2 增加主干路径计算。

已知局限（诚实记录）：
  - 真环与路径主干的交互未实现：若主干分量含真环且路径穿环，v5 优先
    放直路径，环分支按受约束段处理（可能打折，违反 §六“环优先”）。
    IP 无真环（0 个），本局限未在真实数据上触发。
  - 路径分支内的自环段（如 Body.150 的 SEG32，5.1mm）画在路径关节上
    的小三角形，不计入路径直线跨度（直线跨度 = 总长 − 自环段长）。

用法：
  python3 unfold_2d_v5.py <topology.json> -o <outdir> [--clearance 5.0]
  python3 unfold_2d_v5.py <topology.json> --hash-only   # 内部用：只打印 layout.json MD5

输入：pipeline_4step_rules 的 topology.json。
输出（outdir）：unfold_v5.dxf、unfold_v5.xlsx、layout.json、checklist_v5.md。
硬失败时只写 layout.json 与 checklist_v5.md，不写 DXF/Excel。

运行环境：plain python3 即可；ezdxf 不在系统 Python 里时用 ~/workspace/.pylibs 兜底。
"""

import argparse
import hashlib
import heapq
import itertools
import json
import math
import os
import subprocess
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ezdxf 兜底：系统 Python 没有时用 ~/workspace/.pylibs（同 v4 做法）
try:
    import ezdxf  # noqa: F401
except ImportError:
    _pylibs = os.path.expanduser("~/workspace/.pylibs")
    if os.path.isdir(_pylibs) and _pylibs not in sys.path:
        sys.path.insert(0, _pylibs)

from unfold_2d_v3 import (
    Topo, Layout, write_dxf, write_excel, dist, angle_of,
    add_pt, unit_from_angle,
    seg_proper_intersect, seg_collinear_overlap, seg_seg_dist,
    pt_eq, CLEARANCE_DEFAULT,
)
from unfold_2d_v3_fix import (
    layout_data, count_interference_detailed,
    TRUNK_CENTER_TOL, TRUNK_ANGLE_TOL,
)
from unfold_2d_v4 import (
    LayoutV4, layout_data_v4, _ring_test_status,
)

# ---------- v5 阈值 ----------
LEN_ERR_TOL_V5 = 0.1        # H2：最大长度误差 ≤0.1mm（同 v4）
TRUNK_COLLINEAR_TOL_MM = 0.01   # H1a：路径关节共线，max|y−y主干| ≤0.01mm
CENTER_TOL_V5 = TRUNK_CENTER_TOL  # H1c：居中偏差 ≤5%（横竖都要查）
TOP_SIDE_SEARCH_N = 6       # 放置侧搜索：子树总长最大的 6 根一级分支，穷举 2^6 种


class LayoutV5(LayoutV4):
    """v5 布局：主干 = 连接器—连接器最长路径，整条拉直水平；其余复用 v4。"""

    def __init__(self, topo, clearance=5.0, verbose=True):
        super().__init__(topo, clearance=clearance, verbose=verbose)
        # 主干路径（compute_trunk_path 填充）
        self.trunk_path = []            # 分支 key 列表，按路径顺序（左→右）
        self.trunk_path_joints = []     # 29 个路径关节，按路径顺序（左→右）
        self.trunk_path_length = 0.0    # 路径总长 = 各分支 3D 弧长之和
        self.trunk_path_span = 0.0      # 直线跨度（总长 − 路径内自环段长）
        self.trunk_path_endpoints = (None, None)  # (左端连接器, 右端连接器)
        self.trunk_path_second = None   # 次长 (长度, 端点1, 端点2)
        self.trunk_path_set = set()
        self._trunk_index = {}          # 分支 key -> 在路径中的下标

    # ---------- 主干路径计算（§五：连接器到连接器最长路径） ----------
    def compute_trunk_path(self):
        """枚举全部连接器节点两两之间的最长路径（Dijkstra，每连接器为源）。

        边 = 分支（边权 = 分支 3D 中心线真实弧长）；纯自环分支（node0==node1）
        不进邻接表（简单路径不可能经过它）。最长按总长取最大，平局取端点
        对字典序最小者（确定性）。走向：字典序较大的端点在左
        （IP：CON08 左、CON01 右，与校核值一致）。
        """
        topo = self.topo
        adj = defaultdict(list)
        for key in sorted(topo.branches):
            b = topo.branches[key]
            u, v = b['node0'], b['node1']
            if u == v:
                continue
            adj[u].append((v, key, b['length']))
            adj[v].append((u, key, b['length']))
        for u in adj:
            adj[u].sort(key=lambda t: (t[0], t[1]))

        conns = sorted(c for c, n in topo.nodes.items()
                       if n['type'] == 'connector')

        def dijkstra(src):
            dist = {src: 0.0}
            prev = {}
            heap = [(0.0, src)]
            while heap:
                du, u = heapq.heappop(heap)
                if du > dist[u] + 1e-9:
                    continue
                for v, k, w in adj[u]:
                    nd = du + w
                    if v not in dist or nd < dist[v] - 1e-9:
                        dist[v] = nd
                        prev[v] = (u, k)
                        heapq.heappush(heap, (nd, v))
            return dist, prev

        # 全部连接器对的最长路径（按长度降序、端点字典序升序，确定性取首）
        all_pairs = []
        for s in conns:
            dist, _ = dijkstra(s)
            for t in conns:
                if t <= s:
                    continue
                if t in dist:
                    all_pairs.append((dist[t], s, t))
        if not all_pairs:
            # 退化数据（连接器不足 2 个或不连通）：退回 v4 单根最长分支
            fallback = sorted(
                topo.branches,
                key=lambda k: (-topo.branches[k]['length'], k))[0]
            b = topo.branches[fallback]
            self.trunk_path = [fallback]
            self.trunk_path_joints = [b['node0'], b['node1']]
            self.trunk_path_length = b['length']
            self.trunk_path_endpoints = (b['node0'], b['node1'])
            self.trunk_path_set = {fallback}
            self._trunk_index = {fallback: 0}
            self.log_phase('主干',
                           f"无连接器—连接器路径，退回最长单根 {fallback}"
                           f"（{b['length']:.1f}mm）")
            return self.trunk_path
        all_pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
        total, a, b = all_pairs[0]
        if len(all_pairs) > 1:
            self.trunk_path_second = (all_pairs[1][0], all_pairs[1][1],
                                      all_pairs[1][2])
        # 重建路径 a → b（分支序列）
        _, prev = dijkstra(a)
        keys = []
        u = b
        while u != a:
            pu, k = prev[u]
            keys.append(k)
            u = pu
        keys.reverse()
        # 路径关节序列（链式拼接）
        joints = [a]
        cur = a
        for k in keys:
            ns = topo.branch_nodes(k)
            nxt = ns[-1] if ns[0] == cur else ns[0]
            joints.append(nxt)
            cur = nxt
        # 走向：字典序较大的端点在左（确定性；IP 实测：CON08 左、CON01 右，
        # 与校核值 CON08→CON01 一致，也与 v4“CON01 向右”的约定一致）
        keys.reverse()
        joints.reverse()
        a, b = b, a
        self.trunk_path = keys
        self.trunk_path_joints = joints
        self.trunk_path_length = total
        self.trunk_path_endpoints = (a, b)
        self.trunk_path_set = set(keys)
        self._trunk_index = {k: i for i, k in enumerate(keys)}
        # 直线跨度：总长 − 路径分支内自环段长（自环画三角形，不推进直线）
        loop_len = 0.0
        for k in keys:
            for pc in topo.branches[k]['pieces']:
                if pc['na'] == pc['nb']:
                    loop_len += pc['length']
        self.trunk_path_span = total - loop_len
        second_txt = ''
        if self.trunk_path_second:
            sl, s1, s2 = self.trunk_path_second
            second_txt = f"；次长 {sl:.1f}mm（{s1}→{s2}）"
        self.log_phase('主干',
                       f"连接器—连接器最长路径 {a}→{b}，总长 {total:.1f}mm，"
                       f"{len(keys)} 根分支，{len(joints)} 个关节，"
                       f"直线跨度 {self.trunk_path_span:.1f}mm{second_txt}")
        return self.trunk_path

    # ---------- 路径分支的走向与跨度 ----------
    def _path_forward(self, key):
        """该路径分支的 node0→node1 方向是否与路径走向一致。"""
        i = self._trunk_index[key]
        return self.topo.branches[key]['node0'] == self.trunk_path_joints[i]

    def _path_ordered_pieces(self, key):
        """路径分支的各段，按路径走向排列（na/nb 已换成走向方向）。"""
        pieces = self.topo.branches[key]['pieces']
        if self._path_forward(key):
            return [{'seg': pc['seg'], 'na': pc['na'], 'nb': pc['nb'],
                     'length': pc['length']} for pc in pieces]
        return [{'seg': pc['seg'], 'na': pc['nb'], 'nb': pc['na'],
                 'length': pc['length']} for pc in reversed(pieces)]

    def _trunk_joint_x(self):
        """{关节: 沿路径的 x 坐标}（第一关节 x=0），含路径分支的中间关节
        （如 Body.113 上的 CLP01）。自环段不推进 x。"""
        xs = {}
        x = 0.0
        for i, key in enumerate(self.trunk_path):
            j0 = self.trunk_path_joints[i]
            xs[j0] = x
            for pc in self._path_ordered_pieces(key):
                if pc['na'] == pc['nb']:
                    continue
                x += pc['length']
                if pc['nb'] != self.trunk_path_joints[i + 1]:
                    xs.setdefault(pc['nb'], x)
        xs[self.trunk_path_joints[-1]] = x
        return xs

    # ---------- 拓扑分析：分支树（以整条路径为根） ----------
    def build_branch_tree(self):
        """分支树 BFS：主干分量以 28 根路径分支为根（depth 0），其余分支
        按邻接 BFS 挂接；其他分量（IP 无）沿用 v4 做法（最长分支为根）。"""
        topo = self.topo
        node_branches = defaultdict(list)
        for key in topo.branches:
            for nd in topo.branch_nodes(key):
                node_branches[nd].append(key)
        self.tree = {}
        self.tree_root = None
        for comp in topo.components():
            comp_set = set(comp)
            if self.trunk_path_set & comp_set:
                roots = [k for k in self.trunk_path if k in comp_set]
                if self.tree_root is None:
                    self.tree_root = roots[0]
                for r in roots:
                    self.tree[r] = {"parent": None, "anchor": None,
                                    "depth": 0, "children": []}
                queue = list(roots)
                visited = set(roots)
            else:
                root = max(comp, key=lambda k: topo.branches[k]['length'])
                if self.tree_root is None:
                    self.tree_root = root
                self.tree[root] = {"parent": None, "anchor": None,
                                   "depth": 0, "children": []}
                queue = [root]
                visited = {root}
            while queue:
                cur = queue.pop(0)
                for nd in topo.branch_nodes(cur):
                    for nb in sorted(node_branches[nd]):
                        if nb in visited or nb not in comp_set:
                            continue
                        visited.add(nb)
                        self.tree[nb] = {"parent": cur, "anchor": nd,
                                         "depth": self.tree[cur]["depth"] + 1,
                                         "children": []}
                        self.tree[cur]["children"].append(nb)
                        queue.append(nb)
        # 排序：子分支按长度降序（长的先画），同长按 key
        for info in self.tree.values():
            info["children"].sort(
                key=lambda k: (-self.topo.branches[k]["length"], k))
        return self.tree

    # ---------- 关节清点（H6：先找齐再画） ----------
    def inventory_all_joints(self):
        """清点全部（父分支，关节）组的子分支并记入阶段日志。
        trunk_inventory 改为路径关节版：29 个路径关节（+ 中间关节）
        各挂接哪些分支，按沿路径的 x 排序。"""
        groups = defaultdict(list)
        for key, info in self.tree.items():
            if info["parent"] is None:
                continue
            groups[(info["parent"], info["anchor"])].append(key)
        for (parent, joint), children in sorted(groups.items()):
            children = sorted(
                children,
                key=lambda k: (-self.topo.branches[k]['length'], k))
            self.joint_inventory.append((parent, joint, children))
        # 路径关节清点（供 layout.json trunk_inventory 查阅）
        inv_map = {(p, j): c for (p, j, c) in self.joint_inventory}
        xs = self._trunk_joint_x()
        self.trunk_inventory = []
        for j, x in sorted(xs.items(), key=lambda kv: (kv[1], kv[0])):
            attached = []
            for (p, jj), c in inv_map.items():
                if jj == j and p in self.trunk_path_set:
                    attached.extend(c)
            attached = sorted(set(attached),
                              key=lambda k: (-self.topo.branches[k]['length'],
                                             k))
            self.trunk_inventory.append((j, round(x, 1), attached))
        self.log_phase("清点", "清点 %d 个关节组、%d 根分支；主干路径 %d 个关节" % (
            len(self.joint_inventory), len(self.tree) - len(self.trunk_path),
            len(self.trunk_path_joints)))
        return self.joint_inventory

    # ---------- 路径主干放置（整条共线水平） ----------
    def _layout_path_branch(self, key, ox, oy, xs):
        """一根路径分支的直线放置（不做干涉试算——路径先画，几何由弧长唯一确定）：
        各直段共线水平（y=oy），自环段画在关节上的小三角形（方向固定 +90°，
        与主干线只交于关节顶点，绝不共线重叠）。
        返回与 layout_branch 同格式的 res dict。"""
        joints = self._joints(key)
        pieces = self._path_ordered_pieces(key)
        forward = self._path_forward(key)
        pos = {}
        seg_pts = {}
        j0 = self.trunk_path_joints[self._trunk_index[key]]
        pos[j0] = (ox + xs[j0], oy)
        cur = j0
        for pc in pieces:
            sg = pc['seg']
            if pc['na'] == pc['nb']:
                if pc.get('stub'):
                    # §十八：退化短管画直线短线头（不是环），固定朝上
                    tick = [pos[cur], add_pt(pos[cur],
                                             unit_from_angle(90.0),
                                             pc['length'])]
                    seg_pts[sg] = tick if forward else tick[::-1]
                    continue
                # 自环三角形：固定朝上（+90°），三边均不与主干线共线
                tri = self.triangle_loop(pos[cur], 90.0, pc['length'])
                seg_pts[sg] = tri if forward else tri[::-1]
                continue
            far = pc['nb']
            pos[far] = (ox + xs[far], oy)
            pts = [pos[cur], pos[far]]
            seg_pts[sg] = pts if forward else pts[::-1]
            cur = far
        joint_pos = {i: pos[nd] for i, nd in enumerate(joints)}
        # 整根点列（按分支自身 node0→node1 顺序组装，与 layout_branch 一致）
        points = []
        for pc in self.topo.branches[key]['pieces']:
            pts = seg_pts[pc['seg']]
            if not points:
                points += pts
            else:
                points += pts[1:]
        if len(points) < 2:
            return None
        return {'points': points,
                'pieces': {sg: (pts[0], pts[-1])
                           for sg, pts in seg_pts.items()},
                'seg_pts': seg_pts, 'joint_pos': joint_pos,
                'bends': [], 'warnings': [], 'n_bad': 0}

    def place_path_trunk(self, origin):
        """整条路径主干共线水平放置：29 个路径关节全部落在 y=origin_y 的
        直线上，按路径顺序、各段按真实弧长排。返回 True/False。"""
        ox, oy = origin
        xs = self._trunk_joint_x()
        for key in self.trunk_path:
            res = self._layout_path_branch(key, ox, oy, xs)
            if res is None:
                self.warnings.append(f"主干路径分支 {key} 放置失败")
                return False
            self._commit(key, res)
            self.placed_kind[key] = 'trunk'
        return True

    # ---------- 分量布局（主干分量先放路径，其余按 BFS 深度放置） ----------
    def layout_component(self, comp_keys, origin):
        """一个连通分量的展开：主干分量先放整条路径主干，再按 BFS 深度
        放置其余分支；非主干分量沿用 v4（真环先画，否则最长分支为主干）。"""
        comp = set(comp_keys)
        rings, self_loops, parallels = self.topo.find_cycles(comp_keys)
        self.cycle_info[len(self.cycle_info)] = {'rings': rings, 'self_loops': self_loops,
                                                 'parallel_pairs': parallels}
        for sg in self_loops:
            self.self_loop_segs.add(sg)
        for (a, b_) in parallels:
            self.parallel_sib[a].append(b_)
            self.parallel_sib[b_].append(a)
        is_trunk_comp = bool(self.trunk_path_set & comp)
        started = False
        if is_trunk_comp:
            if rings:
                self.warnings.append(
                    f"主干分量含 {len(rings)} 个真环，v5 路径主干优先放置，"
                    f"环分支按受约束段处理（§六环优先未实现，见清单局限）")
            started = self.place_path_trunk(origin)
            if not started:
                self.warnings.append("主干路径放置失败，退回单根最长分支作主干")
                trunk = sorted(comp_keys,
                               key=lambda k: (-self.topo.branches[k]['length'], k))[0]
                started = self.place_trunk(trunk, origin)
        else:
            if rings:
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
        # BFS 放置：按（深度，长度降序，key）排序，父分支先于子分支
        remaining = set(comp_keys) - set(self.placed)
        order = sorted(remaining,
                       key=lambda k: (self.tree[k]['depth'],
                                      -self.topo.branches[k]['length'], k))
        for k in order:
            if k in self.placed:
                continue
            if not any(n in self.node_pos for n in self._joints(k)):
                # 与已放置部分无连接节点（不应发生）：另起主干
                self.warnings.append(f"{k} 与已放置部分无连接节点，另起主干放置")
                self.place_trunk(k, self.next_origin())
                continue
            if not self.place_branch_best(k):
                self.warnings.append(f"{k} 放置失败，强制另起主干")
                self.place_trunk(k, self.next_origin())

    # ---------- 放置侧搜索（阶段 4 前置）：顶层一级分支侧组合穷举 ----------
    def search_top_sides(self):
        """与 v4 同法、改选支：子树总长最大的 6 根一级分支（直接挂在路径
        上，IP 共 13 根一级分支），穷举 2^6=64 种侧组合，各跑一遍放置，
        选综合最优者作为 side_override。评分 = 居中偏差% + 0.5×X交叉数。
        一级分支是垂直居中的主杠杆（整棵侧枝随它上下翻）。"""
        def subtree_len(k):
            s = self.topo.branches[k]['length']
            for c in self.tree[k]['children']:
                s += subtree_len(c)
            return s

        d1 = [k for k, v in self.tree.items() if v['depth'] == 1]
        lv = sorted(d1, key=lambda k: (-subtree_len(k), k))[:TOP_SIDE_SEARCH_N]
        if not lv:
            return
        best = None
        for bits in itertools.product([0, 1], repeat=len(lv)):
            ov = dict(zip(lv, bits))
            trial = LayoutV5(self.topo, clearance=self.clearance,
                             verbose=False)
            trial.run_projection()
            trial.compute_trunk_path()
            trial.build_branch_tree()
            trial.assign_slots()
            trial.inventory_all_joints()
            trial.side_override = ov
            Layout.run(trial)
            dev = trial._center_dev_of_bbox(trial.bbox())
            n_x, n_near, n_ov = count_interference_detailed(trial)
            score = dev + 0.5 * n_x
            cand = (round(score, 9), round(dev, 9), n_x, n_near, bits)
            if best is None or cand < best[0]:
                best = (cand, ov, dev, n_x, n_near, n_ov)
        _, ov, dev, n_x, n_near, n_ov = best
        self.side_override = ov
        flipped = sorted(k for k, v in ov.items() if v == 1)
        self.log_phase('放置侧搜索',
                       f"穷举 {2 ** len(lv)} 种一级分支侧组合（{lv}），最优居中偏差 "
                       f"{dev:.2f}% X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}；"
                       f"翻转侧：{flipped if flipped else '无'}")

    # ---------- 六阶段主流程 ----------
    def run(self):
        self.log_phase('开始',
            f"分支 {len(self.topo.branches)} / 节点 {len(self.topo.nodes)} "
            f"/ 线段 {len(self.topo.segs)}")
        self.run_projection()          # 阶段 3：初始二维投影（PCA）
        self.compute_trunk_path()      # 阶段 2：主干路径（连接器—连接器最长路径）
        self.build_branch_tree()       # 阶段 2：拓扑分析（分支树 BFS，路径为根）
        self.assign_slots()            # 阶段 4 准备：槽位分配
        self.inventory_all_joints()    # H6：先找齐再画
        self.search_top_sides()        # 阶段 4 前置：一级分支侧组合穷举（放置即居中）
        Layout.run(self)               # 阶段 4：结构化布局（路径主干 + 正交放置）
        n_x, n_near, n_ov = count_interference_detailed(self)
        self.log_phase('放置完成', f"残留 X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}")
        # 阶段 5：居中与消交叉交替（最多 5 轮），直至两者同时达标或一轮内无翻转
        # v5 改动：消交叉至少跑一次——放置后居中/重叠已达标时直接退出会跳过
        # 消交叉；IP 实测这一步把 X 从 16 降到 11（间距 2→0），居中不变。
        untangle_tried = False
        for rnd in range(5):
            n_x, n_near, n_ov = count_interference_detailed(self)
            dev = self._center_dev_of_bbox(self.bbox())
            if n_ov == 0 and dev <= CENTER_TOL_V5 * 100.0:
                if not untangle_tried:
                    untangle_tried = True
                    self.flip_untangle()
                    continue
                break
            flips_before = len(self.center_flips) + len(self.untangle_flips)
            self.flip_center()         # 阶段 5a：居中爬山（180° 翻转）
            n_x, n_near, n_ov = count_interference_detailed(self)
            self.log_phase('居中完成', f"残留 X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}")
            self.flip_untangle()       # 阶段 5b：消交叉爬山（180° 翻转，守居中）
            untangle_tried = True
            flips_after = len(self.center_flips) + len(self.untangle_flips)
            if flips_after == flips_before:
                break
        self.recenter_bbox()
        self.center_info = self.measure_trunk_center()
        ci = self.center_info
        self.log_phase('居中',
            f"主干路径 {ci.get('trunk')} 中点=({ci.get('trunk_x_mid')}, {ci.get('trunk_y')})mm，"
            f"图纸中心=({ci.get('center_x')}, {ci.get('center_y')})mm，"
            f"横偏差 {ci.get('dev_x_mm')}mm（{ci.get('dev_x_pct')}%），"
            f"竖偏差 {ci.get('dev_y_mm')}mm（{ci.get('dev_y_pct')}%），"
            f"共线最大偏差 {ci.get('trunk_max_y_dev_mm')}mm")
        return self

    # ---------- 主干中点（路径版：两端关节的中点） ----------
    def _trunk_mid(self):
        p0 = self.node_pos[self.trunk_path_joints[0]]
        p1 = self.node_pos[self.trunk_path_joints[-1]]
        return ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)

    # ---------- 居中测量（v5：路径主干三查——共线/水平/居中） ----------
    def measure_trunk_center(self):
        """路径主干居中测量：(a)29 个路径关节共线 (b)水平 (c)路径中点与
        图纸中心横竖偏差（平移不变量）。dev 取横竖两方向的最大值。"""
        if not self.trunk_path or self.trunk_path_joints[0] not in self.node_pos:
            return {'ok': False, 'reason': '主干路径未放置'}
        ys = [self.node_pos[j][1] for j in self.trunk_path_joints]
        trunk_y = sum(ys) / len(ys)
        max_y_dev = max(abs(y - trunk_y) for y in ys)
        p0 = self.node_pos[self.trunk_path_joints[0]]
        p1 = self.node_pos[self.trunk_path_joints[-1]]
        trunk_x_mid = (p0[0] + p1[0]) / 2.0
        ang = angle_of(p0, p1) % 180.0
        ang_from_h = min(ang, 180.0 - ang)
        xmin, ymin, xmax, ymax = self.bbox()
        h = ymax - ymin
        w = xmax - xmin
        cy = (ymin + ymax) / 2.0
        cx = (xmin + xmax) / 2.0
        dev_y = abs(trunk_y - cy)
        dev_x = abs(trunk_x_mid - cx)
        dev_y_pct = dev_y / h * 100.0 if h > 0 else 0.0
        dev_x_pct = dev_x / w * 100.0 if w > 0 else 0.0
        a, b = self.trunk_path_endpoints
        return {
            'ok': True,
            'trunk': f"{a}→{b}（{len(self.trunk_path)}根）",
            'trunk_y': round(trunk_y, 2),
            'trunk_x_mid': round(trunk_x_mid, 2),
            'trunk_angle_deg': round(ang, 2),
            'trunk_angle_from_horizontal_deg': round(ang_from_h, 2),
            'trunk_max_y_dev_mm': round(max_y_dev, 4),
            'trunk_path_joints': len(self.trunk_path_joints),
            'trunk_path_length_mm': round(self.trunk_path_length, 1),
            'trunk_path_span_mm': round(self.trunk_path_span, 1),
            'trunk_path_branches': len(self.trunk_path),
            'center_y': round(cy, 2),
            'center_x': round(cx, 2),
            'dev_x_mm': round(dev_x, 2),
            'dev_x_pct': round(dev_x_pct, 2),
            'dev_y_mm': round(dev_y, 2),
            'dev_y_pct': round(dev_y_pct, 2),
            'dev_mm': round(max(dev_x, dev_y), 2),
            'dev_pct': round(max(dev_x_pct, dev_y_pct), 2),
            'height': round(h, 1),
            'width': round(w, 1),
            'tol_pct': TRUNK_CENTER_TOL * 100.0,
        }

    # ---------- 规则检查清单（v5：H1 改为路径主干三查，新增 S8 主干路径） ----------
    def run_checklist(self, det_md5_a=None, det_md5_b=None, det_pass=None):
        """在 v4 清单基础上改 H1（路径主干）并追加 S8（主干路径）。
        H2–H9 与 v4 相同（长度/拓扑/压着画/全画出/先清点/投影/确定性/正交）。"""
        checklist, _ = super().run_checklist(
            det_md5_a=det_md5_a, det_md5_b=det_md5_b, det_pass=det_pass)
        ci = self.center_info

        # H1 路径主干——(a)共线 (b)水平 (c)横竖两方向居中
        h1a = ci.get('trunk_max_y_dev_mm', 99) <= TRUNK_COLLINEAR_TOL_MM
        h1b = ci.get('trunk_angle_from_horizontal_deg', 99) <= TRUNK_ANGLE_TOL
        h1c = (ci.get('dev_x_pct', 99) <= ci.get('tol_pct', 5.0)
               and ci.get('dev_y_pct', 99) <= ci.get('tol_pct', 5.0))
        h1_pass = bool(ci.get('ok')) and h1a and h1b and h1c
        checklist['hard'][0] = {
            'id': 'H1',
            'rule': '§五/§十三 路径主干整条拉直、水平画在图正中间',
            'name': '路径主干共线、水平且居中（横竖两方向）',
            'value': (f"主干路径 {ci.get('trunk')}，总长 "
                      f"{ci.get('trunk_path_length_mm')}mm，"
                      f"{ci.get('trunk_path_joints')} 个路径关节；"
                      f"(a)共线：最大 |y−y主干| = {ci.get('trunk_max_y_dev_mm')}mm；"
                      f"(b)水平：与水平夹角 {ci.get('trunk_angle_from_horizontal_deg')}°；"
                      f"(c)居中：路径中点=({ci.get('trunk_x_mid')}, {ci.get('trunk_y')})mm，"
                      f"图纸中心=({ci.get('center_x')}, {ci.get('center_y')})mm；"
                      f"横偏差 {ci.get('dev_x_mm')}mm（{ci.get('dev_x_pct')}% 图纸宽 "
                      f"{ci.get('width')}mm），竖偏差 {ci.get('dev_y_mm')}mm"
                      f"（{ci.get('dev_y_pct')}% 图纸高 {ci.get('height')}mm）"),
            'threshold': (f"(a)共线 ≤ {TRUNK_COLLINEAR_TOL_MM}mm；"
                          f"(b)夹角 ≤ {TRUNK_ANGLE_TOL}°；"
                          f"(c)横竖偏差均 ≤ {TRUNK_CENTER_TOL * 100:.0f}%"),
            'pass': h1_pass,
        }

        # S1 说明里的版本号 v4 → v5
        for s in checklist['soft']:
            if s['id'] == 'S1':
                s['note'] = ('v5 目标 0；残留交叉点位置已记入 layout.json 的 crossings，'
                             '查看器中以红色标记标出')

        # S8 主干路径（新增）
        second_txt = '无（连接器对不足）'
        if self.trunk_path_second:
            sl, s1, s2 = self.trunk_path_second
            second_txt = f"{sl:.1f}mm（{s1}→{s2}）"
        a, b = self.trunk_path_endpoints
        checklist['soft'].append({
            'id': 'S8', 'rule': '§五 主干定义', 'name': '主干路径',
            'value': (f"{a}→{b}，总长 {self.trunk_path_length:.1f}mm，"
                      f"{len(self.trunk_path)} 根分支，"
                      f"{len(self.trunk_path_joints)} 个关节，"
                      f"直线跨度 {self.trunk_path_span:.1f}mm；次长 {second_txt}"),
            'note': ('主干 = 连接器到连接器之间最长路径（§五，2026-11-17 20:34 '
                     '用户纠正）；由程序枚举全部连接器两两 Dijkstra 算出，未写死；'
                     '直线跨度小于总长是路径内自环段（Body.150 SEG32 5.1mm）所致'),
        })

        checklist['all_hard_pass'] = all(c['pass'] for c in checklist['hard'])
        return checklist, checklist['all_hard_pass']


# ---------------------------------------------------------------- 输出

def layout_data_v5(layout, include_checklist=None):
    """组装 v5 layout.json（在 v4 格式上改版本号并新增 trunk_path）。"""
    data = layout_data_v4(layout, include_checklist=include_checklist)
    data['meta']['source'] = 'unfold_2d_v5.py'
    data['meta']['version'] = 'v5'
    a, b = layout.trunk_path_endpoints
    data['meta']['trunk_path'] = {
        'endpoints': [a, b],
        'length_mm': round(layout.trunk_path_length, 1),
        'span_mm': round(layout.trunk_path_span, 1),
        'branches': len(layout.trunk_path),
        'branch_list': list(layout.trunk_path),
        'joints': len(layout.trunk_path_joints),
        'joint_list': list(layout.trunk_path_joints),
    }
    data['stats']['trunk_path_length_mm'] = round(layout.trunk_path_length, 1)
    data['stats']['trunk_path_branches'] = len(layout.trunk_path)
    data['stats']['trunk_path_endpoints'] = f"{a}→{b}"
    return data


def canonical_json_v5(layout):
    """确定性哈希用的规范序列化（不含清单、无时间戳、键排序）。"""
    data = layout_data_v5(layout, include_checklist=None)
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def write_layout_json_v5(layout, checklist, out_path):
    data = layout_data_v5(layout, include_checklist=checklist)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return out_path


def write_checklist_md_v5(checklist, out_path, topo_path):
    """检查清单 Markdown（逐条打勾/打叉，附实测数值）。"""
    lines = []
    lines.append('# v5 规则检查清单')
    lines.append('')
    lines.append(f'输入：`{topo_path}`')
    lines.append('程序：`unfold_2d_v5.py`')
    lines.append('')
    lines.append('## 硬规则（任一失败则退出码非 0，不生成 DXF/Excel/查看器）')
    lines.append('')
    for c in checklist['hard']:
        mark = '✅ 通过' if c['pass'] else '❌ 失败'
        lines.append(f"- **{c['id']} {c['name']}**（{c['rule']}）：{mark}")
        lines.append(f"  - 实测：{c['value']}")
        lines.append(f"  - 阈值：{c['threshold']}")
    lines.append('')
    lines.append('## 软性项（警告，不阻塞）')
    lines.append('')
    for c in checklist['soft']:
        lines.append(f"- **{c['id']} {c['name']}**（{c['rule']}）：{c['value']}")
        lines.append(f"  - 说明：{c['note']}")
    lines.append('')
    lines.append('## 结论')
    lines.append('')
    if checklist['all_hard_pass']:
        lines.append('硬规则全部通过，DXF/Excel 已生成。')
    else:
        failed = [c['id'] for c in checklist['hard'] if not c['pass']]
        lines.append(f"硬规则失败：{', '.join(failed)}。未生成 DXF/Excel/查看器。")
    lines.append('')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return out_path


# ---------------------------------------------------------------- 主入口

def build_layout(topo, clearance, verbose=True):
    layout = LayoutV5(topo, clearance=clearance, verbose=verbose)
    layout.run()
    return layout


def _subprocess_hash(topo_path, clearance):
    """独立子进程（全新 PYTHONHASHSEED）跑布局并返回 MD5；
    失败时返回 None。"""
    try:
        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__), topo_path,
             '--hash-only', '--clearance', str(clearance)],
            capture_output=True, text=True, timeout=1200)
        if r.returncode != 0:
            return None
        h = r.stdout.strip().splitlines()
        return h[-1].strip() if h else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description='3D拓扑 → 2D展开图（v5，§五路径主干）')
    ap.add_argument('topo_json')
    ap.add_argument('-o', '--out', default='.')
    ap.add_argument('--clearance', type=float, default=CLEARANCE_DEFAULT)
    ap.add_argument('--hash-only', action='store_true',
                    help='仅输出布局 MD5（供确定性检查的子进程用）')
    args = ap.parse_args()

    topo = Topo(args.topo_json)

    if args.hash_only:
        # 哈希模式：只打印 MD5，不打印其他任何东西
        layout = build_layout(topo, args.clearance, verbose=False)
        h = hashlib.md5(canonical_json_v5(layout).encode('utf-8')).hexdigest()
        print(h)
        return 0

    print(f"输入：分支 {len(topo.branches)} / 节点 {len(topo.nodes)} / "
          f"线段 {len(topo.segs)}")
    comps = topo.components()
    print(f"连通分量：{len(comps)} 个，规模 {[len(c) for c in comps]}")
    for i, c in enumerate(comps):
        rings, sl, pp = topo.find_cycles(c)
        print(f"  分量{i + 1}：真环 {len(rings)} 个，自环线段 {len(sl)} 条，"
              f"平行对 {len(pp)} 对")
    print(f"环分类单测：{_ring_test_status()}")

    layout = build_layout(topo, args.clearance, verbose=True)
    a, b = layout.trunk_path_endpoints
    print(f"[主干路径] {a}→{b}，总长 {layout.trunk_path_length:.1f}mm，"
          f"{len(layout.trunk_path)} 根分支，{len(layout.trunk_path_joints)} 个关节")

    # 确定性：本进程哈希 vs 独立子进程哈希
    hash1 = hashlib.md5(canonical_json_v5(layout).encode('utf-8')).hexdigest()
    print('[确定性] 本进程 MD5：%s，正在跑独立子进程…' % hash1)
    hash2 = _subprocess_hash(args.topo_json, args.clearance)
    print('[确定性] 子进程 MD5：%s' % hash2)
    det_pass = (hash2 is not None and hash1 == hash2)

    checklist, hard_pass = layout.run_checklist(
        det_md5_a=hash1, det_md5_b=hash2, det_pass=det_pass)

    os.makedirs(args.out, exist_ok=True)
    lj = os.path.join(args.out, 'layout.json')
    ck = os.path.join(args.out, 'checklist_v5.md')
    write_layout_json_v5(layout, checklist, lj)
    write_checklist_md_v5(checklist, ck, args.topo_json)
    print(f"已写 {lj}")
    print(f"已写 {ck}")

    if not hard_pass:
        failed = [c['id'] for c in checklist['hard'] if not c['pass']]
        print(f"硬规则失败：{', '.join(failed)}，不生成 DXF/Excel，退出码 1")
        return 1

    dxf = os.path.join(args.out, 'unfold_v5.dxf')
    xls = os.path.join(args.out, 'unfold_v5.xlsx')
    write_dxf(layout, dxf)
    write_excel(layout, xls)
    print(f"已写 {dxf}")
    print(f"已写 {xls}")
    print('硬规则全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
