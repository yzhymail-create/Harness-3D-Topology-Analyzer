#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3D拓扑 → 2D展开图（v3 修正版，unfold_2d_v3_fix.py）

修复 2026-11-16 第一版（unfold_2d_v3.py）的三处违规（用户看截图后指出）：
1. §五 主干没放中间：第一版只把最长分支画成水平，落在图最右边。
   本版：布局按投影方向展开（投影本身主干近居中），完成后校验主干 y 与
   图纸中心 y 的偏差（≤5% 图纸高度），不合格则硬失败，不出图。
2. §四 没做投影：第一版是构造式贪心直接摆。
   本版：两步流程——① PCA 投影到最佳拟合平面得初始布局（节点 xyz → 2D，
   主干轴旋转到水平）；② 按 v3 规则分区域调整：主干拉直水平居中、分支按
   投影方向（吸附到 30° 网格）散开、干涉拐弯。初始布局与最终布局都存进
   layout.json（projection / branches）。
   分区域调整含垂直平衡：纯投影布局的主干居中偏差若超 3.5%，对非主干挂接
   分支的投影方向角加 tilt·cosθ 倾斜（近水平分支倾斜最多、垂直分支不动，
   主干挂接分支 §八垂直始终不加），割线法迭代至居中；tilt 值记入
   layout.json meta 与清单 S7。
3. §八 边找边画：第一版一根根边找分支点边画。
   本版：layout_component 开始时先清点主干上所有分支点（按弧长从左到右排序，
   附每点挂接分支），记入阶段日志，之后再逐个画分支。

约束机制（用户原问"怎么约束你随便犯错"）：
- 每条 v3 硬规则对应一个自动检查函数，运行结束输出 checklist_v3.md，
  逐条打勾/打叉并附实测数值。
- 硬规则检查失败时程序退出码非 0，且不生成 DXF/Excel（查看器也不生成，
  由调用方根据退出码决定）。
- 软性项（X 交叉残留数、CLEARANCE 暂定 5mm 等）记为警告，不阻塞。

用法：
  python3 unfold_2d_v3_fix.py topology.json -o out_dir [--clearance 5]
输出：unfold_v3.dxf / unfold_v3.xlsx / layout.json / checklist_v3.md
  （硬检查失败时只写 layout.json + checklist_v3.md，退出码 1）
"""

import json, math, os, sys, argparse, hashlib, subprocess
from collections import defaultdict, deque

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ezdxf 兜底：本机系统 Python 未装 ezdxf 时，v1 环境把它放在
# ~/workspace/.pylibs；仅当 import 失败时才把该目录加入 sys.path。
try:
    import ezdxf  # noqa: F401
except ImportError:
    _pylibs = os.path.expanduser('~/workspace/.pylibs')
    if os.path.isdir(os.path.join(_pylibs, 'ezdxf')):
        sys.path.insert(0, _pylibs)
from unfold_2d_v3 import (
    Topo, Layout, write_dxf, write_excel,
    seg_proper_intersect, seg_collinear_overlap, seg_seg_dist, pt_eq,
    dist, angle_of, unit_from_angle, add_pt, CLEARANCE_DEFAULT,
)

# ---- 检查阈值（写死在代码里，改阈值要改代码 + 改需求说明） ----
TRUNK_CENTER_TOL = 0.05    # H1 主干居中：偏差 ≤ 5% 图纸高度
TRUNK_CENTER_TARGET = 0.035  # 平衡迭代目标：≤ 3.5%（留裕量）
TRUNK_ANGLE_TOL = 0.5      # H2 主干水平：与水平夹角 ≤ 0.5°
LEN_ERR_TOL = 0.5          # H3 长度 1:1：最大误差 ≤ 0.5mm
PROJ_DIR_TOL_DEG = 30.0    # H8 投影方向符合：偏差 ≤ 30°
PROJ_DIR_MIN_FRAC = 0.60   # H8 至少 60% 分支按投影方向放置
PROJ_MIN_LEN = 20.0        # 主干投影长度 < 20mm 时改用 XY 平面
ANGLE_GRID = 30.0          # 方向吸附网格（度，与 §八 30° 间隔一致）
TILT_SENSITIVITY = 17.0   # 倾斜灵敏度估计：约 17mm/度（仅首轮猜测，割线法自修正）
TILT_MAX = 30.0           # 倾斜角限幅（度），超出则硬失败不硬拗
TILT_MAX_ATTEMPTS = 5     # 平衡迭代最多轮数

# ---------------------------------------------------------------- 投影

def pca_project(topo):
    """PCA 投影到最佳拟合平面，主干轴旋转到水平。
    返回 (proj, meta)：proj 为 {node: (u, v)}，meta 含平面/方差占比/主干投影长度。"""
    codes = sorted(topo.nodes.keys())
    xyz = np.array([topo.nodes[c]['xyz'] for c in codes], dtype=float)
    if np.isnan(xyz).any():
        raise ValueError('节点 xyz 含空值，无法投影')
    cen = xyz.mean(axis=0)
    X = xyz - cen
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    var = (S**2) / (S**2).sum()
    proj2 = X @ Vt[:2].T
    P = {c: proj2[i] for i, c in enumerate(codes)}
    plane = 'PCA最佳拟合平面'
    var_ratio = [round(float(v), 3) for v in var]
    # 主干（最长分支，长度相同取编号最小者，保证确定性）
    trunk = sorted(topo.branches,
                   key=lambda k: (-topo.branches[k]['length'], k))[0]
    b = topo.branches[trunk]
    n0, n1 = b['node0'], b['node1']
    d = P[n1] - P[n0]
    L = float(np.linalg.norm(d))
    if L < PROJ_MIN_LEN:
        # 主干在 PCA 平面内投影太短（主干近垂直于平面），改用 XY 平面
        P = {c: np.array([topo.nodes[c]['xyz'][0],
                          topo.nodes[c]['xyz'][1]], dtype=float)
             for c in codes}
        d = P[n1] - P[n0]
        L = float(np.linalg.norm(d))
        plane = 'XY平面（PCA主干投影过短，改用XY）'
        var_ratio = None
    ang = math.degrees(math.atan2(d[1], d[0]))
    th = math.radians(-ang)
    R = np.array([[math.cos(th), -math.sin(th)],
                  [math.sin(th), math.cos(th)]])
    Q = {c: R @ p for c, p in P.items()}
    # 平移到主干起点为原点（只为可读性；方向角不受平移影响）
    o = Q[n0].copy()
    Q = {c: (q - o) for c, q in Q.items()}
    meta = {
        'plane': plane,
        'var_ratio': var_ratio,
        'trunk': trunk,
        'trunk_proj_len': round(L, 1),
        'trunk_3d_len': round(b['length'], 1),
        'trunk_angle_before_rot': round(ang, 1),
    }
    proj = {c: (round(float(q[0]), 2), round(float(q[1]), 2))
            for c, q in Q.items()}
    return proj, meta

# ---------------------------------------------------------------- 干涉分类计数

def count_interference_detailed(layout):
    """残留干涉分类计数：(X交叉, 间距<clearance, 共线重叠)。
    与 make_viewer.py 同逻辑：共享端点的两段只计共线重叠；自环三角不计间距。"""
    pp = layout.placed_pieces
    n_x = n_near = n_ov = 0
    for i in range(len(pp)):
        for j in range(i + 1, len(pp)):
            if pp[i][2] == pp[j][2] and pp[i][3] == pp[j][3]:
                continue  # 同一段的子段
            a1, a2, b1, b2 = pp[i][0], pp[i][1], pp[j][0], pp[j][1]
            shared = (pt_eq(a1, b1) or pt_eq(a1, b2)
                      or pt_eq(a2, b1) or pt_eq(a2, b2))
            if seg_proper_intersect(a1, a2, b1, b2):
                n_x += 1
            elif seg_collinear_overlap(a1, a2, b1, b2):
                n_ov += 1
            elif (not shared and not (pp[i][4] or pp[j][4])
                    and seg_seg_dist(a1, a2, b1, b2) < layout.clearance):
                n_near += 1
    return n_x, n_near, n_ov

# ---------------------------------------------------------------- 布局引擎（修正版）

class LayoutFix(Layout):
    """v3 修正版布局：投影引导 + 主干清点 + 检查清单。
    复用 unfold_2d_v3.Layout 的几何/环/自环/平行对/输出机械，
    只改：角度候选来源（投影方向优先）、阶段顺序（投影→清点→放置）、
    以及新增居中测量与清单检查。"""

    def __init__(self, topo, clearance=CLEARANCE_DEFAULT, verbose=True,
                 tilt=0.0):
        super().__init__(topo, clearance)
        self.verbose = verbose
        # 垂直倾斜 tilt（度）：投影方向角 θ 改为 θ + tilt·cosθ，用于平衡主干居中。
        # cos 加权使近水平分支倾斜最多、垂直分支几乎不动（Body.113 天然不受影响）；
        # tilt=0 表示纯投影方向。主干挂接分支（§八垂直）仍显式排除。
        self.tilt = tilt
        self.proj = {}
        self.proj_meta = {}
        self.phase_log = []       # [(seq, phase, msg)] 按执行顺序
        self.trunk_key = None     # 全局最长分支（主干）
        self.trunk_inventory = [] # [(joint, x_along, [branch...])]
        self._trunk_attached = set()  # 直接挂在主干上的分支（§八，不加倾斜）
        self.proj_usage = {}      # branch -> {proj_dir, chosen_dir, dev}
        self.center_info = {}
        self._seq = 0
        self._placed_logged = False

    def log_phase(self, phase, msg):
        """阶段日志：记入 phase_log（供清单 H7 查顺序），verbose 时打印。"""
        self._seq += 1
        self.phase_log.append((self._seq, phase, msg))
        if self.verbose:
            print(f"[{phase}] {msg}")

    # ---- 阶段 1：投影 ----
    def run_projection(self):
        self.proj, self.proj_meta = pca_project(self.topo)
        self.trunk_key = self.proj_meta['trunk']
        # 主干挂接分支（§八垂直规则适用，不加垂直偏置）
        trunk_nodes = set(self._joints(self.trunk_key))
        for j in trunk_nodes:
            for k in self.topo.node_branches[j]:
                if k != self.trunk_key:
                    self._trunk_attached.add(k)
        n = len(self.proj)
        self.log_phase('投影',
            f"平面={self.proj_meta['plane']}，方差占比="
            f"{self.proj_meta['var_ratio']}，主干 {self.trunk_key} 投影长 "
            f"{self.proj_meta['trunk_proj_len']}mm（3D "
            f"{self.proj_meta['trunk_3d_len']}mm），节点 {n}/"
            f"{len(self.topo.nodes)} 已投影，垂直倾斜 tilt={self.tilt:.2f}°，"
            f"主干挂接分支（不加倾斜）：{sorted(self._trunk_attached)}")

    def _apply_tilt(self, theta_deg):
        """垂直倾斜：θ' = θ + tilt·cosθ。近水平分支倾斜最多（cos≈±1），
        垂直分支几乎不动（cos≈0）；单根改变量天然 ≤ |tilt|。"""
        return (theta_deg + self.tilt * math.cos(math.radians(theta_deg))) % 360.0

    def proj_direction(self, anchor, far):
        """从 anchor 节点指向 far 节点的投影方向角（度，旋转后帧，
        主干方向为 0°）；投影距离 < 1mm 时方向无意义，返回 None。"""
        a = self.proj.get(anchor)
        b = self.proj.get(far)
        if a is None or b is None:
            return None
        dx, dy = b[0] - a[0], b[1] - a[1]
        if math.hypot(dx, dy) < 1.0:
            return None
        return math.degrees(math.atan2(dy, dx))

    # ---- 阶段 2：主干分支点清点（§八） ----
    def inventory_trunk(self, comp_keys):
        """清点本分量主干上的所有分支点（按弧长从左到右排序），打日志。
        必须在任何分支放置之前执行（由 layout_component 保证顺序）。"""
        comp = set(comp_keys)
        trunk = sorted(comp_keys,
                       key=lambda k: (-self.topo.branches[k]['length'], k))[0]
        b = self.topo.branches[trunk]
        joints = self._joints(trunk)
        cum = [0.0]
        for pc in b['pieces']:
            cum.append(cum[-1] + pc['length'])
        inv = []
        for idx, j in enumerate(joints):
            attached = sorted(k for k in self.topo.node_branches[j]
                              if k != trunk and k in comp)
            inv.append((j, round(cum[idx], 1), attached))
        if trunk == self.trunk_key:
            self.trunk_inventory = inv
        detail = '；'.join(
            f"{j}@x={x}挂接{len(a)}根{a}" for j, x, a in inv)
        self.log_phase('清点',
            f"主干 {trunk}（{b['length']:.1f}mm）：{len(joints)} 个关节——{detail}")
        return trunk, inv

    # ---- 角度候选：投影方向优先，§八扇形角补充 ----
    def _run_angle_options(self, key, anchor_idx, direction):
        """某自由延伸段的候选角度（存入 run_angles 的值）。
        注意 run_angles 存的是 +1 方向角，-1 延伸段实际方向 = 存角 + 180°，
        所以 -1 段的候选存角 = 期望实际方向 + 180°。
        返回 (opts, proj_dir)：opts 为去重后的候选存角列表（投影优先），
        proj_dir 为本段投影方向角（度）或 None。"""
        joints = self._joints(key)
        anchor = joints[anchor_idx]
        far = joints[len(joints) - 1] if direction > 0 else joints[0]
        pd = self.proj_direction(anchor, far)
        # 垂直倾斜（主干挂接分支除外，§八垂直不动）
        if pd is not None and self.tilt != 0.0 \
                and key not in self._trunk_attached:
            pd = self._apply_tilt(pd)
        opts = []
        seen = set()
        def add(a):
            a = round(a % 360.0, 6)
            if a not in seen:
                seen.add(a)
                opts.append(a)
        if pd is not None:
            want = pd if direction > 0 else (pd + 180.0) % 360.0
            base = round(want / ANGLE_GRID) * ANGLE_GRID
            for d in (0, 30, -30, 60, -60, 90, -90, 180):
                add(base + d)
        fan = self._base_angle(anchor)
        for d in (0, 180, 30, -30, 60, -60):
            add(fan + d)
        return opts, pd

    def place_branch_best(self, key):
        """覆盖父类：候选角度按投影方向生成，评分加入方向偏差。
        评分元组 (干涉, 方向偏差(30°单位), 警告数, 拐弯总量)：
        干涉优先，方向其次——宁可拐弯/微偏，也不压着画。"""
        runs = self._free_runs(key)
        joints = self._joints(key)
        if not runs:
            res = self.layout_branch(key, {})
            if res is not None:
                self._commit(key, res)
                self._record_proj_usage(key, res)
                return True
            return False
        run_opts = []
        for (j, d) in runs:
            opts, pd = self._run_angle_options(key, j, d)
            run_opts.append((j, d, opts, pd))

        def dev_of(stored, d, pd):
            if pd is None:
                return 0
            actual = stored if d > 0 else (stored + 180.0) % 360.0
            diff = abs((actual - pd + 180.0) % 360.0 - 180.0)
            return int(round(diff / ANGLE_GRID))

        same_anchor = len(runs) == 2 and runs[0][0] == runs[1][0]
        combos = []  # (angles_dict, dir_dev)
        if same_anchor or len(runs) == 1:
            j, d, opts, pd = run_opts[0]
            for a0 in opts:
                combos.append(({j: a0}, dev_of(a0, d, pd)))
        else:
            (j0, d0, o0, p0), (j1, d1, o1, p1) = run_opts
            for a0 in o0[:4]:
                for a1 in o1[:4]:
                    combos.append(({j0: a0, j1: a1},
                                   dev_of(a0, d0, p0) + dev_of(a1, d1, p1)))
        # 按方向偏差排序：投影最优先，首个干净候选即最忠于投影的干净候选
        combos.sort(key=lambda c: c[1])
        best, best_score = None, None
        best_angles = None

        def score_of(res, dd):
            return (res['n_bad'], dd, len(res['warnings']),
                    sum(abs(b['delta']) for b in res['bends']
                        if isinstance(b['delta'], (int, float))))
        for angles, dd in combos:
            res = self.layout_branch(key, angles)
            if res is None:
                continue
            sc = score_of(res, dd)
            if best_score is None or sc < best_score:
                best, best_score, best_angles = res, sc, angles
                if sc[0] == 0 and sc[1] == 0 and sc[2] == 0:
                    break
        if best is None:
            return False
        if best_score[0] > 0:
            self.warnings.append(f"{key} 所有候选角度均有干涉，取最少干涉方案")
        self._commit(key, best)
        self._record_proj_usage(key, best)
        return True

    def _record_proj_usage(self, key, res):
        """记录本分支最终整体方向与投影方向的偏差（供清单 H8 统计）。"""
        joints = self._joints(key)
        n = len(joints) - 1
        p0 = res['joint_pos'].get(0)
        p1 = res['joint_pos'].get(n)
        pd = self.proj_direction(joints[0], joints[-1])
        dev = None
        chosen = None
        if p0 is not None and p1 is not None and not pt_eq(p0, p1):
            chosen = angle_of(p0, p1)
            if pd is not None:
                dev = abs((chosen - pd + 180.0) % 360.0 - 180.0)
        self.proj_usage[key] = {
            'proj_dir': (round(pd, 1) if pd is not None else None),
            'chosen_dir': (round(chosen, 1) if chosen is not None else None),
            'dev': (round(dev, 1) if dev is not None else None),
        }

    def _commit(self, key, res):
        if not self._placed_logged:
            self._placed_logged = True
            self.log_phase('放置', f"开始放置分支，首根 {key}")
        super()._commit(key, res)

    # ---- 阶段顺序：清点 → 放置 ----
    def layout_component(self, comp_keys, origin):
        self.inventory_trunk(comp_keys)
        return super().layout_component(comp_keys, origin)

    def run(self):
        self.log_phase('开始',
            f"分支 {len(self.topo.branches)} / 节点 {len(self.topo.nodes)} "
            f"/ 线段 {len(self.topo.segs)}")
        self.run_projection()
        super().run()
        self.recenter_bbox()
        self.center_info = self.measure_trunk_center()
        self.log_phase('居中',
            f"主干 {self.center_info.get('trunk')} y={self.center_info.get('trunk_y')}mm，"
            f"图纸中心 y={self.center_info.get('center_y')}mm，偏差 "
            f"{self.center_info.get('dev_mm')}mm（{self.center_info.get('dev_pct')}%）")
        return self

    # ---- 平移与居中测量 ----
    def translate(self, dx, dy):
        """整体平移所有已放置几何（长度/角度/干涉不变）。"""
        for code in self.node_pos:
            x, y = self.node_pos[code]
            self.node_pos[code] = (x + dx, y + dy)
        for res in self.placed.values():
            res['points'] = [(x + dx, y + dy) for (x, y) in res['points']]
            res['seg_pts'] = {sg: [(x + dx, y + dy) for (x, y) in pts]
                              for sg, pts in res['seg_pts'].items()}
            res['pieces'] = {sg: ((p1[0] + dx, p1[1] + dy),
                                  (p2[0] + dx, p2[1] + dy))
                             for sg, (p1, p2) in res['pieces'].items()}
            res['joint_pos'] = {i: (x + dx, y + dy)
                                for i, (x, y) in res['joint_pos'].items()}
        self.piece_pos = {sg: ((p1[0] + dx, p1[1] + dy),
                               (p2[0] + dx, p2[1] + dy))
                          for sg, (p1, p2) in self.piece_pos.items()}
        self.placed_pieces = [((p1[0] + dx, p1[1] + dy),
                               (p2[0] + dx, p2[1] + dy), b, s, sd)
                              for (p1, p2, b, s, sd) in self.placed_pieces]

    def recenter_bbox(self):
        """把图纸包围盒中心平移到原点（只为 DXF 坐标干净；
        平移不改变主干相对中心的位置，居中靠布局本身保证）。"""
        xmin, ymin, xmax, ymax = self.bbox()
        dx = -(xmin + xmax) / 2.0
        dy = -(ymin + ymax) / 2.0
        self.translate(dx, dy)
        return {'dx': round(dx, 2), 'dy': round(dy, 2)}

    def measure_trunk_center(self):
        """主干居中测量：主干 y 与图纸中心 y 的偏差（平移不变量）。"""
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
        dev = abs(trunk_y - cy)
        return {
            'ok': True,
            'trunk': self.trunk_key,
            'trunk_y': round(trunk_y, 2),
            'trunk_x_mid': round(trunk_x_mid, 2),
            'trunk_angle_deg': round(ang, 2),
            'trunk_angle_from_horizontal_deg': round(ang_from_h, 2),
            'center_y': round(cy, 2),
            'center_x': round(cx, 2),
            'dev_mm': round(dev, 2),
            'dev_pct': round(dev / h * 100.0, 2) if h > 0 else 0.0,
            'height': round(h, 1),
            'width': round(w, 1),
            'tol_pct': TRUNK_CENTER_TOL * 100.0,
        }

    # ---- 规则检查清单（约束机制核心） ----
    def run_checklist(self, det_md5_a=None, det_md5_b=None, det_pass=None):
        """执行 v3 规则检查清单。返回 (checklist, all_hard_pass)。
        checklist['hard'] 每条：{id, rule, name, value, threshold, pass}；
        checklist['soft'] 每条：{id, rule, name, value, note}（警告，不阻塞）。"""
        st = self.validate()
        n_x, n_near, n_ov = count_interference_detailed(self)
        ci = self.center_info
        hard = []
        soft = []

        # H1 主干垂直居中（§五）
        h1_pass = bool(ci.get('ok')) and ci['dev_pct'] <= ci['tol_pct']
        hard.append({
            'id': 'H1', 'rule': '§五 主干水平画在中间', 'name': '主干垂直居中',
            'value': (f"主干 y={ci.get('trunk_y')}mm，图纸中心 y={ci.get('center_y')}mm，"
                      f"偏差 {ci.get('dev_mm')}mm（{ci.get('dev_pct')}%），"
                      f"图纸高 {ci.get('height')}mm"),
            'threshold': f"偏差 ≤ {TRUNK_CENTER_TOL * 100:.0f}% 图纸高度",
            'pass': h1_pass,
        })

        # H2 主干水平（§五）
        h2_pass = bool(ci.get('ok')) and \
            ci['trunk_angle_from_horizontal_deg'] <= TRUNK_ANGLE_TOL
        hard.append({
            'id': 'H2', 'rule': '§五 主干水平画在中间', 'name': '主干水平',
            'value': f"主干与水平夹角 {ci.get('trunk_angle_from_horizontal_deg')}°",
            'threshold': f"≤ {TRUNK_ANGLE_TOL}°",
            'pass': h2_pass,
        })

        # H3 长度 1:1（§二.1）
        max_err = st['max_len_err_mm']
        worst = ''
        if st['len_errs']:
            w = sorted(st['len_errs'],
                       key=lambda t: (-abs(t[3]), t[0]))[0]
            worst = (f"（最大误差分支 {w[0]}，3D {w[1]:.1f}mm → "
                     f"2D {w[2]:.1f}mm，误差 {w[3]:+.2f}mm）")
        h3_pass = max_err <= LEN_ERR_TOL
        hard.append({
            'id': 'H3', 'rule': '§二.1 长度 1:1', 'name': '长度 1:1',
            'value': f"2D 长度与 3D 弧长最大误差 {max_err:.2f}mm{worst}",
            'threshold': f"≤ {LEN_ERR_TOL}mm",
            'pass': h3_pass,
        })

        # H4 拓扑不变（§二.2）：每根分支的关节位置与 node_pos 一致
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
        h4_pass = not bad
        hard.append({
            'id': 'H4', 'rule': '§二.2 拓扑不变', 'name': '拓扑不变',
            'value': f"核对 {checked} 个分支-关节端点，"
                     + (f"{len(bad)} 处不一致：{bad[:5]}" if bad else "全部与 3D 节点一致"),
            'threshold': '0 处不一致',
            'pass': h4_pass,
        })

        # H5 零压着画（§二.3）
        h5_pass = n_ov == 0
        hard.append({
            'id': 'H5', 'rule': '§二.3 不重叠（压着画）', 'name': '零压着画',
            'value': f"共线重叠 {n_ov} 对",
            'threshold': '0 对',
            'pass': h5_pass,
        })

        # H6 全画出
        h6_pass = (st['branches_placed'] == st['branches_total'] and
                   st['nodes_placed'] == st['nodes_total'])
        hard.append({
            'id': 'H6', 'rule': '§二 完整性', 'name': '全画出',
            'value': f"分支 {st['branches_placed']}/{st['branches_total']}，"
                     f"节点 {st['nodes_placed']}/{st['nodes_total']}",
            'threshold': '全部画出',
            'pass': h6_pass,
        })

        # H7 分支点先找齐再画（§八）：清点阶段在放置阶段之前，且清点完整
        inv_seq = None
        place_seq = None
        for (s, ph, _m) in self.phase_log:
            if ph == '清点' and inv_seq is None:
                inv_seq = s
            if ph == '放置' and place_seq is None:
                place_seq = s
        order_ok = (inv_seq is not None and place_seq is not None
                    and inv_seq < place_seq)
        # 清点完整性：主干每个关节都在清点里，每关节挂接分支与拓扑一致
        inv_complete = False
        inv_detail = ''
        if self.trunk_key in self.topo.branches:
            joints = self._joints(self.trunk_key)
            inv_map = {j: a for (j, _x, a) in self.trunk_inventory}
            comp = set(self.topo.branches.keys())
            ok_all = len(inv_map) == len(joints)
            for j in joints:
                expect = sorted(k for k in self.topo.node_branches[j]
                                if k != self.trunk_key)
                if inv_map.get(j) != expect:
                    ok_all = False
                    break
            inv_complete = ok_all
            total_attached = sum(len(a) for (_j, _x, a) in self.trunk_inventory)
            inv_detail = (f"主干 {self.trunk_key} 共 {len(joints)} 个关节、"
                          f"挂接 {total_attached} 根分支已清点；"
                          f"清点阶段 seq={inv_seq}，放置阶段 seq={place_seq}")
        h7_pass = order_ok and inv_complete
        hard.append({
            'id': 'H7', 'rule': '§八 先找齐分支点再画', 'name': '分支点先找齐再画',
            'value': inv_detail or '无清点记录',
            'threshold': '清点在放置之前，且清点完整',
            'pass': h7_pass,
        })

        # H8 投影步已执行（§四）：全部节点有投影坐标，且多数分支按投影方向放置
        n_proj = len(self.proj)
        n_nodes = len(self.topo.nodes)
        devs = [u['dev'] for u in self.proj_usage.values()
                if u['dev'] is not None]
        n_with = len(devs)
        n_ok = sum(1 for d in devs if d <= PROJ_DIR_TOL_DEG)
        frac = (n_ok / n_with) if n_with else 0.0
        n_30_60 = sum(1 for d in devs
                      if PROJ_DIR_TOL_DEG < d <= 60.0)
        n_gt60 = sum(1 for d in devs if d > 60.0)
        h8_pass = (n_proj == n_nodes and n_with > 0
                   and frac >= PROJ_DIR_MIN_FRAC)
        hard.append({
            'id': 'H8', 'rule': '§四 先投影再分区域调', 'name': '投影步已执行',
            'value': (f"投影节点 {n_proj}/{n_nodes}（{self.proj_meta.get('plane')}）；"
                      f"分支方向偏差≤30° {n_ok}/{n_with} 根（{frac * 100:.1f}%），"
                      f"30°~60° {n_30_60} 根，>60° {n_gt60} 根"),
            'threshold': f"投影 100%，且 ≥ {PROJ_DIR_MIN_FRAC * 100:.0f}% 分支偏差 ≤ 30°",
            'pass': h8_pass,
        })

        # H9 确定性（§二.5）：独立子进程跑出的布局与本进程一致
        h9_pass = bool(det_pass) and det_md5_a is not None \
            and det_md5_a == det_md5_b
        hard.append({
            'id': 'H9', 'rule': '§二.5 确定性', 'name': '确定性',
            'value': f"本进程 MD5 {det_md5_a}，独立子进程 MD5 {det_md5_b}",
            'threshold': '两次 MD5 一致',
            'pass': h9_pass,
        })

        # ---- 软性项（警告，不阻塞） ----
        soft.append({
            'id': 'S1', 'rule': '§二.3 X 交叉（v2 允许，用户希望零交叉）',
            'name': 'X 交叉残留',
            'value': f"{n_x} 对",
            'note': 'v2 规则允许 X 交叉；用户希望零交叉，彻底消除需换布局策略',
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
            'note': '在最后干净的点拐弯，拐到刚好避开',
        })
        # 真环：IP 无真环
        rings, self_loops, parallels = self.topo.find_cycles(
            list(self.topo.branches.keys()))
        soft.append({
            'id': 'S4', 'rule': '§六 有环先完整画环', 'name': '真环画环',
            'value': f"真环 {len(rings)} 个，自环 {len(self_loops)} 个，平行对 {len(parallels)} 个",
            'note': 'IP 无真实几何环，真环画环逻辑未在真实数据上验证',
        })
        # 主干水平位置说明
        soft.append({
            'id': 'S5', 'rule': '§五 主干位置', 'name': '主干水平位置',
            'value': (f"主干中点 x={ci.get('trunk_x_mid')}mm，图纸中心 x={ci.get('center_x')}mm"),
            'note': '主干是叶附枝（整棵树只挂在 CLP23 端），水平方向居左是拓扑事实；'
                    '规则只要求垂直居中',
        })
        soft.append({
            'id': 'S6', 'rule': '§四 投影', 'name': '投影平面',
            'value': f"{self.proj_meta.get('plane')}，方差占比 {self.proj_meta.get('var_ratio')}",
            'note': 'PCA 最佳拟合平面；主干投影长 '
                    f"{self.proj_meta.get('trunk_proj_len')}mm（3D "
                    f"{self.proj_meta.get('trunk_3d_len')}mm，缩短源于弯管端点距）",
        })
        soft.append({
            'id': 'S7', 'rule': '§五 主干居中（平衡调整）', 'name': '垂直倾斜 tilt',
            'value': f"tilt={self.tilt:.2f}°（主干挂接分支 {sorted(self._trunk_attached)} 不加倾斜）",
            'note': '分区域调整的一部分：纯投影布局主干偏离中心时，对非主干挂接分支的'
                    '投影方向角加 tilt·cosθ 倾斜（近水平分支倾斜最多、垂直分支不动），'
                    '割线法迭代至居中；tilt 值记入 layout.json meta',
        })

        all_hard_pass = all(c['pass'] for c in hard)
        return {'hard': hard, 'soft': soft,
                'all_hard_pass': all_hard_pass}, all_hard_pass

# ---------------------------------------------------------------- 输出

def layout_data(layout, include_checklist=None):
    """组装 layout.json 的数据字典（与 v1 格式兼容，新增 projection /
    trunk_inventory / phase_log / checklist 与扩展 stats）。
    include_checklist=None 时不含清单（用于确定性哈希，避免循环）。"""
    topo = layout.topo
    st = layout.validate()
    n_x, n_near, n_ov = count_interference_detailed(layout)
    st['residual_x_cross'] = n_x
    st['residual_near_lt_clearance'] = n_near
    st['residual_collinear_overlap'] = n_ov
    st['trunk_center'] = layout.center_info
    data = {
        'meta': {'source': 'unfold_2d_v3_fix.py',
                 'clearance_mm': layout.clearance,
                 'trunk': layout.trunk_key,
                 'tilt_deg': round(layout.tilt, 3)},
        'stats': st,
        'projection': {
            'meta': layout.proj_meta,
            'nodes': {c: list(p) for c, p in sorted(layout.proj.items())},
        },
        'trunk_inventory': [
            {'joint': j, 'x_along': x, 'branches': a}
            for (j, x, a) in layout.trunk_inventory],
        'phase_log': [{'seq': s, 'phase': p, 'msg': m}
                      for (s, p, m) in layout.phase_log],
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
        l2 = sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        data['branches'].append({
            'key': key, 'dia': round(b['dia'], 2),
            'len_3d': round(b['length'], 1), 'len_2d': round(l2, 1),
            'node0': b['node0'], 'node1': b['node1'],
            'points': [[round(x, 2), round(y, 2)] for (x, y) in pts],
            'pieces': [{'seg': sg, 'na': topo.segs[sg]['na'],
                        'nb': topo.segs[sg]['nb'],
                        'pts': [[round(x, 2), round(y, 2)] for (x, y) in p]}
                       for sg, p in res['seg_pts'].items()],
        })
    for code in sorted(layout.node_pos):
        nd = topo.nodes.get(code, {})
        x, y = layout.node_pos[code]
        data['nodes'].append({'code': code, 'type': nd.get('type', '?'),
                              'name_3d': nd.get('name_3d', ''),
                              'x': round(x, 2), 'y': round(y, 2)})
    if include_checklist is not None:
        data['checklist'] = include_checklist
    return data


def canonical_json(layout):
    """确定性哈希用的规范序列化（不含清单、无时间戳、键排序）。"""
    data = layout_data(layout, include_checklist=None)
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def write_layout_json_fix(layout, checklist, out_path):
    data = layout_data(layout, include_checklist=checklist)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return out_path


def write_checklist_md(checklist, out_path, topo_path):
    """检查清单 Markdown（逐条打勾/打叉，附实测数值）。"""
    lines = []
    lines.append('# v3 规则检查清单')
    lines.append('')
    lines.append(f'输入：`{topo_path}`')
    lines.append(f'程序：`unfold_2d_v3_fix.py`')
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

def build_layout(topo, clearance, verbose=True, tilt=0.0):
    layout = LayoutFix(topo, clearance=clearance, verbose=verbose,
                       tilt=tilt)
    layout.run()
    return layout


def _subprocess_hash(topo_path, clearance, tilt=0.0):
    """独立子进程（全新 PYTHONHASHSEED）跑布局并返回 MD5；
    失败时返回 None。"""
    try:
        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__), topo_path,
             '--hash-only', '--clearance', str(clearance),
             '--tilt', str(tilt)],
            capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return None
        h = r.stdout.strip().splitlines()
        return h[-1].strip() if h else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description='3D拓扑 → 2D展开图（v3 修正版）')
    ap.add_argument('topo_json')
    ap.add_argument('-o', '--out', default='.')
    ap.add_argument('--clearance', type=float, default=CLEARANCE_DEFAULT)
    ap.add_argument('--tilt', type=float, default=0.0,
                    help='垂直倾斜角（度，仅 --hash-only 子进程用；正常运行由平衡迭代自动定）')
    ap.add_argument('--hash-only', action='store_true',
                    help='仅输出布局 MD5（供确定性检查的子进程用）')
    args = ap.parse_args()

    topo = Topo(args.topo_json)

    if args.hash_only:
        # 哈希模式：只打印 MD5，不打印其他任何东西
        layout = build_layout(topo, args.clearance, verbose=False,
                              tilt=args.tilt)
        h = hashlib.md5(canonical_json(layout).encode('utf-8')).hexdigest()
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

    # 平衡迭代：tilt（度）用割线法求解主干偏差=0，最多 TILT_MAX_ATTEMPTS 轮，
    # 取偏差最小的一轮。首轮 tilt=0（纯投影）；主干挂接分支始终不加倾斜。
    tilt = 0.0
    best_layout = None
    best_dev = None
    history = []  # [(tilt, dev_signed_mm)]，dev>0 表示主干在中心上方
    for attempt in range(TILT_MAX_ATTEMPTS):
        layout = build_layout(topo, args.clearance, verbose=True,
                              tilt=tilt)
        ci = layout.center_info
        dev_pct = ci.get('dev_pct', 100.0)
        dev_signed = ci.get('trunk_y', 0.0) - ci.get('center_y', 0.0)
        print(f"[平衡] 第 {attempt + 1} 轮：tilt={tilt:.2f}°，"
              f"主干偏差 {dev_signed:+.1f}mm（{dev_pct}%）")
        history.append((tilt, dev_signed))
        if best_dev is None or dev_pct < best_dev:
            best_layout, best_dev = layout, dev_pct
        if dev_pct <= TRUNK_CENTER_TARGET * 100.0:
            break
        if len(history) == 1:
            # 首轮：用估计灵敏度猜下一轮（主干偏上 → tilt 为正，把树往上抬）
            tilt = tilt + dev_signed / TILT_SENSITIVITY
        else:
            (t0, d0), (t1, d1) = history[-2], history[-1]
            if abs(d1 - d0) < 1e-9:
                break
            tilt = t1 - d1 * (t1 - t0) / (d1 - d0)
        tilt = max(-TILT_MAX, min(TILT_MAX, tilt))
    layout = best_layout
    print(f"[平衡] 取偏差最小的一轮：tilt={layout.tilt:.2f}°，"
          f"主干偏差 {layout.center_info.get('dev_pct')}%")

    # 确定性：本进程哈希 vs 独立子进程哈希（同一 tilt）
    hash1 = hashlib.md5(canonical_json(layout).encode('utf-8')).hexdigest()
    print('[确定性] 本进程 MD5：%s，正在跑独立子进程…' % hash1)
    hash2 = _subprocess_hash(args.topo_json, args.clearance,
                             tilt=layout.tilt)
    print('[确定性] 子进程 MD5：%s' % hash2)
    det_pass = (hash2 is not None and hash1 == hash2)

    checklist, hard_pass = layout.run_checklist(
        det_md5_a=hash1, det_md5_b=hash2, det_pass=det_pass)

    os.makedirs(args.out, exist_ok=True)
    lj = os.path.join(args.out, 'layout.json')
    ck = os.path.join(args.out, 'checklist_v3.md')
    write_layout_json_fix(layout, checklist, lj)
    write_checklist_md(checklist, ck, args.topo_json)
    print(f"已写 {lj}")
    print(f"已写 {ck}")

    if not hard_pass:
        failed = [c['id'] for c in checklist['hard'] if not c['pass']]
        print(f"硬规则失败：{', '.join(failed)}，不生成 DXF/Excel，退出码 1")
        return 1

    dxf = os.path.join(args.out, 'unfold_v3.dxf')
    xls = os.path.join(args.out, 'unfold_v3.xlsx')
    write_dxf(layout, dxf)
    write_excel(layout, xls)
    print(f"已写 {dxf}")
    print(f"已写 {xls}")
    print('硬规则全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
