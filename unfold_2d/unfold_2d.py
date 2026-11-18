#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3D拓扑 → 2D展开图（按 v7/UNFOLD_2D_RULES.md v2规则）

功能：
  读取 topology.json（3D提取结果），按层级递归展开成2D直线图，
  输出2D数据表（Excel）+ DXF文件（CAD直接打开）。

规则摘要：
  - 每根管子画成直线，长度=3D弧长（1:1）
  - 主干=最长管子，水平放置
  - 先找分支点（从左到右排序），再画分支
  - 单分支→垂直主干向上90°；多分支→以垂直向上为基准，30°间隔对称散开
  - 上方相交则试下方；都不行则报错，不压着画
  - 不分页；暂不画图框
  - 递归：每根有子分支的管子可作为下一级图的"主干"

用法：
  python unfold_2d.py topology.json --level 0 -o out_dir
"""

import json, math, os, sys, argparse
from collections import defaultdict

# ---------- 2D几何基础 ----------

def seg_intersect(p1, p2, p3, p4):
    """两线段是否相交（端点相接不算相交）。"""
    def orient(a, b, c):
        v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    def on_seg(a, b, c):
        return (min(a[0],c[0])-1e-9 <= b[0] <= max(a[0],c[0])+1e-9 and
                min(a[1],c[1])-1e-9 <= b[1] <= max(a[1],c[1])+1e-9)
    o1, o2 = orient(p1,p2,p3), orient(p1,p2,p4)
    o3, o4 = orient(p3,p4,p1), orient(p3,p4,p2)
    if o1 != o2 and o3 != o4:
        return True
    # 共线重叠也算相交（压着画）
    if o1 == 0 and on_seg(p1,p3,p2): return True
    if o2 == 0 and on_seg(p1,p4,p2): return True
    if o3 == 0 and on_seg(p3,p1,p4): return True
    if o4 == 0 and on_seg(p3,p2,p4): return True
    return False

def pt_eq(a, b, tol=1e-6):
    return abs(a[0]-b[0]) < tol and abs(a[1]-b[1]) < tol

# ---------- 拓扑图构建 ----------

def build_graph(topo):
    """
    从topology.json构建管子连接图。
    返回：{branch_key: {'length':, 'dia':, 'p0':, 'p1':, 'occ':}}
    以及邻接表：{branch_key: [(neighbor_key, via_node_id), ...]}
    """
    branches = {}
    for b in topo.get('branches', []):
        key = b.get('key') or b.get('occ') or b.get('proto')
        branches[key] = {
            'length': b.get('length', 0),
            'dia': b.get('dia', 0),
            'p0': b.get('p0', [0,0,0]),
            'p1': b.get('p1', [0,0,0]),
            'occ': b.get('occ', b.get('proto', '')),
        }
    # 用segments构建邻接
    adj = defaultdict(list)
    for s in topo.get('segments', []):
        # segments字段：seg, branch, tube, na, nb
        # 需要找到branch key；这里用tube名称匹配
        pass
    # 更可靠：用nodes的segments反推
    # node有segments列表，表示穿过该节点的seg
    # 简化：用branch的node0/node1
    for b in topo.get('branches', []):
        key = b.get('key') or b.get('occ') or b.get('proto')
        for nk in ('node0', 'node1'):
            nid = b.get(nk)
            if nid:
                adj[key].append((nid, nk))
    return branches, adj

def find_branch_points_on_trunk(topo, trunk_key):
    """
    找出主干上的所有分支点。
    返回：[(沿主干弧长位置t, node_code, [连接的分支key列表]), ...] 按t从左到右排序
    主干左端t=0，右端t=1。
    """
    branches = {}
    for b in topo.get('branches', []):
        key = b.get('key') or b.get('occ') or b.get('proto')
        branches[key] = b
    if trunk_key not in branches:
        return []

    trunk = branches[trunk_key]
    n0, n1 = trunk.get('node0'), trunk.get('node1')

    # 找所有以n0或n1为端点的非主干branch
    bp_map = defaultdict(list)  # node_code -> [branch_key]
    for b in topo.get('branches', []):
        key = b.get('key') or b.get('occ') or b.get('proto')
        if key == trunk_key:
            continue
        bn0, bn1 = b.get('node0'), b.get('node1')
        if bn0 == n0 or bn1 == n0:
            bp_map[n0].append(key)
        elif bn0 == n1 or bn1 == n1:
            bp_map[n1].append(key)
        # 注意：中间分支点（fork落在主干中部）需要3D投影定位，
        # CODEX的topology.json里branch只有端点node，中部分支点暂不支持，
        # 先处理端点连接的情况

    result = []
    for nid, bkeys in bp_map.items():
        t = 0.0 if nid == n0 else 1.0
        result.append((t, nid, bkeys))
    result.sort(key=lambda x: x[0])
    return result

# ---------- 2D布局 ----------

def layout_level(topo, trunk_key):
    """
    对一级（主干+直接分支）做2D布局。
    返回：{
      'segments_2d': [(seg_id, (x1,y1), (x2,y2), length, dia), ...],
      'nodes_2d': {node_id: (x, y, type)},
      'errors': [...]
    }
    """
    branches, adj = build_graph(topo)
    if trunk_key not in branches:
        return {'segments_2d': [], 'nodes_2d': {}, 'errors': [f'主干 {trunk_key} 不存在']}

    trunk = branches[trunk_key]
    L = trunk['length']
    errors = []

    segments_2d = []  # (seg_id, p_start, p_end, length, dia)
    nodes_2d = {}     # node_id -> (x, y, type)
    placed_segs = []  # [(p1, p2)] 已放置的线段，用于相交检测

    # 主干水平放置，左端在原点
    trunk_start = (0.0, 0.0)
    trunk_end = (L, 0.0)
    segments_2d.append((trunk_key, trunk_start, trunk_end, L, trunk['dia']))
    placed_segs.append((trunk_start, trunk_end))

    # 找分支点
    bps = find_branch_points_on_trunk(topo, trunk_key)

    nodes_by_code = {n.get('code'): n for n in topo.get('nodes', [])}

    # 构建branch连接关系：{branch_key: set(neighbor_branch_keys)}
    # 通过node code关联
    node_to_branches = defaultdict(set)
    for b in topo.get('branches', []):
        key = b.get('key') or b.get('occ') or b.get('proto')
        for nk in ('node0', 'node1'):
            nid = b.get(nk)
            if nid:
                node_to_branches[nid].add(key)

    branch_neighbors = defaultdict(set)
    for nid, bkeys in node_to_branches.items():
        bkeys = list(bkeys)
        for i in range(len(bkeys)):
            for j in range(i+1, len(bkeys)):
                branch_neighbors[bkeys[i]].add(bkeys[j])
                branch_neighbors[bkeys[j]].add(bkeys[i])

    for t_ratio, nid, bkeys in bps:
        # 分支点在主干上的2D坐标
        bp_x = t_ratio * L
        bp_y = 0.0
        bp = (bp_x, bp_y)

        # 记录节点
        nd = nodes_by_code.get(nid, {})
        nodes_2d[nid] = (bp_x, bp_y, nd.get('type', '?'))

        # 过滤：只画"往下没有分叉"的分支（叶子分支）
        # 如果分支自身还连着别的管子（除了主干），归到下一级，不在本级画
        leaf_bkeys = []
        for bk in bkeys:
            others = branch_neighbors.get(bk, set()) - {trunk_key}
            if not others:
                leaf_bkeys.append(bk)
            # else: 有子分支，下一级再画

        n = len(leaf_bkeys)
        if n == 0:
            continue

        # 计算每个分支的角度
        if n == 1:
            angles = [90.0]  # 单分支：垂直向上
        else:
            # 多分支：以90°为中心，30°间隔对称散开
            # N=2: 75,105; N=3: 60,90,120; N=4: 45,75,105,135
            start_offset = -(n - 1) * 15.0
            angles = [90.0 + start_offset + i * 30.0 for i in range(n)]

        # 先试上方，不行试下方
        for idx, bkey in enumerate(leaf_bkeys):
            b = branches[bkey]
            blen = b['length']
            ang = angles[idx] if idx < len(angles) else 90.0

            placed = False
            for side_sign, side_name in [(1, '上'), (-1, '下')]:
                rad = math.radians(ang if side_sign > 0 else (180 - ang + 180) % 360)
                # 上方：角度不变；下方：镜像到下方（90°→270°）
                if side_sign < 0:
                    rad = math.radians(360 - ang)
                dx = math.cos(rad) * blen
                dy = math.sin(rad) * blen
                p_end = (bp[0] + dx, bp[1] + dy)

                # 检查与已放置线段是否相交（端点相接不算）
                conflict = False
                for (q1, q2) in placed_segs:
                    if pt_eq(bp, q1) or pt_eq(bp, q2):
                        continue  # 共用分支点不算相交
                    if seg_intersect(bp, p_end, q1, q2):
                        conflict = True
                        break

                if not conflict:
                    segments_2d.append((bkey, bp, p_end, blen, b['dia']))
                    placed_segs.append((bp, p_end))
                    placed = True
                    break

            if not placed:
                errors.append(f'分支点 {nid} 的分支 {bkey} 上下都相交，无法无重叠绘制')

    return {'segments_2d': segments_2d, 'nodes_2d': nodes_2d, 'errors': errors}

# ---------- 输出 ----------

def write_dxf(layout, out_path):
    """写DXF文件（需ezdxf库）。"""
    try:
        import ezdxf
    except ImportError:
        return "未安装ezdxf，跳过DXF输出（pip install ezdxf）"

    doc = ezdxf.new('R2000')  # AC1015，兼容性最好；R2010(AC1024)太新，部分CAD不认
    msp = doc.modelspace()

    for seg_id, p1, p2, length, dia in layout['segments_2d']:
        msp.add_lwpolyline([p1, p2])
        # 标注
        mx, my = (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
        msp.add_text(f'{seg_id} L={length:.1f}',
                     height=3.0).set_placement((mx, my+2))

    for nid, (x, y, ntype) in layout['nodes_2d'].items():
        if ntype == 'connector':
            msp.add_circle((x, y), 5.0)
        elif ntype == 'clamp':
            msp.add_circle((x, y), 3.0)
        else:
            msp.add_point((x, y))
        msp.add_text(f'{nid}', height=2.5).set_placement((x+6, y))

    doc.saveas(out_path)
    return f'DXF已保存: {out_path}'

def write_excel(layout, out_path):
    """写2D数据表Excel。"""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '2D管子'
    ws.append(['SEG_ID', '起点X', '起点Y', '终点X', '终点Y', '长度(mm)', '直径(mm)'])
    for seg_id, p1, p2, length, dia in layout['segments_2d']:
        ws.append([seg_id, round(p1[0],2), round(p1[1],2),
                   round(p2[0],2), round(p2[1],2),
                   round(length,1), round(dia,1) if dia else ''])

    ws2 = wb.create_sheet('2D节点')
    ws2.append(['NODE_ID', '类型', 'X', 'Y'])
    for nid, (x, y, ntype) in layout['nodes_2d'].items():
        ws2.append([nid, ntype, round(x,2), round(y,2)])

    if layout['errors']:
        ws3 = wb.create_sheet('错误')
        ws3.append(['错误信息'])
        for e in layout['errors']:
            ws3.append([e])

    wb.save(out_path)
    return f'Excel已保存: {out_path}'

# ---------- 主入口 ----------

def main():
    ap = argparse.ArgumentParser(description='3D拓扑 → 2D展开')
    ap.add_argument('topo_json', help='topology.json路径')
    ap.add_argument('--level', type=int, default=0, help='层级（暂只支持0）')
    ap.add_argument('-o', '--out', default='.', help='输出目录')
    ap.add_argument('--trunk', default=None, help='指定主干branch key（默认取最长）')
    args = ap.parse_args()

    with open(args.topo_json) as f:
        topo = json.load(f)

    branches, _ = build_graph(topo)
    if not branches:
        print(' topology.json中没有branches')
        return 1

    # 选主干：最长的
    if args.trunk:
        trunk_key = args.trunk
    else:
        trunk_key = max(branches.keys(), key=lambda k: branches[k]['length'])
    print(f'主干: {trunk_key} (长{branches[trunk_key]["length"]:.1f}mm)')

    layout = layout_level(topo, trunk_key)

    print(f'2D管子: {len(layout["segments_2d"])} 段')
    print(f'2D节点: {len(layout["nodes_2d"])} 个')
    for e in layout['errors']:
        print(f'  ERROR: {e}')

    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, f'unfold_L{args.level}')
    print(write_excel(layout, base + '.xlsx'))
    print(write_dxf(layout, base + '.dxf'))
    return 0

if __name__ == '__main__':
    sys.exit(main())
