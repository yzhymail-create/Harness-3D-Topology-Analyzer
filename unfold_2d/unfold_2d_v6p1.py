#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仪表线束（IP-Harness）3D → 2D 展开 v6p1。

相对 v6 的唯一改动：平行对画法改按《需求说明.md》§十五（2026-11-17 22:21
用户亲定）——平行对只画一根，留走主干/脊线那根，被隐藏的那根不画线但
数据不丢（记入 plan.json 的 hidden_parallel、checklist、Excel 与 layout.json
中保留分支的 parallel_hidden 标注，供查看器弹窗展示两根管子的数据）。
打折（bends）画法随之作废：被留下的那根按真实长度画直，端点间距按它的
长度定。判定按脊线归属、不按长度（IP 实测：BN04 对里主干成员是较短的
Body.113 17.0mm，不是较长的 Body.114 20.0mm）。自环（Body.96 小三角）
不是平行对，不动。v6 原文件不改，本文件是 v6 的完整复制 + §十五增量。

相对 v5 的根本改动：分支画法改按《需求说明.md》§十四（2026-11-17 20:53–21:00
语音，用户亲定）——分支逐层最长路径规则：
  1. 主干 = 最长连接器—连接器路径（§五，v5 已实现），整条拉直水平居中。
  2. 找出主干上全部支点（关节），每个关节上挂了几个分支先数清楚。
  3. 每个关节：从关节出发，计算到该点上所有分支上的所有连接器的全部
     路径，找出最长的一条记下来；该最长路径拉直画出，垂直于上级主干。
  4. 剩下的分支形成新分支，沿已画出的主分支往下走，每个关节重复 2–3 步，
     逐层做下去，直到全部画完。
  5. 铁律：先算完再画，不许边算边画。

实现要点（与 v5 的区别）：
  - 分解（全部计算在绘制之前完成）：段级生成树（109 边，平行对去掉一个、
    自环段除外）上做逐层最长路径分解。每个关节的每个侧向分量取一条最长
    路径（简单路径，不重复经过同一关节）作为一条“脊线”（spine）；脊线
    整体拉直、垂直于上级脊线；同关节最长者为主分支（优先取投影侧），
    其余按 §十三 槽位（前两根垂直分两侧，第三根起偏 30°）挂同一关节。
    每个脊线分支归属唯一；纯自环分支（Body.96）不进脊线，另行放置；
    平行单段分支（Body.114/Body.48）按 §十五整根隐藏（v6p1）。
  - “路径”的定义：段级简单路径（不重复经过同一关节）。分支级路径可能
    两次经过同一关节（IP 实测：BN19 出发经 Body.48→Body.159 的分支级
    路径长 879.0mm→CON19，但两次经过 BN01——一次为 Body.46 端点、一次
    为 Body.159 中部关节；画直后 BN01 会有两个位置，拓扑不一致），故
    不取；段级最长简单路径为 854.1mm→CON12。主干路径两种定义同路
    （CON08→CON01；分支级 2343.4mm 含 Body.150 自环段 5.1mm，段级
    2338.4mm 不含，主干仍按 v5 分支级口径报告）。
  - 放置：脊线为单位整条放置（先算出全部关节位置，再逐根提交分支），
    保证脊线共线；§十五起平行对只画一根（留脊线/主干那根按真实长度
    画直，不再打折），被隐藏的平行段（Body.46 的 SEG11、Body.134 的
    SEG22、Body.48、Body.114）不画线；自环三角形 24 朝向试选。
  - 翻转粒度：扁平树（同脊线分支皆为脊线首根的子节点），_rotation_safe
    天然只允许整条脊线旋转，脊线中部分支转不动（会断拓扑），故居中/
    消交叉翻转不破坏脊线拉直。
  - 两阶段分离：第一阶段只计算，产出完整方案 plan.json（主干关节表、
    每关节侧枝数、每关节最长路径及长度、槽位分配），写盘；第二阶段只按
    plan.json 绘制。清单 H6 验证方案完整先于放置开始（记 seq 号）。
  - 清单 H1–H10（任务书定版）：H1 路径主干共线/水平/居中；H2 长度 1:1；
    H3 拓扑不变；H4 零压着画；H5 全画出；H6 先算完再画（plan.json 完整
    先于放置）；H7 投影步已执行；H8 确定性；H9 侧枝正交（逐条脊线与上级
    夹角 90°±30°k，100%）；H10 每关节主分支拉直（该路径全部关节共线，
    max 偏差 ≤0.01mm，逐条列出）。DXF 逐块回读（110/110 与 layout.json
    一致）是交付前验证步骤，不占清单编号；失败则退出码非 0。
  - H1(c) 竖向居中豁免（2026-11-17 21:39 用户决定）：名义阈值仍 5%，实测
    14.45% 已接受（BN19 脊线 854.1mm 独大，结构性下限），见
    H1_VERTICAL_EXEMPTION；横向仍按 5% 硬查。

用法：
  python3 unfold_2d_v6p1.py <topology.json> -o <outdir> [--clearance 5.0]
  python3 unfold_2d_v6p1.py <topology.json> --hash-only   # 内部用：只打印 layout.json MD5

输出（outdir）：unfold_v6p1.dxf、unfold_v6p1.xlsx、layout.json、plan.json、
checklist_v6p1.md。硬失败时只写 layout.json、plan.json 与 checklist_v6p1.md，
不写 DXF/Excel。

运行环境：plain python3 即可；ezdxf 不在系统 Python 里时用 ~/workspace/.pylibs 兜底。
多连通分量：每分量各取一条最长连接器—连接器路径作该分量脊线 0（主分量
即全局主干，H1 只查主分量）；IP 只有 1 个分量，多分量逻辑未在真实多分量
数据上验证（地板 7 分量待后续任务）。
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
from collections import defaultdict, deque

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ezdxf 兜底：系统 Python 没有时用 ~/workspace/.pylibs（同 v4/v5 做法）
try:
    import ezdxf  # noqa: F401
except ImportError:
    _pylibs = os.path.expanduser("~/workspace/.pylibs")
    if os.path.isdir(_pylibs) and _pylibs not in sys.path:
        sys.path.insert(0, _pylibs)

from unfold_2d_v3 import (
    Topo, Layout, write_dxf, write_excel, dist, angle_of,
    seg_proper_intersect, seg_collinear_overlap, seg_seg_dist,
    pt_eq, pt_seg_dist, unit_from_angle, add_pt, rot_pt, CLEARANCE_DEFAULT,
    sanitize_block_name,
)
from unfold_2d_v3_fix import (
    layout_data, count_interference_detailed,
    TRUNK_CENTER_TOL, TRUNK_ANGLE_TOL,
)
from unfold_2d_v4 import (
    LayoutV4, layout_data_v4, _ring_test_status, SLOT_OFFSETS,
    ORTHO_TOL_DEG, _seg_intersection_point, line_angle, ang_diff,
)
from unfold_2d_v5 import (
    LayoutV5, layout_data_v5,
)

# ---------- v6p1 阈值 ----------
LEN_ERR_TOL_V6 = 0.1            # H2：最大长度误差 ≤0.1mm（同 v4/v5）
TRUNK_COLLINEAR_TOL_MM = 0.01   # H1a：路径关节共线，max|y−y主干| ≤0.01mm
CENTER_TOL_V6 = TRUNK_CENTER_TOL  # H1c：居中偏差 ≤5%（横竖都要查）
# H1(c) 竖向居中豁免——用户决定（2026-11-17 21:39），显式、有决策日期，
# 不藏默认参数、不改名义阈值。背景：v6 按 §十四 拉直后，BN19 脊线 854.1mm
# 一家独大（次长 BN09 脊线 471.1mm），上下伸展 850.5/469.1，64 种分法最优
# 竖偏差下限即 14.45%；进 5% 须把 BN19 脊线弯约 50°（违 §十四拉直）。
# 用户决定接受 14.45%，不弯脊线，布局不动。豁免只针对竖向（横向仍按 5%
# 硬查），且只豁免到已接受的实测值（14.45% + 0.05 舍入裕量）；超出仍失败，
# 不是空白支票。设为 None 即取消豁免。
H1_VERTICAL_EXEMPTION = {
    'decision_date': '2026-11-17 21:39',
    'decision': '用户决定放宽竖向，接受 14.45%',
    'accepted_dev_y_pct': 14.45,
}
H1_EXEMPTION_MARGIN_PCT = 0.05  # 豁免上限舍入裕量（百分点）
SPINE_STRAIGHT_TOL_MM = 0.01    # H10：脊线共线，关节到脊线垂距 ≤0.01mm
DXF_READBACK_TOL_MM = 0.01      # 交付前验证：DXF 回读逐块最大误差 ≤0.01mm（非清单项）
TOP_SIDE_SEARCH_N = 6           # 放置侧搜索：一级脊线中子树总长最大的 6 条
SPINE_DIR_TOL_DEG = 0.5         # 脊线方向与分配方向的容差（度）
# §二十二 过孔零件排除清单（分支 key → 原因），只在此处定义：
# 清单里的分支不是线束路径，展开入口加载拓扑后删掉（Topo.drop_branches），
# 拓扑文件本身不动。用户再认出过孔零件往这里加一行即可。
EXCLUDED_BRANCHES = {
    'C289': '过孔零件，非线束路径（2026-11-18 用户定）',
}


class LayoutV6p1(LayoutV5):
    """v6p1 布局：§十四 逐层最长路径（脊线分解）+ §五 路径主干 + §十三 正交。"""

    def __init__(self, topo, clearance=5.0, verbose=True):
        super().__init__(topo, clearance=clearance, verbose=verbose)
        # ---- §十四 分解结果（全部计算在绘制之前完成） ----
        self.spines = []            # 脊线列表（按创建顺序，即 BFS 层序）
        self.spine_by_id = {}       # id -> 脊线 dict
        self.layers = []            # 逐层记录 [(spine_id, joint, cands, main_idx)]
        self.tails = []             # 尾段记录 [{branch, spine, joint, far, seg, len, kind}]
        self.tail_by_seg = {}       # seg -> 尾段记录
        self.stub_groups = []       # stub 组 [{tail_seg, joint, children:[spine id]}]
        self.unassigned_branches = []  # [(branch, reason)] 未进脊线的分支
        self.branch_spine = {}      # branch -> spine id
        self.seg_tree_adj = {}      # 段级生成树邻接：node -> [(nbr, seg, len)]
        self.dropped_segs = {}      # seg -> 原因（平行对去掉的段）
        self.dropped_ring_segs = {}  # seg -> 原因（真环去掉的闭环段）
        self._comps = []            # 连通分量（topo.components() 顺序）
        self._main_comp = 0         # 主分量下标（含全局主干路径的分量）
        self._ring_spines = set()   # 按 §六整体画环的闭环脊线 id（H10 豁免）
        self._spine_joint_branch = {}  # (spine_id, joint) -> 该脊线中含此关节的最后分支
        self.side_override = {}     # {脊线首根分支: 0=分配侧, 1=翻转侧}（放置侧搜索用）
        self.plan = None            # 第一阶段产物（build_plan 组装，见 §十四铁律）
        self.plan_path = None       # plan.json 写盘路径（main 设定；None 则不写盘）
        self.excluded_branches = []  # §二十二：已排除分支 [{key, reason}]（build_layout 填）
        # ---- §十五 平行对只画一根（2026-11-17 22:21 用户定，v6p1 新增） ----
        # 全部在分解阶段（先算后画）定死，放置阶段只读。隐藏的是“线段”，
        # 不是“数据”：隐藏段的分支/长度/直径全数记入 hidden_parallel，
        # 并随 plan.json / checklist / Excel / layout.json 一并交付。
        self.hidden_parallel = []   # 隐藏记录 [{pair, nodes, hidden_*, kept_*, kind}]
        self.hidden_parallel_segs = set()   # 隐藏的线段 id（放置时跳过）
        self.hidden_whole_branches = set()  # 整根隐藏的分支（全部段都被隐藏）
        self.hidden_seg_len_by_branch = {}  # branch -> 该分支被隐藏段总长（H2 用）
        # ---- 环弦符号（2026-11-18 v6p2 配套，§六环优先 interim） ----
        # 弧长 < 两端点距离的受约束段（1:1 直线在几何上不可能），不画
        # 对角线，改画等边小三角符号（周长=弧长）于一端，另一端只记
        # 节点坐标；真值在弹窗里。登记 [{seg, branch, na, nb, length_mm,
        # dia_mm, at}]，merge 按自环通道改画小环符号。
        self.symbol_segs = []

    # ---------- 自测（v6p1 覆盖：§十五隐藏段按应画长度核查） ----------
    def validate(self):
        """v3 validate 的 §十五 版：长度误差按“应画长度”算——分支 3D 弧长
        减去该分支被隐藏平行段的长度（如 Body.46 应画 60.0−28.1=31.9mm，
        Body.134 应画 66.2−48.5=17.7mm）。其余统计与 v3 一致。
        len_errs 元组仍为 (分支, 3D长, 2D长, 误差)，其中误差 = 2D长 − 应画长
        （有隐藏段的分支误差不再等于 2D−3D，见 H2 注）。"""
        st = super().validate()
        len_errs = []
        for key, b in self.topo.branches.items():
            if key not in self.placed:
                continue
            pts = self.placed[key]['points']
            l2 = sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            expected = b['length'] - self.hidden_seg_len_by_branch.get(key, 0.0)
            len_errs.append((key, b['length'], l2, l2 - expected))
        st['max_len_err_mm'] = round(
            max((abs(e[3]) for e in len_errs), default=0.0), 2)
        st['len_errs'] = [(k, round(a, 1), round(c, 1), round(e, 2))
                          for (k, a, c, e) in len_errs if abs(e) > 0.05]
        st['hidden_parallel_segs'] = len(self.hidden_parallel_segs)
        st['hidden_whole_branches'] = len(self.hidden_whole_branches)
        return st

    # ---------- 段级生成树 ----------
    def build_seg_tree(self):
        """段级生成树：全部非自环段，平行对去掉一个（优先去掉非主干段，
        否则去掉较短的；主干段全保留）；真环每环去掉闭环段（地板 4 个，
        IP 为 0）。返回邻接表；IP 应为 109 边/110 节点且连通（自环 3 +
        平行对 4 去掉后 116−3−4=109）。"""
        trunk_segs = set()
        for k in self.trunk_path:
            for pc in self.topo.branches[k]['pieces']:
                trunk_segs.add(pc['seg'])
        rings, self_loops, parallels = self.topo.find_cycles(
            list(self.topo.branches.keys()))
        drop = {}
        for a, b in parallels:
            la, lb = self.topo.segs[a]['length'], self.topo.segs[b]['length']
            a_tr, b_tr = a in trunk_segs, b in trunk_segs
            if a_tr and not b_tr:
                drop[b] = f"平行对去段（{a} 为主干段，保留）"
            elif b_tr and not a_tr:
                drop[a] = f"平行对去段（{b} 为主干段，保留）"
            elif la <= lb:
                drop[a] = f"平行对去短段（{la:.1f} ≤ {lb:.1f}）"
            else:
                drop[b] = f"平行对去短段（{lb:.1f} ≤ {la:.1f}）"
        self.dropped_segs = drop
        # 真环去段（2026-11-18 地板修复）：段级生成树必须是树，否则
        # _lp_from 的无 visited 集 DFS 会枚举全部简单路径，40 秒吃光
        # 6GB（地板实测 OOM 根因：4 个真环，含 2 个 47 段大环）。
        # 每环去掉 find_cycles 的闭环段（rings[i][0]），剩下的恰为生成树；
        # 被去段仍随其分支画出（尾段），数据不丢。§六环优先画环未实现
        # （见 layout_component 警告），此处只保树结构，不改规则。
        ring_drop = {}
        for r in rings:
            closing = r[0]
            if closing not in drop:
                ring_drop[closing] = f"真环去段（环 {len(r)} 段，闭环段）"
        self.dropped_ring_segs = ring_drop
        adj = defaultdict(list)
        n_edge = 0
        for sg, s in self.topo.segs.items():
            if sg in self_loops or sg in drop or sg in ring_drop:
                continue
            adj[s['na']].append((s['nb'], sg, s['length']))
            adj[s['nb']].append((s['na'], sg, s['length']))
            n_edge += 1
        for u in adj:
            adj[u].sort(key=lambda t: (t[0], t[1]))
        self.seg_tree_adj = dict(adj)
        # 连通性核查（每分量一棵树）
        n_nodes = len(self.topo.nodes)
        seen = set()
        n_comp_seen = 0
        for start in sorted(adj):
            if start in seen:
                continue
            n_comp_seen += 1
            dq = deque([start])
            while dq:
                u = dq.popleft()
                if u in seen:
                    continue
                seen.add(u)
                for v, _, _ in adj[u]:
                    if v not in seen:
                        dq.append(v)
        self.log_phase('生成树',
                       f"段级生成树 {n_edge} 边 / {len(adj)} 节点，"
                       f"{n_comp_seen} 棵树；去掉平行段 {len(drop)} 条"
                       f"{sorted(drop)}，自环段 {len(self_loops)} 条")
        if ring_drop:
            # 单独记一条（IP 无真环时不记，布局 MD5 与历史值保持一致）
            self.log_phase('生成树（真环）',
                           f"真环 {len(rings)} 个，去闭环段 "
                           f"{len(ring_drop)} 条{sorted(ring_drop)}")
        if n_edge != n_nodes - n_comp_seen:
            self.warnings.append(
                f"段级生成树边数 {n_edge} ≠ 节点数−树数 "
                f"{n_nodes - n_comp_seen}，非树结构（不应发生）")
        return self.seg_tree_adj

    # ---------- 最长路径（树上 DFS，简单路径） ----------
    def _lp_from(self, start, forbidden, assigned_segs):
        """从 start 出发（不许经过 forbidden）、在未分配树边内，到连接器的
        最长简单路径。返回 (length, connector, seg_list, node_list,
        has_connector)。无连接器时退回最远叶节点（IP 不触发）。"""
        is_conn = self._is_conn
        adj = self.seg_tree_adj
        best = [0.0, None, [], [start]]
        if is_conn.get(start):
            best = [0.0, start, [], [start]]
        best_leaf = [0.0, None, [], [start]]
        stack = [(start, forbidden, 0.0, [], [start])]
        while stack:
            u, parent, L, segs, nodes = stack.pop()
            if is_conn.get(u) and L > best[0]:
                best = [L, u, list(segs), list(nodes)]
            # v not in nodes：只走简单路径（树上恒成立；有环漏网时防
            # 非简单路径爆炸——2026-11-18 地板教训：无此检查时环上 DFS
            # 会反复绕环，路径数指数增长）
            nbrs = [(v, sg, w) for v, sg, w in adj.get(u, [])
                    if sg not in assigned_segs and v != parent
                    and v not in nodes]
            if not nbrs and u != start and L > best_leaf[0]:
                best_leaf = [L, u, list(segs), list(nodes)]
            for v, sg, w in nbrs:
                stack.append((v, u, L + w, segs + [sg], nodes + [v]))
        if best[1] is not None:
            return tuple(best) + (True,)
        return tuple(best_leaf) + (False,)

    # ---------- 分量内最长连接器—连接器路径（非主分量脊线 0 用） ----------
    def _component_trunk_path(self, comp_keys):
        """与 compute_trunk_path 同法、限于一个分量：枚举分量内连接器两两
        最长路径（Dijkstra）。返回 (keys, joints, length, endpoints) 或 None
        （连接器不足 2 个时调用方退回最长单根）。"""
        topo = self.topo
        comp = set(comp_keys)
        adj = defaultdict(list)
        for key in sorted(comp):
            b = topo.branches[key]
            u, v = b['node0'], b['node1']
            if u == v:
                continue
            adj[u].append((v, key, b['length']))
            adj[v].append((u, key, b['length']))
        for u in adj:
            adj[u].sort(key=lambda t: (t[0], t[1]))
        conns = sorted(c for c in {n for k in comp
                                   for n in topo.branch_nodes(k)}
                       if topo.nodes[c]['type'] == 'connector')

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

        all_pairs = []
        for s in conns:
            dist, _ = dijkstra(s)
            for t in conns:
                if t <= s:
                    continue
                if t in dist:
                    all_pairs.append((dist[t], s, t))
        if not all_pairs:
            return None
        all_pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
        total, a, b = all_pairs[0]
        _, prev = dijkstra(a)
        keys = []
        u = b
        while u != a:
            pu, k = prev[u]
            keys.append(k)
            u = pu
        keys.reverse()
        joints = [a]
        cur = a
        for k in keys:
            ns = topo.branch_nodes(k)
            nxt = ns[-1] if ns[0] == cur else ns[0]
            joints.append(nxt)
            cur = nxt
        keys.reverse()
        joints.reverse()
        return keys, joints, total, (b, a)

    # ---------- §十四 分解：逐层最长路径（全部计算在绘制之前） ----------
    def decompose(self):
        """逐层最长路径分解（§十四）。先算后画：本方法只做计算，不碰任何
        放置状态；全部脊线、层记录、尾段、槽位都在放置开始前定死。

        脊线 dict：{id, level, comp, parent, anchor, branches, joints,
        segs, length, end, is_main, slot_offset, direction}。
        branches/joints/segs 均按路径顺序（从 anchor 到 end）。
        """
        topo = self.topo
        self._is_conn = {c: (n['type'] == 'connector')
                         for c, n in topo.nodes.items()}
        seg_branch = {sg: s['branch'] for sg, s in topo.segs.items()}
        self.build_seg_tree()
        self._comps = topo.components()
        trunk_set = set(self.trunk_path)
        self._main_comp = next(
            (i for i, c in enumerate(self._comps) if trunk_set & set(c)), 0)

        assigned_segs = set()
        assigned_branches = set()

        def mark_branch_assigned(key):
            assigned_branches.add(key)
            self.branch_spine[key] = current_spine_id[0]
            for pc in topo.branches[key]['pieces']:
                assigned_segs.add(pc['seg'])

        def spine_joints_ordered(branch_keys, first_joint):
            """按路径顺序组装脊线关节（含中间关节），连续重复去重
            （自环段会使同一关节连续出现两次，如 Body.150 的 BN03）。"""
            joints = []
            cur = first_joint
            for k in branch_keys:
                js = topo.branch_nodes(k)
                if js[0] == cur:
                    seq = js
                elif js[-1] == cur:
                    seq = js[::-1]
                else:
                    # 分支经中间关节进入（锚点在中部）：从 cur 所在位置起
                    idx = js.index(cur)
                    seq = js[idx:] if idx < len(js) - 1 else js[idx::-1]
                    # 进入方向由下一分支的连接点决定；此处取朝向远端一侧
                    # （路径段已定，见调用方保证的 branch_keys 顺序）
                if not joints:
                    joints += seq
                else:
                    joints += seq[1:]
                cur = joints[-1]
            out = []
            for j in joints:
                if not out or out[-1] != j:
                    out.append(j)
            return out

        current_spine_id = [0]
        self.spines = []
        self.spine_by_id = {}
        self.layers = []
        self.tails = []
        self.tail_by_seg = {}
        self.stub_groups = []

        def new_spine(level, comp, parent, anchor, branches, joints, segs,
                      length, end, is_main):
            sid = len(self.spines)
            current_spine_id[0] = sid
            s = {'id': sid, 'level': level, 'comp': comp, 'parent': parent,
                 'anchor': anchor, 'branches': list(branches),
                 'joints': list(joints), 'segs': list(segs),
                 'length': length, 'end': end, 'is_main': is_main,
                 'slot_offset': 0.0, 'direction': None,
                 'proj_ang': None, 'side_match': None}
            self.spines.append(s)
            self.spine_by_id[sid] = s
            for b in branches:
                mark_branch_assigned(b)
            return s

        # ---- 脊线 0：每分量一条（主分量 = 全局主干路径 v5 已算出） ----
        queue = deque()
        for ci, comp in enumerate(self._comps):
            comp_set = set(comp)
            if ci == self._main_comp:
                keys = list(self.trunk_path)
                joints = spine_joints_ordered(keys, self.trunk_path_joints[0])
                length = self.trunk_path_length
                end = self.trunk_path_endpoints[1]
            else:
                got = self._component_trunk_path(comp)
                if got is None:
                    # 无连接器分量（如地板 C289 单分支分量）：无连接器对可跑
                    # 最长路径，取最长分支作脊线 0；关节须走
                    # spine_joints_ordered（含中间关节），只取 [node0, node1]
                    # 会丢中间关节（如 C289 的 CLP01/CLP02），放置时端点
                    # 未定位、整根分支被丢（2026-11-18 地板实测 H5 失败根因）
                    keys = [sorted(comp, key=lambda k: (-topo.branches[k]['length'], k))[0]]
                    b = topo.branches[keys[0]]
                    joints = spine_joints_ordered(keys, b['node0'])
                    length = b['length']
                    end = joints[-1]
                else:
                    keys, pj, length, (a, b_) = got
                    joints = spine_joints_ordered(keys, pj[0])
                    end = b_
            segs = []
            for k in keys:
                for pc in topo.branches[k]['pieces']:
                    if pc['na'] != pc['nb']:
                        segs.append(pc['seg'])
            s0 = new_spine(0, ci, None, None, keys, joints, segs,
                           length, end, True)
            queue.append(('spine', s0))

        # ---- 逐层：处理脊线/ stub 的每个关节 ----
        # stub = 自由尾段的远端关节（尾段本身不是脊线，但其远端关节上
        # 可能挂侧枝；stub 的子脊线垂直于尾段方向，方向基准在槽位分配
        # 时（尾段方向定死后）才确定，故 stub 队列项携带尾段 seg）。
        while queue:
            kind, obj = queue.popleft()
            if kind == 'spine':
                S = obj
                joints = S['joints']
                sid = S['id']
                level = S['level']
                comp = S['comp']
                stub_group = None
            else:
                J0, psid, tail_seg = obj
                joints = [J0]
                sid = f"stub@{J0}"
                S = None
                level = self.spine_by_id[psid]['level'] + 1
                comp = self.spine_by_id[psid]['comp']
                stub_group = {'tail_seg': tail_seg, 'joint': J0,
                              'children': []}
                self.stub_groups.append(stub_group)
            for J in joints:
                nbrs = [(v, sg, w) for v, sg, w in
                        self.seg_tree_adj.get(J, [])
                        if sg not in assigned_segs]
                if not nbrs:
                    continue
                cands = []
                for v, sg, w in sorted(nbrs, key=lambda t: (t[0], t[1])):
                    L2, conn2, segs2, nodes2, has2 = self._lp_from(
                        v, J, assigned_segs)
                    segs = [sg] + segs2
                    nodes = [J] + nodes2
                    brs = []
                    for s2 in segs:
                        b2 = seg_branch[s2]
                        if not brs or brs[-1] != b2:
                            brs.append(b2)
                    cands.append({
                        'first_seg': sg, 'first_branch': seg_branch[sg],
                        'length': w + L2, 'connector': conn2,
                        'has_connector': has2, 'segs': segs, 'nodes': nodes,
                        'branches': brs, 'spine_id': None})
                # 最长者为主分支；平局按（终点连接器，首根分支）确定性排序
                cands.sort(key=lambda c: (-c['length'],
                                          c['connector'] or '',
                                          c['first_branch']))
                rec = {'spine': sid, 'joint': J, 'candidates': cands,
                       'main_idx': 0}
                self.layers.append(rec)
                for ci2, c in enumerate(cands):
                    if kind == 'spine':
                        ns = new_spine(
                            level + 1, comp, S['id'], J,
                            c['branches'], c['nodes'], c['segs'],
                            c['length'], c['connector'], ci2 == 0)
                    else:
                        ns = new_spine(
                            level, comp, psid, J,
                            c['branches'], c['nodes'], c['segs'],
                            c['length'], c['connector'], ci2 == 0)
                        # stub 子脊线：父脊线为尾段所在脊线，方向基准是尾段方向
                        ns['stub_seg'] = tail_seg
                        stub_group['children'].append(ns['id'])
                    c['spine_id'] = ns['id']
                    # 尾段：子脊线分支上不在路径上的段
                    path_segs = set(c['segs'])
                    on_path = set(c['nodes'])
                    for b2 in c['branches']:
                        for pc in topo.branches[b2]['pieces']:
                            if pc['seg'] in path_segs or \
                                    pc['na'] == pc['nb']:
                                continue
                            a_in = pc['na'] in on_path
                            b_in = pc['nb'] in on_path
                            if a_in and b_in:
                                kind2 = 'constrained'
                                tail = {'branch': b2, 'spine': ns['id'],
                                        'joint': pc['na'], 'far': pc['nb'],
                                        'seg': pc['seg'],
                                        'length': pc['length'], 'kind': kind2,
                                        'direction': None}
                            elif a_in:
                                kind2 = 'free'
                                tail = {'branch': b2, 'spine': ns['id'],
                                        'joint': pc['na'], 'far': pc['nb'],
                                        'seg': pc['seg'],
                                        'length': pc['length'], 'kind': kind2,
                                        'direction': None}
                                queue.append(('stub', (pc['nb'], ns['id'],
                                                       pc['seg'])))
                            elif b_in:
                                kind2 = 'free'
                                tail = {'branch': b2, 'spine': ns['id'],
                                        'joint': pc['nb'], 'far': pc['na'],
                                        'seg': pc['seg'],
                                        'length': pc['length'], 'kind': kind2,
                                        'direction': None}
                                queue.append(('stub', (pc['na'], ns['id'],
                                                       pc['seg'])))
                            else:
                                # detached：两端都不在脊线路径上。远端关节须
                                # 排 stub 探索下游——否则该段被记为已分配，
                                # 其下游子树永远到不了剥离队列（2026-11-18
                                # 地板实测：SEG31 切断 CLP05 子树，19 根分支
                                # 未进脊线、H2 最大误差 +2919.57mm）。远端按
                                # 自由尾段定位（槽位方向伸出，见放置段）。
                                kind2 = 'detached'
                                tail = {'branch': b2, 'spine': ns['id'],
                                        'joint': pc['na'], 'far': pc['nb'],
                                        'seg': pc['seg'],
                                        'length': pc['length'], 'kind': kind2,
                                        'direction': None}
                                queue.append(('stub', (pc['nb'], ns['id'],
                                                       pc['seg'])))
                                self.warnings.append(
                                    f"尾段 {pc['seg']}（{b2}）两端都不在脊线"
                                    f" {ns['id']} 路径上，按自由尾段定位远端"
                                    f"并探索下游")
                            self.tails.append(tail)
                            self.tail_by_seg[pc['seg']] = tail
                    queue.append(('spine', ns))

        # ---- 未进脊线的分支：分类（纯自环 / 平行单段 / 其他） ----
        self.unassigned_branches = []
        for key in sorted(set(topo.branches) - assigned_branches):
            pieces = topo.branches[key]['pieces']
            if all(pc['na'] == pc['nb'] for pc in pieces):
                # 全部段都是自环段（单段或多段，如地板 15 根双自环分支）：
                # 不进生成树、不计侧枝；§十八：退化短管画短线头，真环画小三角
                # （原条件只认单段，多段自环分支被误标“未分配（不应发生）”，
                # 2026-11-18 地板实测）
                if all(pc.get('stub') for pc in pieces):
                    reason = '退化短管分支（不计侧枝，画短线头）'
                else:
                    reason = '纯自环分支（不计侧枝，画小三角）'
            elif all(pc['seg'] in self.dropped_segs for pc in pieces):
                sibs = []
                for pc in pieces:
                    for sg2, s2 in topo.segs.items():
                        if sg2 != pc['seg'] and s2['na'] == pc['na'] and \
                                s2['nb'] == pc['nb']:
                            sibs.append(sg2)
                reason = (f"平行单段分支（段 {pieces[0]['seg']} 与 "
                          f"{','.join(sibs)} 平行，两端已定，打折画出）")
            elif all(pc['seg'] in self.dropped_ring_segs for pc in pieces):
                reason = (f"真环闭环段分支（段 {pieces[0]['seg']} 为真环"
                          f"闭环段，已从生成树去掉；按受约束段画出）")
            else:
                reason = '未分配（不应发生：既非自环亦非全平行段）'
                self.warnings.append(f"分支 {key} 未进脊线：{reason}")
            self.unassigned_branches.append((key, reason))

        # §十五：平行对只画一根（分解阶段定死，先算后画）
        self.apply_parallel_single_rule()
        n_side = sum(len(r['candidates']) for r in self.layers)
        self.log_phase('分解',
                       f"§十四逐层最长路径：脊线 {len(self.spines)} 条"
                       f"（主干 1 + 侧枝 {len(self.spines) - len(self._comps)}），"
                       f"层记录 {len(self.layers)} 个关节、{n_side} 个侧枝候选，"
                       f"尾段 {len(self.tails)} 段，未进脊线 "
                       f"{len(self.unassigned_branches)} 根"
                       f"{[k for k, _ in self.unassigned_branches]}；"
                       f"§十五平行对 {len(self.hidden_parallel)} 对只画一根，"
                       f"隐藏 {len(self.hidden_parallel_segs)} 段"
                       f"{sorted(self.hidden_parallel_segs)}")
        # 段放置序只依赖分解结果，在此建好（搜索试跑实例同样需要）
        self._build_seg_ranks()
        return self.spines

    # ---------- §十五 平行对只画一根（v6p1） ----------
    def apply_parallel_single_rule(self):
        """§十五（2026-11-17 22:21 用户定）：平行对只画一根。
        在分解阶段调用（先算后画）：枚举全部平行段对（同一无序节点对
        之间 ≥2 段），按脊线归属判定留哪根——走主干/脊线那根留下画直，
        另一根隐藏（不画线，数据记入 hidden_parallel）。判定不按长度：
        BN04 对里主干成员是较短的 Body.113（17.0mm），不是较长的
        Body.114（20.0mm）。自环段（na==nb）不是平行对，不动。
        两段同为脊线段时无法隐藏（会断脊线），两根都留并记警告
        （IP 不触发）。"""
        topo = self.topo
        # 段 -> 脊线 id（主干脊线 0 也算脊线）
        seg_spine = {}
        for s in self.spines:
            for sg in s['segs']:
                seg_spine[sg] = s['id']
        self._seg_spine_map = seg_spine
        # 平行段分组（按无序节点对；自环段排除）
        groups = defaultdict(list)
        for sg, s in topo.segs.items():
            if s['na'] == s['nb']:
                continue
            groups[tuple(sorted((s['na'], s['nb'])))].append(sg)
        for nodes in sorted(groups):
            segs = sorted(groups[nodes])
            if len(segs) < 2:
                continue
            spine_segs = [sg for sg in segs if sg in seg_spine]
            if len(spine_segs) >= 2:
                self.warnings.append(
                    f"平行对 {nodes[0]}—{nodes[1]} 两段同为脊线段"
                    f"{spine_segs}，无法隐藏（会断脊线），两根都留")
                continue
            if len(spine_segs) == 1:
                kept = spine_segs[0]
            else:
                # 两段都不在脊线上（IP 不触发）：留较长者，平局取段 id 最小
                kept = sorted(
                    segs,
                    key=lambda sg: (-topo.segs[sg]['length'], sg))[0]
                self.warnings.append(
                    f"平行对 {nodes[0]}—{nodes[1]} 两段都不在脊线上，"
                    f"留较长者 {kept}（非脊线判定）")
            for sg in segs:
                if sg == kept:
                    continue
                self._hide_parallel_seg(sg, kept, nodes)

    def _hide_parallel_seg(self, sg, kept, nodes):
        """隐藏一条平行段：记入 hidden_parallel；尾段标 hidden，
        单段未分配分支整根隐藏并改写 reason。"""
        topo = self.topo
        s = topo.segs[sg]
        k = topo.segs[kept]
        hb = s['branch']
        tail = self.tail_by_seg.get(sg)
        if tail is not None:
            kind = 'tail_segment'
            tail['hidden'] = True
            tail['kept_seg'] = kept
        elif any(key == hb for key, _r in self.unassigned_branches) and \
                all(pc['seg'] == sg or pc['seg'] in self.hidden_parallel_segs
                    for pc in topo.branches[hb]['pieces']):
            kind = 'whole_branch'
            self.hidden_whole_branches.add(hb)
            self.unassigned_branches = [
                (key, (f"平行未单画（§十五）：段 {sg} 与 {kept}（{k['branch']}）"
                       f"平行，图上只画 {k['branch']}；数据见 hidden_parallel")
                 if key == hb else reason)
                for key, reason in self.unassigned_branches]
        else:
            self.warnings.append(
                f"平行段 {sg}（{hb}）既非尾段亦非单段未分配分支，"
                f"无法隐藏，照常画出")
            return
        self.hidden_parallel_segs.add(sg)
        self.hidden_seg_len_by_branch[hb] = \
            self.hidden_seg_len_by_branch.get(hb, 0.0) + s['length']
        self.hidden_parallel.append({
            'pair': f"{nodes[0]}—{nodes[1]}",
            'hidden_seg': sg, 'hidden_branch': hb,
            'hidden_length_mm': round(s['length'], 1),
            'hidden_dia_mm': round(s.get('dia') or 0.0, 1),
            'hidden_kind': kind,
            'kept_seg': kept, 'kept_branch': k['branch'],
            'kept_length_mm': round(k['length'], 1),
            'kept_dia_mm': round(k.get('dia') or 0.0, 1),
            'kept_spine': self._seg_spine_map.get(kept),
        })

    # ---------- 分支树（扁平：同脊线分支皆为脊线首根的子节点） ----------
    def build_branch_tree(self):
        """扁平树：脊线首根的父 = 上级脊线中含锚点的最后分支；
        同脊线其余分支的父 = 脊线首根；未分配分支的父 = 含其一端关节的
        脊线分支。扁平结构 + _rotation_safe 使翻转只能整条脊线转，
        脊线中部分支转不动（会断拓扑），故翻转不破坏脊线拉直。"""
        topo = self.topo
        # 每条脊线中含某关节的最后分支（按脊线路径顺序）
        self._spine_joint_branch = {}
        for s in self.spines:
            for b in s['branches']:
                for nd in topo.branch_nodes(b):
                    self._spine_joint_branch[(s['id'], nd)] = b
        self.tree = {}
        self.tree_root = None
        for s in self.spines:
            if s['level'] == 0:
                if self.tree_root is None:
                    self.tree_root = s['branches'][0]
                for b in s['branches']:
                    self.tree[b] = {"parent": None, "anchor": None,
                                    "depth": 0, "children": []}
                continue
            parent_spine = self.spine_by_id[s['parent']]
            anchor = s['anchor']
            pbranch = self._spine_joint_branch.get(
                (parent_spine['id'], anchor))
            if pbranch is None:
                # 锚点不在上级脊线分支关节里（stub 远端关节）：用尾段所属分支
                pbranch = None
                for t in self.tails:
                    if t['far'] == anchor and t['spine'] == parent_spine['id']:
                        pbranch = t['branch']
                        break
            first = s['branches'][0]
            self.tree[first] = {"parent": pbranch, "anchor": anchor,
                                "depth": s['level'], "children": []}
            if pbranch is not None and pbranch in self.tree:
                self.tree[pbranch]["children"].append(first)
            for b in s['branches'][1:]:
                # 锚点 = 该分支的入口关节（路径上前一分支的出口）
                joints = topo.branch_nodes(b)
                entry = None
                for nd in s['joints']:
                    if nd in joints:
                        entry = nd
                        break
                self.tree[b] = {"parent": first, "anchor": entry,
                                "depth": s['level'] + 1, "children": []}
                self.tree[first]["children"].append(b)
        # 未分配分支：父 = 含其一端关节的脊线分支（按脊线 id 升序确定性取首）
        for key, _reason in self.unassigned_branches:
            joints = topo.branch_nodes(key)
            parent = None
            anchor = None
            for s in self.spines:
                for b in s['branches']:
                    for nd in joints:
                        if nd in topo.branch_nodes(b):
                            parent, anchor = b, nd
                            break
                    if parent is not None:
                        break
                if parent is not None:
                    break
            depth = (self.tree[parent]["depth"] + 1) if parent in self.tree else 1
            self.tree[key] = {"parent": parent, "anchor": anchor,
                              "depth": depth, "children": []}
            if parent is not None and parent in self.tree:
                self.tree[parent]["children"].append(key)
        # 排序：子分支按长度降序（确定性）
        for info in self.tree.values():
            info["children"].sort(
                key=lambda k: (-self.topo.branches[k]["length"], k))
        return self.tree

    # ---------- 槽位分配（§十三：前两根垂直分两侧，第三根起偏 30°） ----------
    def _spine_proj_dir(self, spine, joint):
        """上级脊线在 joint 处的投影方向（度，沿脊线路径走向）。
        取 joint → 下一路径关节的投影方向；末关节取上一关节 → joint。"""
        joints = spine['joints']
        if joint not in joints:
            return None
        idx = joints.index(joint)
        if idx + 1 < len(joints):
            return self.proj_direction(joint, joints[idx + 1])
        if idx > 0:
            return self.proj_direction(joints[idx - 1], joint)
        return None

    def _child_proj_rel(self, spine, joint, end_node, first_branch):
        """子脊线相对上级脊线的投影角（度，(-180, 180]；+90=左侧垂直）。
        子方向取 joint → 终点连接器；无方向时取 joint → 首根分支远端。"""
        pdir = self._spine_proj_dir(spine, joint)
        if pdir is None:
            return None
        cdir = None
        if end_node is not None:
            cdir = self.proj_direction(joint, end_node)
        if cdir is None and first_branch is not None:
            far = self._far_end(first_branch, joint)
            if far is not None and far != joint:
                cdir = self.proj_direction(joint, far)
        if cdir is None:
            return None
        rel = (cdir - pdir) % 360.0
        return rel - 360.0 if rel > 180.0 else rel

    def assign_spine_slots(self):
        """为每个（上级脊线，关节）组分配槽位偏移角（相对上级脊线方向）。

        规则（§十三）：第 1 根（主分支）取投影侧 ±90°；第 2 根取对侧
        ±90°；第 3 根起取离投影角最近的剩余槽位（±60/±120/±30/±150）。
        自由/detached 尾段排在脊线之后，同组内占剩余槽位（方向相对本脊线）。
        stub 组（第二遍）：子脊线槽位相对尾段方向。
        全部确定性：组内按（-路径长，终点连接器，首根分支）排序。
        """
        # 组：(parent_spine_id, joint) -> {'spines': [...], 'tails': [...]}
        groups = defaultdict(lambda: {'spines': [], 'tails': []})
        for s in self.spines:
            if s['level'] == 0 or 'stub_seg' in s:
                continue
            groups[(s['parent'], s['anchor'])]['spines'].append(s)
        for t in self.tails:
            if t['kind'] in ('free', 'detached'):
                groups[(t['spine'], t['joint'])]['tails'].append(t)

        def nearest_slot(rel_ang, taken):
            """离 rel_ang 最近的剩余槽位（角距最小；平局取 |偏移| 小者，
            再平局取正号）。rel_ang=None 时按 SLOT_OFFSETS 顺序取首个剩余。"""
            cands = [o for o in SLOT_OFFSETS if o not in taken]
            if not cands:
                return None
            if rel_ang is None:
                return cands[0]
            def key(o):
                d = abs((o - rel_ang + 180.0) % 360.0 - 180.0)
                return (round(d, 9), abs(o), 0 if o > 0 else 1)
            return sorted(cands, key=key)[0]

        self.slot_groups = []
        self.slot_info = {}
        for (psid, joint), g in sorted(groups.items()):
            pspine = self.spine_by_id[psid]
            spines = sorted(g['spines'],
                            key=lambda s: (-s['length'], s['end'] or '',
                                           s['branches'][0]))
            tails = sorted(g['tails'],
                           key=lambda t: (-t['length'], t['branch']))
            taken = set()
            rec = {}
            # 第 1 根：主分支，投影侧 ±90°
            for i, s in enumerate(spines):
                rel = self._child_proj_rel(pspine, joint, s['end'],
                                           s['branches'][0])
                if i == 0:
                    off = 90.0 if (rel is None or rel >= 0) else -90.0
                elif i == 1:
                    first_off = spines[0]['slot_offset']
                    off = -first_off
                else:
                    off = nearest_slot(rel, taken)
                    if off is None:
                        off = 90.0  # 槽位用尽（>10 根同点，IP 不触发）：兜底
                        self.warnings.append(
                            f"关节 {joint} 侧枝超 10 根，槽位用尽，{s['branches'][0]} 兜底 +90°")
                taken.add(off)
                s['slot_offset'] = off
                s['proj_ang'] = None if rel is None else round(rel, 1)
                s['side_match'] = (None if rel is None else
                                   ((off > 0) == (rel > 0)) if abs(rel) > 1e-9 else None)
                first = s['branches'][0]
                self.slot_info[first] = {
                    'proj_ang': s['proj_ang'], 'slot': off,
                    'side_match': s['side_match'],
                    'offset_dev': round(abs(abs(off) - 90.0), 1),
                }
                rec[first] = off
            # 自由/detached 尾段：排在脊线之后，占剩余槽位
            for t in tails:
                rel = self._child_proj_rel(pspine, joint, t['far'],
                                           t['branch'])
                off = nearest_slot(rel, taken)
                if off is None:
                    off = 90.0
                    self.warnings.append(
                        f"关节 {joint} 槽位用尽，尾段 {t['seg']} 兜底 +90°")
                taken.add(off)
                t['slot_offset'] = off
                t['proj_ang'] = None if rel is None else round(rel, 1)
            children = [s['branches'][0] for s in spines]
            pbranch = self._spine_joint_branch.get((psid, joint))
            self.slot_groups.append((pbranch, joint, children, rec))

        # 第二遍：stub 组（子脊线槽位相对尾段方向）
        for sg in self.stub_groups:
            tail = self.tail_by_seg[sg['tail_seg']]
            base_off = tail.get('slot_offset')
            if base_off is None:
                # 尾段方向未定（不应发生）：默认 +90°
                base_off = 90.0
                tail['slot_offset'] = base_off
            children = sorted(
                (self.spine_by_id[cid] for cid in sg['children']),
                key=lambda s: (-s['length'], s['end'] or '',
                               s['branches'][0]))
            taken = set()
            for i, s in enumerate(children):
                # stub 子脊线的投影角：相对尾段投影方向
                tdir = self.proj_direction(tail['joint'], tail['far'])
                cdir = None
                if s['end'] is not None:
                    cdir = self.proj_direction(sg['joint'], s['end'])
                rel = None
                if tdir is not None and cdir is not None:
                    rel = (cdir - tdir) % 360.0
                    rel = rel - 360.0 if rel > 180.0 else rel
                if i == 0:
                    off = 90.0 if (rel is None or rel >= 0) else -90.0
                elif i == 1:
                    off = -children[0]['slot_offset']
                else:
                    off = nearest_slot(rel, taken)
                    if off is None:
                        off = 90.0
                taken.add(off)
                s['slot_offset'] = off
                s['proj_ang'] = None if rel is None else round(rel, 1)
                s['side_match'] = (None if rel is None else
                                   ((off > 0) == (rel > 0)) if abs(rel) > 1e-9 else None)
                first = s['branches'][0]
                self.slot_info[first] = {
                    'proj_ang': s['proj_ang'], 'slot': off,
                    'side_match': s['side_match'],
                    'offset_dev': round(abs(abs(off) - 90.0), 1),
                }
        n_main = sum(1 for s in self.spines if s['level'] > 0 and s['is_main'])
        n_det = sum(1 for t in self.tails if t['kind'] == 'detached')
        self.log_phase('槽位',
                       f"分配 {len(self.slot_groups)} 个关节组、"
                       f"{len(self.slot_info)} 根脊线首根槽位；"
                       f"主分支 {n_main} 条，自由尾段 "
                       f"{sum(1 for t in self.tails if t['kind'] == 'free')} 段"
                       + (f"、detached 尾段 {n_det} 段" if n_det else ""))
        return self.slot_info

    # ---------- 关节清点（H10 子项：先找齐再画） ----------
    def inventory_layers(self):
        """清点全部（上级脊线，关节）组的侧枝并记入阶段日志；
        同时填充 trunk_inventory（主干关节，供 layout.json 查阅）。"""
        groups = defaultdict(list)
        for s in self.spines:
            if s['level'] == 0:
                continue
            groups[(s['parent'], s['anchor'])].append(s['branches'][0])
        for (psid, joint), children in sorted(groups.items()):
            children = sorted(
                children,
                key=lambda k: (-self.topo.branches[k]['length'], k))
            pbranch = self._spine_joint_branch.get((psid, joint))
            self.joint_inventory.append((pbranch, joint, children))
        # 主干关节清点（供 layout.json trunk_inventory 查阅）
        xs = self._trunk_joint_x()
        inv_map = {(p, j): c for (p, j, c) in self.joint_inventory}
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
        total_attached = sum(len(c) for (_p, _j, c) in self.joint_inventory)
        self.log_phase("清点", "清点 %d 个关节组、%d 根脊线首根；主干路径 %d 个关节" % (
            len(self.joint_inventory), total_attached,
            len(self.trunk_path_joints)))
        return self.joint_inventory

    # ---------- 脊线方向（自顶向下；side_override 翻转槽位符号） ----------
    def compute_spine_directions(self):
        """由槽位偏移自顶向下算每条脊线的绝对方向（度）。
        脊线 0 方向 0°（水平）；子脊线 = 上级方向 + 槽位偏移；
        stub 子脊线 = 尾段方向 + 槽位偏移（尾段方向 = 本脊线方向 + 尾段偏移）。
        side_override 翻转指定脊线首根的槽位符号（镜像到另一侧）。
        校验：同关节各子脊线（含尾段）方向不得重合（模 360，容差 1°），
        否则返回 False（放置侧搜索跳过该组合）。
        """
        # 尾段方向（相对本脊线）：需先知本脊线方向，故与脊线方向同序计算
        for s in self.spines:
            if s['level'] == 0:
                s['direction'] = 0.0
        # 按层序（spines 已按创建顺序 = BFS 层序，父先于子）
        for s in self.spines:
            if s['level'] == 0:
                continue
            off = s['slot_offset']
            first = s['branches'][0]
            if self.side_override.get(first) == 1:
                off = -off
            if 'stub_seg' in s:
                tail = self.tail_by_seg[s['stub_seg']]
                base = tail.get('direction')
                if base is None:
                    # 尾段方向未算（父脊线方向已知时可算）
                    pspine = self.spine_by_id[s['parent']]
                    base = (pspine['direction'] +
                            tail.get('slot_offset', 90.0)) % 360.0
                    tail['direction'] = base
                s['direction'] = (base + off) % 360.0
            else:
                pspine = self.spine_by_id[s['parent']]
                s['direction'] = (pspine['direction'] + off) % 360.0
        # 自由/detached 尾段方向（未在 stub 计算中覆盖的）
        for t in self.tails:
            if t['kind'] in ('free', 'detached') and t.get('direction') is None:
                s = self.spine_by_id[t['spine']]
                t['direction'] = (s['direction'] +
                                  t.get('slot_offset', 90.0)) % 360.0
        # 校验：同关节方向不得重合
        by_joint = defaultdict(list)
        for s in self.spines:
            if s['level'] == 0:
                continue
            key = (s['parent'], s['anchor']) if 'stub_seg' not in s else \
                ('stub', s['anchor'])
            by_joint[key].append((s['direction'], s['branches'][0]))
        for t in self.tails:
            if t['kind'] in ('free', 'detached'):
                by_joint[(t['spine'], t['joint'])].append(
                    (t['direction'], t['seg']))
        for key, dirs in by_joint.items():
            ds = sorted(d % 360.0 for d, _ in dirs)
            if len(ds) < 2:
                continue
            for a, b in zip(ds, ds[1:] + ds[:1]):
                if abs((b - a) % 360.0) < 1.0 or \
                        abs((b - a) % 360.0 - 360.0) < 1.0:
                    return False
        return True

    # ---------- 放置：以脊线为单位（先算全部关节位置，再逐根提交） ----------
    # ---------- 翻转安全：只允许整条脊线旋转 ----------
    def _rotation_safe(self, root_key, anchor_node):
        """覆盖 v4：脊线非首根分支（中部/末根）一律不可转。
        末根是叶子时 v4 的判定会误判可转，flip_center 会把脊线末端
        折回去（2026-11-17 实测：Body.89 被折回，造 3 处重叠），破坏
        §十四脊线拉直。脊线首根与未分配分支走 v4 原判定。"""
        sid = self.branch_spine.get(root_key)
        if sid is not None:
            s = self.spine_by_id[sid]
            if s['branches'][0] != root_key:
                return False
        return super()._rotation_safe(root_key, anchor_node)

    # ---------- 方案 plan.json（第一阶段产物：先算完，写盘，再画） ----------
    def build_plan(self):
        """组装 plan.json 内容：主干关节表、每关节侧枝数、每关节最长路径
        及长度、槽位分配、全部脊线与尾段。只读计算结果，不碰放置状态。
        run() 在放置开始前调用并写盘（§十四铁律：先算后画）。
        返回 plan dict，同时存入 self.plan。"""
        topo = self.topo
        a, b = self.trunk_path_endpoints
        s0 = self.spine_by_id[0]
        # 主干关节表（按路径顺序，累计弧长；段用端点对查，不依赖 segs 顺序）
        seg_by_pair = {}
        for sg in s0['segs']:
            s = topo.segs[sg]
            seg_by_pair[tuple(sorted((s['na'], s['nb'])))] = sg
        trunk_joints = []
        cum = 0.0
        for i, nd in enumerate(s0['joints']):
            trunk_joints.append({'joint': nd, 'cum_arc_mm': round(cum, 1)})
            if i + 1 < len(s0['joints']):
                sg = seg_by_pair.get(
                    tuple(sorted((nd, s0['joints'][i + 1]))))
                if sg is not None:
                    cum += topo.segs[sg]['length']
        layers = []
        for rec in self.layers:
            layers.append({
                'spine': rec['spine'], 'joint': rec['joint'],
                'n_candidates': len(rec['candidates']),
                'candidates': [{
                    'first_branch': c['first_branch'],
                    'connector': c['connector'],
                    'length_mm': round(c['length'], 1),
                    'is_main': (i == rec['main_idx']),
                    'spine_id': c['spine_id'],
                    'branches': list(c['branches']),
                } for i, c in enumerate(rec['candidates'])],
            })
        spines = []
        for s in self.spines:
            spines.append({
                'id': s['id'], 'level': s['level'], 'parent': s['parent'],
                'anchor': s['anchor'], 'branches': list(s['branches']),
                'joints': list(s['joints']), 'segs': list(s['segs']),
                'length_mm': round(s['length'], 1), 'end': s['end'],
                'is_main': s['is_main'],
                'slot_offset_deg': s.get('slot_offset'),
                'direction_deg': (None if s.get('direction') is None
                                  else round(s['direction'], 1)),
                'proj_ang_deg': s.get('proj_ang'),
                'side_match': s.get('side_match'),
            })
        slots = {
            'groups': [{'parent': p, 'joint': j, 'children': list(c),
                        'offsets': {k: v for k, v in sorted(o.items())}}
                       for (p, j, c, o) in self.slot_groups],
            'info': {k: v for k, v in sorted(self.slot_info.items())},
        }
        tails = [{
            'branch': t['branch'], 'spine': t['spine'], 'joint': t['joint'],
            'far': t['far'], 'seg': t['seg'],
            'length_mm': round(t['length'], 1), 'kind': t['kind'],
            'slot_offset_deg': t.get('slot_offset'),
            'direction_deg': (None if t.get('direction') is None
                              else round(t['direction'], 1)),
            'hidden': bool(t.get('hidden')),
            'kept_seg': t.get('kept_seg'),
        } for t in self.tails]
        # 方案完整性：全部 110 分支有归属，全部子脊线方向已定且槽位已记
        complete = (
            len(self.branch_spine) + len(self.unassigned_branches)
            == len(topo.branches)
            and all(s.get('direction') is not None for s in self.spines)
            and len(self.layers) > 0
            and len(self.slot_info) == sum(1 for s in self.spines
                                           if s['level'] > 0))
        self.plan = {
            'meta': {'version': 'v6p1',
                     'rule': '§十四 逐层最长路径 + §十五 平行对只画一根',
                     'branches': len(topo.branches),
                     'nodes': len(topo.nodes), 'segs': len(topo.segs)},
            'trunk': {'endpoints': [a, b],
                      'length_mm': round(self.trunk_path_length, 1),
                      'span_mm': round(self.trunk_path_span, 1),
                      'branches': len(self.trunk_path),
                      'branch_list': list(self.trunk_path),
                      'joints': trunk_joints},
            'layers': layers,
            'spines': spines,
            'slots': slots,
            'tails': tails,
            'hidden_parallel': [dict(r) for r in self.hidden_parallel],
            'unassigned': [{'branch': k, 'reason': r}
                           for k, r in self.unassigned_branches],
            'side_override': {k: v
                              for k, v in sorted(self.side_override.items())},
            'complete': complete,
        }
        return self.plan

    def write_plan(self, out_path):
        """plan.json 写盘（run 在放置开始前调用）。"""
        if self.plan is None:
            self.build_plan()
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(self.plan, f, ensure_ascii=False, indent=1)
        return out_path

    def _build_seg_ranks(self):
        """段放置序（平行预折决策用）：路径段按（脊线 id，0，分支序）；
        尾段按（脊线 id，1，分支序）；未分配分支的段排最后。
        路径段的弦长在脊线关节预计算时即定死（早于一切分支提交），
        故同脊线内路径段恒先于尾段——秩的第二分量先分路径/尾段，
        再按分支序（2026-11-17 实测教训：先按分支序会让 Body.46 的
        尾段 SEG11 秩低于 Body.159 的路径段 SEG08，SEG08 漏打折、
        SEG11 被拉长 2.9mm 且与 SEG08 重叠）。
        平行对中先放置的一段按较短兄弟长度打折（打折段画折线补长，
        后放置的受约束段恰好 fitting，长度零误差）。"""
        self._seg_rank = {}
        for s in self.spines:
            for i, b in enumerate(s['branches']):
                for pc in self.topo.branches[b]['pieces']:
                    if pc['seg'] in s['segs']:
                        self._seg_rank[pc['seg']] = (s['id'], 0, i)
        for t in self.tails:
            s = self.spine_by_id[t['spine']]
            i = s['branches'].index(t['branch'])
            self._seg_rank[t['seg']] = (t['spine'], 1, i)
        for j, (k, _r) in enumerate(self.unassigned_branches):
            for pc in self.topo.branches[k]['pieces']:
                self._seg_rank[pc['seg']] = (10 ** 6 + j, 0, 0)

    def _piece_chord(self, seg):
        """段的弦长（脊线推进距离）：自环段 0（三角不推进）；
        平行段若有更短的后放置兄弟，取最短兄弟长（预折）；
        否则取段长。§十五（v6p1）：被隐藏的平行兄弟不参与取短，
        留下的那根弦长即其真实长度，画直不再打折。"""
        pc = self.topo.segs[seg]
        if pc['na'] == pc['nb']:
            return 0.0
        chord = pc['length']
        my_rank = self._seg_rank.get(seg)
        if my_rank is None:
            return chord
        for sib in self.parallel_sib.get(seg, []):
            if sib in self.hidden_parallel_segs:
                continue  # §十五：隐藏的平行兄弟不约束弦长
            sib_rank = self._seg_rank.get(sib)
            if sib_rank is None or sib_rank <= my_rank:
                continue
            sl = self.topo.segs[sib]['length']
            if sl < chord:
                chord = sl
        return chord

    def _spine_total_chord(self, spine):
        """脊线总弦长 = 全部路径段弦长之和（尾段/自环不推进）。"""
        return sum(self._piece_chord(sg) for sg in spine['segs'])

    def _triangle_best(self, p, base_angle, length, check_subs):
        """自环三角 24 朝向试选（15° 步进），取干涉最少者；
        平局取先试到的（确定性）。返回 (tri, bad)，bad 为真实干涉数。
        选分另加方向罚分：任一边与脊线方向平行（k%4==0，三角三边
        与 base_angle 的夹角为 0°/120°/240°）的朝向选分 +5——只影响
        选取，不计入 bad，警告仍报真实干涉数。
        根因（2026-11-18 地板实测）：三角在脊线分支序中排在被重叠段
        之前时，试选时后序段尚未放置，k=0（首边沿脊线方向）呈假干净
        被立即选中；后序路径段按直线放置压过三角底边（SEG66/SEG47
        各重叠 1.67mm，H4 失败）。罚分 5 的排序：非共线小冲突（1~3）
        胜共线干净（5），共线干净（5）胜非共线真重叠（10），共线
        重叠（15）最差；只有选分 0 的朝向才提前终止。"""
        tri, bad, best_score = None, None, None
        for k in range(24):
            t = self.triangle_loop(p, base_angle + 15.0 * k, length)
            s = [(t[m], t[m + 1]) for m in range(3)]
            b = check_subs(s, skip_dist=True)
            score = b + (5 if k % 4 == 0 else 0)
            if best_score is None or score < best_score:
                tri, bad, best_score = t, b, score
                if b == 0 and k % 4 != 0:
                    break
        return tri, bad

    def _kink_best(self, a, b, length, check_subs):
        """两点间折线（总长 length、弦 |AB|）：两侧都试，取干涉最少者；
        平局取左侧（+1）。length <= |AB| 时直接返回直线。"""
        if length <= dist(a, b) + 1e-9:
            return [a, b], 0
        best, best_bad = None, None
        for side in (1, -1):
            pts = self.kink_points(a, b, length, side)
            subs = [(pts[0], pts[1]), (pts[1], pts[2])]
            bad = check_subs(subs)
            if best_bad is None or bad < best_bad:
                best, best_bad = pts, bad
                if bad == 0:
                    break
        return best, best_bad

    def ring_polygon(self, lengths):
        """覆盖 v3：给定各边长，解圆半径 R 使弦多边形闭合，返回顶点（质心在原点）。
        v3 版假设全部边对劣弧——钝角形（最长边对角 >90°，外心在形外）时
        最长边应对优弧，v3 的二分收敛到错误半径，闭合边长错（2026-11-18
        地板实测：C289 弦 65.98/85.92/40.95，v3 排出的第三边 55.13 ≠ 40.95，
        H2 +13.92mm）。本版分两种情况：先试全劣弧（Σ2·asin=2π）；若
        R=max/2 处 Σ 仍 <2π（外心在外），改解优弧方程
        2·asin(Lmax/2R)=Σ其余 2·asin(L/2R)，最长边占优弧。
        若最长边 >= 其余边之和则无法闭合，返回 None。"""
        if max(lengths) >= sum(lengths) - max(lengths):
            return None
        imax = lengths.index(max(lengths))
        # 情况一：全劣弧（外心在形内）
        lo = max(lengths) / 2.0 * 1.000001
        s_lo = sum(2.0 * math.asin(min(1.0, L / (2.0 * lo)))
                   for L in lengths)
        if s_lo > 2.0 * math.pi:
            hi = 1e7
            for _ in range(200):
                mid = (lo + hi) / 2.0
                s = sum(2.0 * math.asin(min(1.0, L / (2.0 * mid)))
                        for L in lengths)
                if s > 2.0 * math.pi:
                    lo = mid
                else:
                    hi = mid
            R = (lo + hi) / 2.0
            angs = [2.0 * math.asin(L / (2.0 * R)) for L in lengths]
        else:
            # 情况二：最长边占优弧（外心在形外）
            # f(R)=2·asin(Lmax/2R)−Σ其余 2·asin(L/2R)：R=max/2 处 >0、
            # R→∞ 处 <0（最长边 < 其余和），二分有根。
            def f(R):
                a_max = 2.0 * math.asin(
                    min(1.0, lengths[imax] / (2.0 * R)))
                a_rest = sum(2.0 * math.asin(min(1.0, L / (2.0 * R)))
                             for i, L in enumerate(lengths) if i != imax)
                return a_max - a_rest
            lo2 = max(lengths) / 2.0 * 1.000001
            hi2 = 1e7
            for _ in range(200):
                mid = (lo2 + hi2) / 2.0
                if f(mid) > 0:
                    lo2 = mid
                else:
                    hi2 = mid
            R = (lo2 + hi2) / 2.0
            angs = []
            for i, L in enumerate(lengths):
                a = 2.0 * math.asin(min(1.0, L / (2.0 * R)))
                angs.append((2.0 * math.pi - a) if i == imax else a)
        pts, ang = [], 0.0
        for a in angs:
            pts.append((R * math.cos(ang), R * math.sin(ang)))
            ang += a
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        return [(p[0] - cx, p[1] - cy) for p in pts]

    def _place_spine(self, spine, anchor_pt):
        """以脊线为单位放置：先算出全部关节位置（沿脊线方向累计弦长），
        再逐根分支提交（_layout_spine_branch）。anchor_pt 为脊线起点
        （0 级由调用方按居中/原点定；子脊线为锚点关节已放置位置）。
        闭环脊线（首末关节相同，≥3 个不同关节）按 §六整体画环，不拉直。"""
        topo = self.topo
        u = unit_from_angle(spine['direction'])
        # 段查找：(na, nb) -> 路径段（生成树内唯一）
        seg_between = {}
        for sg in spine['segs']:
            s = topo.segs[sg]
            seg_between[(s['na'], s['nb'])] = sg
            seg_between[(s['nb'], s['na'])] = sg
        # 闭环脊线（§六整体画环）：首末关节相同且 ≥3 个不同关节时，
        # 不拉直——按 3D 弦长排闭合多边形（ring_polygon），各边再按弧长
        # 打折补长（见 _layout_spine_branch 路径段的 kink）。弧长不能
        # 直接作多边形边：弧长是管中心线长，弦才是节点直线距，最长弧
        # 可能超过其余弧之和（如 C289 SEG526 147.6 > 87.8+41.1），多边形
        # 闭合不了；3D 弦必满足多边形不等式。
        joints = spine['joints']
        if (len(joints) >= 4 and joints[0] == joints[-1]
                and len(set(joints)) >= 3):
            ring_nodes = joints[:-1]
            chords = []
            for a, b in zip(ring_nodes, ring_nodes[1:] + ring_nodes[:1]):
                pa = topo.nodes[a]['xyz']
                pb = topo.nodes[b]['xyz']
                chords.append(math.dist(pa, pb))
            poly = self.ring_polygon(chords)
            if poly is not None:
                pos = {nd: (anchor_pt[0] + p[0], anchor_pt[1] + p[1])
                       for nd, p in zip(ring_nodes, poly)}
                self.rings_drawn.append(
                    {'segs': list(spine['segs']), 'nodes': list(ring_nodes)})
                self._ring_spines.add(spine['id'])
                for b in spine['branches']:
                    self._layout_spine_branch(b, spine, pos)
                return
            self.warnings.append(
                f"脊线 {spine['id']} 闭环 3D 弦无法排多边形，改走拉直放置")
        # 关节位置：沿脊线方向累计弦长
        pos = {spine['joints'][0]: anchor_pt}
        cur = anchor_pt
        for j0, j1 in zip(spine['joints'], spine['joints'][1:]):
            sg = seg_between.get((j0, j1))
            if sg is None:
                self.warnings.append(
                    f"脊线 {spine['id']} 相邻关节 {j0}—{j1} 间无路径段，"
                    f"位置重合（不应发生）")
                pos[j1] = cur
                continue
            cur = add_pt(cur, u, self._piece_chord(sg))
            pos[j1] = cur
        # 逐根分支提交（路径序；后提交的分支能看到先提交的干涉）
        for b in spine['branches']:
            self._layout_spine_branch(b, spine, pos)

    def _layout_spine_branch(self, key, spine, pos):
        """放置一条脊线分支：路径段沿脊线直线（平行预折画折线补长）、
        自环段画小三角、尾段（受约束打折/自由沿槽位方向）。
        全部关节位置已由 _place_spine 预先算好（除自由尾段远端）。
        生成与 v3 layout_branch 同形的 res 并 _commit。"""
        topo = self.topo
        b = topo.branches[key]
        pieces = b['pieces']
        joints = self._joints(key)
        path_segs = set(spine['segs'])
        seg_pts = {}
        bends, warnings = [], []
        n_bad = 0
        trial_subs = []

        def check_subs(subs, skip_dist=False):
            bad = 0
            for (q1, q2) in subs:
                if self.piece_overlaps(q1, q2, trial_subs):
                    bad += 10
                elif self.piece_conflicts(q1, q2, trial_subs,
                                          skip_dist=skip_dist):
                    bad += 1
            return bad

        def accept_subs(subs, skip_dist=False):
            for (q1, q2) in subs:
                trial_subs.append((q1, q2, skip_dist))

        joint_pos = {}
        for idx, nd in enumerate(joints):
            if nd in pos:
                joint_pos[idx] = pos[nd]
        # 自由尾段远端：沿尾段槽位方向伸出（此时其关节已在 pos 中）
        # §十五隐藏尾段不定位远端：远端关节已由留下的平行段所在脊线
        # 定位，在此重算会记入 joint_pos 与 node_pos 冲突（2026-11-18
        # 地板实测 H3 6 处不一致根因）
        for pc in pieces:
            t = self.tail_by_seg.get(pc['seg'])
            if t is not None and t['kind'] == 'free':
                if t.get('hidden') or pc['seg'] in self.hidden_parallel_segs:
                    continue
                jp = pos.get(t['joint'])
                if jp is None:
                    warnings.append(f"{key}/{pc['seg']} 自由尾段关节 "
                                    f"{t['joint']} 未定位")
                    continue
                far = add_pt(jp, unit_from_angle(t['direction']),
                             t['length'])
                pos[t['far']] = far
                if t['far'] in joints:
                    joint_pos[joints.index(t['far'])] = far
        # detached 尾段远端：与自由尾段同法定位（沿槽位方向伸出；
        # 须在自由尾段之后——其关节可能由同分支自由尾段定位，如
        # SEG31 的关节 BN06 由 SEG39 定位）。远端已定位时不动
        # （用已有位置画受约束段）。
        for pc in pieces:
            t = self.tail_by_seg.get(pc['seg'])
            if t is None or t['kind'] != 'detached':
                continue
            if t.get('hidden') or pc['seg'] in self.hidden_parallel_segs:
                continue
            if t['far'] in pos:
                if t['far'] in joints:
                    joint_pos[joints.index(t['far'])] = pos[t['far']]
                continue
            if t['far'] in self.node_pos:
                pos[t['far']] = self.node_pos[t['far']]
                if t['far'] in joints:
                    joint_pos[joints.index(t['far'])] = pos[t['far']]
                continue
            jp = pos.get(t['joint'])
            if jp is None:
                warnings.append(f"{key}/{pc['seg']} detached 尾段关节 "
                                f"{t['joint']} 未定位")
                continue
            if t.get('direction') is None:
                warnings.append(f"{key}/{pc['seg']} detached 尾段方向未定")
                continue
            far = add_pt(jp, unit_from_angle(t['direction']),
                         t['length'])
            pos[t['far']] = far
            if t['far'] in joints:
                joint_pos[joints.index(t['far'])] = far
        # 两遍画：先画非自环段（路径段/尾段），再画自环三角——三角试选
        # 须看到本分支已画的路径段，否则三角首边可能与后续路径段重叠
        # （2026-11-17 实测：Body.117 的 SEG12 三角首边与 SEG13 重叠）。
        # 点列组装仍按 pieces 原顺序，不受绘制顺序影响。
        draw_order = sorted(pieces,
                            key=lambda pc: 1 if pc['na'] == pc['nb'] else 0)
        for pc in draw_order:
            sg = pc['seg']
            if sg in self.hidden_parallel_segs:
                continue  # §十五：平行未单画，只画脊线/主干那根
            a_pt = joint_pos.get(joints.index(pc['na'])) \
                if pc['na'] in joints else pos.get(pc['na'])
            b_pt = joint_pos.get(joints.index(pc['nb'])) \
                if pc['nb'] in joints else pos.get(pc['nb'])
            if pc['na'] == pc['nb']:
                # 自环三角（在原线上画小三角，不推进）
                if a_pt is None:
                    warnings.append(f"{key}/{sg} 自环关节 {pc['na']} 未定位")
                    continue
                if pc.get('stub'):
                    # §十八：退化短管画直线短线头（不是环）
                    tick, bad = self._tick_best(
                        a_pt, spine['direction'], pc['length'], check_subs)
                    seg_pts[sg] = tick
                    accept_subs([(tick[0], tick[1])], skip_dist=True)
                    if bad:
                        n_bad += bad
                        warnings.append(
                            f"{key}/{sg} 短线头与已画线干涉 {bad} 处")
                    continue
                tri, bad = self._triangle_best(
                    a_pt, spine['direction'], pc['length'], check_subs)
                seg_pts[sg] = tri
                subs = [(tri[m], tri[m + 1]) for m in range(3)]
                accept_subs(subs, skip_dist=True)
                if bad:
                    n_bad += bad
                    warnings.append(f"{key}/{sg} 自环三角与已画线干涉 {bad} 处")
                continue
            if a_pt is None or b_pt is None:
                warnings.append(f"{key}/{sg} 端点未定位（{pc['na']}→{pc['nb']}）")
                continue
            t = self.tail_by_seg.get(sg)
            if sg in path_segs:
                # 弦取实际端点距与 _piece_chord 的较小者：普通脊线两者
                # 相等（关节按 _piece_chord 累计）；闭环脊线关节按 3D 弦
                # 排多边形，实际端点距 < 弧长，须打折补长（否则 H2 报错）
                chord = min(self._piece_chord(sg), dist(a_pt, b_pt))
                if chord < pc['length'] - 1e-9:
                    pts, bad = self._kink_best(a_pt, b_pt, pc['length'],
                                               check_subs)
                    bends.append({'branch': key, 'seg': sg,
                                  'at': pc['na'], 'delta': 'kink',
                                  'note': (f"闭环边打折：弦 {chord:.1f} < "
                                           f"段长 {pc['length']:.1f}")
                                  if spine['id'] in self._ring_spines else
                                  (f"平行预折：弦 {chord:.1f} < "
                                   f"段长 {pc['length']:.1f}")})
                else:
                    pts, bad = [a_pt, b_pt], check_subs([(a_pt, b_pt)])
                seg_pts[sg] = pts
                subs = [(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
                accept_subs(subs)
                if bad:
                    n_bad += bad
                    warnings.append(f"{key}/{sg} 路径段与已画线干涉 {bad} 处")
            elif t is not None and t['kind'] in ('constrained', 'detached'):
                # 受约束/detached 尾段：两端已定，打折补长（恰好 fitting
                # 时为直线；detached 远端已在上步按槽位方向定位，弦长即弧长）
                # 环弦符号（2026-11-18）：段长 < 端点距时 1:1 直线在几何上
                # 不可能（_kink_best 只会拉直，见地板 SEG05 43.5mm 画成
                # 3079mm 的斜线），改画等边小三角符号（周长=弧长）于近端，
                # merge 按自环通道改画小环符号；§六环优先待实现后取消。
                if pc['length'] < dist(a_pt, b_pt) - 1e-9:
                    tri, bad = self._triangle_best(
                        a_pt, angle_of(a_pt, b_pt), pc['length'], check_subs)
                    seg_pts[sg] = tri
                    self.symbol_segs.append(
                        {'seg': sg, 'branch': key, 'na': pc['na'],
                         'nb': pc['nb'], 'length_mm': pc['length'],
                         'dia_mm': self.topo.branches[key]['dia'],
                         'at': pc['na']})
                    subs = [(tri[k], tri[k + 1]) for k in range(3)]
                    accept_subs(subs, skip_dist=True)
                    if bad:
                        n_bad += bad
                    warnings.append(
                        f"{key}/{sg} 环弦符号：段长 {pc['length']:.1f} < "
                        f"端点距 {dist(a_pt, b_pt):.1f}，无法按 1:1 画直线，"
                        f"画小三角符号于 {pc['na']}（§六环优先待实现）")
                    continue
                pts, bad = self._kink_best(a_pt, b_pt, pc['length'],
                                           check_subs)
                if len(pts) > 2:
                    bends.append({'branch': key, 'seg': sg,
                                  'at': pc['na'], 'delta': 'kink',
                                  'note': f"{'受约束' if t['kind'] == 'constrained' else 'detached'}"
                                          f"尾段打折：弦 "
                                          f"{dist(a_pt, b_pt):.1f} < "
                                          f"段长 {pc['length']:.1f}"})
                seg_pts[sg] = pts
                subs = [(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
                accept_subs(subs)
                if bad:
                    n_bad += bad
                    warnings.append(f"{key}/{sg} 受约束尾段与已画线干涉 {bad} 处")
            elif t is not None and t['kind'] == 'free':
                pts = [a_pt, b_pt]
                bad = check_subs([(a_pt, b_pt)])
                seg_pts[sg] = pts
                accept_subs([(a_pt, b_pt)])
                if bad:
                    n_bad += bad
                    warnings.append(f"{key}/{sg} 自由尾段与已画线干涉 {bad} 处")
            else:
                # 既非路径段亦非尾段（不应发生）：按直线画
                warnings.append(f"{key}/{sg} 既非路径段亦非尾段，按直线画")
                pts = [a_pt, b_pt]
                seg_pts[sg] = pts
                accept_subs([(a_pt, b_pt)])
        # 关节位置补全：分支全部关节必须有位置（H3 用）
        for idx, nd in enumerate(joints):
            if idx not in joint_pos and nd in pos:
                joint_pos[idx] = pos[nd]
        points = []
        for pc in pieces:
            pts = seg_pts.get(pc['seg'])
            if pts is None:
                continue
            if not points:
                points += pts
            else:
                points += pts[1:]
        if len(points) < 2:
            self.warnings.append(f"{key} 脊线分支放置失败（点列不足）")
            return False
        res = {'points': points,
               'pieces': {sg: (pts[0], pts[-1])
                          for sg, pts in seg_pts.items()},
               'seg_pts': seg_pts, 'joint_pos': dict(joint_pos),
               'bends': bends, 'warnings': warnings, 'n_bad': n_bad}
        self._commit(key, res)
        self.placed_kind[key] = 'spine'
        self.placed_angle[key] = spine['direction']
        return True

    def place_branch_best(self, key):
        """覆盖 v3：单段未分配分支若两端已定且段长 < 端点距（1:1 直线在
        几何上不可能），不画对角线，改画等边小三角符号（周长=弧长）于
        一端（§六环优先 interim：地板 SEG05 43.5mm 曾被 v3 拉直成
        3079mm 的斜线，H2 失败）。三角朝向取 24 朝向中干涉最少者（同
        _triangle_best，含避开脊线方向的罚分）。其余分支走 v3 原逻辑。
        多段分支若含不可能受约束段暂不处理（数据中无此情况），仍走
        v3 原逻辑并由其记录长度误差。"""
        b = self.topo.branches[key]
        pieces = b['pieces']
        if len(pieces) == 1:
            pc = pieces[0]
            if pc['na'] != pc['nb']:
                A = self.node_pos.get(pc['na'])
                B = self.node_pos.get(pc['nb'])
                if (A is not None and B is not None
                        and pc['length'] < dist(A, B) - 1e-9):
                    def check_subs(subs, skip_dist=False):
                        bad = 0
                        for (q1, q2) in subs:
                            if self.piece_overlaps(q1, q2, []):
                                bad += 10
                            elif self.piece_conflicts(
                                    q1, q2, [], skip_dist=skip_dist):
                                bad += 1
                        return bad
                    tri, bad = self._triangle_best(
                        A, angle_of(A, B), pc['length'], check_subs)
                    res = {'points': tri,
                           'pieces': {pc['seg']: (tri[0], tri[-1])},
                           'seg_pts': {pc['seg']: tri},
                           'joint_pos': {0: A, 1: B},
                           'bends': [],
                           'warnings': [f"{key}/{pc['seg']} 环弦符号：段长 "
                                        f"{pc['length']:.1f} < 端点距 "
                                        f"{dist(A, B):.1f}，无法按 1:1 画直线，"
                                        f"画小三角符号于 {pc['na']}"
                                        f"（§六环优先待实现）"],
                           'n_bad': bad}
                    self.symbol_segs.append(
                        {'seg': pc['seg'], 'branch': key, 'na': pc['na'],
                         'nb': pc['nb'], 'length_mm': pc['length'],
                         'dia_mm': b['dia'], 'at': pc['na']})
                    self._commit(key, res)
                    return True
        return super().place_branch_best(key)

    # ---------- 分量布局（脊线 0 → 子脊线 BFS → 未分配分支） ----------
    def layout_component(self, comp_keys, origin):
        """一个连通分量的展开：先放脊线 0（主分量居中），再按 BFS 层序
        放子脊线，最后放未分配分支（平行单段/纯自环，受约束路径）。"""
        comp = set(comp_keys)
        rings, self_loops, parallels = self.topo.find_cycles(comp_keys)
        self.cycle_info[len(self.cycle_info)] = {'rings': rings, 'self_loops': self_loops,
                                                 'parallel_pairs': parallels}
        for sg in self_loops:
            self.self_loop_segs.add(sg)
        for (a, b_) in parallels:
            self.parallel_sib[a].append(b_)
            self.parallel_sib[b_].append(a)
        ci = next(i for i, c in enumerate(self._comps) if set(c) == comp)
        spines = [s for s in self.spines if s['comp'] == ci]
        if rings:
            self.warnings.append(
                f"分量含 {len(rings)} 个真环：闭环脊线按 §六整体画环，"
                f"其余环分支按受约束段处理；弧长<端点距的环弦画小三角"
                f"符号（§六未全实现，见清单局限）")
        for s in spines:
            if s['level'] != 0:
                continue
            if ci == self._main_comp:
                anchor_pt = (origin[0] - self._spine_total_chord(s) / 2.0,
                             origin[1])
            else:
                anchor_pt = origin
            self._place_spine(s, anchor_pt)
        for s in spines:
            if s['level'] == 0:
                continue
            anchor_pt = self.node_pos.get(s['anchor'])
            if anchor_pt is None:
                self.warnings.append(
                    f"脊线 {s['id']}（{s['branches'][0]}）锚点 "
                    f"{s['anchor']} 未放置，跳过")
                continue
            self._place_spine(s, anchor_pt)
        for key, _reason in self.unassigned_branches:
            if key not in comp or key in self.placed:
                continue
            if key in self.hidden_whole_branches:
                continue  # §十五：平行未单画，整根不画线（数据在 hidden_parallel）
            if not self.place_branch_best(key):
                self.warnings.append(f"{key} 放置失败，强制另起主干")
                self.place_trunk(key, self.next_origin())

    # ---------- 放置侧搜索（一级脊线子树总长前 6，穷举 64 种） ----------
    def search_top_sides(self):
        """与 v5 同法、改选支：子树总长最大的 6 根一级脊线首根，
        穷举 2^6=64 种侧组合，各跑一遍放置，选综合最优者作为
        side_override。评分 = 居中偏差% + 0.5×X交叉数。
        槽位碰撞的组合（同关节方向重合）跳过。"""
        def subtree_len(k):
            s = self.topo.branches[k]['length']
            for c in self.tree[k]['children']:
                s += subtree_len(c)
            return s

        d1 = [s['branches'][0] for s in self.spines if s['level'] == 1]
        lv = sorted(d1, key=lambda k: (-subtree_len(k), k))[:TOP_SIDE_SEARCH_N]
        if not lv:
            return
        best = None
        for bits in itertools.product([0, 1], repeat=len(lv)):
            ov = dict(zip(lv, bits))
            trial = LayoutV6p1(self.topo, clearance=self.clearance,
                             verbose=False)
            trial.run_projection()
            trial.compute_trunk_path()
            trial.decompose()
            trial.build_branch_tree()
            trial.assign_spine_slots()
            trial.inventory_layers()
            trial.side_override = ov
            if not trial.compute_spine_directions():
                continue
            Layout.run(trial)
            dev = trial._center_dev_of_bbox(trial.bbox())
            n_x, n_near, n_ov = count_interference_detailed(trial)
            score = dev + 0.5 * n_x
            cand = (round(score, 9), round(dev, 9), n_x, n_near, bits)
            if best is None or cand < best[0]:
                best = (cand, ov, dev, n_x, n_near, n_ov)
        if best is None:
            self.warnings.append("放置侧搜索：64 种组合全部槽位碰撞，"
                                 "保持分配侧")
            return
        _, ov, dev, n_x, n_near, n_ov = best
        self.side_override = ov
        flipped = sorted(k for k, v in ov.items() if v == 1)
        self.log_phase('放置侧搜索',
                       f"穷举 {2 ** len(lv)} 种顶层侧组合，最优居中偏差 "
                       f"{dev:.2f}% X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}；"
                       f"翻转侧：{flipped if flipped else '无'}")

    # ---------- 孤岛分量就近放置（§十九） ----------
    def relocate_island_components(self, clearance=20.0, max_radius=1200.0):
        """孤岛分量就近放置（2026-11-18，用户报“孤岛路径”）。

        非主分量（与主线束无连接的独立分量，如 C289 真环）不再一律放
        主分量包围盒右侧（3D 里贴着 20.1-23X、图上却隔 4747mm），而是
        放到它在 3D 里最近的邻居节点附近的干净空位，图面反映真实空间
        关系。平移是刚体变换：长度、角度、拓扑全不变，只改坐标。
        锚点：分量 3D 质心最近的主分量节点（拓扑 xyz 欧氏距离）。
        空位：以锚点 2D 位置为中心螺旋搜索，包围盒 + clearance 间隙
        内无线段交叉、无节点穿入（15mm）即为干净；搜不到保持原位记警告。
        """
        if len(self._comps) <= 1:
            return
        main_keys = set(self._comps[self._main_comp])
        main_nodes = set()
        for k in main_keys:
            main_nodes.update(self.topo.branch_nodes(k))
        # 其余分量的线段与节点（干涉检查用，全图除本分量）
        for ci, comp in enumerate(self._comps):
            if ci == self._main_comp:
                continue
            comp_keys = [k for k in comp if k in self.placed]
            if not comp_keys:
                continue
            comp_nodes = set()
            for k in comp_keys:
                comp_nodes.update(self.topo.branch_nodes(k))
            comp_nodes &= set(self.node_pos)
            # 3D 质心 -> 最近的主分量节点
            pts3 = [self.topo.nodes[c]['xyz'] for c in comp_nodes
                    if self.topo.nodes.get(c, {}).get('xyz')]
            if not pts3:
                continue
            cen3 = [sum(p[i] for p in pts3) / len(pts3) for i in range(3)]
            best_n, best_d = None, 1e18
            for c in main_nodes:
                xyz = self.topo.nodes.get(c, {}).get('xyz')
                if not xyz or c not in self.node_pos:
                    continue
                d = math.dist(cen3, xyz)
                if d < best_d:
                    best_n, best_d = c, d
            if best_n is None:
                continue
            ax, ay = self.node_pos[best_n]
            # 本分量 2D 质心与点列
            comp_pts = []
            for k in comp_keys:
                comp_pts.extend(self.placed[k]['points'])
            if not comp_pts:
                continue
            ccx = sum(p[0] for p in comp_pts) / len(comp_pts)
            ccy = sum(p[1] for p in comp_pts) / len(comp_pts)
            # 其余线段（包围盒预筛）与节点
            rest_segs = []
            for k, res in self.placed.items():
                if k in comp_keys:
                    continue
                pp = res['points']
                for i in range(len(pp) - 1):
                    rest_segs.append((pp[i], pp[i + 1]))
            rest_nodes = {c: p for c, p in self.node_pos.items()
                          if c not in comp_nodes}
            comp_segs = []
            for k in comp_keys:
                pp = self.placed[k]['points']
                for i in range(len(pp) - 1):
                    comp_segs.append((pp[i], pp[i + 1]))

            def _clean(dx, dy):
                moved = [((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy))
                         for a, b in comp_segs]
                xs = [p[0] for s in moved for p in s]
                ys = [p[1] for s in moved for p in s]
                x0, x1 = min(xs) - clearance, max(xs) + clearance
                y0, y1 = min(ys) - clearance, max(ys) + clearance
                for (a, b) in moved:
                    for (c, e) in rest_segs:
                        if (max(c[0], e[0]) < x0 or min(c[0], e[0]) > x1
                                or max(c[1], e[1]) < y0
                                or min(c[1], e[1]) > y1):
                            continue
                        if seg_proper_intersect(a, b, c, e):
                            return False
                        if pt_seg_dist(a, c, e) < 15.0 or pt_seg_dist(
                                b, c, e) < 15.0:
                            return False
                for (nx, ny) in rest_nodes.values():
                    if not (x0 <= nx <= x1 and y0 <= ny <= y1):
                        continue
                    for (a, b) in moved:
                        if pt_seg_dist((nx, ny), a, b) < 15.0:
                            return False
                for c in comp_nodes:
                    px, py = self.node_pos[c]
                    qx, qy = px + dx, py + dy
                    for (a, b) in rest_segs:
                        if (max(a[0], b[0]) < qx - 15.0
                                or min(a[0], b[0]) > qx + 15.0
                                or max(a[1], b[1]) < qy - 15.0
                                or min(a[1], b[1]) > qy + 15.0):
                            continue
                        if pt_seg_dist((qx, qy), a, b) < 15.0:
                            return False
                return True

            # 螺旋搜索：半径 50mm 步进，12 个方向
            found = None
            r = 50.0
            while r <= max_radius and found is None:
                for k in range(12):
                    ang = math.radians(k * 30.0)
                    tx, ty = ax + r * math.cos(ang), ay + r * math.sin(ang)
                    dx, dy = tx - ccx, ty - ccy
                    if _clean(dx, dy):
                        found = (dx, dy, r)
                        break
                r += 50.0
            if found is None:
                self.warnings.append(
                    f"孤岛分量 {ci}（{comp_keys[0]}）：{max_radius:.0f}mm 内"
                    f"无干净空位，保持原位")
                continue
            dx, dy, r = found
            old_dist = math.hypot(ccx - ax, ccy - ay)
            # 落地：平移本分量全部几何状态
            for c in comp_nodes:
                px, py = self.node_pos[c]
                self.node_pos[c] = (px + dx, py + dy)
            for k in comp_keys:
                res = self.placed[k]
                res['points'] = [(x + dx, y + dy) for (x, y) in res['points']]
                res['joint_pos'] = {i: (x + dx, y + dy)
                                    for i, (x, y) in res['joint_pos'].items()}
                res['pieces'] = {sg: ((a[0] + dx, a[1] + dy),
                                      (b[0] + dx, b[1] + dy))
                                 for sg, (a, b) in res['pieces'].items()}
                res['seg_pts'] = {sg: [(x + dx, y + dy) for (x, y) in pts]
                                  for sg, pts in res['seg_pts'].items()}
                for sg in res['pieces']:
                    if sg in self.piece_pos:
                        (a, b) = self.piece_pos[sg]
                        self.piece_pos[sg] = ((a[0] + dx, a[1] + dy),
                                              (b[0] + dx, b[1] + dy))
            self.placed_pieces = [
                ((a[0] + dx, a[1] + dy) if k in comp_keys else a,
                 (b[0] + dx, b[1] + dy) if k in comp_keys else b,
                 k, sg, sk)
                for (a, b, k, sg, sk) in self.placed_pieces]
            if ci < len(self.comp_boxes):
                (x0, y0, x1, y1) = self.comp_boxes[ci]
                self.comp_boxes[ci] = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
            self.log_phase('孤岛就近',
                           f"分量 {ci}（{comp_keys[0]}）3D 最近邻 {best_n}"
                           f"（{best_d:.1f}mm），2D 从距锚点 {old_dist:.0f}mm"
                           f" 移到 {r:.0f}mm")

    # ---------- 主流程 ----------
    def run(self):
        self.log_phase('开始',
            f"分支 {len(self.topo.branches)} / 节点 {len(self.topo.nodes)} "
            f"/ 线段 {len(self.topo.segs)}")
        self.run_projection()          # 阶段 3：初始二维投影（PCA）
        self.compute_trunk_path()      # 阶段 2：主干路径（连接器—连接器最长路径）
        self.decompose()               # §十四：逐层最长路径分解（先算后画）
        self.build_branch_tree()       # 扁平树（同脊线分支皆为脊线首根子节点）
        self.assign_spine_slots()      # 阶段 4 准备：脊线槽位分配
        self.inventory_layers()        # H6/H10：先找齐再画（关节清点）
        self.search_top_sides()        # 阶段 4 前置：一级脊线侧组合穷举
        if not self.compute_spine_directions():
            self.warnings.append("脊线方向槽位碰撞（不应发生于分配侧）")
        # §十四铁律：先算后画——完整方案组装并写盘，再开始绘制
        self.build_plan()
        if self.plan_path:
            self.write_plan(self.plan_path)
        self.log_phase('方案',
            f"plan.json 完整：脊线 {len(self.spines)} 条、层记录 "
            f"{len(self.layers)} 个关节、槽位 {len(self.slot_info)} 根；"
            f"方案先于放置")
        Layout.run(self)               # 阶段 4：脊线单位布局
        self.relocate_island_components()  # 孤岛分量就近放置（§十九）
        n_x, n_near, n_ov = count_interference_detailed(self)
        self.log_phase('放置完成', f"残留 X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}")
        # 阶段 5：居中与消交叉交替（最多 5 轮），直至两者同时达标或一轮内无翻转
        # 消交叉至少跑一次——放置后居中/重叠已达标时直接退出会跳过消交叉。
        # 翻转安全由 _rotation_safe 覆盖保证：只许脊线首根转（整条脊线
        # 连同子树一起旋），脊线中部/末根禁转——否则会把脊线折回自身
        # （2026-11-17 实测：Body.89 被折回，造 3 处重叠），破坏 §十四。
        untangle_tried = False
        for rnd in range(5):
            n_x, n_near, n_ov = count_interference_detailed(self)
            dev = self._center_dev_of_bbox(self.bbox())
            if n_ov == 0 and dev <= CENTER_TOL_V6 * 100.0:
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

    # ---------- 正交核查（脊线级，H8） ----------
    def _ortho_check(self):
        """H9（脊线级）：每条子脊线的首段弦方向 vs 上级脊线方向，
        夹角应为 90°±30°k（k=0,1,2,3；同点第 3 根起 30° 偏转在
        ±30°k 内），容差 0.5°；同时核查每条脊线内部共线
        （关节偏离脊线直线 ≤0.01mm）。未分配分支跳过（受约束段）。
        返回 (checked, bad, details, deviated_30, spine_straight_bad)。"""
        checked, bad = 0, 0
        details = []
        deviated_30 = []
        spine_straight_bad = []
        # 脊线内部共线：关节偏离（首关节→末关节）直线
        for s in self.spines:
            js = s['joints']
            if len(js) < 3:
                continue
            p0 = self.node_pos.get(js[0])
            p1 = self.node_pos.get(js[-1])
            if p0 is None or p1 is None or pt_eq(p0, p1):
                continue
            for j in js[1:-1]:
                p = self.node_pos.get(j)
                if p is None:
                    continue
                d = pt_seg_dist(p, p0, p1)
                if d > SPINE_STRAIGHT_TOL_MM:
                    spine_straight_bad.append((s['id'], j, round(d, 3)))
        # 子脊线 vs 上级脊线方向
        for s in self.spines:
            if s['level'] == 0:
                continue
            js = s['joints']
            if len(js) < 2:
                continue
            p0 = self.node_pos.get(js[0])
            p1 = self.node_pos.get(js[1])
            if p0 is None or p1 is None or pt_eq(p0, p1):
                continue
            child_ang = angle_of(p0, p1)
            if 'stub_seg' in s:
                tail = self.tail_by_seg[s['stub_seg']]
                tp0 = self.node_pos.get(tail['joint'])
                tp1 = self.node_pos.get(tail['far'])
                if tp0 is None or tp1 is None or pt_eq(tp0, tp1):
                    continue
                parent_ang = angle_of(tp0, tp1)
            else:
                ps = self.spine_by_id[s['parent']]
                pjs = ps['joints']
                # 上级脊线在锚点处的走向：锚点→下一路径关节（末关节取上一关节→锚点）
                if s['anchor'] not in pjs:
                    continue
                ai = pjs.index(s['anchor'])
                if ai + 1 < len(pjs):
                    q0 = self.node_pos.get(pjs[ai])
                    q1 = self.node_pos.get(pjs[ai + 1])
                elif ai > 0:
                    q0 = self.node_pos.get(pjs[ai - 1])
                    q1 = self.node_pos.get(pjs[ai])
                else:
                    continue
                if q0 is None or q1 is None or pt_eq(q0, q1):
                    continue
                parent_ang = angle_of(q0, q1)
            rel = (child_ang - parent_ang) % 180.0
            # 到最近的 90°±30°k 的距离
            devs = [abs(rel - t) for t in (30.0, 60.0, 90.0, 120.0, 150.0)]
            dev = min(devs)
            checked += 1
            first = s['branches'][0]
            if dev > ORTHO_TOL_DEG:
                bad += 1
                details.append((first, round(rel, 1), round(dev, 1)))
            elif abs(rel - 90.0) > ORTHO_TOL_DEG:
                deviated_30.append((first, round(rel, 1)))
        return checked, bad, details, deviated_30, spine_straight_bad

    # ---------- 投影方向符合率（脊线级，S5 用） ----------
    def _side_compliance(self):
        """脊线级投影侧符合率：子脊线首段实际方向与投影方向是否同侧
        （相对上级脊线方向的符号一致）。返回 (total, match, mismatches)。"""
        total, match = 0, 0
        mismatches = []
        for s in self.spines:
            if s['level'] == 0:
                continue
            rel = s.get('proj_ang')
            if rel is None or abs(rel) < 1e-9:
                continue
            js = s['joints']
            if len(js) < 2:
                continue
            p0 = self.node_pos.get(js[0])
            p1 = self.node_pos.get(js[1])
            if p0 is None or p1 is None or pt_eq(p0, p1):
                continue
            child_ang = angle_of(p0, p1)
            if 'stub_seg' in s:
                tail = self.tail_by_seg[s['stub_seg']]
                tp0 = self.node_pos.get(tail['joint'])
                tp1 = self.node_pos.get(tail['far'])
                if tp0 is None or tp1 is None or pt_eq(tp0, tp1):
                    continue
                parent_ang = angle_of(tp0, tp1)
            else:
                ps = self.spine_by_id[s['parent']]
                pjs = ps['joints']
                if s['anchor'] not in pjs:
                    continue
                ai = pjs.index(s['anchor'])
                if ai + 1 < len(pjs):
                    q0 = self.node_pos.get(pjs[ai])
                    q1 = self.node_pos.get(pjs[ai + 1])
                elif ai > 0:
                    q0 = self.node_pos.get(pjs[ai - 1])
                    q1 = self.node_pos.get(pjs[ai])
                else:
                    continue
                if q0 is None or q1 is None or pt_eq(q0, q1):
                    continue
                parent_ang = angle_of(q0, q1)
            actual = (child_ang - parent_ang) % 360.0
            actual = actual - 360.0 if actual > 180.0 else actual
            total += 1
            if (actual > 0) == (rel > 0):
                match += 1
            else:
                mismatches.append((s['branches'][0], round(rel, 1),
                                   round(actual, 1)))
        return total, match, mismatches

    # ---------- 脊线共线偏差（H10 用） ----------
    def _spine_straightness(self):
        """每条脊线的共线偏差与单调性：全部关节到脊线（首关节→末关节
        直线）的最大垂距；关节沿脊线方向的投影须按路径顺序单调递增
        （折回即非单调——2026-11-17 实测 flip_center 曾把脊线 7 末根
        Body.89 折回，折后仍共线，共线检查抓不到，必须查单调性）。
        返回 [(spine_id, anchor, end, n_joints, max_dev_mm, mono_ok)]；
        关节未放置时 max_dev 为 None、mono_ok 为 False。
        闭环脊线（§六整体画环）不适用拉直核查：记 0.0/True，清单另注豁免。"""
        out = []
        for s in self.spines:
            joints = s['joints']
            if s['id'] in self._ring_spines:
                out.append((s['id'], s['anchor'], s['end'], len(joints),
                            0.0, True))
                continue
            a = self.node_pos.get(joints[0])
            b = self.node_pos.get(joints[-1])
            if a is None or b is None:
                out.append((s['id'], s['anchor'], s['end'], len(joints),
                            None, False))
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            if L < 1e-9:
                out.append((s['id'], s['anchor'], s['end'], len(joints),
                            0.0, True))
                continue
            ux, uy = dx / L, dy / L
            max_dev = 0.0
            mono_ok = True
            prev = None
            for nd in joints:
                p = self.node_pos.get(nd)
                if p is None:
                    max_dev = None
                    mono_ok = False
                    break
                dev = abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / L
                max_dev = max(max_dev, dev)
                proj = (p[0] - a[0]) * ux + (p[1] - a[1]) * uy
                if prev is not None and proj < prev - 1e-6:
                    mono_ok = False
                prev = proj if prev is None else max(prev, proj)
            out.append((s['id'], s['anchor'], s['end'], len(joints),
                        None if max_dev is None else round(max_dev, 4),
                        mono_ok))
        return out

    # ---------- 规则检查清单（v6p1：H1–H10 独立实现，不复用 v4 清单） ----------
    # 注意：v4 的 run_checklist 依赖 v4 版 _ortho_check/_side_compliance 的
    # 返回签名，v6 两者均为脊线级新签名，故 v6p1 清单独立实现。
    # 编号按任务书定版：H1 路径主干 / H2 长度 / H3 拓扑 / H4 零压着画 /
    # H5 全画出 / H6 先算完再画（plan.json 完整先于放置）/ H7 投影 /
    # H8 确定性 / H9 正交（脊线级）/ H10 主分支拉直（脊线共线）。
    # DXF 回读是交付前验证步骤（见 main），不占清单编号。
    def run_checklist(self, det_md5_a=None, det_md5_b=None, det_pass=None):
        """执行 v6p1 规则检查清单。返回 (checklist, all_hard_pass)。"""
        st = self.validate()
        n_x, n_near, n_ov = count_interference_detailed(self)
        ci = self.center_info
        hard = []
        soft = []

        # H1 路径主干——(a)共线 (b)水平 (c)横竖两方向居中（同 v5）
        h1a = ci.get('trunk_max_y_dev_mm', 99) <= TRUNK_COLLINEAR_TOL_MM
        h1b = ci.get('trunk_angle_from_horizontal_deg', 99) <= TRUNK_ANGLE_TOL
        h1c_x = ci.get('dev_x_pct', 99) <= ci.get('tol_pct', 5.0)
        h1c_y_nominal = ci.get('dev_y_pct', 99) <= ci.get('tol_pct', 5.0)
        # 竖向豁免（H1_VERTICAL_EXEMPTION，用户 2026-11-17 21:39 决定）：
        # 名义阈值仍是 5%，实测值照实记录；仅当竖偏差未超已接受值时豁免通过。
        h1c_y_exempt = (
            not h1c_y_nominal
            and H1_VERTICAL_EXEMPTION is not None
            and ci.get('dev_y_pct', 99)
            <= H1_VERTICAL_EXEMPTION['accepted_dev_y_pct']
            + H1_EXEMPTION_MARGIN_PCT)
        h1c = h1c_x and (h1c_y_nominal or h1c_y_exempt)
        h1_pass = bool(ci.get('ok')) and h1a and h1b and h1c
        h1_exempt_note = ''
        if h1c_y_exempt:
            h1_exempt_note = (
                f"【豁免通过】{H1_VERTICAL_EXEMPTION['decision']}（"
                f"{H1_VERTICAL_EXEMPTION['decision_date']}）；竖偏差实测 "
                f"{ci.get('dev_y_pct')}% 已接受（上限 "
                f"{H1_VERTICAL_EXEMPTION['accepted_dev_y_pct']}%，名义阈值仍为 5%）")
        hard.append({
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
                          f"(c)横竖偏差均 ≤ {CENTER_TOL_V6 * 100:.0f}%"),
            'pass': h1_pass,
            'exempt': bool(h1c_y_exempt),
            'exempt_note': h1_exempt_note,
        })

        # H2 长度 1:1（§二.1；§十五隐藏段按应画长度核查，见 validate）
        max_err = st['max_len_err_mm']
        worst = ''
        if st['len_errs']:
            w = sorted(st['len_errs'],
                       key=lambda t: (-abs(t[3]), t[0]))[0]
            worst = (f"（最大误差分支 {w[0]}，3D {w[1]:.1f}mm → "
                     f"2D {w[2]:.1f}mm，误差 {w[3]:+.2f}mm）")
        adj_txt = ''
        partial_hidden = {
            k: v for k, v in self.hidden_seg_len_by_branch.items()
            if k not in self.hidden_whole_branches}
        if partial_hidden:
            adj_txt = '；§十五隐藏段按应画长度核查：' + '、'.join(
                f"{k} 应画 "
                f"{self.topo.branches[k]['length'] - v:.1f}mm"
                f"（3D {self.topo.branches[k]['length']:.1f}−隐藏 {v:.1f}）"
                for k, v in sorted(partial_hidden.items()))
        if self.symbol_segs:
            adj_txt += '；环弦符号 ' + '、'.join(
                f"{r['branch']} {r['seg']} {r['length_mm']:.1f}mm"
                f"（{r['na']}—{r['nb']}，段长<端点距，画小三角符号于 "
                f"{r['at']}，三角周长=弧长故 1:1 误差 0；§六环优先待实现）"
                for r in self.symbol_segs)
        h2_pass = max_err <= LEN_ERR_TOL_V6 + 1e-9
        hard.append({
            'id': 'H2', 'rule': '§二.1 长度 1:1', 'name': '长度 1:1',
            'value': f"2D 长度与 3D 弧长最大误差 {max_err:.2f}mm{worst}{adj_txt}",
            'threshold': f"≤ {LEN_ERR_TOL_V6}mm",
            'pass': h2_pass,
        })

        # H3 拓扑不变（§二.2）：每根分支的关节位置与 node_pos 一致
        bad = []
        checked = 0
        for key, res in self.placed.items():
            joints = self._joints(key)
            for idx, pos in res['joint_pos'].items():
                checked += 1
                node = joints[idx]
                if node not in self.node_pos or \
                        not pt_eq(self.node_pos[node], pos, tol=1e-6):
                    bad.append(f"{key}@{node}")
        h3_pass = not bad
        hard.append({
            'id': 'H3', 'rule': '§二.2 拓扑不变', 'name': '拓扑不变',
            'value': f"核对 {checked} 个分支-关节端点，"
                     + (f"{len(bad)} 处不一致：{bad[:5]}" if bad else "全部与 3D 节点一致"),
            'threshold': '0 处不一致',
            'pass': h3_pass,
        })

        # H4 零压着画（§二.3）
        h4_pass = n_ov == 0
        hard.append({
            'id': 'H4', 'rule': '§二.3 不重叠（压着画）', 'name': '零压着画',
            'value': f"共线重叠 {n_ov} 对",
            'threshold': '0 对',
            'pass': h4_pass,
        })

        # H5 全画出（§十五：平行未单画的分支/线段不计入应画数，
        # 数据在 hidden_parallel，不算漏画；§二十二：已排除的过孔零件
        # 不在拓扑里，应画数按排除后计）
        n_segs_placed = len(self.piece_pos)
        n_segs_total = len(self.topo.segs)
        n_hb = len(self.hidden_whole_branches)
        n_hs = len(self.hidden_parallel_segs)
        h5_pass = (st['branches_placed'] == st['branches_total'] - n_hb and
                   st['nodes_placed'] == st['nodes_total'] and
                   n_segs_placed == n_segs_total - n_hs)
        excl_txt = ''
        if self.excluded_branches:
            excl_txt = ('；已排除过孔零件 '
                        + '、'.join(e['key']
                                    for e in self.excluded_branches)
                        + '（§二十二，不画，不计入应画数）')
        hard.append({
            'id': 'H5', 'rule': '§二 完整性 + §十五 平行对只画一根 + §二十二 过孔零件排除',
            'name': '全画出',
            'value': (f"分支 {st['branches_placed']}/{st['branches_total']} "
                      f"（平行未单画 {n_hb} 根：{sorted(self.hidden_whole_branches)}），"
                      f"节点 {st['nodes_placed']}/{st['nodes_total']}，"
                      f"线段 {n_segs_placed}/{n_segs_total} "
                      f"（平行未单画 {n_hs} 段：{sorted(self.hidden_parallel_segs)}）"
                      f"{excl_txt}"),
            'threshold': '全部画出（§十五平行未单画除外，数据记入 hidden_parallel；§二十二已排除除外）',
            'pass': h5_pass,
        })

        # H6 先算完再画（§十四铁律）：方案 plan.json 完整先于放置开始；
        # 方案内容核查：每关节主分支确实最长、层记录覆盖全部子脊线、
        # 自环分支不参与、全部 110 分支有归属
        plan_seq = place_seq = None
        for (s, ph, _m) in self.phase_log:
            if ph == '方案' and plan_seq is None:
                plan_seq = s
            if ph == '放置' and place_seq is None:
                place_seq = s
        order_ok = (plan_seq is not None and place_seq is not None
                    and plan_seq < place_seq)
        plan = self.plan or {}
        n_in_spines = len(self.branch_spine)
        n_unassigned = len(self.unassigned_branches)
        cover_ok = (plan.get('complete') is True
                    and n_in_spines + n_unassigned == len(self.topo.branches)
                    and len(plan.get('layers', [])) == len(self.layers)
                    and len(plan.get('slots', {}).get('info', {}))
                    == len(self.slot_info))
        layer_problems = []
        n_joints = len(self.layers)
        n_cands = sum(len(r['candidates']) for r in self.layers)
        n_main = 0
        seen_spines = {}
        for r in self.layers:
            cands = r['candidates']
            if not cands:
                layer_problems.append(f"关节 {r['joint']} 无候选")
                continue
            lengths = [c['length'] for c in cands]
            if abs(max(lengths) - cands[0]['length']) > 1e-9:
                layer_problems.append(
                    f"关节 {r['joint']} 主分支不是最长"
                    f"（首候选 {cands[0]['length']:.1f}，最大 {max(lengths):.1f}）")
            main = cands[0]
            sid = main['spine_id']
            s = self.spine_by_id.get(sid)
            if s is None:
                layer_problems.append(f"关节 {r['joint']} 主分支脊线 {sid} 不存在")
                continue
            if not s['is_main']:
                layer_problems.append(f"关节 {r['joint']} 主分支脊线 {sid} 未标主分支")
            if abs(s['length'] - main['length']) > 1e-9:
                layer_problems.append(
                    f"关节 {r['joint']} 主分支长度不一致"
                    f"（脊线 {s['length']:.1f} vs 记录 {main['length']:.1f}）")
            if s['branches'][0] != main['first_branch']:
                layer_problems.append(
                    f"关节 {r['joint']} 主分支首根不一致"
                    f"（{s['branches'][0]} vs {main['first_branch']}）")
            n_main += 1
            for c in cands:
                if c['spine_id'] in seen_spines:
                    layer_problems.append(
                        f"脊线 {c['spine_id']} 在两个层记录中出现")
                seen_spines[c['spine_id']] = r['joint']
        n_child_spines = sum(1 for s in self.spines if s['level'] > 0)
        if len(seen_spines) != n_child_spines:
            layer_problems.append(
                f"层记录覆盖子脊线 {len(seen_spines)} 条 ≠ 子脊线总数 {n_child_spines}")
        pure_loops = {k for k, _r in self.unassigned_branches
                      if len(self.topo.branches[k]['pieces']) == 1 and
                      self.topo.branches[k]['pieces'][0]['na'] ==
                      self.topo.branches[k]['pieces'][0]['nb']}
        for r in self.layers:
            for c in r['candidates']:
                for b in c['branches']:
                    if b in pure_loops:
                        layer_problems.append(
                            f"自环分支 {b} 出现在关节 {r['joint']} 的候选中")
        h6_pass = order_ok and cover_ok and not layer_problems
        hard.append({
            'id': 'H6', 'rule': '§十四 先算后画（铁律）', 'name': '先算完再画',
            'value': (f"方案阶段 seq={plan_seq}，放置阶段 seq={place_seq}，"
                      f"方案在放置之前；方案完整：脊线内分支 {n_in_spines} + "
                      f"未分配 {n_unassigned} = {len(self.topo.branches)}；"
                      f"层记录 {n_joints} 个关节、{n_cands} 个侧枝候选、"
                      f"主分支 {n_main} 条；子脊线 {n_child_spines} 条全部在层记录中；"
                      f"自环分支 {sorted(pure_loops)} 未参与"
                      + (f"；问题：{layer_problems[:5]}" if layer_problems else "；逐关节主分支均为最长")),
            'threshold': '方案完整且在放置之前；每关节主分支确实最长，层记录覆盖全部子脊线，自环不参与',
            'pass': h6_pass,
        })

        # H7 投影方向有记录（§四）：投影 100% 且在放置之前；每条子脊线
        # 都有投影角记录（proj_ang 已填，None 表示无方向可投影）
        n_proj = len(self.proj)
        n_nodes = len(self.topo.nodes)
        proj_seq = None
        for (s, ph, _m) in self.phase_log:
            if ph == '投影' and proj_seq is None:
                proj_seq = s
        proj_first = (proj_seq is not None and place_seq is not None
                      and proj_seq < place_seq)
        n_spine_child = sum(1 for s in self.spines if s['level'] > 0)
        n_slot_rec = len(self.slot_info)
        h7_pass = (n_proj == n_nodes and proj_first
                   and n_slot_rec == n_spine_child)
        hard.append({
            'id': 'H7', 'rule': '§四 先投影再分区域调', 'name': '投影方向有记录',
            'value': (f"投影节点 {n_proj}/{n_nodes}（{self.proj_meta.get('plane')}，"
                      f"方差占比 {self.proj_meta.get('var_ratio')}）；"
                      f"投影阶段 seq={proj_seq}，在放置之前；"
                      f"子脊线投影角记录 {n_slot_rec}/{n_spine_child} 条"),
            'threshold': '投影 100%，投影在放置之前，子脊线投影角记录完整',
            'pass': h7_pass,
        })

        # H8 确定性（§二.5）：独立子进程跑出的布局与本进程一致
        h8_pass = bool(det_pass) and det_md5_a is not None \
            and det_md5_a == det_md5_b
        hard.append({
            'id': 'H8', 'rule': '§二.5 确定性', 'name': '确定性',
            'value': f"本进程 MD5 {det_md5_a}，独立子进程 MD5 {det_md5_b}",
            'threshold': '两次 MD5 一致',
            'pass': h8_pass,
        })

        # H9 正交规则（§十三，脊线级）：子脊线首段 vs 上级脊线 90°±30°k
        # （脊线内部共线另由 H10 核查）
        o_checked, o_bad, o_details, o_dev30, _o_straight = self._ortho_check()
        o_passed = o_checked - o_bad
        o_rate = (o_passed / o_checked * 100.0) if o_checked else 0.0
        h9_pass = o_checked > 0 and o_bad == 0
        dev_txt = ('；偏离 90°（30°k 槽位）：' + '、'.join(
            f"{b}（{a}°）" for b, a in o_dev30)) if o_dev30 else ''
        fail_txt = ''
        if o_details:
            fail_txt = '；不通过：' + '、'.join(
                f"{b}（夹角 {a}°，偏离 {d}°）" for b, a, d in o_details[:5])
        hard.append({
            'id': 'H9', 'rule': '§十三 正交规则（脊线级）', 'name': '正交规则',
            'value': (f"核查 {o_checked} 条子脊线，通过 {o_passed} 条（{o_rate:.1f}%）"
                      f"{dev_txt}{fail_txt}"),
            'threshold': '核查脊线 100% 通过（夹角 90°±30°k，容差 0.5°）',
            'pass': h9_pass,
        })

        # H10 每关节主分支拉直（§十四）：每条脊线全部关节共线，逐条列出
        # （主干脊线 0 含 30 个关节——29 路径关节＋Body.113 中间关节 CLP01；
        # 其偏差与 H1a 同值，作参照）
        straight = self._spine_straightness()
        ring_ids = sorted(self._ring_spines)
        worst_dev = max((d for (_i, _a, _e, _n, d, _m) in straight
                         if d is not None), default=None)
        bad_spines = [(i, d) for (i, _a, _e, _n, d, m) in straight
                      if d is None or d > SPINE_STRAIGHT_TOL_MM or not m]
        h10_pass = not bad_spines
        detail = '；'.join(
            f"脊线{sid} {a or '—'}→{e or '—'}（{n}关节，"
            f"{'闭环画环，不计拉直' if sid in ring_ids else f'{d}mm'}"
            f"{'' if m else '，非单调折回'}）"
            for (sid, a, e, n, d, m) in straight)
        hard.append({
            'id': 'H10', 'rule': '§十四 每关节主分支拉直', 'name': '主分支拉直',
            'value': (f"{len(straight)} 条脊线全部关节共线，"
                      f"最大偏差 {worst_dev}mm"
                      + (f"；闭环脊线 {ring_ids} 按 §六整体画环（不计拉直）"
                         if ring_ids else "")
                      + f"；{detail}"),
            'threshold': (f"每条脊线关节到脊线垂距 ≤ {SPINE_STRAIGHT_TOL_MM}mm；"
                          f"关节沿脊线单调（不折回）"
                          + ("；闭环脊线按 §六整体画环，不适用本条"
                             if ring_ids else "")),
            'pass': h10_pass,
        })

        # ---- 软性项（警告，不阻塞） ----
        soft.append({
            'id': 'S1', 'rule': '§二.3 X 交叉（v2 允许，用户希望零交叉）',
            'name': 'X 交叉残留',
            'value': f"{n_x} 对",
            'note': 'v6p1 目标 0；残留交叉点位置已记入 layout.json 的 crossings，'
                    '查看器中以红色标记标出',
        })
        soft.append({
            'id': 'S2', 'rule': '§二.3 间距', 'name': '间距 < CLEARANCE',
            'value': f"{n_near} 对（CLEARANCE={self.clearance}mm）",
            'note': 'CLEARANCE=5mm 为暂定值（§十一.3 未决）',
        })
        n_bends = len(self.bends)
        soft.append({
            'id': 'S3', 'rule': '§九 干涉拐弯', 'name': '干涉拐弯',
            'value': f"{n_bends} 次",
            'note': '§十五起平行对只画一根，打折（平行预折）画法作废；脊线内部不拐弯',
        })
        rings, self_loops, parallels = self.topo.find_cycles(
            list(self.topo.branches.keys()))
        ring_test = _ring_test_status()
        if self.rings_drawn:
            s4_note = ('闭环脊线（首末关节相同）按 §六整体画环：按 3D 弦长排'
                       '闭合多边形、各边打折补长；非脊线环分支（如主干上的'
                       'theta 环弦）仍按受约束段处理，环分类单测通过')
        elif self.excluded_branches:
            # §二十二：真环被当过孔零件排除了，不要写成 IP 那句
            s4_note = ('真环 '
                       + '、'.join(e['key']
                                   for e in self.excluded_branches)
                       + ' 为过孔零件（§二十二），已排除不画；'
                         '其余无真实几何环')
        else:
            s4_note = 'IP 无真实几何环，真环画环逻辑未在真实数据上验证（合成单测通过）'
        soft.append({
            'id': 'S4', 'rule': '§六 有环先完整画环', 'name': '环分类',
            'value': (f"真环 {len(rings)} 个，自环 {len(self_loops)} 个，"
                      f"平行对 {len(parallels)} 个；已画真环 {len(self.rings_drawn)} 个；"
                      f"环分类单测 {ring_test}"),
            'note': s4_note,
        })
        s_total, s_matched, _s_mm = self._side_compliance()
        s_rate = (s_matched / s_total * 100.0) if s_total else 0.0
        n_place_flip = sum(1 for v in self.placed_flip.values() if v)
        n_side_flip = sum(1 for v in self.side_override.values() if v == 1)
        soft.append({
            'id': 'S5', 'rule': '§十三 哪侧按投影方向', 'name': '投影侧符合率',
            'value': (f"{s_matched}/{s_total} 条子脊线（{s_rate:.1f}%）与投影同侧；"
                      f"放置侧搜索翻转 {n_side_flip} 条，放置时翻转 {n_place_flip} 根，"
                      f"居中翻转 {len(self.center_flips)} 次，"
                      f"消交叉翻转 {len(self.untangle_flips)} 次"),
            'note': '投影方向是初始选择；分区域调整阶段为居中/消干涉可翻转整棵子树',
        })
        soft.append({
            'id': 'S6', 'rule': '§十三 同点 3 根以上', 'name': '槽位分布',
            'value': (f"{len(self.slot_groups)} 个关节组；"
                      f"30° 偏转（第三根起）{len(o_dev30)} 条"),
            'note': '前两根垂直分两侧，第三根起偏 30° 展开（30° 间隔）',
        })
        soft.append({
            'id': 'S7', 'rule': '§二 图纸', 'name': '图纸尺寸',
            'value': f"{ci.get('width')} × {ci.get('height')}mm",
            'note': '包围盒尺寸；不分页',
        })
        second_txt = '无（连接器对不足）'
        if self.trunk_path_second:
            sl, s1, s2 = self.trunk_path_second
            second_txt = f"{sl:.1f}mm（{s1}→{s2}）"
        a, b = self.trunk_path_endpoints
        soft.append({
            'id': 'S8', 'rule': '§五 主干定义', 'name': '主干路径',
            'value': (f"{a}→{b}，总长 {self.trunk_path_length:.1f}mm，"
                      f"{len(self.trunk_path)} 根分支，"
                      f"{len(self.trunk_path_joints)} 个关节，"
                      f"直线跨度 {self.trunk_path_span:.1f}mm；次长 {second_txt}"),
            'note': ('主干 = 连接器到连接器之间最长路径（§五，2026-11-17 20:34 '
                     '用户纠正）；由程序枚举全部连接器两两 Dijkstra 算出，未写死；'
                     '直线跨度小于总长是路径内自环段（Body.150 SEG32 5.1mm）所致'),
        })
        soft.append({
            'id': 'S9', 'rule': '§十四 脊线分解', 'name': '脊线分解',
            'value': (f"脊线 {len(self.spines)} 条（主干 1 + 侧枝 "
                      f"{len(self.spines) - len(self._comps)}），层级 0–"
                      f"{max((s['level'] for s in self.spines), default=0)}；"
                      f"尾段 {len(self.tails)} 段（受约束 "
                      f"{sum(1 for t in self.tails if t['kind'] == 'constrained')}、"
                      f"自由 {sum(1 for t in self.tails if t['kind'] == 'free')}"
                      + (f"、detached "
                         f"{sum(1 for t in self.tails if t['kind'] == 'detached')}"
                         if any(t['kind'] == 'detached' for t in self.tails)
                         else "")
                      + "）；"
                      f"未进脊线 {len(self.unassigned_branches)} 根"
                      f"{[k for k, _ in self.unassigned_branches]}；"
                      f"§十五平行未单画 {len(self.hidden_parallel)} 对"),
            'note': '分解在绘制之前全部完成（先算后画）；完整方案见 plan.json，逐层明细见 branch_layers.md',
        })
        if self.hidden_parallel:
            pair_txt = '；'.join(
                f"{r['pair']}：留 {r['kept_branch']} {r['kept_seg']} "
                f"{r['kept_length_mm']:.1f}mm（脊线 {r['kept_spine']}），"
                f"隐藏 {r['hidden_branch']} {r['hidden_seg']} "
                f"{r['hidden_length_mm']:.1f}mm（{r['hidden_kind']}）"
                for r in self.hidden_parallel)
            s10_value = f"{len(self.hidden_parallel)} 对平行对各只画一根：{pair_txt}"
        else:
            s10_value = '无平行对'
        soft.append({
            'id': 'S10', 'rule': '§十五 平行对只画一根', 'name': '平行对单画',
            'value': s10_value,
            'note': '留走主干/脊线那根（按脊线归属，不按长度）；隐藏段不画线但数据不丢，见 plan.json 的 hidden_parallel、layout.json 中保留分支的 parallel_hidden 与 Excel 备注',
        })

        all_hard_pass = all(c['pass'] for c in hard)
        return {'hard': hard, 'soft': soft,
                'all_hard_pass': all_hard_pass}, all_hard_pass


# ---------------------------------------------------------------- 输出

def layout_data_v6p1(layout, include_checklist=None):
    """组装 v6p1 layout.json（在 v3-fix 基础格式上新增 crossings / slots /
    flips / joint_inventory / tree / spines / layers / trunk_path 与
    扩展 stats）。不复用 layout_data_v4：v4 的 _ortho_check/_side_compliance
    签名与 v6p1 脊线级版本不同。"""
    data = layout_data(layout, include_checklist=include_checklist)
    data['meta']['source'] = 'unfold_2d_v6p1.py'
    data['meta']['version'] = 'v6p1'
    # §二十二：已排除分支（过孔零件等非路径件，不画；合并与查看器认这项）
    data['meta']['excluded_branches'] = [
        dict(e) for e in getattr(layout, 'excluded_branches', [])]
    # §十五：平行未单画记录（顶层）+ 保留分支上的标注（供查看器弹窗
    # 展示两根管子的数据）+ 部分隐藏分支的标注（解释 len_2d < len_3d）
    data['hidden_parallel'] = [dict(r) for r in layout.hidden_parallel]
    # 环弦符号（顶层）：段长 < 端点距的受约束段，画小三角符号于一端；
    # merge 按自环通道改画小环符号（见 merge_joints_v6p2.py）。
    data['symbol_segs'] = [dict(r) for r in layout.symbol_segs]
    by_kept = defaultdict(list)
    by_hidden_branch = defaultdict(list)
    for r in layout.hidden_parallel:
        by_kept[r['kept_branch']].append(r)
        by_hidden_branch[r['hidden_branch']].append(r)
    for b in data['branches']:
        if b['key'] in by_kept:
            b['parallel_hidden'] = [dict(r) for r in by_kept[b['key']]]
        if b['key'] in by_hidden_branch:
            b['hidden_segs'] = [{
                'seg': r['hidden_seg'],
                'length_mm': r['hidden_length_mm'],
                'dia_mm': r['hidden_dia_mm'],
                'kept_seg': r['kept_seg'],
                'kept_branch': r['kept_branch'],
            } for r in by_hidden_branch[b['key']]]
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
    # X 交叉点（用于查看器干涉标记；与 count_interference_detailed 同口径）
    crossings = []
    pp = layout.placed_pieces
    for i in range(len(pp)):
        for j in range(i + 1, len(pp)):
            if pp[i][2] == pp[j][2] and pp[i][3] == pp[j][3]:
                continue
            if not seg_proper_intersect(pp[i][0], pp[i][1], pp[j][0], pp[j][1]):
                continue
            pt = _seg_intersection_point(pp[i][0], pp[i][1], pp[j][0], pp[j][1])
            if pt is not None:
                crossings.append({'x': round(pt[0], 2), 'y': round(pt[1], 2),
                                  'branches': sorted([pp[i][2], pp[j][2]])})
    data['crossings'] = crossings
    data['slots'] = {
        'groups': [{'parent': p, 'joint': j, 'children': c,
                    'offsets': {k: v for k, v in sorted(o.items())}}
                   for (p, j, c, o) in layout.slot_groups],
        'info': {k: v for k, v in sorted(layout.slot_info.items())},
    }
    data['flips'] = {
        'center': layout.center_flips,
        'untangle': layout.untangle_flips,
        'placement': sorted(k for k, v in layout.placed_flip.items() if v),
        'side_search': sorted(k for k, v in layout.side_override.items()
                              if v == 1),
    }
    data['joint_inventory'] = [
        {'parent': p, 'joint': j, 'children': c}
        for (p, j, c) in layout.joint_inventory]
    data['tree'] = {k: {'parent': v['parent'], 'anchor': v['anchor'],
                        'depth': v['depth']}
                    for k, v in sorted(layout.tree.items())}
    data['spines'] = [
        {'id': s['id'], 'level': s['level'], 'parent': s['parent'],
         'anchor': s['anchor'], 'branches': s['branches'],
         'joints': s['joints'], 'length': round(s['length'], 1),
         'end': s['end'], 'is_main': s['is_main'],
         'slot_offset': s['slot_offset'],
         'direction': (round(s['direction'], 1)
                       if s['direction'] is not None else None)}
        for s in layout.spines]
    data['layers'] = [
        {'spine': r['spine'], 'joint': r['joint'],
         'candidates': [{'first_branch': c['first_branch'],
                         'length': round(c['length'], 1),
                         'connector': c['connector'],
                         'branches': c['branches'],
                         'spine_id': c['spine_id'],
                         'is_main': (i == r['main_idx'])}
                        for i, c in enumerate(r['candidates'])]}
        for r in layout.layers]
    data['tails'] = [
        {'seg': t['seg'], 'branch': t['branch'], 'spine': t['spine'],
         'joint': t['joint'], 'far': t['far'],
         'length': round(t['length'], 1), 'kind': t['kind'],
         'hidden': bool(t.get('hidden')), 'kept_seg': t.get('kept_seg')}
        for t in layout.tails]
    data['unassigned_branches'] = [
        {'branch': k, 'reason': r} for k, r in layout.unassigned_branches]
    # stats 扩展（脊线级口径）
    o_checked, o_bad, _o_d, o_dev30, o_straight = layout._ortho_check()
    s_total, s_matched, _s_mm = layout._side_compliance()
    data['stats']['ortho_checked'] = o_checked
    data['stats']['ortho_passed'] = o_checked - o_bad
    data['stats']['ortho_rate_pct'] = round(
        (o_checked - o_bad) / o_checked * 100.0, 1) if o_checked else 0.0
    data['stats']['ortho_deviated_30'] = len(o_dev30)
    data['stats']['spine_straight_bad'] = len(o_straight)
    data['stats']['side_match'] = s_matched
    data['stats']['side_total'] = s_total
    data['stats']['flips_center'] = len(layout.center_flips)
    data['stats']['flips_untangle'] = len(layout.untangle_flips)
    data['stats']['flips_placement'] = sum(
        1 for v in layout.placed_flip.values() if v)
    data['stats']['crossings'] = len(crossings)
    data['stats']['trunk_path_length_mm'] = round(layout.trunk_path_length, 1)
    data['stats']['trunk_path_branches'] = len(layout.trunk_path)
    data['stats']['trunk_path_endpoints'] = f"{a}→{b}"
    data['stats']['spines'] = len(layout.spines)
    data['stats']['layers'] = len(layout.layers)
    return data


def canonical_json_v6p1(layout):
    """确定性哈希用的规范序列化（不含清单、无时间戳、键排序）。"""
    data = layout_data_v6p1(layout, include_checklist=None)
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def write_layout_json_v6p1(layout, checklist, out_path):
    data = layout_data_v6p1(layout, include_checklist=checklist)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return out_path


def write_checklist_md_v6p1(checklist, out_path, topo_path):
    """检查清单 Markdown（逐条打勾/打叉，附实测数值）。"""
    lines = []
    lines.append('# v6p1 规则检查清单')
    lines.append('')
    lines.append(f'输入：`{topo_path}`')
    lines.append('程序：`unfold_2d_v6p1.py`（§十四 分支逐层最长路径 + §十五 平行对只画一根）')
    lines.append('')
    lines.append('## 硬规则（任一失败则退出码非 0，不生成 DXF/Excel/查看器）')
    lines.append('')
    for c in checklist['hard']:
        mark = '✅ 通过' if c['pass'] else '❌ 失败'
        if c.get('exempt'):
            mark = '✅ 通过（豁免）'
        lines.append(f"- **{c['id']} {c['name']}**（{c['rule']}）：{mark}")
        lines.append(f"  - 实测：{c['value']}")
        lines.append(f"  - 阈值：{c['threshold']}")
        if c.get('exempt_note'):
            lines.append(f"  - 豁免：{c['exempt_note']}")
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


def write_branch_layers_md(layout, out_path):
    """逐层清单（H10 附带输出）：逐关节列出侧枝数、各侧枝最长路径长度
    与终点连接器，以及脊线/尾段/未分配分支总览。"""
    lines = []
    lines.append('# v6p1 分支逐层清单（§十四 + §十五）')
    lines.append('')
    lines.append('主干 = 最长连接器—连接器路径；每层从关节出发，取到该点'
                 '所有分支上所有连接器的最长简单路径拉直画出。')
    lines.append('')
    a, b = layout.trunk_path_endpoints
    lines.append(f"主干路径：{a}→{b}，{layout.trunk_path_length:.1f}mm，"
                 f"{len(layout.trunk_path)} 根分支，"
                 f"{len(layout.trunk_path_joints)} 个关节。")
    lines.append('')
    lines.append(f"脊线 {len(layout.spines)} 条，层记录 {len(layout.layers)} 个关节，"
                 f"尾段 {len(layout.tails)} 段，"
                 f"未进脊线 {len(layout.unassigned_branches)} 根。")
    lines.append('')
    lines.append('## 逐关节侧枝（按脊线 id、关节排序）')
    lines.append('')
    for r in sorted(layout.layers,
                    key=lambda r: (str(r['spine']), r['joint'])):
        cands = r['candidates']
        lines.append(f"### 上级脊线 {r['spine']} · 关节 {r['joint']} · "
                     f"{len(cands)} 个侧枝")
        lines.append('')
        lines.append('| 侧枝 | 最长路径 | 终点连接器 | 根数 | 脊线 | 是否主分支 |')
        lines.append('|---|---|---|---|---|---|')
        for i, c in enumerate(cands):
            main = '主分支' if i == r['main_idx'] else ''
            lines.append(f"| {c['first_branch']} | {c['length']:.1f}mm | "
                         f"{c['connector'] or '（无连接器）'} | "
                         f"{len(c['branches'])} | {c['spine_id']} | {main} |")
        lines.append('')
    lines.append('## 脊线总览（按 id）')
    lines.append('')
    lines.append('| 脊线 | 层级 | 上级 | 锚点 | 长度 | 终点 | 根数 | 主/侧 |')
    lines.append('|---|---|---|---|---|---|---|---|')
    for s in layout.spines:
        lines.append(f"| {s['id']} | {s['level']} | "
                     f"{s['parent'] if s['parent'] is not None else '—'} | "
                     f"{s['anchor'] or '—'} | {s['length']:.1f}mm | "
                     f"{s['end'] or '—'} | {len(s['branches'])} | "
                     f"{'主' if s['is_main'] else '侧'} |")
    lines.append('')
    lines.append('## 尾段')
    lines.append('')
    for t in layout.tails:
        mark = (f"，平行未单画（§十五，只画 {t['kept_seg']}）"
                if t.get('hidden') else '')
        lines.append(f"- {t['seg']}（{t['branch']}，脊线 {t['spine']}）："
                     f"{t['joint']}→{t['far']}，{t['length']:.1f}mm，{t['kind']}{mark}")
    if not layout.tails:
        lines.append('（无）')
    lines.append('')
    lines.append('## 未进脊线的分支')
    lines.append('')
    for k, reason in layout.unassigned_branches:
        lines.append(f"- {k}：{reason}")
    if not layout.unassigned_branches:
        lines.append('（无）')
    lines.append('')
    lines.append('## 平行未单画（§十五，用户 2026-11-17 22:21 决定）')
    lines.append('')
    lines.append('平行对只画一根，留走主干/脊线那根；隐藏段不画线，数据不丢。')
    lines.append('')
    for r in layout.hidden_parallel:
        lines.append(f"- {r['pair']}：留 {r['kept_branch']} {r['kept_seg']} "
                     f"{r['kept_length_mm']:.1f}mm（Φ{r['kept_dia_mm']:.1f}，"
                     f"脊线 {r['kept_spine']}），隐藏 {r['hidden_branch']} "
                     f"{r['hidden_seg']} {r['hidden_length_mm']:.1f}mm"
                     f"（Φ{r['hidden_dia_mm']:.1f}，{r['hidden_kind']}）")
    if not layout.hidden_parallel:
        lines.append('（无）')
    lines.append('')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return out_path


def verify_dxf_readback(layout, dxf_path):
    """交付前验证：DXF 回读逐块核对——用 ezdxf 读回 DXF，对每个 TUBE 块取其
    LWPOLYLINE，经 INSERT（insert + rotation）变换回世界坐标，与
    layout 的分支点列逐点比对。返回 {'checked', 'max_err', 'pass',
    'detail'}。v3/v4 的块位移 bug（局部坐标未减 origin）在此会被抓出。
    不占清单编号；失败时 main 退出码 1、不交付 DXF。
    """
    import ezdxf
    fwd = {}
    for k in layout.placed:
        name = sanitize_block_name('TUBE_' + k)
        if name in fwd:
            return {'checked': 0, 'max_err': None, 'pass': False,
                    'detail': f"块名冲突：{fwd[name]} 与 {k} 消毒后同名 {name}"}
        fwd[name] = k
    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as e:
        return {'checked': 0, 'max_err': None, 'pass': False,
                'detail': f"DXF 读回失败：{e}"}
    msp = doc.modelspace()
    checked = 0
    max_err = 0.0
    worst = None
    seen = set()
    for ins in msp.query('INSERT'):
        name = ins.dxf.name
        if name not in fwd:
            continue
        key = fwd[name]
        seen.add(key)
        blk = doc.blocks.get(name)
        poly = None
        for e in blk:
            if e.dxftype() == 'LWPOLYLINE':
                poly = e
                break
        if poly is None:
            return {'checked': checked, 'max_err': None, 'pass': False,
                    'detail': f"{key}（块 {name}）内无多段线"}
        ins_pt = ins.dxf.insert
        rot = math.radians(ins.dxf.rotation)
        c, s = math.cos(rot), math.sin(rot)
        expect = layout.placed[key]['points']
        got = []
        for (lx, ly) in poly.get_points('xy'):
            got.append((ins_pt.x + lx * c - ly * s,
                        ins_pt.y + lx * s + ly * c))
        if len(got) != len(expect):
            return {'checked': checked, 'max_err': None, 'pass': False,
                    'detail': f"{key} 点数不一致（DXF {len(got)} vs 布局 "
                              f"{len(expect)}）"}
        for (gx, gy), (ex, ey) in zip(got, expect):
            err = math.hypot(gx - ex, gy - ey)
            if err > max_err:
                max_err = err
                worst = key
        checked += 1
    missing = sorted(set(layout.placed) - seen)
    if missing:
        return {'checked': checked, 'max_err': max_err, 'pass': False,
                'detail': f"DXF 缺 {len(missing)} 个 TUBE 块：{missing[:5]}"}
    ok = max_err <= DXF_READBACK_TOL_MM
    return {'checked': checked, 'max_err': round(max_err, 6), 'pass': ok,
            'detail': (f"逐块回读 {checked}/{len(layout.placed)} 个 TUBE 块，"
                       f"全部点列最大误差 {max_err:.4f}mm"
                       + (f"（{worst}）" if worst else ""))}


def annotate_excel_hidden(layout, xls_path):
    """§十五：把平行未单画记入 Excel（v3 write_excel 只写已画分支）。
    - '2D管子'：整根隐藏分支追加一行（2D 长度/误差留空，备注标明）；
      部分隐藏分支把误差列修正为应画口径并加备注。
    - '2D线段'：隐藏段追加一行（坐标留空，备注标明）。
    - '验证'：追加平行未单画清单。"""
    import openpyxl
    if not layout.hidden_parallel:
        return xls_path
    wb = openpyxl.load_workbook(xls_path)
    # --- 2D管子（11 列，追加第 12 列“备注”） ---
    ws = wb['2D管子']
    ws.cell(row=1, column=12, value='备注')
    by_key = {}
    for row in ws.iter_rows(min_row=2, max_col=1):
        by_key[row[0].value] = row[0].row
    for key, v in sorted(layout.hidden_seg_len_by_branch.items()):
        if key in by_key and key not in layout.hidden_whole_branches:
            r = by_key[key]
            b = layout.topo.branches[key]
            expected = b['length'] - v
            l2 = ws.cell(row=r, column=7).value  # 2D长度
            ws.cell(row=r, column=8,
                    value=round(l2 - expected, 2))  # 误差改应画口径
            hidden = [rec for rec in layout.hidden_parallel
                      if rec['hidden_branch'] == key]
            ws.cell(row=r, column=12, value='；'.join(
                f"{rec['hidden_seg']} {rec['hidden_length_mm']:.1f}mm 平行未单画"
                f"（§十五，只画 {rec['kept_branch']} {rec['kept_seg']}）；"
                f"应画长度 {expected:.1f}mm" for rec in hidden))
    for key in sorted(layout.hidden_whole_branches):
        b = layout.topo.branches[key]
        rec = next(r for r in layout.hidden_parallel
                   if r['hidden_branch'] == key)
        ws.append([key, None, None, None, None,
                   round(b['length'], 1), None, None,
                   round(b['dia'], 1), len(b['pieces']), 0,
                   f"平行未单画（§十五）：与 {rec['kept_branch']} "
                   f"{rec['kept_seg']} 平行，图上只画 {rec['kept_branch']}"])
    # --- 2D线段（10 列，追加第 11 列“备注”） ---
    ws2 = wb['2D线段']
    ws2.cell(row=1, column=11, value='备注')
    for rec in layout.hidden_parallel:
        s = layout.topo.segs[rec['hidden_seg']]
        ws2.append([rec['hidden_seg'], rec['hidden_branch'], s['na'], s['nb'],
                    None, None, None, None,
                    round(s['length'], 1), round(s.get('dia') or 0.0, 1),
                    f"平行未单画（§十五），图上只画 {rec['kept_branch']} "
                    f"{rec['kept_seg']}"])
    # --- 验证 ---
    ws4 = wb['验证']
    ws4.append([])
    ws4.append(['平行未单画（§十五）', '隐藏分支/段', '长度', '直径', '只画'])
    for rec in layout.hidden_parallel:
        ws4.append([rec['pair'],
                    f"{rec['hidden_branch']} {rec['hidden_seg']}",
                    rec['hidden_length_mm'], rec['hidden_dia_mm'],
                    f"{rec['kept_branch']} {rec['kept_seg']}"])
    wb.save(xls_path)
    return xls_path


def fix_dxf_labels(layout, dxf_path):
    """§十五：部分隐藏分支的 DXF 块标签改应画长度——v3 write_dxf 的标签
    写的是分支 3D 总长（如 Body.46 L=60.0），而块内线只有应画部分
    （31.9mm），标签与实测不一致。只改 TEXT 内容，不动几何（回读验证
    只核几何，标签修正不影响验证结论）；整根隐藏的分支本来就没有块。
    """
    import ezdxf
    partial = {k: v for k, v in layout.hidden_seg_len_by_branch.items()
               if k not in layout.hidden_whole_branches}
    if not partial:
        return dxf_path
    doc = ezdxf.readfile(dxf_path)
    for key, v in sorted(partial.items()):
        b = layout.topo.branches[key]
        expected = b['length'] - v
        blk_name = sanitize_block_name('TUBE_' + key)
        blk = doc.blocks.get(blk_name)
        if blk is None:
            continue
        hidden = [rec for rec in layout.hidden_parallel
                  if rec['hidden_branch'] == key]
        note = '、'.join(f"{rec['hidden_seg']} {rec['hidden_length_mm']:.1f}"
                         for rec in hidden)
        for e in blk:
            if e.dxftype() == 'TEXT':
                e.dxf.text = (f"{key} Φ{b['dia']:.1f} L={expected:.1f}"
                              f"（+{note} 平行未单画）")
    doc.saveas(dxf_path)
    return dxf_path


# ---------------------------------------------------------------- 主入口

def build_layout(topo, clearance, verbose=True, plan_path=None):
    layout = LayoutV6p1(topo, clearance=clearance, verbose=verbose)
    layout.plan_path = plan_path
    # §二十二：排除记录从 topo 带到布局（进 layout.json meta，供合并与查看器认）
    layout.excluded_branches = [
        {'key': k, 'reason': EXCLUDED_BRANCHES.get(k, '')}
        for k in getattr(topo, 'dropped_branches', [])]
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
    ap = argparse.ArgumentParser(description='3D拓扑 → 2D展开图（v6p1，§十四逐层最长路径+§十五平行对只画一根）')
    ap.add_argument('topo_json')
    ap.add_argument('-o', '--out', default='.')
    ap.add_argument('--clearance', type=float, default=CLEARANCE_DEFAULT)
    ap.add_argument('--hash-only', action='store_true',
                    help='仅输出布局 MD5（供确定性检查的子进程用）')
    args = ap.parse_args()

    topo = Topo(args.topo_json)
    n_b0, n_n0, n_s0 = (len(topo.branches), len(topo.nodes), len(topo.segs))
    # §二十二：过孔零件等非路径件先删掉再展开（拓扑文件本身不动）
    dropped = topo.drop_branches(set(EXCLUDED_BRANCHES))

    if args.hash_only:
        # 哈希模式：只打印 MD5，不打印其他任何东西
        layout = build_layout(topo, args.clearance, verbose=False)
        h = hashlib.md5(canonical_json_v6p1(layout).encode('utf-8')).hexdigest()
        print(h)
        return 0

    print(f"输入：分支 {n_b0} / 节点 {n_n0} / "
          f"线段 {n_s0}")
    if dropped:
        print(f"已排除过孔零件 {len(dropped)} 根（§二十二，不画）："
              + "、".join(
                  f"{k}（{EXCLUDED_BRANCHES.get(k, '')}）" for k in dropped)
              + f"；展开用分支 {len(topo.branches)} / 节点 {len(topo.nodes)} "
              f"/ 线段 {len(topo.segs)}")
    comps = topo.components()
    print(f"连通分量：{len(comps)} 个，规模 {[len(c) for c in comps]}")
    for i, c in enumerate(comps):
        rings, sl, pp = topo.find_cycles(c)
        print(f"  分量{i + 1}：真环 {len(rings)} 个，自环线段 {len(sl)} 条，"
              f"平行对 {len(pp)} 对")
    print(f"环分类单测：{_ring_test_status()}")

    os.makedirs(args.out, exist_ok=True)
    plan_path = os.path.join(args.out, 'plan.json')
    layout = build_layout(topo, args.clearance, verbose=True,
                          plan_path=plan_path)
    a, b = layout.trunk_path_endpoints
    print(f"[主干路径] {a}→{b}，总长 {layout.trunk_path_length:.1f}mm，"
          f"{len(layout.trunk_path)} 根分支，{len(layout.trunk_path_joints)} 个关节")

    # 确定性：本进程哈希 vs 独立子进程哈希
    hash1 = hashlib.md5(canonical_json_v6p1(layout).encode('utf-8')).hexdigest()
    print('[确定性] 本进程 MD5：%s，正在跑独立子进程…' % hash1)
    hash2 = _subprocess_hash(args.topo_json, args.clearance)
    print('[确定性] 子进程 MD5：%s' % hash2)
    det_pass = (hash2 is not None and hash1 == hash2)

    checklist, hard_pass = layout.run_checklist(
        det_md5_a=hash1, det_md5_b=hash2, det_pass=det_pass)

    lj = os.path.join(args.out, 'layout.json')
    ck = os.path.join(args.out, 'checklist_v6p1.md')
    bl = os.path.join(args.out, 'branch_layers.md')
    write_layout_json_v6p1(layout, checklist, lj)
    write_checklist_md_v6p1(checklist, ck, args.topo_json)
    write_branch_layers_md(layout, bl)
    print(f"已写 {plan_path}（放置开始前已写盘）")
    print(f"已写 {lj}")
    print(f"已写 {ck}")
    print(f"已写 {bl}")

    if not hard_pass:
        failed = [c['id'] for c in checklist['hard'] if not c['pass']]
        print(f"硬规则失败：{', '.join(failed)}，不生成 DXF/Excel，退出码 1")
        return 1

    # 交付前验证：DXF 先写临时文件做逐块回读核对（v3/v4 块位移 bug 不许重现），
    # 通过才正式交付；失败则删临时文件、退出码 1（不占清单编号）
    tmp_dxf = os.path.join(args.out, '.unfold_v6p1.tmp.dxf')
    write_dxf(layout, tmp_dxf)
    dxf_check = verify_dxf_readback(layout, tmp_dxf)
    print(f"[DXF回读] {dxf_check['detail']}")
    if not dxf_check['pass']:
        try:
            os.remove(tmp_dxf)
        except OSError:
            pass
        print("DXF 回读验证失败，不交付 DXF，退出码 1")
        return 1

    dxf = os.path.join(args.out, 'unfold_v6p1.dxf')
    xls = os.path.join(args.out, 'unfold_v6p1.xlsx')
    os.replace(tmp_dxf, dxf)
    write_excel(layout, xls)
    annotate_excel_hidden(layout, xls)   # §十五：隐藏段记入 Excel
    fix_dxf_labels(layout, dxf)          # §十五：部分隐藏分支的块标签改应画长度
    print(f"已写 {dxf}")
    print(f"已写 {xls}")
    print('硬规则全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
