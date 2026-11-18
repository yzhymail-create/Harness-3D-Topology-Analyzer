#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3D拓扑 → 2D展开图（主干链条版）

规则：
  - 主干 = 拓扑图直径路径（最长链条），水平绘制，总长=各管弧长之和
  - 链条上每根管子的侧分支：单分支→垂直向上90°；多分支→30°对称散开
  - 侧分支若还有子分支，递归绘制（BFS）
  - 长度1:1；交叉允许，重合禁止；不分页

用法：
  python unfold_2d_chain.py topology.json -o out_dir
"""

import json, math, os, sys, argparse
from collections import defaultdict, deque

def seg_overlap(p1, p2, p3, p4):
    """是否共线重合（压着画）。横向交叉允许。"""
    def orient(a, b, c):
        v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    def on_seg(a, b, c):
        return (min(a[0],c[0])-1e-9 <= b[0] <= max(a[0],c[0])+1e-9 and
                min(a[1],c[1])-1e-9 <= b[1] <= max(a[1],c[1])+1e-9)
    o1, o2 = orient(p1,p2,p3), orient(p1,p2,p4)
    o3, o4 = orient(p3,p4,p1), orient(p3,p4,p2)
    if o1==0 and o2==0 and o3==0 and o4==0:
        if on_seg(p1,p3,p2) or on_seg(p1,p4,p2) or on_seg(p3,p1,p4) or on_seg(p3,p2,p4):
            return True
    return False

def pt_eq(a, b, tol=1e-6):
    return abs(a[0]-b[0]) < tol and abs(a[1]-b[1]) < tol

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('topo_json')
    ap.add_argument('-o', '--out', default='.')
    args = ap.parse_args()

    with open(args.topo_json) as f:
        topo = json.load(f)

    branches = {}
    for b in topo.get('branches', []):
        key = b.get('key') or b.get('occ')
        branches[key] = b
    nodes_by_code = {n.get('code'): n for n in topo.get('nodes', [])}

    node_to_branches = defaultdict(set)
    for key, b in branches.items():
        for nk in ('node0', 'node1'):
            nid = b.get(nk)
            if nid: node_to_branches[nid].add(key)
    neighbors = defaultdict(set)
    for nid, bkeys in node_to_branches.items():
        bkeys = list(bkeys)
        for i in range(len(bkeys)):
            for j in range(i+1, len(bkeys)):
                neighbors[bkeys[i]].add(bkeys[j])
                neighbors[bkeys[j]].add(bkeys[i])

    # 找直径路径（主干链条）
    def bfs_farthest(start):
        dist = {start: 0}; q = deque([start]); far = start
        while q:
            u = q.popleft()
            for v in neighbors.get(u, []):
                if v not in dist:
                    dist[v] = dist[u]+1; q.append(v)
                    if dist[v] > dist[far]: far = v
        return far, dist
    s0 = next(iter(branches.keys()))
    e1, _ = bfs_farthest(s0)
    e2, _ = bfs_farthest(e1)
    # 重建路径
    parent = {e1: None}; q = deque([e1])
    while q:
        u = q.popleft()
        if u == e2: break
        for v in neighbors.get(u, []):
            if v not in parent:
                parent[v] = u; q.append(v)
    chain = []
    cur = e2
    while cur is not None:
        chain.append(cur); cur = parent.get(cur)
    chain.reverse()
    print(f'主干链条: {len(chain)}根管子')

    chain_set = set(chain)
    # 链条上每根管子的2D位置：水平排列
    # chain[i] 从 x_offset[i] 到 x_offset[i]+length
    x_offsets = {}
    x = 0.0
    placed = {}  # branch_key -> (p1, p2)
    placed_segs = []
    for key in chain:
        L = branches[key].get('length', 0)
        p1, p2 = (x, 0.0), (x+L, 0.0)
        placed[key] = (p1, p2)
        placed_segs.append((p1, p2))
        x_offsets[key] = x
        x += L
    total_len = x
    print(f'主干总长: {total_len:.1f}mm')

    nodes_2d = {}
    errors = []
    visited = set(chain)

    # 对链条上每根管子，找侧分支并绘制
    # 侧分支的连接点：在链条管子上的t比例
    # 简化：侧分支统一从链条管子的中点发出（t=0.5）
    # 更精确需要3D投影，这里先用中点

    # BFS：队列为 (branch_key, parent_2d_p1, parent_2d_p2, parent_3d_branch)
    # 为简化，侧分支都从父管中点发出
    queue = deque()
    for key in chain:
        queue.append(key)

    # 记录每个branch在2D上的"发出点"（用于子分支）
    # 对于链条上的管子，发出点为中点；对于侧分支，为其起点（连接点）

    while queue:
        parent_key = queue.popleft()
        if parent_key not in placed:
            continue
        pp1, pp2 = placed[parent_key]
        # 父管中点
        mid = ((pp1[0]+pp2[0])/2, (pp1[1]+pp2[1])/2)
        # 父管方向角
        pdx, pdy = pp2[0]-pp1[0], pp2[1]-pp1[1]
        parent_ang = math.degrees(math.atan2(pdy, pdx))
        base_ang = parent_ang + 90.0  # 垂直方向

        # 找未访问的邻居
        nbs = [nb for nb in neighbors.get(parent_key, []) if nb not in visited]
        if not nbs:
            continue

        n = len(nbs)
        if n == 1:
            rel_angles = [90.0]
        else:
            start_off = -(n-1)*15.0
            rel_angles = [90.0 + start_off + i*30.0 for i in range(n)]

        for idx, nb_key in enumerate(nbs):
            nb = branches[nb_key]
            blen = nb.get('length', 0)
            rel_ang = rel_angles[idx] if idx < len(rel_angles) else 90.0
            abs_ang = base_ang + (rel_ang - 90.0)

            ok = False
            for side in [0, 180]:
                rad = math.radians(abs_ang + side)
                p_end = (mid[0] + math.cos(rad)*blen,
                         mid[1] + math.sin(rad)*blen)
                conflict = False
                for (q1, q2) in placed_segs:
                    if pt_eq(mid, q1) or pt_eq(mid, q2):
                        continue
                    if seg_overlap(mid, p_end, q1, q2):
                        conflict = True; break
                if not conflict:
                    placed[nb_key] = (mid, p_end)
                    placed_segs.append((mid, p_end))
                    visited.add(nb_key)
                    queue.append(nb_key)
                    ok = True
                    break
            if not ok:
                errors.append(f'{nb_key} 无法放置')
                visited.add(nb_key)

    print(f'2D管子: {len(placed)} / {len(branches)}')
    for e in errors[:5]: print(f'  ERR: {e}')

    # 输出
    import openpyxl
    os.makedirs(args.out, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = '2D管子'
    ws.append(['SEG_ID', '起点X', '起点Y', '终点X', '终点Y', '长度', '直径'])
    for key, (p1, p2) in placed.items():
        b = branches[key]
        ws.append([key, round(p1[0],1), round(p1[1],1),
                   round(p2[0],1), round(p2[1],1),
                   round(b.get('length',0),1), round(b.get('dia',0),1)])
    wb.save(os.path.join(args.out, 'unfold_chain.xlsx'))
    print('Excel OK')

    import ezdxf
    doc = ezdxf.new('R2000')
    msp = doc.modelspace()
    for key, (p1, p2) in placed.items():
        msp.add_lwpolyline([p1, p2])
        b = branches[key]
        mx, my = (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
        msp.add_text(f'{key.split("#")[-1]} L={b.get("length",0):.0f}',
                     height=8.0).set_placement((mx, my+5))
    # 主干链条加粗显示（用不同图层）
    doc.saveas(os.path.join(args.out, 'unfold_chain.dxf'))
    print('DXF OK')

if __name__ == '__main__':
    main()
