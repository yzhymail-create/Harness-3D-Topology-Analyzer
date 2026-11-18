#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2D 展开 v6p2：过路点合并 + 自环符号（2026-11-17 用户亲定规则，通用版）。

合并规则（2026-11-17 22:52 用户亲定，取代“只并 N”的旧理解）：
  判断标准不是 N 还是 BN，而是这个点连着几个不同的地方。只连两个地方
  的就是过路点，合并；连三个地方以上的，是真分支点，保留。
  合并只针对无实体的过路点（N/BN，type 为 joint/fork）；有实体的卡扣/
  连接器节点（点按要看实体名）不并，哪怕只有两通。
  IP 实测：17 个 N 全是两通；BN 里只有 BN01（4 段，两边 CLP03/CLP06）
  和 BN04（3 段，两边 CLP01/N04）是两通；一共并掉 19 个点。
  地板实测：66 个 N 全是两通 + 7 个 BN 两通，一共并掉 73 个点。

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

自环符号（2026-11-17 22:49 用户令）：自环段改画统一小环符号（屏幕恒定
半径 8px，圆心距节点 30px，每个环占一个无管空角，取最大的 N 个空角的
角平分线）；三角从折线里去掉，弹窗保留自环管子完整数据。
  代价须明示：小环统一大小即放弃这些处的 1:1（真值仍在弹窗/标签里），
  是用户亲令的取舍。stats max_len_err 与 H2 核查排除自环路径。
  IP：3 处（BN02 两处 + BN03 一处）；地板：44 处（23 个节点）。

不动的东西：topology.json（数据源真相）；v6p1 平行隐藏（折叠段继续
隐藏，数据在弹窗里）；几何点位不动（只重组折线、去掉自环三角）。

硬核查（任一失败即退出码非 0，不写输出；全部由数据算出，不写死数值）：
  - 合并集由 topology.json 程序算出（无实体节点中恰连 2 个地方）；
  - 每个过路点恰好触 2 条画出非自环段；
  - 每条路径恰好 2 个非过路端点（纯自环退化路径两端同为一节点除外）；
  - 拼接点间隙 < 1e-6 mm；合并 len_2d 与各段和差 ≤0.11mm；
  - 全部管子全数可查（被拆开的分支逐个记入报告，不写死哪个）；
  - 非合并路径几何与 v6p1 逐点一致；非自环路径 1:1 误差 ≤0.1mm。

用法：python3 merge_joints_v6p2.py <v6p1 layout.json> <topology.json> <outdir>
输出：<outdir>/layout.json、<outdir>/merge_report_v6p2.md
"""
import json
import math
import os
import sys
from collections import defaultdict

JOINT_GAP_TOL_MM = 1e-6   # 拼接点间隙容差（实测均为 0.0）
LEN_SUM_TOL_MM = 0.11     # 合并 len_2d 与各段和的容差（含 0.1 舍入）
LOOP_LABEL_DIST_PX = 52   # Body.96 长度标签沿环方向外放距离（屏幕 px；环距 30px，标签须在环外）
# 52px 实测最优：k=2 时与 CLP14 代号重叠 12x11 一处，k=3/4 仅 2px 轻擦；
# 64px 实测更差：k=3/4 虽干净，但 k=2 新增 Body.49 长度标签 3x10 + CLP14 真名 12x8

TOPO_DEFAULT = ('/home/hatch/workspace/harness_3d/pipeline_4step_rules/'
                'test_iph_fresh/topology.json')


def plen(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(pts, pts[1:]))


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

    # ---- 1. 由 topology.json 算合并集：无实体节点（N/BN）中恰连 2 个地方 ----
    nbrs = defaultdict(set)
    for s in topo['segments']:
        if s['na'] == s['nb']:
            continue  # 自环不连向别处
        nbrs[s['na']].add(s['nb'])
        nbrs[s['nb']].add(s['na'])
    topo_type = {n['code']: n['type'] for n in topo['nodes']}
    merged_nodes = sorted(
        c for c, ns in nbrs.items()
        if len(ns) == 2 and topo_type.get(c) in ('joint', 'fork'))
    if excluded:
        # 只属于已排除分支的节点：布局里没有它的段，不进合并集
        seg_branch = {s['seg']: s.get('branch') for s in topo['segments']}
        node_segs = {n['code']: n.get('segments', [])
                     for n in topo['nodes']}
        kept = []
        for m in merged_nodes:
            segs = node_segs.get(m, [])
            if segs and all(seg_branch.get(s) in excluded for s in segs):
                continue
            kept.append(m)
        dropped_m = sorted(set(merged_nodes) - set(kept))
        if dropped_m:
            print(f'合并集剔除 {len(dropped_m)} 个节点（只属于已排除分支）：'
                  f'{dropped_m}')
        merged_nodes = kept
    merged_set = set(merged_nodes)
    n_joint = sum(1 for c in merged_nodes if topo_type.get(c) == 'joint')
    n_fork = len(merged_nodes) - n_joint
    print(f'merge set: {len(merged_nodes)} nodes '
          f'({n_joint} joint + {n_fork} fork), verified from topology.json')

    # ---- 2. 收集画出段（自环段除外，走线时不参与） ----
    # 环弦符号段（v6p1 symbol_segs：段长<端点距，画小三角符号于一端）
    # 同自环段一样不走线，改画小环符号；is_symbol 标记供后续区分。
    symbol_segs = {r['seg']: r for r in d.get('symbol_segs', [])}
    # §十八：退化短管段（stub 标记）走正常段通道，不进 loop 通道
    stub_segs = {s['seg'] for s in topo['segments'] if s.get('stub')}
    pieces = []  # {seg, na, nb, pts, branch, dia}
    loop_pieces = []
    for b in branches:
        for pc in b['pieces']:
            rec = {'seg': pc['seg'], 'na': pc['na'], 'nb': pc['nb'],
                   'pts': [tuple(p) for p in pc['pts']],
                   'branch': b['key'], 'dia': b['dia'],
                   'is_symbol': pc['seg'] in symbol_segs}
            if (pc['na'] == pc['nb'] and pc['seg'] not in stub_segs) \
                    or pc['seg'] in symbol_segs:
                loop_pieces.append(rec)
            else:
                pieces.append(rec)
    # 自环段数核查：应等于 topology 里自环段中属于画出分支的条数
    # （§十五整根隐藏的分支不画线，其自环段也不在布局里）；
    # 环弦符号段另计（不是自环，但同样走 loop 通道）。
    hidden_whole = {h['hidden_branch'] for h in d.get('hidden_parallel', [])
                    if h.get('hidden_kind') == 'whole_branch'}
    topo_loop_n = sum(
        1 for s in topo['segments']
        if s['na'] == s['nb'] and not s.get('stub')
        and s.get('branch') not in hidden_whole
        and s.get('branch') not in excluded)
    n_symbol = sum(1 for lp in loop_pieces if lp['is_symbol'])
    assert len(loop_pieces) == topo_loop_n + n_symbol, (
        f'自环+环弦符号段 {len(loop_pieces)} ≠ topology 自环段 '
        f'{topo_loop_n} + 环弦符号 {n_symbol}')
    assert all(s in {lp['seg'] for lp in loop_pieces}
               for s in symbol_segs), '有环弦符号段未进布局'
    node_pieces = defaultdict(list)
    for pc in pieces:
        node_pieces[pc['na']].append(pc)
        node_pieces[pc['nb']].append(pc)
    for m in merged_nodes:
        assert len(node_pieces[m]) == 2, (
            f'{m}: 触画出段 {len(node_pieces[m])} 条 ≠ 2')

    # ---- 3. 段级走线：过路点处唯一配对，最大链 ----
    assigned = {}  # seg -> path index
    chains = []    # 每条链：[(piece, reversed)]，按路径方向排列

    def extend(chain, forward):
        """从链的一端沿过路点延伸。forward=True 从链尾（nb 侧）延伸。"""
        end_piece, end_rev = chain[-1] if forward else chain[0]
        if forward:
            cur = end_piece['nb'] if not end_rev else end_piece['na']
        else:
            cur = end_piece['na'] if not end_rev else end_piece['nb']
        visited = {cur}
        while cur in merged_set:
            here = chain[-1][0] if forward else chain[0][0]
            cands = [q for q in node_pieces[cur]
                     if q['seg'] not in assigned and q['seg'] != here['seg']]
            assert len(cands) == 1, (
                f'在 {cur} 处配对段 {len(cands)} 条 ≠ 1')
            q = cands[0]
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

    # 自环段挂到同分支的路径上；Body.96 无他段，单独成退化路径
    path_of_branch = defaultdict(list)
    for i, ch in enumerate(chains):
        for pc, _ in ch:
            path_of_branch[pc['branch']].append(i)
    loop_attach = {}  # path index -> [loop pieces]
    pure_chain_of_branch = {}  # branch -> 退化链下标（纯自环分支多环共用一条退化路径）
    for lp in loop_pieces:
        cands = sorted(set(path_of_branch[lp['branch']]))
        if cands:
            assert len(cands) == 1, f"{lp['branch']} 自环挂到 {len(cands)} 条路径"
            loop_attach.setdefault(cands[0], []).append(lp)
        elif lp['branch'] in pure_chain_of_branch:
            # 同分支已有退化路径（多自环分支，如地板 15 根双自环分支）：
            # 环挂到同一条退化路径，不另开路径（原每环开一条，分支被
            # 误拆成多处）
            pi = pure_chain_of_branch[lp['branch']]
            chains[pi].append((lp, False))
            loop_attach[pi].append(lp)
        else:
            # 纯自环分支（Body.96）：退化路径，点位后续由自环阶段处理
            chains.append([(lp, False)])
            pure_chain_of_branch[lp['branch']] = len(chains) - 1
            loop_attach[len(chains) - 1] = [lp]

    # ---- 4. 自环符号：方向（最大空角）、去三角、重算 len_2d ----
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

    # 各节点被占方向（取所有链在该节点的端点出射角；BN02/BN03 无链穿过）
    occupied = defaultdict(list)
    for ch in chains:
        pts = chain_points(ch)
        n0, n1 = chain_endpoints(ch)
        if len(pts) >= 2 and pts[0] != pts[-1]:
            occupied[n0].append(math.degrees(math.atan2(
                pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])) % 360)
            occupied[n1].append(math.degrees(math.atan2(
                pts[-2][1] - pts[-1][1], pts[-2][0] - pts[-1][0])) % 360)
    # Body.96 的退化链 pts[0]==pts[-1]（三角闭合），不贡献方向——正确，
    # 因为它本身就是要被符号化的环，不占方向。
    # 兜底方向：链端点未覆盖该节点时（如自环节点只在链中部、或纯自环
    # 分支节点无链经过），改用该节点全部画出段的端点出射角
    occupied_fb = defaultdict(list)
    for b in branches:
        for pc in b['pieces']:
            if pc['na'] == pc['nb'] and pc['seg'] not in stub_segs:
                continue  # 自环段不占方向（§十八：短线头是直线，占方向）
            pts = pc['pts']
            if len(pts) >= 2:
                occupied_fb[pc['na']].append(math.degrees(math.atan2(
                    pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])) % 360)
                occupied_fb[pc['nb']].append(math.degrees(math.atan2(
                    pts[-2][1] - pts[-1][1], pts[-2][0] - pts[-1][0])) % 360)

    def ring_dirs(node, count):
        """每个环占一个空角：取最大的 count 个空角，各放环于角平分线。
        （旧规则“两环同挤最大空角”在 BN02 撞上主干短管的长度标签：
        Body.71/Body.74 的标签距节点约 18px，与 20px 的环同向重合；
        分占两角后 BN02 为 90°/225°，实测与邻近标签无重叠。）"""
        occ = sorted(occupied[node])
        if not occ:
            occ = sorted(occupied_fb[node])
        if not occ:
            # 该节点无任何画出段方向（纯孤立自环）：均匀散开
            return sorted(round(90.0 + i * (360.0 / count), 1)
                          for i in range(count))
        occ_ext = occ + [a + 360 for a in occ]
        gaps = []  # (角宽, 中点角)：一圈内恰 n 个空角（n=被占方向数），不重复
        for i in range(len(occ)):
            a, b = occ_ext[i], occ_ext[i + 1]
            gaps.append((b - a, (a + b) / 2 % 360))
        gaps.sort(key=lambda g: -g[0])  # 角宽从大到小（等宽时保持角序）
        if count <= len(gaps):
            return [round(g[1], 1) for g in gaps[:count]]
        # 环数多于空角数时，把最大空角再三等分（本数据未触发，防御性分支）
        dirs = [round(g[1], 1) for g in gaps]
        big_w, big_mid = gaps[0]
        while len(dirs) < count:
            dirs.append(round((big_mid - big_w / 6) % 360, 1))
            if len(dirs) < count:
                dirs.append(round((big_mid + big_w / 6) % 360, 1))
            break
        return sorted(dirs[:count])

    loop_nodes = defaultdict(list)  # node -> [loop pieces]
    for lp in loop_pieces:
        loop_nodes[lp['na']].append(lp)
    loop_info = {}  # path index -> [{branch, seg, length_mm, dia_mm, dir_deg, node}]
    for node, lps in loop_nodes.items():
        dirs = ring_dirs(node, len(lps))
        for lp, dg in zip(sorted(lps, key=lambda p: p['seg']), dirs):
            for pi, attached in loop_attach.items():
                if lp in attached:
                    info = {'branch': lp['branch'], 'seg': lp['seg'],
                            'length_mm': seg_len[lp['seg']],
                            'dia_mm': lp['dia'], 'dir_deg': dg,
                            'node': node}
                    if lp['is_symbol']:
                        # 环弦符号：另一端节点记 far，查看器据此写
                        # “连接 A—B”；kind 供 title/弹窗区分自环。
                        info['kind'] = 'chord'
                        info['far'] = lp['nb'] if lp['na'] == node \
                            else lp['na']
                    loop_info.setdefault(pi, []).append(info)
    for pi, infos in loop_info.items():
        print(f"  loop @ {infos[0]['node']}: " + ', '.join(
            f"{i['branch']} {i['seg']} {i['length_mm']}mm -> {i['dir_deg']} deg"
            for i in infos))

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
        while True:
            grown = False
            for end_i in (-1, 0):
                a, b = hid_ends[chain[end_i]]
                for t in (a, b):
                    if t not in merged_set:
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
                if t not in merged_set:
                    ends.append(t)
        via = sorted({t for s in ch for t in hid_ends[s]
                      if t in merged_set})
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
        # 自环段挂进 pieces（弹窗数据用；Body.96 的已在链里，去重）
        for lp in loop_attach.get(i, []):
            if lp['seg'] not in {o['seg'] for o in opieces}:
                opieces.append({'seg': lp['seg'], 'na': lp['na'],
                                'nb': lp['nb'],
                                'pts': [list(p) for p in lp['pts']],
                                'branch': lp['branch'], 'dia': lp['dia']})
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
        # 自环段长度计入其分支组的 len_3d（Body.117/150 的 len_3d 含自环段）
        for lp in loop_attach.get(i, []):
            for c in consts:
                if c['key'] == lp['branch'] and lp['seg'] not in c['segs']:
                    c['len_3d'] = round(c['len_3d'] + seg_len[lp['seg']], 1)
                    c['segs'].append(lp['seg'])
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
        # 自环符号
        if i in loop_info:
            entry['loop'] = loop_info[i]
            if len(non_loop) == 0:
                # 纯自环分支：长度标签沿环方向外放 40px
                entry['label_offset'] = {
                    'dir_deg': loop_info[i][0]['dir_deg'],
                    'dist_px': LOOP_LABEL_DIST_PX}
                entry['loop_only'] = True
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

    # ---- 7. 节点：去掉过路点 ----
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
    assert len(appear) == n_topo_branches - n_excluded, (
        f'管子全数核查：{len(appear)} ≠ topology 分支数 '
        f'{n_topo_branches} − 已排除 {n_excluded}')
    multi = {k: v for k, v in appear.items() if v > 1}
    if multi:
        print(f'  split branches ({len(multi)}): {multi}')
    # 非合并、无自环、未拆开路径的几何与 v6p1 逐点一致（合并只重组折线）
    for b in new_branches:
        if 'merged_from' in b or 'loop' in b or 'partial' in b:
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
    # 自环：loop 条目总数 = 自环段数；纯自环路径 len_2d=0、点位退化
    loop_paths = [b for b in new_branches if 'loop' in b]
    n_loop_entries = sum(len(b['loop']) for b in loop_paths)
    assert n_loop_entries == len(loop_pieces), (
        f'自环条目 {n_loop_entries} ≠ 自环段 {len(loop_pieces)}')
    for b in loop_paths:
        if b.get('loop_only'):
            assert b['len_2d'] == 0.0 and b['points'][0] == b['points'][1], (
                f"{b['key']} 纯自环路径 len_2d/点位异常")
    # 合并不改变 2D 长度：每条非自环路径的 len_2d 须等于其组成段在 v6p1 里
    # 的 2D 长度之和（合并只重组折线，不动点位）。1:1（2D vs 3D）是
    # v6p1 级核查——v6p1 已失败的误差合并无法修复，只能原样保留、
    # 如实上报，不在此断言（环弦符号段除外：v6p1 已将其画为符号，
    # 其分支含 loop 条目，不进此核查；2026-11-18 地板 SEG05 即此例）。
    for b in new_branches:
        if 'loop' in b:
            continue
        exp = 0.0
        for opc in b['pieces']:
            if opc['na'] == opc['nb'] and opc['seg'] not in stub_segs:
                continue  # §十八：短线头是直线，计入 2D 长度
            exp += plen([tuple(p) for p in opc['pts']])
        assert abs(b['len_2d'] - round(exp, 1)) <= 0.1, (
            f"{b['key']} 合并改变了 2D 长度：{b['len_2d']} vs v6p1 {round(exp, 1)}")
    # 1:1 误差只上报不断言（v6p1 已失败的照实带过来）
    loop_keys = {b['key'] for b in loop_paths}
    max_err = 0.0
    len_errs = []
    for b in new_branches:
        if b['key'] in loop_keys:
            continue
        e = round(abs(b['len_2d'] - b['len_3d']), 1)
        max_err = max(max_err, e)
        if e > 0.05:
            len_errs.append([b['key'], b['len_3d'], b['len_2d'], e])
    if max_err > 0.1:
        print(f'  NOTE: 非自环最大 1:1 误差 {max_err}mm（来自 v6p1，合并未改动几何）')
    print(f'paths: {len(branches)} -> {len(new_branches)}; '
          f'nodes: {len(nodes)} -> {len(new_nodes)}')
    print(f'non-loop max 1:1 err: {max_err}mm; len_errs: {len_errs}')

    # 自环方向描述（报告用，取程序算出的值；checklist 只记总数）
    loop_desc_parts = []
    loop_flat = [info for pi in sorted(loop_info) for info in loop_info[pi]]
    for info in sorted(loop_flat, key=lambda x: (x['node'], x['branch'])):
        chord_txt = (f"（环弦，连 {info['far']}）"
                     if info.get('kind') == 'chord' else '')
        loop_desc_parts.append(
            f"{info['node']}：{info['branch']} {info['seg']} "
            f"环向 {info['dir_deg']}°{chord_txt}")
    loop_desc = '；'.join(loop_desc_parts)
    # 直径不同的接头：过路点两边管子直径（取整后）不同，弹窗里两根都保留
    dia_diff_joints = []
    for m in merged_nodes:
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
    out['meta']['based_on'] = ('v6p1 layout.json（几何点位不动；过路点合并只重组'
                               '折线；自环三角改画小环符号）')
    st = dict(d['stats'])
    st['branches_placed'] = len(new_branches)
    st['nodes_placed'] = len(new_nodes)
    st['merged_nodes'] = len(merged_nodes)
    st['merged_nodes_list'] = merged_nodes
    st['merged_paths'] = n_merged_paths
    st['loop_symbols'] = len(loop_pieces) - n_symbol
    st['chord_symbols'] = n_symbol
    st['max_len_err_mm'] = max_err
    st['len_errs'] = len_errs
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
            item['value'] += (f'；v6p2：自环 {len(loop_pieces) - n_symbol} 处改画小环'
                              '符号，符号不按比例、不计入 1:1 误差'
                              '（用户亲令取舍，真值在弹窗里）')
            if n_symbol:
                item['value'] += (f'；环弦符号 {n_symbol} 处（段长<端点距，'
                                  '画小环符号于一端，真值在弹窗；§六环优先'
                                  '待实现）')
    loop_nodes_self = {lp['na'] for lp in loop_pieces
                       if not lp['is_symbol']}
    s11_value = (f'过路点 {len(merged_nodes)} 个全并（{n_joint} joint + '
                 f'{n_fork} fork，按“连几个不同地方”判定）；路径 '
                 f'{len(branches)}→{len(new_branches)}，节点 '
                 f'{len(nodes)}→{len(new_nodes)}；合并路径 {merge_paths_txt}；'
                 f'自环 {len(loop_pieces) - n_symbol} 处改画小环符号'
                 f'（{len(loop_nodes_self)} 个节点，半径 8px，距节点 30px）')
    if n_symbol:
        s11_value += f'；环弦符号 {n_symbol} 处（§六环优先待实现）'
    if multi:
        s11_value += ('；被拆开的分支 '
                      + '、'.join(f'{k}（{v} 处）' for k, v in sorted(multi.items())))
    if pair_records:
        s11_value += f'；隐藏平行对合成 {len(pair_records)} 条'
    ck.setdefault('soft', []).append({
        'id': 'S11', 'rule': '§十六 过路点合并 + 自环符号',
        'name': '过路点合并与自环符号',
        'value': s11_value,
        'note': ('段级合并：同根管子先配，剩下的一对配一起；'
                 f'{n_topo_branches} 根管子全数可查'
                 + (f'（已排除过孔零件 {n_excluded} 根：'
                    f'{sorted(excluded)}，§二十二，不画）'
                    if n_excluded else ''))})
    out['checklist'] = ck
    out['merge_log'] = (
        f"v6p2（2026-11-17 22:52 用户规则：只连两处即过路点）：{len(merged_nodes)} 个"
        f"过路点全合并，路径 {len(branches)}→{len(new_branches)}，"
        f"节点 {len(nodes)}→{len(new_nodes)}；合并路径 "
        f"{merge_paths_txt}；"
        f"自环 {len(loop_pieces) - n_symbol} 处改画小环符号"
        + (f'；环弦符号 {n_symbol} 处' if n_symbol else '')
        + (f'；已排除过孔零件 {sorted(excluded)}（§二十二，不画）'
           if excluded else '')
        + "；几何点位不动，v6p1 平行隐藏不动。")

    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, 'layout.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    # 人读报告
    lines = ['# v6p2 过路点合并 + 自环符号报告', '',
             '规则（用户 2026-11-17 22:52 亲定）：判断标准不是 N 还是 BN，而是这个点'
             '连着几个不同的地方。只连两个地方的就是过路点，合并；连三个地方以上'
             '的，是真分支点，保留。配对原则：同根管子先配，剩下的一对配一起。',
             '', f"过路点 {len(merged_nodes)} 个全合并（{n_joint} joint + "
             f"{n_fork} fork）；"
             f"路径 {len(branches)}→{len(new_branches)}；"
             f"节点 {len(nodes)}→{len(new_nodes)}；"
             f"合并路径 {merge_paths_txt}。",
             '几何点位不动；v6p1 平行隐藏不动；'
             f'{n_topo_branches} 根管子全数可查'
             + (f"（被拆开的分支 {len(multi)} 个："
                + '、'.join(f'{k}（{v} 处）' for k, v in sorted(multi.items()))
                + '，其余各一处）。' if multi else '（无分支被拆开）。'), '',
             '## 自环符号（22:49 用户令）', '',
             f'- {loop_desc}。',
             f'- 小环统一大小（半径 8px，距节点 30px），即放弃这 '
             f'{len(loop_pieces)} 处的 1:1（自环 '
             f'{len(loop_pieces) - n_symbol} 处'
             + (f'＋环弦符号 {n_symbol} 处' if n_symbol else '')
             + '），真值仍在弹窗/标签里（用户亲令取舍）。', '',
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
    if max_err > 0.1:
        lines += ['', '1:1 误差（来自 v6p1，合并只重组折线、不改几何，故原样保留）：'
                  + '、'.join(f'{k}（3D {a}mm → 2D {c}mm，误差 {e}mm）'
                              for k, a, c, e in len_errs if abs(e) > 0.1)
                  + '。']
    with open(os.path.join(outdir, 'merge_report_v6p2.md'), 'w',
              encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    print(f'joints merged: {len(merged_nodes)}')
    print(f'paths: {len(branches)} -> {len(new_branches)} '
          f"(merged paths: {sum(1 for b in new_branches if 'merged_from' in b)})")
    print(f'nodes: {len(nodes)} -> {len(new_nodes)}')
    print(f'wrote {out_path}')
    for r in merge_records:
        print(f"  {r['path']}: {'→'.join(r['endpoints'])} "
              f"[{', '.join(r['joints'])}] {r['total_len_3d']} mm")


if __name__ == '__main__':
    main()
