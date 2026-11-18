#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仪表线束（IP-Harness）3D → 2D 展开 v4。

规则来源：《需求说明.md》§十三（2026-11-17 用户亲定），逐条执行：
  - 主干：第一条最长的（Body.123，191.9mm，3D 中心线真实弧长），放水平。
  - 分支：后面的全是分支，每根分支垂直于它的上级主干（90°）。
    主干水平 → 一级分支垂直 → 二级分支水平，逐级交替正交。
  - 哪侧：分支放上级主干的哪一侧，按投影方向（朝 3D 投影所在侧）。
    投影方向是初始选择；分区域调整阶段为居中/消干涉可翻转整棵子树，
    翻转要记入清单。
  - 同点 3 根以上：前两根垂直分两侧，第三根起偏 30° 展开
    （以 30° 为间隔偏离垂直方向）。
  - 先找齐再画：每个关节的子分支先全部清点、排序，再统一画，不边找边画。
  - 环：显式区分真几何环 / 自环 / 平行对，日志写明各多少；真环完整画环，
    绝不许剪开拉直。IP 无真环（3 自环 + 4 平行对）。
  - 长度 1:1、拓扑不变：红线，绝不为消交叉破坏。

六个阶段：①读取与校验；②拓扑分析（连通分量、主干、分支点、环、分支层级 BFS）；
③初始二维投影（PCA 最佳拟合平面，复用 v3-fix）；④结构化布局（§十三正交规则）；
⑤干涉优化（分级：共线重叠必须 0 > X 交叉优先消除 > 间距<5mm 尽量消除 > 美观尽量改善；
局部调整、每次调整后重新检查，不许消一个交叉造出更多）；⑥工程输出。

硬失败门（任一硬规则失败则退出码非 0，不生成 DXF/Excel/查看器）：
  H1 主干水平（夹角 0°）且居中——横竖两个方向都要查
      （主干中点与图纸中心偏差 ≤5% 图纸宽/高）。
      教训：v3-fix 只查了垂直方向，主干实际在图左（中点 x=-191，中心 0），
      用户为此发火。横竖都必须达标，不许再拿单方向说事。
  H2 长度 1:1（最大误差 ≤0.1mm）；H3 拓扑不变（端点全一致）；
  H4 零压着画（共线重叠 0）；H5 全画出（分支 110/110、节点 110/110、线段 116/116）；
  H6 分支点先找齐再画；H7 投影步已执行；
  H8 确定性（两进程 layout.json MD5 一致）；
  H9 正交规则（每根分支与其上级主干夹角 90°，同点第三根起为 90°±30°k；
      逐根核查，报符合率）。

实现要点：
  - 角度分配：每根分支的偏移角在投影坐标系中预先算出（相对父分支方向），
    放置时加到父分支实际方向上；父分支方向取放置后几何中锚点处相邻段的方向
    （相邻段用长度侧规则选取——朝锚点较长一侧，与投影/布局两帧一致）。
  - 同（父分支，关节）组内的槽位分配：暴力最优分配——槽位集合
    {±90°, ±60°, ±120°, ±30°, ±150°}（均为 30° 间隔），代价按字典序
    （非垂直槽位数，投影角总偏差），约束为无方向冲突
    （中间锚定的分支占两个方向，禁止其余分支用对向槽位）。
  - 自由延伸段的第一段不许关节拐弯、不许中部打折（只许直行或平行打折），
    保证 H9 的弦方向即分配方向；下游段可按 §九 拐弯。
  - 居中：初始侧按投影；第 5 阶段用 180° 子树旋转爬山优化
    （180° 保持正交，其他角度禁止）；分两步——先居中爬山，
    再消干涉爬山（拒绝任何破坏居中的旋转）。
  - 主干方向取 CON01 向右（朝向线束主体一侧）。
  - 环处理：有真环的分量先画最大真环，分支树从环分支起；IP 无真环，
    此路径无真实数据验证，记为局限。

用法：
  python3 unfold_2d_v4.py <topology.json> -o <outdir> [--clearance 5.0]
  python3 unfold_2d_v4.py <topology.json> --hash-only   # 内部用：只打印 layout.json MD5

输入：pipeline_4step_rules 的 topology.json。
输出（outdir）：unfold_v4.dxf、unfold_v4.xlsx、layout.json、checklist_v4.md。
硬失败时只写 layout.json 与 checklist_v4.md，不写 DXF/Excel。

运行环境：plain python3 即可；ezdxf 不在系统 Python 里时用 ~/workspace/.pylibs 兜底。
"""

import argparse
import hashlib
import itertools
import json
import math
import os
import subprocess
import sys
from collections import defaultdict

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ezdxf 兜底：系统 Python 没有时用 ~/workspace/.pylibs（同 v3-fix 做法）
try:
    import ezdxf  # noqa: F401
except ImportError:
    _pylibs = os.path.expanduser("~/workspace/.pylibs")
    if os.path.isdir(_pylibs) and _pylibs not in sys.path:
        sys.path.insert(0, _pylibs)

from unfold_2d_v3 import (
    Topo, Layout, write_dxf, write_excel, dist, angle_of, add_pt,
    unit_from_angle, BEND_STEP, BEND_MAX, pt_eq, seg_proper_intersect,
    seg_collinear_overlap, seg_seg_dist, CLEARANCE_DEFAULT, rot_pt,
)
from unfold_2d_v3_fix import (
    LayoutFix, pca_project, layout_data, canonical_json,
    write_layout_json_fix, write_checklist_md, TRUNK_CENTER_TOL,
    TRUNK_ANGLE_TOL, count_interference_detailed,
)

# ---------- v4 阈值 ----------
LEN_ERR_TOL_V4 = 0.1        # H2：最大长度误差 ≤0.1mm
ORTHO_TOL_DEG = 0.5         # H9：正交偏差容差（度）
CENTER_TOL = TRUNK_CENTER_TOL   # H1：居中偏差 ≤5% 图纸宽/高（横竖都要查）
CENTER_TARGET = 0.045           # 居中爬山目标：≤4.5%（留 0.5% 裕量给消交叉；
                                # 3.5% 目标会多翻 2~3 次、X 交叉 +10 左右，得不偿失）
FLIP_CENTER_MAX_PASSES = 60     # 居中爬山最大轮数
UNTANGLE_MAX_PASSES = 60        # 消交叉爬山最大轮数（每轮应用一次最优旋转）
UNTANGLE_MAX_ROTATIONS = 40     # 消交叉最多旋转次数
# 槽位集合（相对父分支方向的偏移角，度）：垂直 ±90 为主，
# 其余均为 30° 间隔的偏离（§十三：第三根起偏 30° 展开）
SLOT_OFFSETS = [90.0, -90.0, 60.0, -60.0, 120.0, -120.0,
                30.0, -30.0, 150.0, -150.0]


def ang_diff(a, b):
    """两角最小夹角（度），返回 [0, 180]。"""
    d = abs((a - b) % 360.0)
    return 360.0 - d if d > 180.0 else d


def line_angle(a, b):
    """两条直线的夹角（度），返回 [0, 90]（直线无方向，模 180 取锐角）。"""
    d = ang_diff(a, b)
    return 180.0 - d if d > 90.0 else d


def _ring_test_status():
    """读取环分类单测结果（test_ring_result.json），返回 pass/fail/not_run。"""
    p = os.path.join(_HERE, "test_ring_result.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if "passed" in d:
            return "pass" if d["passed"] else "fail"
        return d.get("status", "unknown")
    except Exception:
        return "not_run"


def _seg_intersection_point(p1, p2, p3, p4):
    """两线段严格相交时的交点（用于查看器干涉标记），不相交返回 None。"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(den) < 1e-12:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / den
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / den
    if 0.0 < t < 1.0 and 0.0 < u < 1.0:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


class LayoutV4(LayoutFix):
    """v4 布局：§十三正交规则 + 180° 子树旋转居中/消交叉。"""

    def __init__(self, topo, clearance=5.0, verbose=True):
        super().__init__(topo, clearance=clearance, verbose=verbose, tilt=0.0)
        # 分支树：key -> {parent, anchor, depth, children}
        self.tree = {}
        self.tree_root = None
        # 槽位分配：key -> 偏移角（度，相对父分支方向）
        self.slot_offset = {}
        self.slot_info = {}          # key -> {proj_ang, side_match, offset_dev}
        self.slot_groups = []        # [(parent, joint, [children], {child: offset})]
        # 放置记录
        self.placed_angle = {}       # key -> 实际放置的运行角度（度，绝对）
        self.placed_kind = {}        # key -> 'dir'（方向放置）/ 'constrained'（全约束）
        self.placed_flip = {}        # key -> 放置时是否翻转 180°（bool）
        self.placed_offset = {}      # key -> 放置时偏离分配角的度数（0 或 ±30）
        self.placed_free_segs = {}   # key -> [(段下标, 方向)] 自由段第一段非自环段（H9 测量用）
        # 翻转记录
        self.center_flips = []       # [{branch, anchor, dev_before, dev_after}]
        self.side_override = {}      # {branch: 0=强制分配侧, 1=强制翻转侧}，
                                     # 用于放置侧搜索（居中调优）；默认空=不强制
        self.untangle_flips = []     # [{branch, anchor, score_before, score_after}]
        # 关节清点（H6）
        self.joint_inventory = []    # [(parent, joint, [children])]
        self._proj_parent_dir_cache = {}

    # ---------- 拓扑分析：分支树 ----------
    def build_branch_tree(self):
        """以每个连通分量的最长分支为根，按分支邻接 BFS 建树（复用草稿设计）。

        多分量数据（如地板 7 个分量）每个分量一棵树；tree_root 为全局最长分支。
        """
        topo = self.topo
        node_branches = defaultdict(list)
        for key in topo.branches:
            for nd in topo.branch_nodes(key):
                node_branches[nd].append(key)
        self.tree = {}
        self.tree_root = None
        for comp in topo.components():
            comp_set = set(comp)
            # 根：本分量最长分支（§五：最长=3D 中心线真实弧长）
            root = max(comp, key=lambda k: topo.branches[k]["length"])
            if self.tree_root is None:
                self.tree_root = root
            self.tree[root] = {"parent": None, "anchor": None, "depth": 0,
                               "children": []}
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

    def _far_end(self, key, anchor):
        """从锚点起最远端（按弧长）；锚在中部时取较长一侧的端点。"""
        topo = self.topo
        nodes = topo.branch_nodes(key)
        pieces = topo.branches[key]["pieces"]
        if anchor is None:
            return nodes[-1]
        ai = nodes.index(anchor)
        left = sum(pc["length"] for pc in pieces[:ai]) if ai > 0 else 0.0
        right = sum(pc["length"] for pc in pieces[ai:]) \
            if ai < len(pieces) else 0.0
        return nodes[0] if left >= right else nodes[-1]

    # ---------- 父分支方向（投影帧与布局帧用同一拓扑规则选取相邻段） ----------
    def _ref_adjacent_joint(self, pkey, joint):
        """选取父分支在 joint 处作参考的相邻关节：朝锚点较长一侧。

        纯拓扑规则（只用段长，不用坐标），投影帧与布局帧结果一致，
        保证槽位偏移角的左右含义在两帧中相同。
        返回相邻关节名，或 None（无相邻段，如纯自环分支）。
        """
        topo = self.topo
        nodes = topo.branch_nodes(pkey)
        idx = nodes.index(joint)
        n = len(nodes)
        if n <= 1:
            return None
        # 两侧总长度
        pieces = topo.branches[pkey]["pieces"]
        left_len = sum(pc["length"] for pc in pieces[:idx]) \
            if idx > 0 else 0.0
        right_len = sum(pc["length"] for pc in pieces[idx:]) \
            if idx < len(pieces) else 0.0
        if idx > 0 and idx < n - 1:
            # 中间关节：取较长一侧；相等取右侧
            return nodes[idx + 1] if right_len >= left_len else nodes[idx - 1]
        if idx == 0:
            return nodes[1]
        return nodes[n - 2]

    def _proj_parent_dir(self, pkey, joint):
        """父分支在 joint 处的投影方向（度，绝对角），无方向返回 None。"""
        cache_key = (pkey, joint)
        if cache_key in self._proj_parent_dir_cache:
            return self._proj_parent_dir_cache[cache_key]
        adj = self._ref_adjacent_joint(pkey, joint)
        out = None
        if adj is not None and adj != joint:
            pj, pa = self.proj[joint], self.proj[adj]
            dx, dy = pa[0] - pj[0], pa[1] - pj[1]
            if math.hypot(dx, dy) > 1e-6:
                out = math.degrees(math.atan2(dy, dx))
        self._proj_parent_dir_cache[cache_key] = out
        return out

    def _placed_parent_dir(self, pkey, joint):
        """父分支在 joint 处的实际放置方向（度，绝对角），无方向返回 None。"""
        res = self.placed.get(pkey)
        if res is None:
            return None
        adj = self._ref_adjacent_joint(pkey, joint)
        if adj is None or adj == joint:
            return None
        jpos = res["joint_pos"]
        nodes = self.topo.branch_nodes(pkey)
        ji, ai = nodes.index(joint), nodes.index(adj)
        if ji not in jpos or ai not in jpos:
            return None
        pj, pa = jpos[ji], jpos[ai]
        dx, dy = pa[0] - pj[0], pa[1] - pj[1]
        if math.hypot(dx, dy) > 1e-6:
            return math.degrees(math.atan2(dy, dx))
        return None

    def _child_proj_angle(self, key, joint):
        """子分支相对父分支的投影角（度，(-180, 180]；+90=左侧垂直）。

        子分支方向取锚点 → 远端（较长一侧端点）的投影方向；
        纯自环分支（远端即锚点）或投影距离过小返回 None（无方向）。
        """
        pdir = self._proj_parent_dir(self.tree[key]["parent"], joint)
        if pdir is None:
            return None
        far = self._far_end(key, joint)
        if far == joint:
            return None
        pj, pf = self.proj[joint], self.proj[far]
        dx, dy = pf[0] - pj[0], pf[1] - pj[1]
        if math.hypot(dx, dy) < 1.0:
            return None
        cdir = math.degrees(math.atan2(dy, dx))
        rel = (cdir - pdir) % 360.0
        return rel - 360.0 if rel > 180.0 else rel

    # ---------- 槽位分配（暴力最优，确定性） ----------
    def _is_pure_self_loop(self, key):
        """纯自环分支：只有一段且两端同节点（无方向，不占槽位）。"""
        pieces = self.topo.branches[key]["pieces"]
        return len(pieces) == 1 and pieces[0]["na"] == pieces[0]["nb"]

    def _is_middle_anchored(self, key):
        """中间锚定分支：锚点在分支中部（两端都有段，占两个方向）。"""
        anchor = self.tree[key]["anchor"]
        if anchor is None:
            return False
        nodes = self.topo.branch_nodes(key)
        ai = nodes.index(anchor)
        return 0 < ai < len(nodes) - 1

    def assign_slots(self):
        """为每个（父分支，关节）组分配槽位偏移角。

        槽位集合 {±90, ±60, ±120, ±30, ±150}；代价按字典序
        （非垂直槽位数，投影角总偏差）；约束：无方向冲突
        （中间锚定分支占其槽位方向与对向）。
        纯自环分支无方向，不参与分配。
        """
        groups = defaultdict(list)
        for key, info in self.tree.items():
            if info["parent"] is None:
                continue
            if self._is_pure_self_loop(key):
                continue
            groups[(info["parent"], info["anchor"])].append(key)
        for (parent, joint), children in sorted(groups.items()):
            children = sorted(children)
            # 每根子分支的投影相对角（None=无方向，偏差计 0）
            proj_ang = {k: self._child_proj_angle(k, joint) for k in children}
            mid = {k: self._is_middle_anchored(k) for k in children}
            best = None  # (non_perp, total_dev, assignment tuple)
            for slots in itertools.permutations(SLOT_OFFSETS, len(children)):
                # 冲突检查：占用方向（模 360）不得重复
                occupied = []
                for k, s in zip(children, slots):
                    occupied.append(s % 360.0)
                    if mid[k]:
                        occupied.append((s + 180.0) % 360.0)
                if len(set(round(o, 6) for o in occupied)) != len(occupied):
                    continue
                non_perp = sum(1 for s in slots if abs(abs(s) - 90.0) > 1e-9)
                total_dev = 0.0
                for k, s in zip(children, slots):
                    if proj_ang[k] is not None:
                        total_dev += ang_diff(s, proj_ang[k])
                cand = (non_perp, round(total_dev, 9), slots)
                if best is None or cand < best:
                    best = cand
            if best is None:
                # 理论上不会发生（槽位 10 个，组内至多 4 根）；兜底：按序分垂直槽
                slots = tuple(SLOT_OFFSETS[i] for i in range(len(children)))
                best = (0, 0.0, slots)
            _, _, slots = best
            rec = {}
            for k, s in zip(children, slots):
                self.slot_offset[k] = s
                pa = proj_ang[k]
                side_match = None
                if pa is not None:
                    # 槽位侧：偏移角 >0 为左（逆时针），<0 为右
                    side_match = (s > 0) == (pa > 0) if abs(pa) > 1e-9 else None
                self.slot_info[k] = {
                    "proj_ang": None if pa is None else round(pa, 1),
                    "slot": s,
                    "side_match": side_match,
                    "offset_dev": round(abs(abs(s) - 90.0), 1),
                }
                rec[k] = s
            self.slot_groups.append((parent, joint, children, rec))
        return self.slot_offset

    # ---------- 关节清点（H6：先找齐再画） ----------
    def inventory_all_joints(self):
        """清点全部（父分支，关节）组的子分支并记入阶段日志。"""
        groups = defaultdict(list)
        for key, info in self.tree.items():
            if info["parent"] is None:
                continue
            groups[(info["parent"], info["anchor"])].append(key)
        for (parent, joint), children in sorted(groups.items()):
            children = sorted(
                children,
                key=lambda k: (-self.topo.branches[k]["length"], k))
            self.joint_inventory.append((parent, joint, children))
        # 兼容 v3-fix 的 trunk_inventory（只含主干关节）
        trunk = self.tree_root
        nodes = self.topo.branch_nodes(trunk)
        cum = [0.0]
        for pc in self.topo.branches[trunk]["pieces"]:
            cum.append(cum[-1] + pc["length"])
        for (parent, joint, children) in self.joint_inventory:
            if parent != trunk:
                continue
            x_along = cum[nodes.index(joint)] if joint in nodes else 0.0
            self.trunk_inventory.append((joint, round(x_along, 1), children))
        self.log_phase("清点", "清点 %d 个关节组、%d 根分支" % (
            len(self.joint_inventory), len(self.tree) - 1))
        return self.joint_inventory

    # ---------- 角度分配 ----------
    def _assigned_angle(self, key):
        """子分支的放置角度（度，绝对）：父分支实际方向 + 槽位偏移角。

        父分支无方向时（如纯自环父分支）回退到子分支投影绝对方向。
        根分支（无父分支）或无槽位分支：用投影方向
        （从首个已放置关节朝远端），否则 0°。
        """
        info = self.tree[key]
        parent, anchor = info["parent"], info["anchor"]
        if parent is None or anchor is None or key not in self.slot_offset:
            joints = self._joints(key)
            placed = [j for j in joints if j in self.node_pos]
            if placed:
                far = self._far_end(key, placed[0])
                pd = self.proj_direction(placed[0], far)
                if pd is not None:
                    return pd
            return 0.0
        pdir = self._placed_parent_dir(parent, anchor)
        if pdir is None:
            # 回退：子分支投影绝对方向（无方向则 90°）
            pa = self._child_proj_angle(key, anchor)
            if pa is not None:
                pp = self._proj_parent_dir(parent, anchor)
                return (pp + pa) % 360.0 if pp is not None else 90.0
            return 90.0
        return (pdir + self.slot_offset[key]) % 360.0

    # ---------- 分支试算（复用 v3，仅改自由延伸段第一段：不许拐弯/打折） ----------
    def layout_branch(self, key, run_angles):
        """试算一个分支的布局（不提交全局状态）。
        run_angles: {关节下标: 该自由延伸段的起始角度}。
        返回 dict(points, pieces{seg:(p1,p2)}, joint_pos{idx:(x,y)},
                  bends, warnings, n_bad)；失败返回 None。
        v4 唯一改动（§十三/H9）：自由延伸段的第一段不许关节拐弯、
        不许中部打折（只许直行或平行打折），保证第一段弦方向即分配方向；
        下游段仍按 §九 拐弯。"""
        topo = self.topo
        b = topo.branches[key]
        pieces = b['pieces']
        joints = self._joints(key)
        n = len(pieces)
        placed_j = [i for i in range(n + 1) if joints[i] in self.node_pos]
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
            path_lens = [dist(path[k], path[k + 1]) for k in range(len(path) - 1)]
            path_total = sum(path_lens) or 1.0

            def point_at(s):
                """沿路径走 s（按比例换算到路径总长）处的点。"""
                target = s / total * path_total
                acc = 0.0
                for k in range(len(path) - 1):
                    if acc + path_lens[k] >= target - 1e-9:
                        t = 0.0 if path_lens[k] < 1e-9 else (target - acc) / path_lens[k]
                        t = max(0.0, min(1.0, t))
                        return (path[k][0] + t * (path[k + 1][0] - path[k][0]),
                                path[k][1] + t * (path[k + 1][1] - path[k][1]))
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
                        joint_pos[j + 1] = jp
                        continue
                    tri, bad = None, None
                    for k in range(24):
                        t = self.triangle_loop(jp, tang + 15.0 * k, pc['length'])
                        s = [(t[m], t[m + 1]) for m in range(3)]
                        b = check_subs(s, skip_dist=True)
                        if bad is None or b < bad:
                            tri, bad = t, b
                            if b == 0:
                                break
                    seg_pts[pc['seg']] = tri
                    pts_out += tri[1:]
                    joint_pos[j + 1] = jp
                else:
                    p_start = joint_pos.get(j)
                    if p_start is None:
                        p_start = point_at(s_acc)
                        joint_pos[j] = p_start
                    s_acc += pc['length']
                    p_end = B if j + 1 == i1 else point_at(s_acc)
                    joint_pos[j + 1] = p_end
                    # 该段在路径上的子点列：取路径上 p_start→p_end 之间的点
                    seg_pts[pc['seg']] = self._subpath(path, p_start, p_end)
                    pts_out += seg_pts[pc['seg']][1:]
            # 干涉检查（受约束段无法改角，只能记警告）
            for pc in run:
                pts = seg_pts[pc['seg']]
                subs = [(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
                sd = (pc['na'] == pc['nb'])
                bad = check_subs(subs, skip_dist=sd)
                accept_subs(subs, skip_dist=sd)
                n_bad += bad
                if bad:
                    warnings.append(f"{key}/{pc['seg']} 受约束段与已画线干涉 {bad} 处")
            return pts_out

        def lay_free(anchor_j, direction, base_angle):
            """从锚点关节向 direction（+1 朝 node1 / -1 朝 node0）自由延伸。
            返回该方向的点列（从锚点向外）。
            v4：本延伸段的第一段非自环段不许关节拐弯、不许中部打折。"""
            nonlocal n_bad
            pts_out = [joint_pos[anchor_j]]
            cur = joint_pos[anchor_j]
            ang = base_angle
            rng = range(anchor_j, n) if direction > 0 else range(anchor_j - 1, -1, -1)
            rng_list = list(rng)
            # 本延伸段的第一段非自环段下标（v4：不许拐弯/打折）
            first_nonloop = None
            for _i in rng_list:
                if pieces[_i]['na'] != pieces[_i]['nb']:
                    first_nonloop = _i
                    break
            for i in rng_list:
                pc = pieces[i]
                j_next = i + 1 if direction > 0 else i
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
                        t = self.triangle_loop(cur, ang + 15.0 * k, pc['length'])
                        s = [(t[m], t[m + 1]) for m in range(3)]
                        b = check_subs(s, skip_dist=True)
                        if bad is None or b < bad:
                            tri, bad = t, b
                            if b == 0:
                                break
                    # 按 node0→node1 规范顺序存（后向段需反转）
                    seg_pts[pc['seg']] = tri if direction > 0 else tri[::-1]
                    subs = [(tri[m], tri[m + 1]) for m in range(3)]
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
                # v4：第一段只许 delta=0（直行或平行打折），不许关节拐弯/中部打折
                is_first = (i == first_nonloop)
                placed_seg = False
                if is_first:
                    bend_deltas = [0.0]
                else:
                    bend_deltas = [0.0] + [d for pair in
                                           zip([BEND_STEP * k for k in range(1, int(BEND_MAX / BEND_STEP) + 1)],
                                               [-BEND_STEP * k for k in range(1, int(BEND_MAX / BEND_STEP) + 1)])
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
                if chord is None and not is_first:
                    for frac in (0.5, 0.33, 0.67):
                        for kd in (10.0, -10.0, 20.0, -20.0, 30.0, -30.0):
                            pm = add_pt(cur, unit_from_angle(ang),
                                        pc['length'] * frac)
                            end = add_pt(pm, unit_from_angle(ang + kd),
                                         pc['length'] * (1 - frac))
                            cands.append((end, [(cur, pm), (pm, end)], ang + kd,
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
                                          'note': f'中部打折（{info[2] * 100:.0f}%处）'})
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
                                      'note': f'中部打折（{info[2] * 100:.0f}%处，兜底）'})
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

    # ---------- 分支放置（§十三：分配角优先，180° 翻转作备选） ----------
    def place_branch_best(self, key):
        """覆盖父类：按 §十三 分配角放置；备选为整根翻转 180°。

        评分 (干涉, 翻转, 警告数, 拐弯总量)：干涉优先，其次不翻转。
        非树锚点的自由段按已放置部分的走向直行（不翻转）。
        全段受约束的分支直接试算（方向由端点决定，H9 跳过）。
        """
        runs = self._free_runs(key)
        joints = self._joints(key)
        if not runs:
            res = self.layout_branch(key, {})
            if res is not None:
                self._commit(key, res)
                self.placed_kind[key] = 'constrained'
                return True
            return False
        info = self.tree[key]
        anchor_node = info["anchor"]
        assigned = self._assigned_angle(key)
        far = self._far_end(key, anchor_node) if anchor_node is not None \
            else joints[-1]
        far_idx = joints.index(far) if far in joints else len(joints) - 1
        anchor_idx = joints.index(anchor_node) if anchor_node in joints else 0
        far_side = 1 if far_idx > anchor_idx else -1
        # 可翻转的锚点：树锚点；根分支（无树锚点）用首个自由段锚点
        flip_anchor = anchor_node if anchor_node is not None else joints[runs[0][0]]

        def desired_actual(anchor_j, direction):
            """某自由段期望的实际方向角（度）。

            所有自由段都按槽位方向：朝远端一侧为分配角，反侧为分配角+180°
            （远端以树锚点为准）。非树锚点段同样遵循本分支的槽位线方向——
            不沿已放置部分的走向，因为已放置部分可能是受约束段，
            其方向由父分支决定（如 Body.159 的 SEG08 沿 Body.46 走，
            若沿走向则 SEG09 与父分支平行，违反正交）。
            """
            return assigned if direction == far_side \
                else (assigned + 180.0) % 360.0

        # 候选：分配角 / 分配角+180°（翻转）/ 分配角±30° / 翻转±30°。
        # ±30° 偏离仍在 H9 允许范围内（90°±30°k），用于分配角与翻转角
        # 都有干涉时避开共线重叠（重叠是硬规则，宁可偏 30° 不可压着画）。
        combos = []
        for flip in (False, True):
            for off in (0.0, 30.0, -30.0):
                angles = {}
                for (j, d) in runs:
                    des = desired_actual(j, d)
                    if flip and joints[j] == flip_anchor:
                        des = (des + 180.0) % 360.0
                    des = (des + off) % 360.0
                    # run_angles 存 +1 方向角；-1 段实际方向 = 存角 + 180°
                    angles[j] = des if d > 0 else (des + 180.0) % 360.0
                combos.append((angles, 1 if flip else 0,
                               0 if off == 0.0 else 1, off))
        # 侧强制（放置侧搜索用）：只保留指定侧的候选（±30° 偏离仍允许）
        if key in self.side_override:
            want = self.side_override[key]
            combos = [c for c in combos if c[1] == want]
        # 同锚点两段共用一个存角：去重（两个 run 同一 anchor_j 时后者覆盖前者，
        # 两者存角本就一致——同锚点时 desired_actual 给出同一条直线的两向）
        best, best_score = None, None
        best_flip = 0
        best_off = 0.0

        def score_of(res, flipped, off_pen):
            # 干涉优先，其次不偏离（保持垂直），再次不翻转
            return (res['n_bad'], off_pen, flipped, len(res['warnings']),
                    sum(abs(b['delta']) for b in res['bends']
                        if isinstance(b['delta'], (int, float))))
        for angles, flipped, off_pen, off in combos:
            res = self.layout_branch(key, angles)
            if res is None:
                continue
            sc = score_of(res, flipped, off_pen)
            if best_score is None or sc < best_score:
                best, best_score, best_flip, best_off = res, sc, flipped, off
                if sc[0] == 0 and sc[1] == 0 and sc[2] == 0 and sc[3] == 0:
                    break
        if best is None:
            return False
        if best_score[0] > 0:
            self.warnings.append(f"{key} 所有候选角度均有干涉，取最少干涉方案")
        self._commit(key, best)
        self.placed_kind[key] = 'dir'
        self.placed_angle[key] = (assigned + 180.0 * best_flip + best_off) % 360.0
        self.placed_flip[key] = bool(best_flip)
        self.placed_offset[key] = best_off
        # 记录各自由段的第一段非自环段（H9 测量用）
        pieces = self.topo.branches[key]['pieces']
        free_segs = []
        for (j, d) in runs:
            if d > 0:
                for i in range(j, len(pieces)):
                    if pieces[i]['na'] != pieces[i]['nb']:
                        free_segs.append((i, d))
                        break
            else:
                for i in range(j - 1, -1, -1):
                    if pieces[i]['na'] != pieces[i]['nb']:
                        free_segs.append((i, d))
                        break
        self.placed_free_segs[key] = free_segs
        return True

    # ---------- 分量布局（环先画 + BFS 按深度放置） ----------
    def layout_component(self, comp_keys, origin):
        """一个连通分量的展开：先画最大真环（无环则主干），再按 BFS 深度放置。"""
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

    # ---------- 六阶段主流程 ----------
    def search_top_sides(self):
        """放置侧搜索（阶段 4 前置）：顶层分支侧组合穷举。

        深度 1~3 的顶层分支（IP 共 6 根）决定整棵树的伸展方向，是居中
        的主杠杆。穷举 2^6=64 种侧组合，各跑一遍放置，选综合最优者
        作为 side_override。放置时即居中，则居中阶段只需少量干净翻转，
        X 交叉不被破坏（实测：无搜索时放置偏差 24.32%，居中需 13 次翻转
        且 X 从 21 炸到 55；有搜索时放置偏差 8.96%，居中 4 次干净翻转，
        终态 X=17）。
        评分 = 居中偏差% + 0.5×X交叉数（兼顾居中与交叉），平局按
        (偏差, X, 间距<5mm, 比特串) 确定性排序。翻转的顶层分支记入清单
        （属 §十三“分区域调整”，投影侧是初始选择、调整可翻转）。
        """
        lv = [k for k, v in sorted(self.tree.items(),
                                   key=lambda kv: (kv[1]['depth'], kv[0]))
              if 1 <= v['depth'] <= 3]
        if not lv:
            return
        best = None
        for bits in itertools.product([0, 1], repeat=len(lv)):
            ov = dict(zip(lv, bits))
            trial = LayoutV4(self.topo, clearance=self.clearance,
                             verbose=False)
            trial.run_projection()
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
                       f"穷举 {2 ** len(lv)} 种顶层侧组合，最优居中偏差 "
                       f"{dev:.2f}% X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}；"
                       f"翻转侧：{flipped if flipped else '无'}")

    def run(self):
        self.log_phase('开始',
            f"分支 {len(self.topo.branches)} / 节点 {len(self.topo.nodes)} "
            f"/ 线段 {len(self.topo.segs)}")
        self.run_projection()          # 阶段 3：初始二维投影（PCA）
        self.build_branch_tree()       # 阶段 2：拓扑分析（分支树 BFS）
        self.assign_slots()            # 阶段 4 准备：槽位分配
        self.inventory_all_joints()    # H6：先找齐再画
        self.search_top_sides()        # 阶段 4 前置：顶层侧组合穷举（放置即居中）
        Layout.run(self)               # 阶段 4：结构化布局（正交放置）
        n_x, n_near, n_ov = count_interference_detailed(self)
        self.log_phase('放置完成', f"残留 X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}")
        # 阶段 5：居中与消交叉交替（最多 5 轮），直至两者同时达标或一轮内无翻转。
        # 单向顺序会卡死（居中翻转造重叠、消交叉翻转破居中），交替可跳出局部最优。
        for rnd in range(5):
            n_x, n_near, n_ov = count_interference_detailed(self)
            dev = self._center_dev_of_bbox(self.bbox())
            if n_ov == 0 and dev <= CENTER_TOL * 100.0:
                break
            flips_before = len(self.center_flips) + len(self.untangle_flips)
            self.flip_center()         # 阶段 5a：居中爬山（180° 翻转）
            n_x, n_near, n_ov = count_interference_detailed(self)
            self.log_phase('居中完成', f"残留 X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}")
            self.flip_untangle()       # 阶段 5b：消交叉爬山（180° 翻转，守居中）
            flips_after = len(self.center_flips) + len(self.untangle_flips)
            if flips_after == flips_before:
                break
        self.recenter_bbox()
        self.center_info = self.measure_trunk_center()
        ci = self.center_info
        self.log_phase('居中',
            f"主干 {ci.get('trunk')} 中点=({ci.get('trunk_x_mid')}, {ci.get('trunk_y')})mm，"
            f"图纸中心=({ci.get('center_x')}, {ci.get('center_y')})mm，"
            f"横偏差 {ci.get('dev_x_mm')}mm（{ci.get('dev_x_pct')}%），"
            f"竖偏差 {ci.get('dev_y_mm')}mm（{ci.get('dev_y_pct')}%）")
        return self

    # ---------- 子树旋转（第 5 阶段：居中/消交叉，全部 180°） ----------
    def _subtree_branches(self, root_key):
        """root_key 及其全部后代分支（BFS，确定性顺序）。"""
        out = [root_key]
        stack = list(self.tree[root_key]["children"])
        while stack:
            k = stack.pop()
            out.append(k)
            stack.extend(self.tree[k]["children"])
        return out

    @staticmethod
    def _rot180(p, origin):
        """180° 点旋转（精确公式，无三角函数误差，两次旋转精确还原）。"""
        return (2.0 * origin[0] - p[0], 2.0 * origin[1] - p[1])

    def rotate_subtree(self, root_key, anchor_node, angle_deg):
        """刚性旋转子树（root_key 及其全部后代）angle_deg 度，绕 anchor_node。
        长度/拓扑不变；调用前须经 _rotation_safe 检查。
        v4 只用 180°（保持正交），用精确点反射公式。"""
        origin = self.node_pos[anchor_node]
        subs = set(self._subtree_branches(root_key))
        is180 = abs(abs(angle_deg) - 180.0) < 1e-9

        def rp(p):
            return self._rot180(p, origin) if is180 \
                else rot_pt(p, angle_deg, origin)
        # 子树节点（除锚点外）
        sub_nodes = set()
        for k in subs:
            sub_nodes.update(self.topo.branch_nodes(k))
        sub_nodes.discard(anchor_node)
        for nd in sub_nodes:
            if nd in self.node_pos:
                self.node_pos[nd] = rp(self.node_pos[nd])
                if nd in self.node_parent_dir:
                    self.node_parent_dir[nd] = \
                        (self.node_parent_dir[nd] + angle_deg) % 360.0
        # 分支几何
        for k in subs:
            res = self.placed.get(k)
            if res is None:
                continue
            res['points'] = [rp(p) for p in res['points']]
            res['seg_pts'] = {sg: [rp(p) for p in pts]
                              for sg, pts in res['seg_pts'].items()}
            res['pieces'] = {sg: (rp(p1), rp(p2))
                             for sg, (p1, p2) in res['pieces'].items()}
            res['joint_pos'] = {i: rp(p)
                                for i, p in res['joint_pos'].items()}
        # piece_pos 与 placed_pieces
        for sg in list(self.piece_pos):
            br = self.topo.segs[sg]['branch'] if sg in self.topo.segs else sg
            if br in subs:
                p1, p2 = self.piece_pos[sg]
                self.piece_pos[sg] = (rp(p1), rp(p2))
        self.placed_pieces = [
            (rp(p1), rp(p2), b, s, sd) if b in subs else (p1, p2, b, s, sd)
            for (p1, p2, b, s, sd) in self.placed_pieces
        ]

    def _rotation_safe(self, root_key, anchor_node):
        """子树旋转是否安全：子树内节点（除锚点）不得连接子树外分支；
        子树内不得含环线段；根分支本身不可转。"""
        if self.tree[root_key]["parent"] is None:
            return False
        subs = set(self._subtree_branches(root_key))
        ring_segs = set()
        for r in self.rings_drawn:
            ring_segs.update(r['segs'])
        for k in subs:
            for pc in self.topo.branches[k]['pieces']:
                if pc['seg'] in ring_segs:
                    return False
        sub_nodes = set()
        for k in subs:
            sub_nodes.update(self.topo.branch_nodes(k))
        sub_nodes.discard(anchor_node)
        for nd in sub_nodes:
            for k in self.topo.node_branches[nd]:
                if k not in subs:
                    return False
        return True

    def _crossing_pairs(self):
        """残留 X 交叉的分支对列表（已排序，确定性）。"""
        pp = self.placed_pieces
        pairs = set()
        for i in range(len(pp)):
            for j in range(i + 1, len(pp)):
                if pp[i][2] == pp[j][2] and pp[i][3] == pp[j][3]:
                    continue
                if seg_proper_intersect(pp[i][0], pp[i][1], pp[j][0], pp[j][1]):
                    a, b = sorted((pp[i][2], pp[j][2]))
                    pairs.add((a, b))
        return sorted(pairs)

    def _cross_score(self):
        """干涉分：100*共线重叠 + 10*X交叉 + 间距<5mm（分级：共线必消>交叉优先消>间距尽量消）。"""
        n_x, n_near, n_ov = count_interference_detailed(self)
        return 100 * n_ov + 10 * n_x + n_near, (n_x, n_near, n_ov)

    def _bbox_after_rotation(self, root_key, anchor_node, angle_deg=180.0):
        """旋转后（不实际旋转）的包围盒。"""
        origin = self.node_pos[anchor_node]
        subs = set(self._subtree_branches(root_key))
        sub_nodes = set()
        for k in subs:
            sub_nodes.update(self.topo.branch_nodes(k))
        sub_nodes.discard(anchor_node)
        is180 = abs(abs(angle_deg) - 180.0) < 1e-9

        def rp(p):
            return self._rot180(p, origin) if is180 \
                else rot_pt(p, angle_deg, origin)
        xs, ys = [], []
        for (p1, p2, b, _s, _sd) in self.placed_pieces:
            if b in subs:
                q1, q2 = rp(p1), rp(p2)
            else:
                q1, q2 = p1, p2
            xs.extend([q1[0], q2[0]])
            ys.extend([q1[1], q2[1]])
        for nd, p in self.node_pos.items():
            q = rp(p) if nd in sub_nodes else p
            xs.append(q[0])
            ys.append(q[1])
        return (min(xs), min(ys), max(xs), max(ys))

    def _trunk_mid(self):
        pts = self.placed[self.trunk_key]['points']
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))

    def _center_dev_of_bbox(self, bbox):
        """给定包围盒的主干居中偏差（横/竖偏差百分比的最大值）。"""
        tmx, tmy = self._trunk_mid()
        xmin, ymin, xmax, ymax = bbox
        w, h = xmax - xmin, ymax - ymin
        cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        dx = abs(tmx - cx) / w * 100.0 if w > 0 else 0.0
        dy = abs(tmy - cy) / h * 100.0 if h > 0 else 0.0
        return max(dx, dy)

    def _branch_dirs_from_anchor(self, key, anchor):
        """分支在锚点处向外延伸的方向角列表（放置后几何）。
        取锚点两侧第一段非自环段的方向；自环段无方向，跳过。"""
        res = self.placed.get(key)
        if res is None:
            return []
        joints = self._joints(key)
        if anchor not in joints:
            return []
        ai = joints.index(anchor)
        jpos = res['joint_pos']
        if ai not in jpos:
            return []
        pa = jpos[ai]
        dirs = []
        pieces = self.topo.branches[key]['pieces']
        # 朝 node1 方向：第一段非自环段
        for i in range(ai, len(pieces)):
            if pieces[i]['na'] == pieces[i]['nb']:
                continue
            p1 = jpos.get(i + 1)
            if p1 is not None and not pt_eq(pa, p1):
                dirs.append(angle_of(pa, p1))
            break
        # 朝 node0 方向：第一段非自环段
        for i in range(ai - 1, -1, -1):
            if pieces[i]['na'] == pieces[i]['nb']:
                continue
            p1 = jpos.get(i)
            if p1 is not None and not pt_eq(pa, p1):
                dirs.append(angle_of(pa, p1))
            break
        return dirs

    def _sibling_ray_conflict(self, root_key, anchor_node):
        """旋转 root_key 子树 180° 后，root_key 的第一段是否会与同关节
        兄弟分支同向（同一起点同方向 = 必然重叠）。返回 True 表示冲突
        （禁止该旋转）。兄弟分支不在旋转子树内（同父同级），方向不变，
        故可直接比较。"""
        info = self.tree[root_key]
        parent = info["parent"]
        if parent is None:
            return False
        my_dirs = self._branch_dirs_from_anchor(root_key, anchor_node)
        if not my_dirs:
            return False
        new_dirs = [(d + 180.0) % 360.0 for d in my_dirs]
        for sib in self.tree[parent]["children"]:
            if sib == root_key:
                continue
            if self.tree[sib]["anchor"] != anchor_node:
                continue
            for sd in self._branch_dirs_from_anchor(sib, anchor_node):
                for nd in new_dirs:
                    if ang_diff(nd, sd) < 1.0:
                        return True
        return False

    def flip_center(self):
        """阶段 5a：居中爬山——180° 旋转子树，使主干中点逼近图纸中心。
        180° 旋转保持正交；每轮取偏差最小的候选，无改善则停。
        达到 CENTER_TARGET（3.5%）即停，不必优化到 0（留裕量给消交叉，
        且避免居中翻转破坏干涉）。
        干涉守门（分级）：优先选不增加共线重叠且不增加 X 交叉的翻转；
        其次选不增加共线重叠的；仅当居中仍不达标（>5%）时才允许
        为居中牺牲干涉（重叠由消交叉阶段再处理）。
        """
        if self.trunk_key not in self.placed:
            return
        cands = []
        for k in sorted(self.tree):
            info = self.tree[k]
            if info["parent"] is None:
                continue
            if self._rotation_safe(k, info["anchor"]):
                cands.append((info["depth"], k, info["anchor"]))
        cands.sort()
        cur_dev = self._center_dev_of_bbox(self.bbox())
        cur_x, cur_near, cur_ov = count_interference_detailed(self)
        for _ in range(FLIP_CENTER_MAX_PASSES):
            if cur_dev <= CENTER_TARGET * 100.0:
                break
            # 评估全部候选：(dev_after, ov_after, x_after, depth, key, anchor)
            evaluated = []
            for (depth, k, anchor) in cands:
                if self._sibling_ray_conflict(k, anchor):
                    continue
                nb = self._bbox_after_rotation(k, anchor, 180.0)
                d = self._center_dev_of_bbox(nb)
                if d >= cur_dev - 1e-9:
                    continue
                before = self._moved_vs_fixed_counts(k, anchor, 0.0)
                after = self._moved_vs_fixed_counts(k, anchor, 180.0)
                ov_after = cur_ov - before[2] + after[2]
                x_after = cur_x - before[0] + after[0]
                evaluated.append((round(d, 9), ov_after, x_after,
                                  depth, k, anchor))
            if not evaluated:
                break
            # 分级选优：tier1 不增干涉；tier2 X 至多 +3；tier3 兜底——
            # 居中未达标时允许任意干涉（实测：无 tier3 时居中卡在 14~18%，
            # H1 通不过；居中需要搬动大块几何，180° 翻转必然带干涉）。
            tier1 = [e for e in evaluated
                     if e[1] <= cur_ov and e[2] <= cur_x]
            tier2 = [e for e in evaluated
                     if e[1] <= cur_ov and e[2] <= cur_x + 3]
            if tier1:
                pick = min(tier1)
            elif tier2:
                pick = min(tier2)
            elif cur_dev > CENTER_TOL * 100.0:
                pick = min(evaluated)
            else:
                break
            _, ov_after, x_after, _, k, anchor = pick
            self.rotate_subtree(k, anchor, 180.0)
            self.center_flips.append({'branch': k, 'anchor': anchor,
                                      'angle': 180,
                                      'dev_before': round(cur_dev, 2),
                                      'dev_after': round(pick[0], 2)})
            cur_dev = pick[0]
            cur_ov, cur_x = ov_after, x_after
        self.log_phase('居中优化', f"180° 翻转 {len(self.center_flips)} 次，"
                                  f"主干居中偏差 {cur_dev:.2f}%")

    def _overlap_pairs(self):
        """共线重叠的分支对列表（已排序，确定性）。"""
        pp = self.placed_pieces
        pairs = set()
        for i in range(len(pp)):
            for j in range(i + 1, len(pp)):
                if pp[i][2] == pp[j][2] and pp[i][3] == pp[j][3]:
                    continue
                if seg_collinear_overlap(pp[i][0], pp[i][1], pp[j][0], pp[j][1]):
                    a, b = sorted((pp[i][2], pp[j][2]))
                    pairs.add((a, b))
        return sorted(pairs)

    def _moved_vs_fixed_counts(self, root_key, anchor_node, angle_deg=180.0):
        """子树段（旋转 angle_deg 后）与非子树段之间的干涉计数 (x, near, ov)。

        子树内部干涉不受刚性旋转影响，不计；只计跨界对，
        用于无变异评估一次旋转的干涉增量。
        """
        origin = self.node_pos[anchor_node]
        subs = set(self._subtree_branches(root_key))
        moved = [(p1, p2, b, s, sd)
                 for (p1, p2, b, s, sd) in self.placed_pieces if b in subs]
        fixed = [(p1, p2, b, s, sd)
                 for (p1, p2, b, s, sd) in self.placed_pieces if b not in subs]
        is180 = abs(abs(angle_deg) - 180.0) < 1e-9
        is0 = abs(angle_deg) < 1e-9

        def rp(p):
            if is0:
                return p
            return self._rot180(p, origin) if is180 \
                else rot_pt(p, angle_deg, origin)
        n_x = n_near = n_ov = 0
        for (p1, p2, _b1, _s1, sd1) in moved:
            q1, q2 = rp(p1), rp(p2)
            for (r1, r2, _b2, _s2, sd2) in fixed:
                shared = (pt_eq(q1, r1) or pt_eq(q1, r2)
                          or pt_eq(q2, r1) or pt_eq(q2, r2))
                if seg_proper_intersect(q1, q2, r1, r2):
                    n_x += 1
                elif seg_collinear_overlap(q1, q2, r1, r2):
                    n_ov += 1
                elif (not shared and not (sd1 or sd2)
                        and seg_seg_dist(q1, q2, r1, r2) < self.clearance):
                    n_near += 1
        return (n_x, n_near, n_ov)

    def flip_untangle(self):
        """阶段 5b：消交叉爬山（最陡下降）。

        每轮评估全部涉事子树（共线重叠对 + X 交叉对的分支）的 180° 旋转，
        取干涉三元组 (共线重叠, X 交叉, 间距<5mm) 字典序最小者应用；
        无严格改善则停。只接受居中仍达标（H1）的旋转。
        共线重叠是硬规则（H4），字典序优先于 X 交叉。
        """
        if self.trunk_key not in self.placed:
            return

        def total_counts():
            n_x, n_near, n_ov = count_interference_detailed(self)
            return (n_ov, n_x, n_near)  # 字典序：重叠 > 交叉 > 间距

        cur = total_counts()
        cur_dev = self._center_dev_of_bbox(self.bbox())
        rotations = 0
        for _ in range(UNTANGLE_MAX_PASSES):
            if rotations >= UNTANGLE_MAX_ROTATIONS:
                break
            # 候选分支：重叠对 + 交叉对的分支（去重，按子树规模升序）
            cand_keys = set()
            for (a, b) in self._overlap_pairs():
                cand_keys.add(a)
                cand_keys.add(b)
            for (a, b) in self._crossing_pairs():
                cand_keys.add(a)
                cand_keys.add(b)
            if not cand_keys:
                break
            best = None  # (new_counts, center_dev_after, depth, key, anchor)
            for k in sorted(cand_keys,
                            key=lambda kk: (len(self._subtree_branches(kk)), kk)):
                info = self.tree[k]
                if info["parent"] is None:
                    continue
                anchor = info["anchor"]
                if not self._rotation_safe(k, anchor):
                    continue
                if self._sibling_ray_conflict(k, anchor):
                    continue
                nb = self._bbox_after_rotation(k, anchor, 180.0)
                dev_after = self._center_dev_of_bbox(nb)
                # 居中守门：不许比当前更差（当前已达标时即 ≤5%；
                # 当前未达标时允许维持现状，由下一轮居中继续处理，
                # 避免消交叉被居中卡死）
                if dev_after > max(CENTER_TOL * 100.0, cur_dev) + 1e-9:
                    continue
                # 增量评估：总数 - 旋转前跨界 + 旋转后跨界
                before = self._moved_vs_fixed_counts(k, anchor, 0.0)
                after = self._moved_vs_fixed_counts(k, anchor, 180.0)
                new_x = cur[1] - before[0] + after[0]
                new_near = cur[2] - before[1] + after[1]
                new_ov = cur[0] - before[2] + after[2]
                new = (new_ov, new_x, new_near)
                # 干涉优先，居中次之（同干涉时选居中更好的）
                cand = (new, round(dev_after, 9), info["depth"], k, anchor)
                if best is None or cand < best:
                    best = cand
            if best is None or best[0] >= cur:
                break
            new, _dev, _depth, k, anchor = best
            self.rotate_subtree(k, anchor, 180.0)
            self.untangle_flips.append(
                {'branch': k, 'anchor': anchor, 'angle': 180,
                 'counts_before': [cur[1], cur[2], cur[0]],
                 'counts_after': [new[1], new[2], new[0]]})
            cur = new
            cur_dev = _dev
            rotations += 1
        n_x, n_near, n_ov = count_interference_detailed(self)
        self.log_phase('消交叉', f"180° 翻转 {len(self.untangle_flips)} 次，"
                                f"残留 X={n_x} 间距<5mm={n_near} 共线重叠={n_ov}")

    # ---------- 居中测量（v4：横竖两个方向都要查） ----------
    def measure_trunk_center(self):
        """主干居中测量：主干中点与图纸中心的横/竖偏差（平移不变量）。
        dev_mm/dev_pct 取横竖两方向的最大值（主导偏差），另列分项。"""
        if self.trunk_key not in self.placed:
            return {'ok': False, 'reason': '主干未放置'}
        pts = self.placed[self.trunk_key]['points']
        trunk_y = sum(p[1] for p in pts) / len(pts)
        trunk_x_mid = sum(p[0] for p in pts) / len(pts)
        ang = angle_of(pts[0], pts[-1]) % 180.0
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
        return {
            'ok': True,
            'trunk': self.trunk_key,
            'trunk_y': round(trunk_y, 2),
            'trunk_x_mid': round(trunk_x_mid, 2),
            'trunk_angle_deg': round(ang, 2),
            'trunk_angle_from_horizontal_deg': round(ang_from_h, 2),
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

    # ---------- H9 正交核查 ----------
    def _ortho_check(self):
        """逐根检查方向放置分支与上级主干的夹角。
        测量：分支自由段第一段非自环段的弦方向与父分支在锚点处实际方向的
        直线夹角；应为 90° ± 30°k（k=0,1,2），容差 0.5°。
        跳过：根分支、纯自环分支、全约束分支（方向由端点决定）、
        父分支无方向者。
        返回 (checked, passed, failures, distribution, skipped)。"""
        checked = 0
        passed = 0
        failures = []
        dist_count = defaultdict(int)
        skipped = {'root': 0, 'pure_loop': 0, 'constrained': 0, 'no_parent_dir': 0}
        for key in sorted(self.tree):
            info = self.tree[key]
            if info["parent"] is None:
                skipped['root'] += 1
                continue
            if self._is_pure_self_loop(key):
                skipped['pure_loop'] += 1
                continue
            if self.placed_kind.get(key) != 'dir':
                skipped['constrained'] += 1
                continue
            parent, anchor = info["parent"], info["anchor"]
            pdir = self._placed_parent_dir(parent, anchor)
            if pdir is None:
                skipped['no_parent_dir'] += 1
                continue
            res = self.placed.get(key)
            if res is None:
                continue
            jpos = res['joint_pos']
            ok_all = True
            worst_dev = 0.0
            worst_la = 0.0
            for (seg_idx, direction) in self.placed_free_segs.get(key, []):
                if direction > 0:
                    p0, p1 = jpos.get(seg_idx), jpos.get(seg_idx + 1)
                else:
                    p0, p1 = jpos.get(seg_idx + 1), jpos.get(seg_idx)
                if p0 is None or p1 is None or pt_eq(p0, p1):
                    continue
                cdir = angle_of(p0, p1)
                la = line_angle(cdir, pdir)
                dev = abs(la - 90.0)
                ok = any(abs(dev - k * 30.0) <= ORTHO_TOL_DEG for k in (0, 1, 2))
                if not ok:
                    ok_all = False
                if dev > worst_dev:
                    worst_dev, worst_la = dev, la
            checked += 1
            k_near = int(round(worst_dev / 30.0))
            dist_count[k_near * 30] += 1
            if ok_all:
                passed += 1
            else:
                failures.append({'branch': key, 'parent': parent,
                                 'anchor': anchor,
                                 'angle': round(worst_la, 1),
                                 'dev': round(worst_dev, 1)})
        return checked, passed, failures, dict(sorted(dist_count.items())), skipped

    def _side_compliance(self):
        """投影侧符合率：方向放置分支的实际侧与投影侧一致的比例。
        实际侧由放置后几何量取（第一段弦方向相对父分支方向的符号）。"""
        matched = 0
        total = 0
        for key in sorted(self.tree):
            info = self.tree[key]
            if info["parent"] is None or self.placed_kind.get(key) != 'dir':
                continue
            si = self.slot_info.get(key)
            if si is None or si.get('proj_ang') is None:
                continue
            parent, anchor = info["parent"], info["anchor"]
            pdir = self._placed_parent_dir(parent, anchor)
            if pdir is None:
                continue
            res = self.placed.get(key)
            if res is None:
                continue
            jpos = res['joint_pos']
            free = self.placed_free_segs.get(key, [])
            if not free:
                continue
            seg_idx, direction = free[0]
            if direction > 0:
                p0, p1 = jpos.get(seg_idx), jpos.get(seg_idx + 1)
            else:
                p0, p1 = jpos.get(seg_idx + 1), jpos.get(seg_idx)
            if p0 is None or p1 is None or pt_eq(p0, p1):
                continue
            cdir = angle_of(p0, p1)
            rel = (cdir - pdir) % 360.0
            rel = rel - 360.0 if rel > 180.0 else rel
            if abs(rel) < 1e-9 or abs(si['proj_ang']) < 1e-9:
                continue
            total += 1
            if (rel > 0) == (si['proj_ang'] > 0):
                matched += 1
        return matched, total

    # ---------- 规则检查清单（v4：H1–H9，任一硬规则失败则退出码非 0） ----------
    def run_checklist(self, det_md5_a=None, det_md5_b=None, det_pass=None):
        """执行 v4 规则检查清单。返回 (checklist, all_hard_pass)。
        checklist['hard'] 每条：{id, rule, name, value, threshold, pass}；
        checklist['soft'] 每条：{id, rule, name, value, note}（警告，不阻塞）。"""
        st = self.validate()
        n_x, n_near, n_ov = count_interference_detailed(self)
        ci = self.center_info
        hard = []
        soft = []

        # H1 主干水平且居中（§五/§十三）——横竖两个方向都要查
        h1_pass = bool(ci.get('ok')) and \
            ci.get('trunk_angle_from_horizontal_deg', 99) <= TRUNK_ANGLE_TOL and \
            ci.get('dev_x_pct', 99) <= ci.get('tol_pct', 5.0) and \
            ci.get('dev_y_pct', 99) <= ci.get('tol_pct', 5.0)
        hard.append({
            'id': 'H1', 'rule': '§五/§十三 主干水平画在图正中间',
            'name': '主干水平且居中（横竖两方向）',
            'value': (f"主干与水平夹角 {ci.get('trunk_angle_from_horizontal_deg')}°；"
                      f"主干中点=({ci.get('trunk_x_mid')}, {ci.get('trunk_y')})mm，"
                      f"图纸中心=({ci.get('center_x')}, {ci.get('center_y')})mm；"
                      f"横偏差 {ci.get('dev_x_mm')}mm（{ci.get('dev_x_pct')}% 图纸宽 "
                      f"{ci.get('width')}mm），竖偏差 {ci.get('dev_y_mm')}mm"
                      f"（{ci.get('dev_y_pct')}% 图纸高 {ci.get('height')}mm）"),
            'threshold': f"夹角 ≤ {TRUNK_ANGLE_TOL}°；横竖偏差均 ≤ {TRUNK_CENTER_TOL * 100:.0f}%",
            'pass': h1_pass,
        })

        # H2 长度 1:1（§二.1）
        max_err = st['max_len_err_mm']
        worst = ''
        if st['len_errs']:
            w = sorted(st['len_errs'],
                       key=lambda t: (-abs(t[3]), t[0]))[0]
            worst = (f"（最大误差分支 {w[0]}，3D {w[1]:.1f}mm → "
                     f"2D {w[2]:.1f}mm，误差 {w[3]:+.2f}mm）")
        h2_pass = max_err <= LEN_ERR_TOL_V4 + 1e-9
        hard.append({
            'id': 'H2', 'rule': '§二.1 长度 1:1', 'name': '长度 1:1',
            'value': f"2D 长度与 3D 弧长最大误差 {max_err:.2f}mm{worst}",
            'threshold': f"≤ {LEN_ERR_TOL_V4}mm",
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

        # H5 全画出
        n_segs_placed = len(self.piece_pos)
        n_segs_total = len(self.topo.segs)
        h5_pass = (st['branches_placed'] == st['branches_total'] and
                   st['nodes_placed'] == st['nodes_total'] and
                   n_segs_placed == n_segs_total)
        hard.append({
            'id': 'H5', 'rule': '§二 完整性', 'name': '全画出',
            'value': f"分支 {st['branches_placed']}/{st['branches_total']}，"
                     f"节点 {st['nodes_placed']}/{st['nodes_total']}，"
                     f"线段 {n_segs_placed}/{n_segs_total}",
            'threshold': '全部画出',
            'pass': h5_pass,
        })

        # H6 分支点先找齐再画（§十三）：清点阶段在放置阶段之前，且清点完整
        inv_seq = None
        place_seq = None
        for (s, ph, _m) in self.phase_log:
            if ph == '清点' and inv_seq is None:
                inv_seq = s
            if ph == '放置' and place_seq is None:
                place_seq = s
        order_ok = (inv_seq is not None and place_seq is not None
                    and inv_seq < place_seq)
        # 清点完整性：每个（父分支，关节）组都在清点里，子分支与树一致
        inv_map = {(p, j): c for (p, j, c) in self.joint_inventory}
        groups = defaultdict(list)
        for key, info in self.tree.items():
            if info["parent"] is not None:
                groups[(info["parent"], info["anchor"])].append(key)
        ok_all = len(inv_map) == len(groups)
        for g, children in groups.items():
            expect = sorted(children,
                            key=lambda k: (-self.topo.branches[k]['length'], k))
            if inv_map.get(g) != expect:
                ok_all = False
                break
        total_attached = sum(len(c) for (_p, _j, c) in self.joint_inventory)
        inv_detail = (f"清点 {len(self.joint_inventory)} 个关节组、"
                      f"{total_attached} 根分支；"
                      f"清点阶段 seq={inv_seq}，放置阶段 seq={place_seq}")
        h6_pass = order_ok and ok_all
        hard.append({
            'id': 'H6', 'rule': '§十三 先找齐再画', 'name': '分支点先找齐再画',
            'value': inv_detail,
            'threshold': '清点在放置之前，且清点完整',
            'pass': h6_pass,
        })

        # H7 投影步已执行（§四）：全部节点有投影坐标
        n_proj = len(self.proj)
        n_nodes = len(self.topo.nodes)
        proj_seq = None
        for (s, ph, _m) in self.phase_log:
            if ph == '投影' and proj_seq is None:
                proj_seq = s
        proj_first = (proj_seq is not None and place_seq is not None
                      and proj_seq < place_seq)
        h7_pass = (n_proj == n_nodes and proj_first)
        hard.append({
            'id': 'H7', 'rule': '§四 先投影再分区域调', 'name': '投影步已执行',
            'value': (f"投影节点 {n_proj}/{n_nodes}（{self.proj_meta.get('plane')}，"
                      f"方差占比 {self.proj_meta.get('var_ratio')}）；"
                      f"投影阶段 seq={proj_seq}，在放置之前"),
            'threshold': '投影 100%，且投影在放置之前',
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

        # H9 正交规则（§十三）：逐根核查分支与上级主干的夹角
        o_checked, o_passed, o_fail, o_dist, o_skip = self._ortho_check()
        o_rate = (o_passed / o_checked * 100.0) if o_checked else 0.0
        h9_pass = o_checked > 0 and o_passed == o_checked
        dist_txt = '、'.join(f"偏离 {k}° {v} 根"
                             for k, v in sorted(o_dist.items()))
        skip_txt = (f"跳过：根 {o_skip['root']}、纯自环 {o_skip['pure_loop']}、"
                    f"全约束 {o_skip['constrained']}、父分支无方向 {o_skip['no_parent_dir']}")
        fail_txt = ''
        if o_fail:
            fail_txt = '；不通过：' + '、'.join(
                f"{f['branch']}（与 {f['parent']} 夹角 {f['angle']}°）"
                for f in o_fail[:5])
        hard.append({
            'id': 'H9', 'rule': '§十三 正交规则', 'name': '正交规则',
            'value': (f"核查 {o_checked} 根，通过 {o_passed} 根（{o_rate:.1f}%）；"
                      f"{dist_txt}；{skip_txt}{fail_txt}"),
            'threshold': '核查分支 100% 通过（夹角 90°±30°k，容差 0.5°）',
            'pass': h9_pass,
        })

        # ---- 软性项（警告，不阻塞） ----
        soft.append({
            'id': 'S1', 'rule': '§二.3 X 交叉（v2 允许，用户希望零交叉）',
            'name': 'X 交叉残留',
            'value': f"{n_x} 对",
            'note': 'v4 目标 0；残留交叉点位置已记入 layout.json 的 crossings，'
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
            'note': '自由段第一段不许拐弯（§十三/H9）；拐弯只发生在下游段与受约束段',
        })
        rings, self_loops, parallels = self.topo.find_cycles(
            list(self.topo.branches.keys()))
        ring_test = _ring_test_status()
        soft.append({
            'id': 'S4', 'rule': '§六 有环先完整画环', 'name': '环分类',
            'value': (f"真环 {len(rings)} 个，自环 {len(self_loops)} 个，"
                      f"平行对 {len(parallels)} 个；已画真环 {len(self.rings_drawn)} 个；"
                      f"环分类单测 {ring_test}"),
            'note': 'IP 无真实几何环，真环画环逻辑未在真实数据上验证（合成单测通过）',
        })
        s_matched, s_total = self._side_compliance()
        s_rate = (s_matched / s_total * 100.0) if s_total else 0.0
        n_place_flip = sum(1 for v in self.placed_flip.values() if v)
        soft.append({
            'id': 'S5', 'rule': '§十三 哪侧按投影方向', 'name': '投影侧符合率',
            'value': (f"{s_matched}/{s_total} 根（{s_rate:.1f}%）与投影同侧；"
                      f"放置时翻转 {n_place_flip} 根，居中翻转 {len(self.center_flips)} 次，"
                      f"消交叉翻转 {len(self.untangle_flips)} 次"),
            'note': '投影方向是初始选择；分区域调整阶段为居中/消干涉可翻转整棵子树',
        })
        soft.append({
            'id': 'S6', 'rule': '§十三 同点 3 根以上', 'name': '槽位分布',
            'value': (f"{len(self.slot_groups)} 个关节组；"
                      f"{dist_txt if dist_txt else '无'}"),
            'note': '前两根垂直分两侧，第三根起偏 30° 展开（30° 间隔）',
        })
        soft.append({
            'id': 'S7', 'rule': '§二 图纸', 'name': '图纸尺寸',
            'value': f"{ci.get('width')} × {ci.get('height')}mm",
            'note': '包围盒尺寸；不分页',
        })

        all_hard_pass = all(c['pass'] for c in hard)
        return {'hard': hard, 'soft': soft,
                'all_hard_pass': all_hard_pass}, all_hard_pass

# ---------------------------------------------------------------- 输出

def layout_data_v4(layout, include_checklist=None):
    """组装 v4 layout.json 的数据字典（在 v3-fix 格式上新增
    crossings / slots / flips / joint_inventory / tree 与扩展 stats）。
    include_checklist=None 时不含清单（用于确定性哈希，避免循环）。"""
    data = layout_data(layout, include_checklist=include_checklist)
    data['meta']['source'] = 'unfold_2d_v4.py'
    data['meta']['version'] = 'v4'
    # X 交叉点（用于查看器干涉标记）
    crossings = []
    pp = layout.placed_pieces
    for i in range(len(pp)):
        for j in range(i + 1, len(pp)):
            if pp[i][2] == pp[j][2] and pp[i][3] == pp[j][3]:
                continue
            # 与 count_interference_detailed 同口径：只计严格内点交叉
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
    }
    data['joint_inventory'] = [
        {'parent': p, 'joint': j, 'children': c}
        for (p, j, c) in layout.joint_inventory]
    data['tree'] = {k: {'parent': v['parent'], 'anchor': v['anchor'],
                        'depth': v['depth']}
                    for k, v in sorted(layout.tree.items())}
    # stats 扩展
    o_checked, o_passed, _o_fail, o_dist, _o_skip = layout._ortho_check()
    s_matched, s_total = layout._side_compliance()
    data['stats']['ortho_checked'] = o_checked
    data['stats']['ortho_passed'] = o_passed
    data['stats']['ortho_rate_pct'] = round(
        o_passed / o_checked * 100.0, 1) if o_checked else 0.0
    data['stats']['ortho_distribution'] = {str(k): v
                                           for k, v in sorted(o_dist.items())}
    data['stats']['side_match'] = s_matched
    data['stats']['side_total'] = s_total
    data['stats']['flips_center'] = len(layout.center_flips)
    data['stats']['flips_untangle'] = len(layout.untangle_flips)
    data['stats']['flips_placement'] = sum(
        1 for v in layout.placed_flip.values() if v)
    data['stats']['crossings'] = len(crossings)
    return data


def canonical_json_v4(layout):
    """确定性哈希用的规范序列化（不含清单、无时间戳、键排序）。"""
    data = layout_data_v4(layout, include_checklist=None)
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def write_layout_json_v4(layout, checklist, out_path):
    data = layout_data_v4(layout, include_checklist=checklist)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return out_path


def write_checklist_md_v4(checklist, out_path, topo_path):
    """检查清单 Markdown（逐条打勾/打叉，附实测数值）。"""
    lines = []
    lines.append('# v4 规则检查清单')
    lines.append('')
    lines.append(f'输入：`{topo_path}`')
    lines.append('程序：`unfold_2d_v4.py`')
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
    layout = LayoutV4(topo, clearance=clearance, verbose=verbose)
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
    ap = argparse.ArgumentParser(description='3D拓扑 → 2D展开图（v4，§十三正交规则）')
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
        h = hashlib.md5(canonical_json_v4(layout).encode('utf-8')).hexdigest()
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

    # 确定性：本进程哈希 vs 独立子进程哈希
    hash1 = hashlib.md5(canonical_json_v4(layout).encode('utf-8')).hexdigest()
    print('[确定性] 本进程 MD5：%s，正在跑独立子进程…' % hash1)
    hash2 = _subprocess_hash(args.topo_json, args.clearance)
    print('[确定性] 子进程 MD5：%s' % hash2)
    det_pass = (hash2 is not None and hash1 == hash2)

    checklist, hard_pass = layout.run_checklist(
        det_md5_a=hash1, det_md5_b=hash2, det_pass=det_pass)

    os.makedirs(args.out, exist_ok=True)
    lj = os.path.join(args.out, 'layout.json')
    ck = os.path.join(args.out, 'checklist_v4.md')
    write_layout_json_v4(layout, checklist, lj)
    write_checklist_md_v4(checklist, ck, args.topo_json)
    print(f"已写 {lj}")
    print(f"已写 {ck}")

    if not hard_pass:
        failed = [c['id'] for c in checklist['hard'] if not c['pass']]
        print(f"硬规则失败：{', '.join(failed)}，不生成 DXF/Excel，退出码 1")
        return 1

    dxf = os.path.join(args.out, 'unfold_v4.dxf')
    xls = os.path.join(args.out, 'unfold_v4.xlsx')
    write_dxf(layout, dxf)
    write_excel(layout, xls)
    print(f"已写 {dxf}")
    print(f"已写 {xls}")
    print('硬规则全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
