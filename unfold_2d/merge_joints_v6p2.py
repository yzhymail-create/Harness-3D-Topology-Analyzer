#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2D 展开 v6p2：过路点合并 + 自环段去掉 + DRC（2026-11-17 用户亲定规则，通用版）。

合并规则（2026-11-17 22:52 用户亲定，取代“只并 N”的旧理解）：
  判断标准不是 N 还是 BN，而是这个点连着几个不同的地方。只连两个地方
  的就是过路点，合并；连三个地方以上的，是真分支点，保留。
  合并只针对无实体的过路点（N/BN，type 为 joint/fork）；有实体的卡扣/
  连接器节点（点按要看实体名）不并，哪怕只有两通。
  IP 实测：17 个 N 全是两通；BN 里只有 BN01（4 段，两边 CLP03/CLP06）
  和 BN04（3 段，两边 CLP01/N04）是两通；一共并掉 19 个点。
  地板实测：66 个 N 全是两通 + 7 个 BN 两通，一共并掉 73 个点。

2026-11-19 用户令（取代上条合并规则）：过路点（joint/fork 两通）是
路由途经点，2D 图里必须保留作命名点，不再合并掉——路由按名字串段
（A→B、B→C）需要 B 这个点，没有实体也要有名有点的节点。不要为了图面
干净继续把路由途经点合并掉。
  - 过路点集照旧由 topology.json 程序算出（waypoint_nodes，供报告与
    隐藏平行配对用），但不再进 merged_set：merged_nodes 恒为空。
  - 走线改同根接续：同根管子的相邻段仍接成一条路径（一管一路径，与
    v6p1 一致），不同管子在过路点处不再接成一条。
  - 效果（地板）：节点 409→490（+81 个途经点：73 joint + 8 fork），
    路径 409→475（一管一路径）；LENGTH 端点解析率 83.5%→100%。
  - 8 个两通 fork 一并保留（与 joint 同为路由途经点，只留 joint 会
    剩 16 个 LENGTH 端点解析不了）；若用户只想留 joint，改
    KEEP_WAYPOINTS 下的 waypoint_nodes 过滤条件即可。

2026-11-19 22:15 用户纠正（废止上条保留点做法，§十六合并恢复执行）：
用户看新版仪表图投诉越做越差——Body.78/Body.92 中间 N15 无分支却留了
断点，还不如以前。定：3D 和 2D 不一样，3D 按 3D 的处理（N15 在
topology.json/pieces 里照旧存在，路由按 §二十四 端点命名串段照旧）；
转 2D 时做图面整洁优化，无分支的过路点在 2D 图面整合掉。KEEP_WAYPOINTS
默认改回 False；True 仅供回归对比，正常不用。

段级合并（不是分支级）：以线段（segment）为单位走线，过路点处的段按
配对原则接续——同根管子先配，剩下的一对配一起。
  - IP 的 BN01：画出的两段是 Body.159 的 SEG08+SEG09（同根，先配），仍为
    CLP03→CLP06 的画出线（113.3mm，几何不动）；藏着的 Body.46 SEG11 +
    Body.48 SEG10（剩下的一对）在数据里接成一条隐藏平行路径
    （CLP03→CLP06，109.7mm），在 Body.159 弹窗里合为一行。
  - IP 的 BN04 与 N04 成链：SEG40（Body.57）+ SEG39（Body.61）+ SEG01
    （Body.113）传递合并成 CLP01→CLP11 一条线（207.0mm）；Body.113
    的 SEG02 另成 CLP01→CLP23 一线（172.4mm，partial 标记）。Body.113
    是 IP 唯一被拆开的分支（其两段落在不同路径里）。

自环段 2D 不出图（2026-11-19 22:27 用户令，§二十七，废止 2026-11-17
小圆环符号做法）：自环段（na==nb）按段去掉，不画小圈、不画虚线引线、
不画线、不进 pieces、不计长度；整根管子只有一个自环段时整根去掉，
还有正常段时只去掉自环段、剩下段照旧画线，长度按剩下段的和。
topology.json 不动（自环段在 3D 数据里照旧存在）；掉落清单进布局
meta.dropped_loop_segments，整根去掉的分支另进 meta.dropped_loop_branches。
  IP：3 段（SEG21 Body.96 整根去；SEG12 Body.117 去一段剩 71.9mm；
  SEG32 Body.150 去一段剩 59.9mm）；地板：1 段（SEG434 多分支29.1-64X
  整根去，§十八 stub 短线头做法随之废止）。

不动的东西：topology.json（数据源真相）；v6p1 平行隐藏（折叠段继续
隐藏，数据在弹窗里）；几何点位不动（只重组折线、去掉自环段）。

硬核查（任一失败即退出码非 0，不写输出；全部由数据算出，不写死数值）：
  - 过路点集由 topology.json 程序算出（无实体节点中恰连 2 个地方）；
  - 每个过路点恰好触 2 条画出非自环段；
  - 每条路径恰好 2 个端点（过路点保留后，路径端点可以是过路点）；
  - 拼接点间隙 < 1e-6 mm；合并 len_2d 与各段和差 ≤0.11mm；
  - 全部管子全数可查（被拆开的分支逐个记入报告，不写死哪个；整根
    去掉的自环分支扣掉，另行列出）；
  - 非合并路径几何与 v6p1 逐点一致；全部路径 1:1 误差 ≤0.1mm（卡口，
    原只上报——§二十九 DRC，2026-11-19）；
  - §二十七闭环：掉落自环段数＝拓扑自环段数；去掉后任一路径不得
    node0==node1，布局里不得有 loop 条目。
  - §二十九 DRC（2026-11-19 用户令“我们自己的 DRC”：以前发现过的
    错误都要写成代码检查，不过不出图）：
    · 过路点闭环：从输出路径重算，无实体节点恰连 2 处即残留，必须 0；
    · 连通性保持：段级连通分量数输入＝输出；输出无孤立节点；
    · 全图硬检查（复用优化器 Checker，同一口径）：交叉 0、压着画 0；
      穿节点不得新增（输出 ≤ 输入；残留逐条列入报告，等用户定夺，
      清掉后卡口收紧为 0）；节点挨近只报告，不卡（残留是用户已接受的）。

用法：python3 merge_joints_v6p2.py <v6p1 layout.json> <topology.json> <outdir>
输出：<outdir>/layout.json、<outdir>/merge_report_v6p2.md
"""
import json
import math
import os
import sys
from collections import defaultdict

# DRC 全图硬检查复用优化器的 Checker（同一口径，不另写判定）。
from optimize_layout import Checker

JOINT_GAP_TOL_MM = 1e-6   # 拼接点间隙容差（实测均为 0.0）
LEN_SUM_TOL_MM = 0.11     # 合并 len_2d 与各段和的容差（含 0.1 舍入）
PIERCE_MM = 15.0          # 穿节点阈值（与优化器默认值一致，2026-11-18 用户定）
# 2026-11-19 22:15 用户纠正：§十六合并恢复执行，保留点做法废止。
# False 时恢复 2026-11-17 合并行为（默认，正常用）；True 时过路点
# 保留作路由命名点（仅供回归对比，正常不用）。
KEEP_WAYPOINTS = False
# LOOP_LABEL_DIST_PX 已删（2026-11-19 §二十七：小圆环符号废止，纯自环
# 路径不再存在，长度标签外放逻辑随之删除）

TOPO_DEFAULT = ('/home/hatch/workspace/harness_3d/pipeline_4step_rules/'
                'test_iph_fresh/topology.json')


def plen(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(pts, pts[1:]))


class _CheckLayout:
    """只给 Checker.full_check 用的最小布局：画出节点 + 路径折线。

    不复用优化器的 Layout 类——它要 spines（合并后布局不保证有），且
    其 branch_nodes 会把 pieces 里指着已合并过路点的 na/nb 也算进去，
    Checker 初始化时按这些编号查节点坐标会 KeyError。这里只认画出节点
    （pieces 的 na/nb 与节点表取交集）：已合并的点不是画出节点，不存在
    “管子穿它”的问题。口径与优化器一致（实测：keepwp 地板布局重算得
    交叉 0、压着画 0、穿节点 2 处，与优化器报告逐项一致）。
    """

    def __init__(self, data):
        self.nodes = {n['code']: (float(n['x']), float(n['y']))
                      for n in data['nodes']}
        self.branches = {
            b['key']: {'points': [(float(p[0]), float(p[1]))
                                  for p in b['points']],
                       'node0': b['node0'], 'node1': b['node1']}
            for b in data['branches']}
        self.branch_nodes = {}
        for b in data['branches']:
            touched = set()
            for pc in b.get('pieces', []):
                for c in (pc.get('na'), pc.get('nb')):
                    if c is not None and c in self.nodes:
                        touched.add(c)
            if not touched:  # 无 pieces 的分支（不应发生）：退回拓扑端点
                for c in (b.get('node0'), b.get('node1')):
                    if c is not None and c in self.nodes:
                        touched.add(c)
            self.branch_nodes[b['key']] = touched
        self.node_branches = {}
        for bk, ts in self.branch_nodes.items():
            for c in ts:
                self.node_branches.setdefault(c, set()).add(bk)

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


def _n_piece_components(piece_pairs):
    """段级连通分量数（按段端点 na/nb 并查集；自环段不连通任何两点）。"""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in piece_pairs:
        if a is None or b is None:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return len({find(x) for x in parent})


def main():
    src = sys.argv[1]
    topo_path = sys.argv[2] if len(sys.argv) > 3 else TOPO_DEFAULT
    outdir = sys.argv[3] if len(sys.argv) > 3 else sys.argv[2]
    d = json.load(open(src, encoding='utf-8'))
    topo = json.load(open(topo_path, encoding='utf-8'))
    branches, nodes = d['branches'], d['nodes']
    # §二十二：已排除分支（过孔零件，不画）——认布局 meta，不在此处硬编码
    excluded = {e['key'] for e in d.get('meta', {}).get('excluded_branches', [])}
    if excluded:
        print(f'已排除分支（§二十二，不画）：{sorted(excluded)}')
    trunk_list = d['meta']['trunk_path']['branch_list']
    trunk_keys = set(trunk_list)
    trunk_idx = {k: i + 1 for i, k in enumerate(trunk_list)}
    by_key = {b['key']: b for b in branches}
    v6p1_order = {b['key']: i for i, b in enumerate(branches)}
    node_xy = {n['code']: (n['x'], n['y']) for n in nodes}
    seg_len = {s['seg']: s['length'] for s in topo['segments']}
    seg_ends = {s['seg']: (s['na'], s['nb']) for s in topo['segments']}

    # ---- 1. 由 topology.json 算过路点集：无实体节点（N/BN）中恰连 2 个地方 ----
    # §十六（2026-11-17 定，2026-11-19 22:15 用户令恢复执行）：过路点在
    # 2D 图面合并掉；2026-11-19 当晚的保留点做法已废止（KEEP_WAYPOINTS
    # 仅供回归对比）。waypoint_nodes 照旧算出（供报告、隐藏平行配对与
    # 直径差异检查用）；KEEP_WAYPOINTS=False 时进 merged_set 合并。
    nbrs = defaultdict(set)
    for s in topo['segments']:
        if s['na'] == s['nb']:
            continue  # 自环不连向别处
        nbrs[s['na']].add(s['nb'])
        nbrs[s['nb']].add(s['na'])
    topo_type = {n['code']: n['type'] for n in topo['nodes']}
    waypoint_nodes = sorted(
        c for c, ns in nbrs.items()
        if len(ns) == 2 and topo_type.get(c) in ('joint', 'fork'))
    if excluded:
        # 只属于已排除分支的节点：布局里没有它的段，不进过路点集
        seg_branch = {s['seg']: s.get('branch') for s in topo['segments']}
        node_segs = {n['code']: n.get('segments', [])
                     for n in topo['nodes']}
        kept = []
        for m in waypoint_nodes:
            segs = node_segs.get(m, [])
            if segs and all(seg_branch.get(s) in excluded for s in segs):
                continue
            kept.append(m)
        dropped_m = sorted(set(waypoint_nodes) - set(kept))
        if dropped_m:
            print(f'过路点集剔除 {len(dropped_m)} 个节点（只属于已排除分支）：'
                  f'{dropped_m}')
        waypoint_nodes = kept
    waypoint_set = set(waypoint_nodes)
    merged_nodes = [] if KEEP_WAYPOINTS else waypoint_nodes
    merged_set = set(merged_nodes)
    n_joint = sum(1 for c in waypoint_nodes
                  if topo_type.get(c) == 'joint')
    n_fork = len(waypoint_nodes) - n_joint
    print(f'waypoints: {len(waypoint_nodes)} nodes '
          f'({n_joint} joint + {n_fork} fork), verified from topology.json; '
          f'{"kept as naming points (2026-11-19)" if KEEP_WAYPOINTS else "merged"}')

    # ---- 2. 收集画出段（自环段除外，走线时不参与） ----
    # §二十七：自环段（na==nb，含 §十八 stub 标记的段）2D 不出图，进掉落集
    # loop_pieces，不进走线。环弦符号段（v6p1 symbol_segs，§六已退役，现行
    # 数据 0 处）若出现直接报错——它连两个不同节点，不是自环，静默丢掉会
    # 丢真实连接，须用户另定；is_symbol 标记供此断言区分。
    symbol_segs = {r['seg']: r for r in d.get('symbol_segs', [])}
    stub_segs = {s['seg'] for s in topo['segments'] if s.get('stub')}
    pieces = []  # {seg, na, nb, pts, branch, dia}
    loop_pieces = []
    for b in branches:
        for pc in b['pieces']:
            rec = {'seg': pc['seg'], 'na': pc['na'], 'nb': pc['nb'],
                   'pts': [tuple(p) for p in pc['pts']],
                   'branch': b['key'], 'dia': b['dia'],
                   'is_symbol': pc['seg'] in symbol_segs}
            if pc['na'] == pc['nb'] or pc['seg'] in symbol_segs:
                loop_pieces.append(rec)
            else:
                pieces.append(rec)
    # 自环段数核查：应等于 topology 里自环段中属于画出分支的条数
    # （§十五整根隐藏的分支不画线，其自环段也不在布局里；§二十七起
    # stub 标记的自环段同样计入掉落集，不再走正常段通道）。
    hidden_whole = {h['hidden_branch'] for h in d.get('hidden_parallel', [])
                    if h.get('hidden_kind') == 'whole_branch'}
    topo_loop_n = sum(
        1 for s in topo['segments']
        if s['na'] == s['nb']
        and s.get('branch') not in hidden_whole
        and s.get('branch') not in excluded)
    n_symbol = sum(1 for lp in loop_pieces if lp['is_symbol'])
    assert n_symbol == 0, (
        f'环弦符号段 {n_symbol} 处再现（§六已退役）：须用户另定画法，'
        '不能按 §二十七静默丢掉')
    assert len(loop_pieces) == topo_loop_n + n_symbol, (
        f'自环+环弦符号段 {len(loop_pieces)} ≠ topology 自环段 '
        f'{topo_loop_n} + 环弦符号 {n_symbol}')
    assert all(s in {lp['seg'] for lp in loop_pieces}
               for s in symbol_segs), '有环弦符号段未进布局'
    node_pieces = defaultdict(list)
    for pc in pieces:
        node_pieces[pc['na']].append(pc)
        node_pieces[pc['nb']].append(pc)
    for m in waypoint_nodes:
        assert len(node_pieces[m]) == 2, (
            f'{m}: 触画出段 {len(node_pieces[m])} 条 ≠ 2')

    # ---- 3. 段级走线：过路点处唯一配对，最大链 ----
    assigned = {}  # seg -> path index
    chains = []    # 每条链：[(piece, reversed)]，按路径方向排列

    def extend(chain, forward):
        """从链的一端延伸。forward=True 从链尾（nb 侧）延伸。
        两种接续：①过路点处跨分支合并（旧行为，KEEP_WAYPOINTS 时
        merged_set 为空不走）；②同根接续（2026-11-19）：同根管子的
        相邻段接成一条路径（一管一路径，与 v6p1 一致），不同管子在
        过路点处不再接续。"""
        end_piece, end_rev = chain[-1] if forward else chain[0]
        if forward:
            cur = end_piece['nb'] if not end_rev else end_piece['na']
        else:
            cur = end_piece['na'] if not end_rev else end_piece['nb']
        visited = {cur}
        while True:
            here = chain[-1][0] if forward else chain[0][0]
            if cur in merged_set:
                cands = [q for q in node_pieces[cur]
                         if q['seg'] not in assigned
                         and q['seg'] != here['seg']]
                assert len(cands) == 1, (
                    f'在 {cur} 处配对段 {len(cands)} 条 ≠ 1')
                q = cands[0]
            elif KEEP_WAYPOINTS:
                # 同根接续：只接同分支的未分配段；无或多条时停下
                # （多条同分支段交于一点是歧义，不猜）
                cands = [q for q in node_pieces[cur]
                         if q['seg'] not in assigned
                         and q['seg'] != here['seg']
                         and q['branch'] == here['branch']]
                if len(cands) != 1:
                    break
                q = cands[0]
            else:
                break
            if forward:
                rev = (q['nb'] == cur)  # 需从 cur 出发
                chain.append((q, rev))
                cur = q['na'] if rev else q['nb']
            else:
                rev = (q['na'] == cur)  # 需在 cur 结束
                chain.insert(0, (q, rev))
                cur = q['nb'] if rev else q['na']
            assigned[q['seg']] = len(chains)
            assert cur not in visited, f'过路点成环：{cur}'
            visited.add(cur)

    for pc in pieces:
        if pc['seg'] in assigned:
            continue
        assigned[pc['seg']] = len(chains)
        chain = [(pc, False)]
        extend(chain, True)
        extend(chain, False)
        chains.append(chain)
    assert len(assigned) == len(pieces), '有画出段未进路径'

    # §二十七：自环段不挂到路径上、不再建退化链，直接掉落，只记清单。
    # 整根去掉的分支 = 其布局内全部段都在掉落集里（Body.96、29.1-64X）；
    # 还有正常段的分支（Body.117、Body.150）只去掉自环段，剩下段照旧成线。
    dropped_loop = []  # {branch, seg, node, length_mm, dia_mm, whole_branch}
    _layout_segs_by_branch = defaultdict(set)
    for b in branches:
        for pc in b['pieces']:
            _layout_segs_by_branch[b['key']].add(pc['seg'])
    _dropped_segs = {lp['seg'] for lp in loop_pieces}
    for lp in sorted(loop_pieces, key=lambda p: (p['branch'], p['seg'])):
        whole = _layout_segs_by_branch[lp['branch']] <= _dropped_segs
        dropped_loop.append({
            'branch': lp['branch'], 'seg': lp['seg'], 'node': lp['na'],
            'length_mm': seg_len[lp['seg']], 'dia_mm': lp['dia'],
            'whole_branch': whole,
            'reason': ('自环段，两端同为 %s，2D 不出图'
                       '（§二十七，2026-11-19 用户定）' % lp['na'])})
    dropped_whole_branches = sorted({r['branch'] for r in dropped_loop
                                     if r['whole_branch']})
    for r in dropped_loop:
        print(f"  drop loop seg {r['branch']} {r['seg']} "
              f"{r['length_mm']}mm @ {r['node']}"
              f"{'（整根去掉）' if r['whole_branch'] else ''}")

    # ---- 4. 折线工具（§二十七：小圆环符号已废止，环方向与 loop_info 已删） ----
    def chain_points(chain):
        pts = []
        for pc, rev in chain:
            seg_pts = pc['pts'][::-1] if rev else list(pc['pts'])
            if pts:
                gap = math.hypot(seg_pts[0][0] - pts[-1][0],
                                 seg_pts[0][1] - pts[-1][1])
                assert gap < JOINT_GAP_TOL_MM, (
                    f"{pc['seg']}: 拼接间隙 {gap:.4f}mm")
                pts.extend(seg_pts[1:])
            else:
                pts.extend(seg_pts)
        return pts

    def chain_endpoints(chain):
        p0, r0 = chain[0]
        p1, r1 = chain[-1]
        start = p0['nb'] if r0 else p0['na']
        end = p1['na'] if r1 else p1['nb']
        return start, end

    # ---- 5. 隐藏平行段配对：经同一过路点串联的隐藏段接成一条隐藏路径 ----
    hidden_recs = d.get('hidden_parallel', [])
    hid_by_seg = {h['hidden_seg']: h for h in hidden_recs}
    hid_ends = {h['hidden_seg']: seg_ends[h['hidden_seg']]
                for h in hidden_recs}
    hid_chains = []
    hid_used = set()
    for h in hidden_recs:
        s = h['hidden_seg']
        if s in hid_used:
            continue
        chain = [s]
        hid_used.add(s)
        # 双向延伸：经同一过路点串联的隐藏段接成一条隐藏路径
        # （先向后追加、再向前补，保持与原单向延伸相同的链序）
        # 过路点保留后仍经 waypoint_set 配对（几何连续性未变，IP
        # Body.159 的隐藏平行对仍合为一行）
        while True:
            grown = False
            for end_i in (-1, 0):
                a, b = hid_ends[chain[end_i]]
                for t in (a, b):
                    if t not in waypoint_set:
                        continue
                    for h2 in hidden_recs:
                        s2 = h2['hidden_seg']
                        if s2 in hid_used:
                            continue
                        if t in hid_ends[s2]:
                            if end_i == 0:
                                chain.insert(0, s2)
                            else:
                                chain.append(s2)
                            hid_used.add(s2)
                            grown = True
                            break
                    if grown:
                        break
            if not grown:
                break
        hid_chains.append(chain)
    # 单段链保持原记录；多段链合成一条 pair 记录（挂在 kept 分支的路径上）
    pair_records = {}  # kept_branch -> pair record
    replaced_segs = set()
    for ch in hid_chains:
        if len(ch) == 1:
            continue
        recs = [hid_by_seg[s] for s in ch]
        kept = {r['kept_branch'] for r in recs}
        dias = {r['hidden_dia_mm'] for r in recs}
        ends = []
        for s in ch:
            for t in hid_ends[s]:
                if t not in waypoint_set:
                    ends.append(t)
        via = sorted({t for s in ch for t in hid_ends[s]
                      if t in waypoint_set})
        if len(kept) != 1 or len(dias) != 1 or len(ends) != 2:
            # 结构不符（kept 分支不唯一/直径不一/端点不是 2 个）：
            # 不配对，各段保持原记录（数据不丢，只是不合成一行）
            print(f'  hidden chain {ch} not paired '
                  f'(kept={kept} dias={dias} ends={ends})')
            continue
        total = round(sum(r['hidden_length_mm'] for r in recs), 1)
        pair_records[kept.pop()] = {
            'pair': f'{ends[0]}—{ends[1]}',
            'hidden_branch': '+'.join(r['hidden_branch'] for r in recs),
            'hidden_seg': '+'.join(ch),
            'hidden_length_mm': total,
            'hidden_dia_mm': recs[0]['hidden_dia_mm'],
            'hidden_kind': 'merged_pair',
            'merged_via': '、'.join(via),
            'kept_branch': recs[0]['kept_branch'],
            'kept_seg': '+'.join(r['kept_seg'] for r in recs),
        }
        replaced_segs.update(ch)
        print(f"  hidden pair: {'+'.join(ch)} -> {ends[0]}->{ends[1]} "
              f"{total}mm via {'、'.join(via)} (kept {recs[0]['kept_branch']})")
    if replaced_segs:
        print(f'  paired hidden segs: {sorted(replaced_segs)}')

    # ---- 6. 组装新路径 ----
    branch_paths = defaultdict(set)
    for i, ch in enumerate(chains):
        for pc, _ in ch:
            branch_paths[pc['branch']].add(i)

    def oriented_pieces(chain):
        out = []
        for pc, rev in chain:
            if rev:
                out.append({'seg': pc['seg'], 'na': pc['nb'], 'nb': pc['na'],
                            'pts': [list(p) for p in pc['pts'][::-1]],
                            'branch': pc['branch'], 'dia': pc['dia']})
            else:
                out.append({'seg': pc['seg'], 'na': pc['na'], 'nb': pc['nb'],
                            'pts': [list(p) for p in pc['pts']],
                            'branch': pc['branch'], 'dia': pc['dia']})
        return out

    new_branches = []
    merge_records = []
    for i, ch in enumerate(chains):
        n0, n1 = chain_endpoints(ch)
        # 去三角：只用非自环段重建折线；纯自环分支退化为 [节点, 节点]
        # （环弦符号段同自环段一样不进折线——其分支退化为 [节点, 节点]，
        #  改画小环符号；否则三角点列会原样画出来）
        # §十八：退化短管段（stub）是直线，进折线
        non_loop = [(pc, rev) for pc, rev in ch
                    if (pc['na'] != pc['nb'] or pc['seg'] in stub_segs)
                    and pc['seg'] not in symbol_segs]
        if non_loop:
            pts = chain_points(non_loop)
        else:
            pts = [node_xy[n0], node_xy[n0]]
        opieces = oriented_pieces(ch)
        # §二十七：自环段已进掉落集，不挂进 pieces、不计长度、不画线
        # 组成管子：连续同分支段归组
        consts = []
        for opc in opieces:
            if (opc['na'] == opc['nb'] and opc['seg'] not in stub_segs) \
                    or opc['seg'] in symbol_segs:
                continue  # 自环段/环弦符号段不单独成组，归属其分支的组
            if consts and consts[-1]['key'] == opc['branch']:
                consts[-1]['segs'].append(opc['seg'])
                consts[-1]['len_3d'] = round(
                    consts[-1]['len_3d'] + seg_len[opc['seg']], 1)
                consts[-1]['len_2d'] = round(
                    consts[-1]['len_2d'] + plen([tuple(p) for p in opc['pts']]), 1)
            else:
                consts.append({'key': opc['branch'], 'dia': opc['dia'],
                               'len_3d': round(seg_len[opc['seg']], 1),
                               'len_2d': round(plen([tuple(p) for p in opc['pts']]), 1),
                               'segs': [opc['seg']]})
        # 纯自环分支（Body.96）：组由自环段构成
        if not consts:
            lp = ch[0][0]
            consts = [{'key': lp['branch'], 'dia': lp['dia'],
                       'len_3d': round(seg_len[lp['seg']], 1),
                       'len_2d': 0.0, 'segs': [lp['seg']]}]
        # §二十七：掉落的自环段长度不计入路径 len_3d（Body.117 只剩
        # SEG13 的 71.9mm，Body.150 只剩 SEG19 的 59.9mm）
        for c in consts:
            c['partial'] = len(branch_paths[c['key']]) > 1
        len_3d = round(sum(c['len_3d'] for c in consts), 1)
        len_2d = round(plen([tuple(p) for p in pts]), 1)
        # 吸收的过路点：链内相邻段之间的节点
        absorbed = []
        for a, b in zip(opieces, opieces[1:]):
            if a['nb'] == b['na'] and a['nb'] in merged_set:
                absorbed.append(a['nb'])
        # 主干位置：组成分支的主干序号（须连续；非主干路径为空）
        tps = sorted(trunk_idx[c['key']] for c in consts
                     if c['key'] in trunk_keys)
        if tps:
            assert tps == list(range(tps[0], tps[-1] + 1)), (
                f'路径 {consts}: 主干序号不连续 {tps}')
            assert len(tps) == len(consts) or any(
                c['partial'] for c in consts), (
                f'路径 {consts}: 主干/非主干混在一条路径里 {tps}')
        merged = len(consts) > 1
        entry = {
            'key': '+'.join(c['key'] for c in consts) if merged else consts[0]['key'],
            'dia': None if merged else consts[0]['dia'],
            'len_3d': len_3d,
            'len_2d': len_2d,
            'node0': n0,
            'node1': n1,
            'points': [list(p) for p in pts],
            'pieces': [{k: v for k, v in opc.items()
                        if k in ('seg', 'na', 'nb', 'pts')}
                       for opc in opieces],
        }
        if merged:
            entry['merged_from'] = consts
        if absorbed:
            entry['merged_nodes'] = absorbed
        if tps:
            entry['trunk_positions'] = tps
        # partial 标记（单根但被拆开的分支：Body.113 余段）
        if not merged and consts[0]['partial']:
            total_3d = by_key[consts[0]['key']]['len_3d']
            others = [pi for pi in sorted(branch_paths[consts[0]['key']])
                      if pi != i]
            entry['partial'] = {
                'branch': consts[0]['key'],
                'segs_here': consts[0]['segs'],
                'total_len_3d': total_3d,
                'other_paths': others,  # 占位，下方换成路径 key
            }
        # 平行隐藏：按 kept_seg 挂到本路径；pair 记录挂 kept 分支路径
        ph = []
        for h in hidden_recs:
            if h['hidden_seg'] in replaced_segs:
                continue
            if h['kept_seg'] in {opc['seg'] for opc in opieces}:
                ph.append(h)
        for kept_branch, pr in pair_records.items():
            if kept_branch in {c['key'] for c in consts}:
                ph.append(pr)
        if ph:
            entry['parallel_hidden'] = ph
        # hidden_segs：组成分支原样带入（Body.46/Body.134 未被合并）
        hs = [h for c in consts
              for h in by_key[c['key']].get('hidden_segs', [])]
        if hs:
            entry['hidden_segs'] = hs
        # §二十七：自环符号已废止，路径上不再有 loop/loop_only 条目
        # 排序键：首个组成分支在 v6p1 中的位置
        entry['_order'] = v6p1_order[consts[0]['key']]
        new_branches.append(entry)
        if merged or absorbed:
            merge_records.append({
                'path': entry['key'],
                'endpoints': [n0, n1],
                'joints': absorbed,
                'constituents': [c['key'] for c in consts],
                'dias': [c['dia'] for c in consts],
                'lengths_3d': [c['len_3d'] for c in consts],
                'segs': [c['segs'] for c in consts],
                'total_len_3d': len_3d,
                'total_len_2d': len_2d,
                'trunk_positions': tps or None,
            })
    # partial 的 other_paths 换成路径 key（此处索引与 chains 一致）
    key_by_idx = {i: b['key'] for i, b in enumerate(new_branches)}
    for b in new_branches:
        if 'partial' in b:
            b['partial']['other_paths'] = [
                key_by_idx[pi] for pi in b['partial']['other_paths']]
    new_branches.sort(key=lambda b: b['_order'])
    for b in new_branches:
        del b['_order']

    # ---- 7. 节点：只去掉合并掉的点 ----
    # §十六合并模式（默认）：merged_set 为过路点集，全部并掉；
    # KEEP_WAYPOINTS 时 merged_set 为空，全部节点保留。
    new_nodes = [n for n in nodes if n['code'] not in merged_set]
    assert len(new_nodes) == len(nodes) - len(merged_nodes)

    # ---- 8. 硬核查（全部由数据算出，不写死数值） ----
    assert len(new_branches) == len(chains), (
        f'路径数 {len(new_branches)} ≠ 链数 {len(chains)}')
    # 全数核查：全部管子各至少出现一次；被拆开的分支逐个记入报告
    appear = defaultdict(int)
    for b in new_branches:
        if 'merged_from' in b:
            for m in b['merged_from']:
                appear[m['key']] += 1
        else:
            appear[b['key']] += 1
    for h in hidden_recs:
        if h['hidden_kind'] == 'whole_branch':
            appear[h['hidden_branch']] += 1
    n_topo_branches = len(topo['branches'])
    n_excluded = len(excluded & {b.get('key') or b.get('occ')
                                 for b in topo['branches']})
    # §二十七：整根去掉的自环分支（Body.96、29.1-64X）不在图上出现，
    # 全数里扣掉，另在掉落清单里列出，不混进总数
    assert len(appear) == (n_topo_branches - n_excluded
                           - len(dropped_whole_branches)), (
        f'管子全数核查：{len(appear)} ≠ topology 分支数 '
        f'{n_topo_branches} − 已排除 {n_excluded} − 自环整根去掉 '
        f'{len(dropped_whole_branches)}')
    multi = {k: v for k, v in appear.items() if v > 1}
    if multi:
        print(f'  split branches ({len(multi)}): {multi}')
    # 非合并、未拆开路径的几何与 v6p1 逐点一致（合并只重组折线）
    for b in new_branches:
        if 'merged_from' in b or 'partial' in b:
            continue
        old = by_key[b['key']]
        assert b['points'] == old['points'], f"{b['key']} 几何变了"
    # 被拆开的分支：每条片段的点位须是原分支点位的子集
    for b in new_branches:
        if 'partial' not in b:
            continue
        old_pts = {tuple(p) for p in by_key[b['key']]['points']}
        assert all(tuple(p) in old_pts for p in b['points']), (
            f"{b['key']} 片段点位不在原分支上")
    # §二十七闭环（每次生成的固定步骤，不是一次性手工删）：
    # 掉落数＝拓扑自环段数；去后任一路径不得 node0==node1；布局里
    # 不得有 loop 条目。任一失败即 raise，不写盘。
    assert len(dropped_loop) == topo_loop_n, (
        f'自环掉落 {len(dropped_loop)} ≠ topology 自环段 {topo_loop_n}')
    _loop_paths = [b['key'] for b in new_branches
                   if b['node0'] == b['node1']]
    assert not _loop_paths, f'自环路径残留：{_loop_paths}'
    assert not any('loop' in b for b in new_branches), 'loop 条目残留'
    # 合并不改变 2D 长度：每条路径的 len_2d 须等于其组成段在 v6p1 里
    # 的 2D 长度之和（合并只重组折线，不动点位；掉落的自环段已不在
    # pieces 里，不进此和）。1:1（2D vs 3D）见下方 DRC 卡口。
    for b in new_branches:
        exp = 0.0
        for opc in b['pieces']:
            if opc['na'] == opc['nb'] and opc['seg'] not in stub_segs:
                continue  # 防御：自环段不应进 pieces（§2 已掉落）
            exp += plen([tuple(p) for p in opc['pts']])
        assert abs(b['len_2d'] - round(exp, 1)) <= 0.1, (
            f"{b['key']} 合并改变了 2D 长度：{b['len_2d']} vs v6p1 {round(exp, 1)}")
    # 1:1 卡口（§二十九 DRC，原只上报不断言，现改为卡口）：每条路径
    # 2D 与 3D 长度误差 ≤0.1mm，否则不出图。合并只重组折线、不动点位，
    # 误差只能来自 v6p1——v6p1 有误差时合并也不许悄悄带过去，报错指回上游。
    max_err = 0.0
    len_errs = []
    for b in new_branches:
        e = round(abs(b['len_2d'] - b['len_3d']), 1)
        max_err = max(max_err, e)
        if e > 0.05:
            len_errs.append([b['key'], b['len_3d'], b['len_2d'], e])
    assert max_err <= 0.1, (
        f'1:1 误差 {max_err}mm 超 0.1mm（来自 v6p1，合并未改动几何）：'
        f'{len_errs}，不出图')

    # ---- 8b. §二十九 DRC：过路点闭环（从输出路径重算，不复用输入判定） ----
    # 合并模式下，输出路径的端点里不得残留过路点：无实体节点（joint/fork）
    # 在输出里恰连 2 处 = 合并漏掉了（N15 两次投诉的教训），必须为 0。
    # KEEP_WAYPOINTS 模式故意保留过路点，跳过。
    if not KEEP_WAYPOINTS:
        _nbrs = defaultdict(set)
        for b in new_branches:
            _nbrs[b['node0']].add(b['node1'])
            _nbrs[b['node1']].add(b['node0'])
        _wp_resid = sorted(c for c, ns in _nbrs.items()
                           if len(ns) == 2
                           and topo_type.get(c) in ('joint', 'fork'))
        assert not _wp_resid, f'过路点残留（§十六合并漏掉）：{_wp_resid}'
    else:
        _wp_resid = []

    # ---- 8c. §二十九 DRC：连通性保持 + 无孤立节点 ----
    # 段级连通分量数（按段端点 na/nb 并查集——按路径端点算会漏掉折线中途
    # 的接头，实测输入 6 个分量是假象）：输入非自环段与输出段须一致，
    # 合并不得拆散/接错图；自环段两端是同一个节点，掉落不改变连通性。
    _comp_in = _n_piece_components([(pc['na'], pc['nb']) for pc in pieces])
    _comp_out = _n_piece_components(
        [(pc['na'], pc['nb']) for b in new_branches
         for pc in b['pieces']])
    assert _comp_in == _comp_out, (
        f'段级连通分量 {_comp_in} → {_comp_out}：合并改变了连通性')
    _used_nodes = ({b['node0'] for b in new_branches}
                   | {b['node1'] for b in new_branches})
    _orphans = sorted(n['code'] for n in new_nodes
                      if n['code'] not in _used_nodes)
    assert not _orphans, f'孤立节点（无路径经过）：{_orphans}'

    # ---- 8d. §二十九 DRC：全图硬检查（交叉/压着画/穿节点） ----
    # 复用优化器的 Checker（同一口径），输入与输出各查一遍，从几何重算，
    # 不复用输入布局里记的数。卡口：交叉 0、压着画 0；穿节点不得新增
    # （输出 ≤ 输入——合并只重组折线、不动点位，新增即合并引入的错误）。
    # 残留的穿节点逐条列入报告，等用户定夺清还是认；清掉后卡口收紧为 0。
    # 节点挨近（node_close）是软指标，只报告不卡（残留是用户已接受的）。
    drc_in = Checker(_CheckLayout(d), PIERCE_MM).full_check()
    drc_out = Checker(_CheckLayout({'branches': new_branches,
                                    'nodes': new_nodes}),
                      PIERCE_MM).full_check()
    assert not drc_out['crossings'], (
        f"交叉 {len(drc_out['crossings'])} 对："
        f"{sorted(set(map(tuple, map(sorted, drc_out['crossings']))))}，不出图")
    assert not drc_out['overlaps'], (
        f"压着画 {len(drc_out['overlaps'])} 对："
        f"{sorted(set(map(tuple, map(sorted, drc_out['overlaps']))))}，不出图")
    assert len(drc_out['piercings']) <= len(drc_in['piercings']), (
        f"穿节点新增：输入 {len(drc_in['piercings'])} 处，输出 "
        f"{len(drc_out['piercings'])} 处：{drc_out['piercings']}，不出图")
    print(f'paths: {len(branches)} -> {len(new_branches)}; '
          f'nodes: {len(nodes)} -> {len(new_nodes)}')
    print(f'max 1:1 err: {max_err}mm; len_errs: {len_errs}')
    print(f"DRC: X {len(drc_in['crossings'])}->{len(drc_out['crossings'])}, "
          f"overlap {len(drc_in['overlaps'])}->{len(drc_out['overlaps'])}, "
          f"pierce {len(drc_in['piercings'])}->{len(drc_out['piercings'])}, "
          f"node_close {len(drc_out['node_close'])}")

    # 自环掉落描述（报告用）：整根去掉的与只去掉一段的分开列；只去掉
    # 一段的写清剩下长度（输出路径里该分支剩下段的 len_3d 之和）
    def _remaining_len(branch_key):
        total = 0.0
        for b in new_branches:
            if 'merged_from' in b:
                for m in b['merged_from']:
                    if m['key'] == branch_key:
                        total += m['len_3d']
            elif b['key'] == branch_key:
                total += b['len_3d']
        return round(total, 1)

    _drop_whole = [r for r in dropped_loop if r['whole_branch']]
    _drop_part = [r for r in dropped_loop if not r['whole_branch']]
    drop_desc_parts = []
    for r in sorted(_drop_whole, key=lambda x: x['branch']):
        drop_desc_parts.append(
            f"{r['branch']} 整根去掉（{r['seg']} {r['length_mm']}mm "
            f"Φ{r['dia_mm']}，两端同为 {r['node']}）")
    for r in sorted(_drop_part, key=lambda x: x['branch']):
        drop_desc_parts.append(
            f"{r['branch']} 去掉 {r['seg']}（{r['length_mm']}mm，两端同为 "
            f"{r['node']}），剩下 {_remaining_len(r['branch'])}mm 照旧画线")
    drop_desc = '；'.join(drop_desc_parts)
    # 直径不同的接头：过路点两边管子直径（取整后）不同，弹窗里两根都保留
    dia_diff_joints = []
    for m in waypoint_nodes:
        pcs = node_pieces[m]
        if len(pcs) == 2 and round(pcs[0]['dia']) != round(pcs[1]['dia']):
            dia_diff_joints.append(
                (m, pcs[0]['dia'], pcs[1]['dia'],
                 pcs[0]['branch'], pcs[1]['branch']))
    n_merged_paths = sum(1 for b in new_branches if 'merged_from' in b)
    # 合并路径总数 = 吸收过路点的路径数（merge_records 条数）：含多分支
    # 合并（n_merged_paths）与单分支跨接头（如 C289 跨 N66、196.1 跨
    # BN06——同根管子两段在接头处接起来，也算一条合并路径）；两者相等
    # 时不写括号说明（IP 即此情况，文本保持原样）
    n_merge_records = len(merge_records)
    merge_paths_txt = (f'{n_merge_records} 条'
                       + (f'（多分支合并 {n_merged_paths} 条）'
                          if n_merge_records != n_merged_paths else ''))

    # ---- 9. 写出 ----
    out = dict(d)
    out['branches'] = new_branches
    out['nodes'] = new_nodes
    out['meta'] = dict(d['meta'])
    out['meta']['version'] = 'v6p2'
    # §二十七掉落清单（与 excluded_branches 同格式、不同清单，绝不混进
    # 过孔零件清单——自环段不是过孔零件，查看器页头不得误标）
    out['meta']['dropped_loop_segments'] = dropped_loop
    out['meta']['dropped_loop_branches'] = [
        {'key': k,
         'reason': next(r['reason'] for r in dropped_loop
                        if r['branch'] == k)}
        for k in dropped_whole_branches]
    # 文案随模式变：合并模式写合并，保留模式（仅回归对比）写保留
    if KEEP_WAYPOINTS:
        based_on_txt = ('v6p1 layout.json（几何点位不动；过路点保留作'
                        '路由命名点，不再合并；自环段按 §二十七去掉）')
        wp_txt = (f'过路点 {len(waypoint_nodes)} 个保留作路由命名点'
                  f'（{n_joint} joint + {n_fork} fork，按“连几个不同地方”'
                  f'判定，2026-11-19 用户令，不再合并）')
        log_head = 'v6p2（2026-11-19 用户令：过路点保留作路由命名点，不再合并）：'
        log_wp = (f'{len(waypoint_nodes)} 个过路点全保留（{n_joint} joint + '
                  f'{n_fork} fork）')
        report_title = '# v6p2 过路点保留 + 自环段去掉报告'
        report_rule = ('规则（用户 2026-11-19 亲定，取代 2026-11-17 合并规则）：过路点是'
                       '路由途经点，2D 图里必须保留作命名点，不再合并掉——路由按名字串段'
                       '（A→B、B→C）需要 B 这个点，没有实体也要有名有点的节点。判断标准'
                       '照旧：无实体节点（N/BN）中只连两个地方的就是过路点。走线改同根接续：'
                       '同根管子的相邻段接成一条路径（一管一路径），不同管子在过路点处不再'
                       '接成一条。')
        report_wp = (f"过路点 {len(waypoint_nodes)} 个全保留（{n_joint} joint + "
                     f"{n_fork} fork）；")
    else:
        based_on_txt = ('v6p1 layout.json（几何点位不动；§十六过路点合并；'
                        '自环段按 §二十七去掉；§二十九 DRC 全过才出图）')
        wp_txt = (f'过路点 {len(waypoint_nodes)} 个合并掉（{n_joint} joint + '
                  f'{n_fork} fork，按“连几个不同地方”判定，§十六；'
                  f'2026-11-19 22:15 用户令恢复 §十六，保留点做法废止；'
                  f'过路点在 3D 数据/pieces 里照旧存在，只在 2D 图面合并）')
        log_head = 'v6p2（§十六过路点合并，2026-11-19 22:15 用户令恢复执行）：'
        log_wp = (f'{len(waypoint_nodes)} 个过路点合并掉（{n_joint} joint + '
                  f'{n_fork} fork）')
        report_title = '# v6p2 过路点合并 + 自环段去掉报告'
        report_rule = ('规则（§十六，用户 2026-11-17 22:44–22:52 亲定，2026-11-19 22:15 '
                       '用户令恢复执行；2026-11-19 当晚保留点做法已废止）：只连两处的'
                       '是过路点，并掉；连三处以上的是真分支点，保留（不按 N/BN 类型判定）。'
                       '数据与图面区分：过路点在 3D 数据（topology.json）与 pieces 的 na/nb '
                       '里照旧存在，路由按 §二十四 端点命名串段照旧；只在 2D 图面整合掉，'
                       '图面整洁。')
        report_wp = (f"过路点 {len(waypoint_nodes)} 个合并掉（{n_joint} joint + "
                     f"{n_fork} fork）；")
    out['meta']['based_on'] = based_on_txt
    st = dict(d['stats'])
    st['branches_placed'] = len(new_branches)
    st['nodes_placed'] = len(new_nodes)
    st['merged_nodes'] = len(merged_nodes)
    st['merged_nodes_list'] = merged_nodes
    st['waypoints_kept'] = len(waypoint_nodes) if KEEP_WAYPOINTS else 0
    st['waypoints_kept_list'] = waypoint_nodes if KEEP_WAYPOINTS else []
    st['merged_paths'] = n_merged_paths
    st['loop_symbols'] = 0  # §二十七：小圆环符号已废止，恒为 0
    st['chord_symbols'] = 0  # §六环弦符号已退役，恒为 0
    st['dropped_loop_segments'] = len(dropped_loop)
    st['dropped_loop_branches'] = len(dropped_whole_branches)
    st['max_len_err_mm'] = max_err
    st['len_errs'] = len_errs
    # §二十九 DRC 结果（输入→输出，元组转列表以便 JSON 序列化）
    st['drc'] = {
        'crossings_in': len(drc_in['crossings']),
        'crossings_out': len(drc_out['crossings']),
        'overlaps_in': len(drc_in['overlaps']),
        'overlaps_out': len(drc_out['overlaps']),
        'piercings_in': len(drc_in['piercings']),
        'piercings_out': len(drc_out['piercings']),
        'piercings': [list(p) for p in drc_out['piercings']],
        'node_close': [list(p) for p in drc_out['node_close']],
        'components_in': _comp_in,
        'components_out': _comp_out,
        'waypoint_residual': _wp_resid,
    }
    # bbox 按新点位重算（自环三角去掉后理论上不变，实测确认）
    xs = [p[0] for b in new_branches for p in b['points']]
    ys = [p[1] for b in new_branches for p in b['points']]
    st['bbox'] = [round(min(xs), 1), round(min(ys), 1),
                  round(max(xs), 1), round(max(ys), 1)]
    out['stats'] = st
    out['merged_joints'] = merge_records
    # checklist：H2 追加 v6p2 说明；加 S11 软条目
    ck = json.loads(json.dumps(d['checklist']))
    for item in ck.get('hard', []):
        if item.get('id') == 'H2':
            item['value'] += (f'；v6p2：自环段 {len(dropped_loop)} 处按 '
                              '§二十七去掉、不画线、不计入 1:1 误差'
                              '（用户亲令：这种情况不可能存在）')
    n_drop_nodes = len({r['node'] for r in dropped_loop})
    s11_value = (wp_txt + '；路径 '
                 f'{len(branches)}→{len(new_branches)}，节点 '
                 f'{len(nodes)}→{len(new_nodes)}；合并路径 {merge_paths_txt}；'
                 f'自环段 {len(dropped_loop)} 处去掉（§二十七，'
                 f'{n_drop_nodes} 个节点，整根去掉 '
                 f'{len(dropped_whole_branches)} 根）；'
                 f"DRC 全过：交叉 0、压着画 0、穿节点 "
                 f"{len(drc_in['piercings'])}→{len(drc_out['piercings'])}"
                 f"（{'无残留' if not drc_out['piercings'] else '残留见报告'}）")
    if multi:
        s11_value += ('；被拆开的分支 '
                      + '、'.join(f'{k}（{v} 处）' for k, v in sorted(multi.items())))
    if pair_records:
        s11_value += f'；隐藏平行对合成 {len(pair_records)} 条'
    ck.setdefault('soft', []).append({
        'id': 'S11', 'rule': '§十六 过路点合并 + §二十七 自环段去掉 + §二十九 DRC',
        'name': '过路点合并、自环段去掉与自我检查',
        'value': s11_value,
        'note': ('段级合并：同根管子先配，剩下的一对配一起；'
                 f'{n_topo_branches} 根管子全数可查'
                 + (f'（已排除过孔零件 {n_excluded} 根：'
                    f'{sorted(excluded)}，§二十二，不画）'
                    if n_excluded else ''))})
    out['checklist'] = ck
    out['merge_log'] = (
        log_head + log_wp
        + f"，路径 {len(branches)}→{len(new_branches)}，"
        f"节点 {len(nodes)}→{len(new_nodes)}；合并路径 "
        f"{merge_paths_txt}；"
        f"自环段 {len(dropped_loop)} 处去掉（§二十七）"
        + (f'；整根去掉 {len(dropped_whole_branches)} 根'
           if dropped_whole_branches else '')
        + (f'；已排除过孔零件 {sorted(excluded)}（§二十二，不画）'
           if excluded else '')
        + "；几何点位不动，v6p1 平行隐藏不动。")

    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, 'layout.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    # 人读报告
    lines = [report_title, '',
             report_rule,
             '', report_wp
             + f"路径 {len(branches)}→{len(new_branches)}；"
             f"节点 {len(nodes)}→{len(new_nodes)}；"
             f"合并路径 {merge_paths_txt}。",
             '几何点位不动；v6p1 平行隐藏不动；'
             f'{n_topo_branches} 根管子全数可查'
             + (f"（被拆开的分支 {len(multi)} 个："
                + '、'.join(f'{k}（{v} 处）' for k, v in sorted(multi.items()))
                + '，其余各一处）。' if multi else '（无分支被拆开）。'), '',
             '## 自环段去掉（§二十七，2026-11-19 22:27 用户令）', '',
             f'- {drop_desc}。',
             f'- 共去掉自环段 {len(dropped_loop)} 处（整根去掉 '
             f'{len(dropped_whole_branches)} 根）；拓扑文件不动，自环段在 '
             '3D 数据里照旧存在；小圆环符号＋虚线引线已废止，不再使用。', '',
             '## 自我检查（DRC，每次生成固定步骤，2026-11-19 用户令）', '',
             f'- 自环：查出 {topo_loop_n} 处，去掉 {len(dropped_loop)} 处，'
             '残留自环路径 0 条、loop 条目 0 个。',
             f'- 过路点闭环：从输出路径重算，残留过路点 '
             f'{len(_wp_resid)} 个。',
             f'- 管子全数：{len(appear)} 根在图上（topology '
             f'{n_topo_branches} 根 − 已排除 {n_excluded} 根 − 自环整根去掉 '
             f'{len(dropped_whole_branches)} 根）。',
             '- 几何：非合并路径与 v6p1 逐点一致；合并只重组折线。',
             f'- 1:1 长度：最大误差 {max_err}mm（卡口 ≤0.1mm）。',
             f'- 连通性：段级连通分量 {_comp_in}→{_comp_out}；孤立节点 0 个。',
             f"- 交叉：输入 {len(drc_in['crossings'])} 对 → 输出 "
             f"{len(drc_out['crossings'])} 对（卡口 0）。",
             f"- 压着画：输入 {len(drc_in['overlaps'])} 对 → 输出 "
             f"{len(drc_out['overlaps'])} 对（卡口 0）。",
             f"- 穿节点：输入 {len(drc_in['piercings'])} 处 → 输出 "
             f"{len(drc_out['piercings'])} 处（卡口：不得新增）"
             + (f"；残留：{'; '.join(f'{b}→{c}' for b, c in drc_out['piercings'])}"
                "，等用户定夺清还是认"
                if drc_out['piercings'] else "；无残留") + '。',
             f"- 节点挨近（软指标，只报告不卡）：{len(drc_out['node_close'])} 对"
             + (f"：{'; '.join(f'{a}–{b} {round(dd, 1)}mm' for a, b, dd in drc_out['node_close'])}"
                if drc_out['node_close'] else "") + '。', '',
             '| 合并路径 | 端点 | 吸收过路点 | 组成（直径/长度/段） | 合并长度 |',
             '|---|---|---|---|---|']
    for r in merge_records:
        comp = ' + '.join(
            f"{c} Φ{dd} {l}（{','.join(sg)}）" for c, dd, l, sg in
            zip(r['constituents'], r['dias'], r['lengths_3d'], r['segs']))
        tp = f"（主干第 {r['trunk_positions'][0]}–{r['trunk_positions'][-1]} 根）" \
            if r['trunk_positions'] else ''
        lines.append(f"| {r['path']} | {'→'.join(r['endpoints'])} | "
                     f"{'、'.join(r['joints']) if r['joints'] else '—'} | "
                     f"{comp} | {r['total_len_3d']} mm {tp}|")
    if dia_diff_joints:
        lines += ['', '直径不同的接头（弹窗里两根都保留）：'
                  + '、'.join(f'{m}（{d0}/{d1}）'
                              for m, d0, d1, _, _ in dia_diff_joints)
                  + '。']
    if pair_records:
        lines += ['', '隐藏平行对合成：'
                  + '、'.join(f"{pr['hidden_branch']}（{pr['hidden_seg']}，"
                              f"{pr['hidden_length_mm']}mm，经 "
                              f"{pr['merged_via']}，留 {pr['kept_branch']}）"
                              for pr in pair_records.values())
                  + '。']
    with open(os.path.join(outdir, 'merge_report_v6p2.md'), 'w',
              encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    if KEEP_WAYPOINTS:
        print(f'waypoints kept: {len(waypoint_nodes)}; joints merged: 0')
    else:
        print(f'waypoints merged: {len(merged_nodes)}; joints merged: '
              f'{len(merged_nodes)}')
    print(f'paths: {len(branches)} -> {len(new_branches)} '
          f"(merged paths: {sum(1 for b in new_branches if 'merged_from' in b)})")
    print(f'nodes: {len(nodes)} -> {len(new_nodes)}')
    print(f'wrote {out_path}')
    for r in merge_records:
        print(f"  {r['path']}: {'→'.join(r['endpoints'])} "
              f"[{', '.join(r['joints'])}] {r['total_len_3d']} mm")


if __name__ == '__main__':
    main()
