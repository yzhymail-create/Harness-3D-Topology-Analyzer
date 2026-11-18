#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环分类单测（v4 新增 3）：用合成数据验证 find_cycles 的三类区分
（真环 / 自环 / 平行对）与真环完整画环（不剪口）。

用法：python3 test_ring_classification.py
通过则退出码 0，并写 test_ring_result.json（供 unfold_2d_v4.py 的清单 S4 引用）。
"""
import json, os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unfold_2d_v3 import Topo, Layout, dist


def _write_topo(path, nodes, segments, branches):
    data = {'nodes': nodes, 'segments': segments, 'branches': branches,
            'runs': [], 'connectors': [], 'relations': [], 'ignored_contacts': []}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def _node(code, x, y, z=0.0, t='fork'):
    return {'code': code, 'type': t, 'name_3d': '', 'xyz': [x, y, z]}


def _seg(seg, branch, na, nb, length, dia=5.0):
    return {'seg': seg, 'branch': branch, 'na': na, 'nb': nb,
            'length': length, 'dia': dia}


def _branch(key, node0, node1, length, segs, dia=5.0):
    return {'key': key, 'node0': node0, 'node1': node1,
            'length': length, 'dia': dia, 'segs': segs}


def test_true_ring(tmp):
    """合成真环：4 节点方形环（每边 100mm）+ 1 根尾巴（50mm）。
    分类：真环 1 个、自环 0、平行对 0；画环：闭合多边形、周长 400mm、长度保真。"""
    p = os.path.join(tmp, 'synth_ring.json')
    nodes = [_node('N1', 0, 0), _node('N2', 100, 0), _node('N3', 100, 100),
             _node('N4', 0, 100), _node('N5', 0, 150, t='connector')]
    segs = [_seg('S1', 'B1', 'N1', 'N2', 100.0),
            _seg('S2', 'B2', 'N2', 'N3', 100.0),
            _seg('S3', 'B3', 'N3', 'N4', 100.0),
            _seg('S4', 'B4', 'N4', 'N1', 100.0),
            _seg('S5', 'B5', 'N1', 'N5', 50.0)]
    branches = [_branch('B1', 'N1', 'N2', 100.0, ['S1']),
                _branch('B2', 'N2', 'N3', 100.0, ['S2']),
                _branch('B3', 'N3', 'N4', 100.0, ['S3']),
                _branch('B4', 'N4', 'N1', 100.0, ['S4']),
                _branch('B5', 'N1', 'N5', 50.0, ['S5'])]
    _write_topo(p, nodes, segs, branches)
    topo = Topo(p)
    rings, sl, pp = topo.find_cycles(list(topo.branches.keys()))
    assert len(rings) == 1, f"真环应为 1 个，实测 {len(rings)}"
    assert len(rings[0]) == 4, f"真环应为 4 段，实测 {len(rings[0])}"
    assert len(sl) == 0 and len(pp) == 0, f"自环/平行对应为 0，实测 {len(sl)}/{len(pp)}"
    layout = Layout(topo).run()
    assert len(layout.rings_drawn) == 1, "应画出 1 个真环"
    assert len(layout.placed) == 5, f"应画出 5 根分支，实测 {len(layout.placed)}"
    # 环闭合：4 个环节点各不相同；每段 2D 长度均为 100mm，周长 400mm
    ring_nodes = layout.rings_drawn[0]['nodes']
    assert len(set(ring_nodes)) == 4, f"环节点应为 4 个不同节点，实测 {ring_nodes}"
    per = 0.0
    for sg in layout.rings_drawn[0]['segs']:
        p1, p2 = layout.piece_pos[sg]
        assert abs(dist(p1, p2) - 100.0) < 0.01, f"{sg} 2D 长应为 100mm"
        per += dist(p1, p2)
    assert abs(per - 400.0) < 0.05, f"环周长应为 400mm，实测 {per:.2f}"
    st = layout.validate()
    assert st['max_len_err_mm'] <= 0.01, f"长度误差应≈0，实测 {st['max_len_err_mm']}"
    return '真环：分类 1/0/0 正确，画环闭合（周长 400mm），5/5 画出，长度误差 0'


def test_parallel_and_selfloop(tmp):
    """平行对 + 自环：A-B 间两段平行（60/80mm），A 上一自环段（30mm），B 外接尾巴。
    分类：真环 0、自环 1、平行对 1。"""
    p = os.path.join(tmp, 'synth_par.json')
    nodes = [_node('A', 0, 0), _node('B', 100, 0), _node('C', 160, 0, t='connector')]
    segs = [_seg('P1', 'BP1', 'A', 'B', 60.0),
            _seg('P2', 'BP2', 'A', 'B', 80.0),
            _seg('L1', 'BL', 'A', 'A', 30.0),
            _seg('T1', 'BT', 'B', 'C', 60.0)]
    branches = [_branch('BP1', 'A', 'B', 60.0, ['P1']),
                _branch('BP2', 'A', 'B', 80.0, ['P2']),
                _branch('BL', 'A', 'A', 30.0, ['L1']),
                _branch('BT', 'B', 'C', 60.0, ['T1'])]
    _write_topo(p, nodes, segs, branches)
    topo = Topo(p)
    rings, sl, pp = topo.find_cycles(list(topo.branches.keys()))
    assert len(rings) == 0, f"真环应为 0，实测 {len(rings)}"
    assert len(sl) == 1 and sl[0] == 'L1', f"自环应为 [L1]，实测 {sl}"
    assert len(pp) == 1, f"平行对应为 1，实测 {len(pp)}"
    layout = Layout(topo).run()
    assert len(layout.placed) == 4, f"应画出 4 根分支，实测 {len(layout.placed)}"
    st = layout.validate()
    assert st['max_len_err_mm'] <= 0.01, f"长度误差应≈0，实测 {st['max_len_err_mm']}"
    return '平行对+自环：分类 0/1/1 正确，4/4 画出，长度误差 0'


def _write_result(passed, details):
    out = {
        'passed': passed,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'details': details,
    }
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'test_ring_result.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return p


def main():
    tmp = '/tmp/unfold_v4_ring_test'
    os.makedirs(tmp, exist_ok=True)
    results = []
    try:
        results.append(test_true_ring(tmp))
        results.append(test_parallel_and_selfloop(tmp))
    except AssertionError as e:
        print(f"FAIL: {e}")
        _write_result(False, str(e))
        return 1
    for r in results:
        print(f"PASS: {r}")
    _write_result(True, '; '.join(results))
    print('全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
