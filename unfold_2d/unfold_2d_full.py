#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3D拓扑 → 2D展开图（完整拓扑，单张）

按 v7/UNFOLD_2D_RULES.md v2规则：
  - 每根管子画成直线，长度=3D弧长（1:1）
  - 主干=最长管子，水平放置
  - 从主干出发，BFS遍历整个拓扑，递归绘制所有管子
  - 单分支→垂直；多分支→30°对称散开；先上后下；不重叠；不分页

用法：
  python unfold_2d_full.py topology.json -o out_dir
"""

import json, math, os, sys, argparse
from collections import defaultdict, deque

def seg_intersect(p1, p2, p3, p4):
    """
    两线段是否"压着"（重合/共线重叠）。
    横向交叉（X形）是允许的——2D线束图里管子交叉很正常。
    只有共线重叠才算"压着画"，禁止。
    """
    def orient(a, b, c):
        v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    def on_seg(a, b, c):
        return (min(a[0],c[0])-1e-9 <= b[0] <= max(a[0],c[0])+1e-9 and
                min(a[1],c[1])-1e-9 <= b[1] <= max(a[1],c[1])+1e-9)
    o1, o2 = orient(p1,p2,p3), orient(p1,p2,p4)
    o3, o4 = orient(p3,p4,p1), orient(p3,p4,p2)
    # 只有四点共线且重叠才算压着
    if o1 == 0 and o2 == 0 and o3 == 0 and o4 == 0:
        if on_seg(p1,p3,p2) or on_seg(p1,p4,p2) or on_seg(p3,p1,p4) or on_seg(p3,p2,p4):
            return True
    return False

def pt_eq(a, b, tol=1e-6):
    return abs(a[0]-b[0]) < tol and abs(a[1]-b[1]) < tol

def dist3(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))

def project_t_on_polyline(pt, polyline):
    """
    把3D点投影到3D折线上，返回弧长比例t（0~1）。
    polyline: [[x,y,z], ...]
    """
    if not polyline or len(polyline) < 2:
        return 0.5
    # 计算每段长度和总长
    seg_lens = []
    total = 0.0
    for i in range(len(polyline)-1):
        l = dist3(polyline[i], polyline[i+1])
        seg_lens.append(l)
        total += l
    if total < 1e-9:
        return 0.5
    # 找最近段
    best_d2, best_t = float('inf'), 0.5
    acc = 0.0
    for i in range(len(polyline)-1):
        a, b = polyline[i], polyline[i+1]
        # 点到线段的投影
        ab = [b[j]-a[j] for j in range(3)]
        ap = [pt[j]-a[j] for j in range(3)]
        ab2 = sum(x*x for x in ab)
        if ab2 < 1e-12:
            t_seg = 0.0
        else:
            t_seg = max(0.0, min(1.0, sum(ap[j]*ab[j] for j in range(3)) / ab2))
        proj = [a[j] + t_seg*ab[j] for j in range(3)]
        d2 = sum((pt[j]-proj[j])**2 for j in range(3))
        if d2 < best_d2:
            best_d2 = d2
            best_t = (acc + t_seg * seg_lens[i]) / total
        acc += seg_lens[i]
    return best_t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('topo_json')
    ap.add_argument('-o', '--out', default='.')
    ap.add_argument('--trunk', default=None, help='指定主干branch key')
    args = ap.parse_args()

    with open(args.topo_json) as f:
        topo = json.load(f)

    # branch key -> info
    branches = {}
    for b in topo.get('branches', []):
        key = b.get('key') or b.get('occ') or b.get('proto')
        branches[key] = b

    if not branches:
        print('无branches'); return 1

    # node code -> node
    nodes_by_code = {n.get('code'): n for n in topo.get('nodes', [])}

    # node code -> set(branch_key)
    node_to_branches = defaultdict(set)
    for key, b in branches.items():
        for nk in ('node0', 'node1'):
            nid = b.get(nk)
            if nid:
                node_to_branches[nid].add(key)

    # branch -> set(neighbor branch)
    neighbors = defaultdict(set)
    for nid, bkeys in node_to_branches.items():
        bkeys = list(bkeys)
        for i in range(len(bkeys)):
            for j in range(i+1, len(bkeys)):
                neighbors[bkeys[i]].add(bkeys[j])
                neighbors[bkeys[j]].add(bkeys[i])

    # 主干 = 最长（或指定）
    if args.trunk:
        trunk_key = args.trunk
    else:
        trunk_key = max(branches.keys(), key=lambda k: branches[k].get('length', 0))
    trunk = branches[trunk_key]
    print(f'主干: {trunk_key} 长{trunk.get("length",0):.1f}mm')

    # 2D布局：branch_key -> (p_start_2d, p_end_2d)
    placed = {}  # branch_key -> (p1, p2)
    placed_segs = []  # [(p1,p2)] for intersect check
    nodes_2d = {}  # node_code -> (x, y, type)
    errors = []

    # 主干水平放置
    L = trunk.get('length', 0)
    placed[trunk_key] = ((0.0, 0.0), (L, 0.0))
    placed_segs.append(((0.0, 0.0), (L, 0.0)))

    # BFS
    # 队列元素：(branch_key, parent_key, via_node_code)
    # 需要知道via_node在parent上的2D位置
    # parent的2D线段已知；via_node在parent上的t比例需要3D投影算出

    # 预计算：每个branch的polyline(3D)
    # 为via_node找t：用node的3D xyz投影到parent的3D polyline

    visited = {trunk_key}
    queue = deque()

    # 初始化：trunk的所有邻居
    def get_t_on_parent(parent_key, node_code):
        """node在parent管子上的弧长比例t（0~1）。"""
        parent = branches[parent_key]
        # 如果node是parent的端点
        if node_code == parent.get('node0'):
            return 0.0
        if node_code == parent.get('node1'):
            return 1.0
        # 否则用3D投影
        nd = nodes_by_code.get(node_code, {})
        xyz = nd.get('xyz')
        poly = parent.get('polyline')
        if xyz and poly:
            return project_t_on_polyline(xyz, poly)
        return 0.5

    def get_2d_pos_on_seg(p1, p2, t):
        return (p1[0] + t*(p2[0]-p1[0]), p1[1] + t*(p2[1]-p1[1]))

    # 按BFS层级处理：每一层收集该层所有待画分支，按父节点分组
    # 为简化，先做简单的BFS，每次处理一个branch的所有未访问邻居

    queue.append(trunk_key)
    while queue:
        parent_key = queue.popleft()
        parent_p1, parent_p2 = placed[parent_key]
        parent_len = branches[parent_key].get('length', 0)

        # 找出parent上所有连接点及其分支
        # connection: node_code -> [neighbor branch keys]
        conn_map = defaultdict(list)
        for nb in neighbors.get(parent_key, []):
            if nb in visited:
                continue
            # 找连接parent和nb的node
            for nid, bkeys in node_to_branches.items():
                if parent_key in bkeys and nb in bkeys:
                    conn_map[nid].append(nb)
                    break

        # 按t排序连接点
        conn_list = []
        for nid, nblist in conn_map.items():
            t = get_t_on_parent(parent_key, nid)
            conn_list.append((t, nid, nblist))
        conn_list.sort(key=lambda x: x[0])

        for t, nid, nblist in conn_list:
            bp = get_2d_pos_on_seg(parent_p1, parent_p2, t)
            nd = nodes_by_code.get(nid, {})
            nodes_2d[nid] = (bp[0], bp[1], nd.get('type', '?'))

            n = len(nblist)
            if n == 1:
                angles = [90.0]
            else:
                start_offset = -(n-1)*15.0
                angles = [90.0 + start_offset + i*30.0 for i in range(n)]

            # 父管子在2D的方向角（用于计算相对角度）
            # 简化：分支角度以"垂直于父管"为基准
            # 父管方向向量
            pdx = parent_p2[0] - parent_p1[0]
            pdy = parent_p2[1] - parent_p1[1]
            parent_ang = math.degrees(math.atan2(pdy, pdx))
            # 垂直方向 = parent_ang + 90
            base_ang = parent_ang + 90.0

            for idx, nb_key in enumerate(nblist):
                nb = branches[nb_key]
                blen = nb.get('length', 0)
                rel_ang = angles[idx] if idx < len(angles) else 90.0
                # rel_ang=90 表示垂直；换算成绝对角度
                # 90°→base_ang, 60°→base_ang-30, 120°→base_ang+30
                abs_ang = base_ang + (rel_ang - 90.0)

                placed_ok = False
                for side in [0, 180]:  # 先上后下（相对）
                    aa = abs_ang + side
                    rad = math.radians(aa)
                    p_end = (bp[0] + math.cos(rad)*blen,
                             bp[1] + math.sin(rad)*blen)
                    # 相交检测
                    conflict = False
                    for (q1, q2) in placed_segs:
                        if pt_eq(bp, q1) or pt_eq(bp, q2):
                            continue
                        if seg_intersect(bp, p_end, q1, q2):
                            conflict = True
                            break
                    if not conflict:
                        placed[nb_key] = (bp, p_end)
                        placed_segs.append((bp, p_end))
                        visited.add(nb_key)
                        queue.append(nb_key)
                        placed_ok = True
                        break
                if not placed_ok:
                    errors.append(f'{nb_key} 无法无重叠放置（经由{parent_key}/{nid}）')
                    visited.add(nb_key)  # 标记已处理，避免死循环

    print(f'2D管子: {len(placed)} / {len(branches)}')
    print(f'2D节点: {len(nodes_2d)}')
    for e in errors[:10]:
        print(f'  ERROR: {e}')
    if len(errors) > 10:
        print(f'  ...还有{len(errors)-10}个错误')

    # 输出Excel
    import openpyxl
    os.makedirs(args.out, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = '2D管子'
    ws.append(['SEG_ID', '起点X', '起点Y', '终点X', '终点Y', '长度(mm)', '直径(mm)'])
    for key, (p1, p2) in placed.items():
        b = branches[key]
        ws.append([key, round(p1[0],2), round(p1[1],2),
                   round(p2[0],2), round(p2[1],2),
                   round(b.get('length',0),1), round(b.get('dia',0),1)])
    ws2 = wb.create_sheet('2D节点')
    ws2.append(['NODE', '类型', 'X', 'Y'])
    for nid, (x, y, t) in nodes_2d.items():
        ws2.append([nid, t, round(x,2), round(y,2)])
    if errors:
        ws3 = wb.create_sheet('错误')
        ws3.append(['错误'])
        for e in errors: ws3.append([e])
    xlsx_path = os.path.join(args.out, 'unfold_full.xlsx')
    wb.save(xlsx_path)
    print(f'Excel: {xlsx_path}')

    # 输出DXF
    import ezdxf
    doc = ezdxf.new('R2000')
    msp = doc.modelspace()
    for key, (p1, p2) in placed.items():
        msp.add_lwpolyline([p1, p2])
        mx, my = (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
        b = branches[key]
        msp.add_text(f'{key} L={b.get("length",0):.0f}',
                     height=4.0).set_placement((mx, my+3))
    for nid, (x, y, t) in nodes_2d.items():
        if t == 'connector':
            msp.add_circle((x, y), 6.0)
        elif t == 'clamp':
            msp.add_circle((x, y), 4.0)
        else:
            msp.add_point((x, y))
        msp.add_text(f'{nid}', height=3.0).set_placement((x+8, y))
    dxf_path = os.path.join(args.out, 'unfold_full.dxf')
    doc.saveas(dxf_path)
    print(f'DXF: {dxf_path}')

if __name__ == '__main__':
    main()
