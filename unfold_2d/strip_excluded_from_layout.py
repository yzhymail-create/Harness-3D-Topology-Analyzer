#!/usr/bin/env python3
"""从已生成的布局 JSON 里删掉已排除分支（§二十二，过孔零件等非路径件）。

用法：strip_excluded_from_layout.py <in_layout.json> <out_layout.json>
       --exclude C289 --reason "过孔零件，非线束路径（2026-11-18 用户定）"
（--exclude/--reason 可重复，多组时按顺序配对。）

只做数据清理，不跑展开：删分支、只属于它们的节点、它们的脊线/拐弯/
树节点/投影点/环分类条目，改统计与清单里受影响的数字，并在 meta 里记
excluded_branches（合并与查看器认这项）。任一步对不上就 raise 不写盘。
"""
import argparse
import json
import re
import sys


def fail(msg):
    raise SystemExit(f'失败：{msg}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--exclude', action='append', required=True,
                    help='要删的分支 key，可重复')
    ap.add_argument('--reason', action='append', default=[],
                    help='排除原因，与 --exclude 按顺序配对')
    args = ap.parse_args()
    excluded = list(dict.fromkeys(args.exclude))  # 去重保序
    reasons = {k: (args.reason[i] if i < len(args.reason) else '')
               for i, k in enumerate(excluded)}
    excluded_set = set(excluded)

    d = json.load(open(args.src, encoding='utf-8'))
    branches, nodes = d['branches'], d['nodes']

    # ---- 1. 被删分支、线段、节点 ----
    removed_branches = [b for b in branches if b['key'] in excluded_set]
    found = {b['key'] for b in removed_branches}
    missing = excluded_set - found
    if missing:
        fail(f'布局里没有这些分支：{sorted(missing)}')
    removed_segs = {pc['seg'] for b in removed_branches
                    for pc in b['pieces']}
    n_pieces = sum(len(b['pieces']) for b in removed_branches)
    len_3d_removed = sum(b.get('len_3d', 0.0) for b in removed_branches)
    # 节点：全部相连段都属于被删分支（且至少沾一段）
    node_branch = {}
    for b in branches:
        for pc in b['pieces']:
            node_branch.setdefault(pc['na'], set()).add(b['key'])
            node_branch.setdefault(pc['nb'], set()).add(b['key'])
    removed_nodes = sorted(
        n['code'] for n in nodes
        if node_branch.get(n['code'])
        and node_branch[n['code']] <= excluded_set)
    removed_nodes_set = set(removed_nodes)

    # ---- 2. 脊线：全部分支都被删的脊线（须是 0 级根脊线，否则侧枝计数会错） ----
    removed_spines = [s for s in d.get('spines', [])
                      if s['branches'] and set(s['branches']) <= excluded_set]
    for s in removed_spines:
        if s['level'] != 0:
            fail(f"脊线 {s['id']}（{s['branches']}）不是 0 级根脊线，"
                 '删它会动侧枝计数，本脚本不处理')
    removed_spine_ids = {s['id'] for s in removed_spines}
    # 被删分支须都在被删脊线里（否则 H6 的"脊线内分支"减数不对）
    spined = {k for s in removed_spines for k in s['branches']}
    if not set(found) <= spined:
        fail(f'被删分支 {sorted(set(found) - spined)} 不在任何被删脊线里')

    # ---- 3. 结构字段清理 ----
    d['branches'] = [b for b in branches if b['key'] not in excluded_set]
    d['nodes'] = [n for n in nodes if n['code'] not in removed_nodes_set]
    d['spines'] = [s for s in d.get('spines', [])
                   if s['id'] not in removed_spine_ids]
    d['bends'] = [b for b in d.get('bends', [])
                  if b.get('branch') not in excluded_set]
    tree = d.get('tree', {})
    for k in excluded:
        tree.pop(k, None)
    proj_nodes = d.get('projection', {}).get('nodes', {})
    for c in removed_nodes:
        proj_nodes.pop(c, None)
    # 环分类：整条目全是被删分支的段才删（混着的不动）
    cycles = d.get('cycles', {})
    for comp, entry in list(cycles.items()):
        all_segs = [s for ring in entry.get('rings', []) for s in ring]
        all_segs += list(entry.get('self_loops', []))
        for pair in entry.get('parallel_pairs', []):
            all_segs += list(pair)
        if all_segs and all(s in removed_segs for s in all_segs):
            del cycles[comp]
    # 阶段日志：删掉提及被删分支的条目，追加一条排除记录
    phase_log = d.get('phase_log', [])
    d['phase_log'] = [
        e for e in phase_log
        if not any(k in json.dumps(e, ensure_ascii=False) for k in excluded)]
    n_b0, n_n0 = len(branches), len(nodes)
    next_seq = max((e.get('seq', 0) for e in d['phase_log']), default=0) + 1
    d['phase_log'].append({
        'seq': next_seq, 'phase': '排除过孔零件',
        'msg': ('§二十二：' + '、'.join(excluded)
                + '（过孔零件，非路径）已从布局删除：分支 '
                + f"{n_b0}→{len(d['branches'])}，节点 "
                + f"{n_n0}→{len(d['nodes'])}"),
    })
    d.setdefault('meta', {})['excluded_branches'] = [
        {'key': k, 'reason': reasons.get(k, '')} for k in excluded]

    # ---- 4. 统计 ----
    st = d['stats']
    st['branches_total'] -= len(removed_branches)
    st['nodes_total'] -= len(removed_nodes)
    st['branches_placed'] = len(d['branches'])
    st['nodes_placed'] = len(d['nodes'])
    st['total_len_3d'] = round(st['total_len_3d'] - len_3d_removed, 1)
    st['len_errs'] = [e for e in st.get('len_errs', [])
                      if e[0] not in excluded_set]
    st['max_len_err_mm'] = round(
        max((abs(e[3]) for e in st['len_errs']), default=0.0), 2)
    st['spines'] = len(d['spines'])
    if 'bends' in st:
        st['bends'] = len(d['bends'])

    # ---- 5. 清单（只改受影响的数字与条目，其余原样） ----
    ck = d.get('checklist', {})
    hard = {it['id']: it for it in ck.get('hard', [])}
    soft = {it['id']: it for it in ck.get('soft', [])}

    def sub_once(text, pattern, repl, what):
        new, n = re.subn(pattern, repl, text, count=1)
        if n != 1:
            fail(f'{what}：模式 {pattern!r} 在清单里没匹配上（格式变了？）')
        return new

    # H2：最大误差分支重算（与 run_checklist 同口径：按 -|误差|、分支名排序取首）
    if 'H2' in hard and st['len_errs']:
        w = sorted(st['len_errs'], key=lambda t: (-abs(t[3]), t[0]))[0]
        worst = (f"（最大误差分支 {w[0]}，3D {w[1]:.1f}mm → "
                 f"2D {w[2]:.1f}mm，误差 {w[3]:+.2f}mm）")
        v = hard['H2']['value']
        v = sub_once(v, r'最大误差 [\d.]+mm',
                     f"最大误差 {st['max_len_err_mm']:.2f}mm", 'H2 最大误差')
        v = sub_once(v, r'（最大误差分支 [^）]*）', worst.replace('\\', '\\\\'),
                     'H2 最大误差分支')
        hard['H2']['value'] = v
    # H3：分支-关节端点减被删分支的关节数（每分支 = 段数 + 1）
    if 'H3' in hard:
        n_joints = sum(len(b['pieces']) + 1 for b in removed_branches)
        m = re.search(r'核对 (\d+) 个分支-关节端点', hard['H3']['value'])
        if not m:
            fail('H3：没找到"核对 N 个分支-关节端点"')
        hard['H3']['value'] = hard['H3']['value'].replace(
            m.group(0), f"核对 {int(m.group(1)) - n_joints} 个分支-关节端点")
    # H5：分支/节点/线段三组数各减，末尾加排除说明
    if 'H5' in hard:
        v = hard['H5']['value']
        m = re.search(r'分支 (\d+)/(\d+) ', v)
        if not m:
            fail('H5：没找到"分支 N/M"')
        v = v.replace(m.group(0),
                      f"分支 {int(m.group(1)) - len(removed_branches)}"
                      f"/{int(m.group(2)) - len(removed_branches)} ")
        m = re.search(r'节点 (\d+)/(\d+)', v)
        if not m:
            fail('H5：没找到"节点 N/M"')
        v = v.replace(m.group(0),
                      f"节点 {int(m.group(1)) - len(removed_nodes)}"
                      f"/{int(m.group(2)) - len(removed_nodes)}")
        m = re.search(r'线段 (\d+)/(\d+) ', v)
        if not m:
            fail('H5：没找到"线段 N/M"')
        v = v.replace(m.group(0),
                      f"线段 {int(m.group(1)) - n_pieces}"
                      f"/{int(m.group(2)) - n_pieces} ")
        v += ('；已排除过孔零件 ' + '、'.join(excluded)
              + '（§二十二，不画，不计入应画数）')
        hard['H5']['value'] = v
    # H6：脊线内分支与总数各减被删分支数
    if 'H6' in hard:
        m = re.search(r'脊线内分支 (\d+) \+ 未分配 (\d+) = (\d+)',
                      hard['H6']['value'])
        if not m:
            fail('H6：没找到"脊线内分支 A + 未分配 B = C"')
        hard['H6']['value'] = hard['H6']['value'].replace(
            m.group(0),
            f"脊线内分支 {int(m.group(1)) - len(removed_branches)}"
            f" + 未分配 {m.group(2)}"
            f" = {int(m.group(3)) - len(removed_branches)}")
    # H7：投影节点减被删节点数
    if 'H7' in hard:
        m = re.search(r'投影节点 (\d+)/(\d+)', hard['H7']['value'])
        if not m:
            fail('H7：没找到"投影节点 N/M"')
        hard['H7']['value'] = hard['H7']['value'].replace(
            m.group(0),
            f"投影节点 {int(m.group(1)) - len(removed_nodes)}"
            f"/{int(m.group(2)) - len(removed_nodes)}")
    # H10：脊线总数减，删掉被删脊线的明细与闭环条款（无环剩下时）
    if 'H10' in hard:
        v = hard['H10']['value']
        m = re.search(r'闭环脊线 \[([^\]]*)\]',
                      hard['H10']['value'])
        ring_ids = set()
        if m and m.group(1).strip():
            ring_ids = {int(x) for x in m.group(1).split(',')}
        ring_left = ring_ids - removed_spine_ids
        v = sub_once(v, r'^\d+ 条脊线', f"{len(d['spines'])} 条脊线",
                     'H10 脊线总数')
        for sid in sorted(removed_spine_ids):
            v = sub_once(v, rf'；脊线{sid} [^；]*）', '', f'H10 脊线{sid} 明细')
        if not ring_left:
            v = sub_once(v, r'；闭环脊线 \[[^\]]*\] 按 §六整体画环（不计拉直）',
                         '', 'H10 闭环条款')
            hard['H10']['threshold'] = hard['H10']['threshold'].replace(
                '；闭环脊线按 §六整体画环，不适用本条', '')
        elif ring_ids != ring_left:
            v = v.replace(f'闭环脊线 {sorted(ring_ids)}',
                          f'闭环脊线 {sorted(ring_left)}')
        hard['H10']['value'] = v
    # S3：干涉拐弯 = 剩余拐弯数
    if 'S3' in soft:
        soft['S3']['value'] = f"{len(d['bends'])} 次"
    # S4：真环减被删的闭环分支数（首末节点相同）
    if 'S4' in soft:
        n_rings = sum(1 for b in removed_branches
                      if b.get('node0') == b.get('node1'))
        m = re.search(r'真环 (\d+) 个，自环 (\d+) 个，平行对 (\d+) 个；'
                      r'已画真环 (\d+) 个；', soft['S4']['value'])
        if not m:
            fail('S4：没找到环分类计数')
        soft['S4']['value'] = soft['S4']['value'].replace(
            m.group(0),
            f"真环 {int(m.group(1)) - n_rings} 个，"
            f"自环 {m.group(2)} 个，平行对 {m.group(3)} 个；"
            f"已画真环 {int(m.group(4)) - n_rings} 个；")
        soft['S4']['note'] = ('真环 ' + '、'.join(excluded)
                              + ' 为过孔零件（§二十二），已排除不画；'
                                '其余无真实几何环')
    # S9：脊线总数减（侧枝数不变：删的是根脊线）
    if 'S9' in soft:
        m = re.search(r'脊线 (\d+) 条（主干 1 \+ 侧枝 (\d+)）',
                      soft['S9']['value'])
        if not m:
            fail('S9：没找到"脊线 N 条（主干 1 + 侧枝 M）"')
        soft['S9']['value'] = soft['S9']['value'].replace(
            m.group(0),
            f"脊线 {len(d['spines'])} 条（主干 1 + 侧枝 {m.group(2)}）")

    # ---- 6. 验残留：结构字段里不许再有被删分支/节点/线段 ----
    bad_fields = []
    structural = {k: v for k, v in d.items()
                  if k not in ('checklist', 'phase_log', 'meta')}
    blob_targets = set(excluded) | removed_nodes_set | removed_segs

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                yield from walk(v, path + '/' + str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                yield from walk(v, path + '[%d]' % i)
        elif isinstance(o, str) and o in blob_targets:
            yield path, o

    for path, val in walk(structural, ''):
        bad_fields.append((path, val))
    if bad_fields:
        fail(f"结构字段仍有残留：{bad_fields[:5]}")

    with open(args.dst, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"已删分支 {sorted(found)}（{n_pieces} 段，3D 长 {len_3d_removed}mm）")
    print(f"已删节点 {removed_nodes}")
    print(f"已删脊线 {sorted(removed_spine_ids)}，拐弯 {len(d['bends'])} 处剩余")
    print(f"分支 {n_b0}→{len(d['branches'])}，节点 {n_n0}→{len(d['nodes'])}，"
          f"脊线 {len(d['spines'])} 条")
    print(f"已写 {args.dst}")


if __name__ == '__main__':
    main()
