#!/usr/bin/env python3
"""make_dxf.py — 2D 展开布局（layout.json）→ DXF 工程图（独立生成器）。

与 make_viewer.py 对应：viewer 读 layout.json 出网页版，本脚本读同一个
layout.json 出 CAD 能打开的 DXF。

块标准（2026-11-18，用户令，按源文件实测定义重写，取代旧 v2 五块做法）：
来源 ~/workspace/user/files/floor_topology_blocks_v5.dxf（R2000/AC1015），
块定义用 ezdxf 实读核准，不靠用户粘贴摘要（摘要有 3 处错：CONNECTOR 圆
r=5.0 不是 0.1；NODE 圆 r=3.0 不是 2.0；CONNECTOR 是 10 个 ATTDEF 不是
9 个）。SEGMENT 块源文件里没有，按用户摘要做，代码里标明未核实。

- DXF 版本 R2000（默认；用户 CAD 兼容性最好，R2010 打不开），毫米单位。
- 6 图层，每块独立一层（2026-11-18 18:02 用户定；FORK 层 19:43 后加）：
  TUBES(7) 管子、CONNECTOR(1)、NODE(5)、FORK(30)、LENGTH(3)、SEGMENT(2)。
  ATTDEF 在块定义内放块自己的图层，INSERT 与 ATTRIB 在模型空间放块的图层；
  冻住一层，那一类整个消失，不留飘着的名字。旧 6 层名
  （CONNECTORS/CLAMPS/FORKS/JOINTS/HANGING）与 TEXT/DIM 作废。
- 5 个块定义（位置是块内坐标，字高/颜色照源文件）：
  CONNECTOR：圆 (0,0) r=5.0 c256；TAG (0,0) h5 c4；NAME (0,-6) h5 c4；
    PARTNUMBER (0,-12) h5 c4；SUPPLIER (-1,-23.8) h5 c256；
    REMARK_001 (-0.4,-17.8) h5 c6；TYPE (-1,-29.4) h4 c256；
    OPTION (-1.2,-34.8) h4 c256；SEALED (-1.1,-39.8) h4 c256；
    PIN (-1,-44.8) h4 c256；CHANGED (0,6) h4 c1。
  NODE：圆 (0,0) r=3.0 c256；NAME (-3.1,-8.5) h5 c6；
    TYPE (-3.2,-14.6) h4 c256；CHANGED (-6.3,3.8) h4 c1。
  FORK：与 NODE 定义逐项相同（分支点单独成块，2026-11-18 19:37 用户定），
    只块名与图层不同。
  LENGTH（无几何，只有属性）：L (0,0) h4 c4；E1 (3.9,0) h4 c256；
    E2 (3.8,-4.9) h4 c256；PART_OF (-2.8,-8.6) h3 c3；
    TYPE (2.8,-12.1) h2.5 c256；CHANGED (-0.6,4.1) h4 c1。
  SEGMENT（未核实，见上）：L (0,0) h3 c2；E1 (13,0) h3 c2；E2 (13,-4) h3 c2；
    CHANGED (0,4) h3 c1。摘要里的 TEXT '=' 已删（E1/E2 隐藏后 '=' 悬在
    L 值后面没意义，见下显示规则）。
- 属性值映射（没有值的属性先留空，2026-11-18 18:02 用户定）：
  CONNECTOR（type=connector 的节点）：TAG=节点编号；NAME=真名短名
    （无真名或 Body. 开头填 ''）；其余 8 个全填 ''。
  NODE（clamp/joint/hanging 节点）：NAME=节点编号；TYPE=type 原值；
    CHANGED=''。
  FORK（分支点）：NAME=节点编号（即管线端点名——相连管子的 E1/E2 在此
    处统一用这个名，路由靠它串；有卡扣/连接器同点的用设备名，地板数据
    里 0 处，规则先记着）；TYPE='fork'；CHANGED=''。
  SEGMENT（每分支一个，管子的长度块，插在弧长中点，直接放线上）：
    L=3D 弧长（1 位小数）；E1=起点节点；E2=终点节点；CHANGED=''。
  LENGTH（只给多段分支的 piece 放，单段分支不放——单段时 piece 长度与整
    管长度完全相同，放了就是重复表达；插在 piece 中点沿法线向下偏移 16mm
    处）：L=piece 折线长度（1 位小数，布局是等长展开，2D≈3D）；E1=na；
    E2=nb；PART_OF=段自身端点对名 na_nb（如 BN01_CLP23，按左前门线束参考
    模型，2026-11-18 19:50 用户定改）；TYPE/CHANGED=''。
- 管子不是块：普通 LWPOLYLINE 直接画在模型空间（TUBES 层）；旧的纯文字
  长度标签删除，改由 SEGMENT 块承担。管子全名在 Excel 里。
- 属性显示规则（2026-11-18 19:21 用户定）：连接器/卡扣只显示名字
  （CONNECTOR/NODE 只显示 NAME），管线只显示长度（SEGMENT/LENGTH 只显示
  L）；其余属性照常写值，只加隐藏标记 flags=1，图上不显示、数据不丢，
  导属性表时还能取到。SEGMENT 的 TEXT '=' 已删（见上）。
- ATTRIB 位置必须是世界坐标（插入点＋块内偏移）：属性值在块参照“外面”，
  INSERT 不对它做变换；传块内坐标会让所有属性堆在原点（旧教训）。

图面短名规则：标签只画短名——取最后一个反斜杠后的部分，再去掉产品名前缀
（如 "Test FLOOR harness-"，同图内所有管子相同，是噪音）；全名仍在 Excel
里。2026-11-18 渲染自查：全名标签 45 字符起，图上互相重叠、盖住管子，没法
看，改短名后才可读。

交付前验证（先写临时文件→回读核对→通过才落盘，失败不写盘、退出码 1）：
- 图层核对：6 层齐全，旧层名（CONNECTORS/CLAMPS/FORKS/JOINTS/HANGING/
  TEXT/DIM）都不存在。
- 块定义核对：5 个块，圆半径/颜色、ATTDEF 数量/位置/字高/颜色/显示标记
  与源文件逐项一致，ATTDEF 在块自己的图层上。
- 多段线逐条回读：与布局分支点列逐点比对，≤0.01mm，每根管子恰好一条，
  都在 TUBES 层。
- INSERT 核对：CONNECTOR/NODE/FORK/LENGTH/SEGMENT 数量、位置、属性值与
  位置（世界坐标）与显示标记，INSERT 与 ATTRIB 都在块的图层上。
- 模型空间不应有 TEXT（旧纯文字标签已删）；ezdxf audit 0 错误。

用法：
    make_dxf.py <layout.json> <out.dxf> [--excel <out.xlsx>]
运行环境：plain python3 即可；ezdxf 不在系统 Python 里时用
~/workspace/.pylibs 兜底（同 v4/v5/v6p1 做法）。
"""
import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '/home/hatch/workspace/.pylibs')

from unfold_2d_v3 import arc_midpoint  # noqa: E402
from make_viewer import _label_name  # noqa: E402

DXF_VERSION = 'R2000'          # 用户 CAD 兼容性最好（SKILL.md）；R2010 打不开
DXF_READBACK_TOL_MM = 0.01     # 同 v6p1：逐块回读最大误差 ≤0.01mm

# 6 图层，每块独立一层（2026-11-18 18:02 用户定；FORK 层 19:43 后加，
# 分支点单独成块）
LAYERS = [
    ('TUBES', 7), ('CONNECTOR', 1), ('NODE', 5), ('FORK', 30),
    ('LENGTH', 3), ('SEGMENT', 2),
]

# 5 个块定义。CONNECTOR/NODE/LENGTH 按源文件
# ~/workspace/user/files/floor_topology_blocks_v5.dxf 用 ezdxf 实读核准
# （ATTDEF 元组：(tag, 块内位置, 字高, 颜色)；圆：(半径, 颜色)）。
# FORK 是 NODE 的复刻（分支点单独成块，2026-11-18 19:37 用户定；定义与
# NODE 逐项相同，只块名与图层不同，冻 NODE 层不影响分支点）。
# SEGMENT 未核实：源文件里没有，按用户粘贴摘要做；TEXT '=' 的位置摘要
# 没给，暂放 (10,0)（L 值和 E1 之间），是猜的，见需求说明 §二十三。
BLOCK_DEFS = {
    'CONNECTOR': {
        'layer': 'CONNECTOR',
        'circle': (5.0, 256),
        'attdefs': [
            ('NAME', (0.0, -6.0), 5.0, 4),
            ('TAG', (0.0, 0.0), 5.0, 4),
            ('PARTNUMBER', (0.0, -12.0), 5.0, 4),
            ('SUPPLIER', (-1.0, -23.8), 5.0, 256),
            ('REMARK_001', (-0.4, -17.8), 5.0, 6),
            ('TYPE', (-1.0, -29.4), 4.0, 256),
            ('OPTION', (-1.2, -34.8), 4.0, 256),
            ('SEALED', (-1.1, -39.8), 4.0, 256),
            ('PIN', (-1.0, -44.8), 4.0, 256),
            ('CHANGED', (0.0, 6.0), 4.0, 1),
        ],
        'text': None,
    },
    'NODE': {
        'layer': 'NODE',
        'circle': (3.0, 256),
        'attdefs': [
            ('NAME', (-3.1, -8.5), 5.0, 6),
            ('TYPE', (-3.2, -14.6), 4.0, 256),
            ('CHANGED', (-6.3, 3.8), 4.0, 1),
        ],
        'text': None,
    },
    'FORK': {
        'layer': 'FORK',
        'circle': (3.0, 256),
        'attdefs': [
            ('NAME', (-3.1, -8.5), 5.0, 6),
            ('TYPE', (-3.2, -14.6), 4.0, 256),
            ('CHANGED', (-6.3, 3.8), 4.0, 1),
        ],
        'text': None,
    },
    'LENGTH': {
        'layer': 'LENGTH',
        'circle': None,  # 无几何，只有属性
        'attdefs': [
            ('L', (0.0, 0.0), 4.0, 4),
            ('E1', (3.9, 0.0), 4.0, 256),
            ('E2', (3.8, -4.9), 4.0, 256),
            ('PART_OF', (-2.8, -8.6), 3.0, 3),
            ('TYPE', (2.8, -12.1), 2.5, 256),
            ('CHANGED', (-0.6, 4.1), 4.0, 1),
        ],
        'text': None,
    },
    'SEGMENT': {
        'layer': 'SEGMENT',
        'circle': None,
        'attdefs': [
            ('L', (0.0, 0.0), 3.0, 2),
            ('E1', (13.0, 0.0), 3.0, 2),
            ('E2', (13.0, -4.0), 3.0, 2),
            ('CHANGED', (0.0, 4.0), 3.0, 1),
        ],
        # TEXT '=' 已删（2026-11-18 19:21 用户定管线只显示长度后，E1/E2 隐藏，
        # '=' 悬在 L 值后面没意义；摘要里的 '=' 本就未核实，如需恢复把下面
        # 改回 ('=', (10.0, 0.0), 3.0, 2)）。
        'text': None,
    },
}

# 每块显示的属性（2026-11-18 19:21 用户定：连接器/卡扣只显示名字，
# 管线只显示长度；其余属性照常写值，只加隐藏标记 flags=1，数据不丢，
# CAD 里不显示、导属性表时还能取到）。
VISIBLE_ATTRS = {
    'CONNECTOR': {'NAME'},
    'NODE': {'NAME'},
    'FORK': {'NAME'},
    'LENGTH': {'L'},
    'SEGMENT': {'L'},
}

# 节点类型 → 块：连接器用 CONNECTOR 块，分支点单独用 FORK 块
# （2026-11-18 19:37 用户定），其余节点类型用 NODE 块
NODE_BLOCK = {'connector': 'CONNECTOR', 'clamp': 'NODE', 'fork': 'FORK',
              'joint': 'NODE', 'hanging': 'NODE'}

SEGMENT_OFFSET_MM = 16.0  # SEGMENT 块沿法线向下偏移，避免与同中点 LENGTH 块重叠


def _short_tail(key):
    """图面短名：取最后一个反斜杠后的部分；再去掉产品名前缀（如
    "Test FLOOR harness-"，同图内所有管子相同，是噪音）。全名仍在
    Excel 里，不丢。"""
    tail = key.rsplit('\\', 1)[-1]
    if 'harness-' in tail:
        tail = tail.rsplit('harness-', 1)[-1]
    return tail


def _node_fullname(n):
    """节点真名短名（无真名或 Body. 开头返回 ''）。"""
    nm = n.get('name_3d') or ''
    if not nm or nm.startswith('Body.'):
        return ''
    return _short_tail(_label_name(nm))


def _piece_len(pts):
    """piece 折线长度（布局是等长展开，2D 折线长 ≈ 3D 弧长）。"""
    return sum(math.hypot(pts[i + 1][0] - pts[i][0],
                          pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))


def _piece_place(pts):
    """LENGTH 块插入点：piece 弧长中点，沿 piece 方向法线向下偏移 16mm。
    法线 n=(-dy,dx)/L，若 n.y>0 则取反，保证始终朝下。返回 (ix, iy)。"""
    mid = arc_midpoint(pts)
    dx = pts[-1][0] - pts[0][0]
    dy = pts[-1][1] - pts[0][1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return mid[0], mid[1] - SEGMENT_OFFSET_MM  # 退化 piece，法线直接朝下
    nx, ny = -dy / L, dx / L
    if ny > 0:
        nx, ny = -nx, -ny
    return mid[0] + nx * SEGMENT_OFFSET_MM, mid[1] + ny * SEGMENT_OFFSET_MM


def _connector_values(n):
    """CONNECTOR 属性值：TAG=编号，NAME=真名短名，其余先留空（用户定）。"""
    return {'TAG': n['code'], 'NAME': _node_fullname(n),
            'PARTNUMBER': '', 'SUPPLIER': '', 'REMARK_001': '',
            'TYPE': '', 'OPTION': '', 'SEALED': '', 'PIN': '', 'CHANGED': ''}


def _node_values(n):
    """NODE 属性值：NAME=编号，TYPE=类型原值，CHANGED 留空。"""
    return {'NAME': n['code'], 'TYPE': n.get('type', ''), 'CHANGED': ''}


def _segment_values(b):
    """SEGMENT 属性值（管子的长度块，每分支一个）：L=3D 弧长，E1/E2=两端
    节点，CHANGED 留空。"""
    return {'L': f"{b['len_3d']:.1f}", 'E1': b['node0'], 'E2': b['node1'],
            'CHANGED': ''}


def _length_values(b, pc):
    """LENGTH 属性值（每 piece 一个）：L=piece 折线长，E1/E2=两端节点，
    PART_OF=段自身端点对名（na_nb，如 BN01_CLP23；2026-11-18 19:50 用户定
    按左前门线束参考模型改，原先填所属管子短名），TYPE/CHANGED 留空。"""
    pts = [(float(x), float(y)) for x, y in pc['pts']]
    return {'L': f"{_piece_len(pts):.1f}", 'E1': pc['na'], 'E2': pc['nb'],
            'PART_OF': f"{pc['na']}_{pc['nb']}", 'TYPE': '', 'CHANGED': ''}


def _add_attribs(ins, blk_name, values, ix, iy):
    """给 INSERT 加全部属性。ATTRIB 位置是世界坐标（插入点＋块内偏移）：
    属性值在块参照“外面”，INSERT 不对它做变换；传块内坐标会全堆原点。"""
    spec = BLOCK_DEFS[blk_name]
    layer = spec['layer']
    for tag, (dx, dy), h, c in spec['attdefs']:
        flags = 0 if tag in VISIBLE_ATTRS[blk_name] else 1
        ins.add_attrib(tag, values.get(tag, ''), (ix + dx, iy + dy),
                       dxfattribs={'layer': layer, 'color': c, 'height': h,
                                   'flags': flags})


def write_dxf_from_layout(d, out_path):
    """读 layout.json 字典写 DXF（新块标准：4 块各占一层）。"""
    import ezdxf

    branches = d['branches']
    nodes = d['nodes']
    for b in branches:
        assert len(b['points']) >= 2, f"分支点列不足 2 点：{b['key']}"

    doc = ezdxf.new(DXF_VERSION)
    doc.units = ezdxf.units.MM
    for name, color in LAYERS:
        doc.layers.add(name, color=color)
    msp = doc.modelspace()

    # --- 5 个块定义 ---
    for blk_name, spec in BLOCK_DEFS.items():
        blk = doc.blocks.new(name=blk_name)
        if spec['circle'] is not None:
            r, c = spec['circle']
            blk.add_circle((0, 0), r,
                           dxfattribs={'layer': spec['layer'], 'color': c})
        for tag, pos, h, c in spec['attdefs']:
            flags = 0 if tag in VISIBLE_ATTRS[blk_name] else 1
            blk.add_attdef(tag, pos, '', height=h,
                           dxfattribs={'layer': spec['layer'], 'color': c,
                                       'flags': flags})
        if spec['text'] is not None:
            txt, pos, h, c = spec['text']
            blk.add_text(txt, height=h,
                         dxfattribs={'layer': spec['layer'], 'color': c}
                         ).set_placement(pos)

    # --- 管子：普通多段线直接画在模型空间（不是块），TUBES 层 ---
    # 旧的纯文字长度标签已删，改由 SEGMENT 块承担。
    for b in branches:
        pts = [(float(x), float(y)) for x, y in b['points']]
        msp.add_lwpolyline(pts, dxfattribs={'layer': 'TUBES'})

    # --- 节点：CONNECTOR / NODE / FORK，插在节点坐标 ---
    for n in nodes:
        t = n.get('type', '?')
        if t not in NODE_BLOCK:
            raise ValueError(f"未知节点类型 {t!r}（节点 {n['code']}），"
                             f"没有对应的块定义，不写盘")
        blk_name = NODE_BLOCK[t]
        layer = BLOCK_DEFS[blk_name]['layer']
        nx, ny = float(n['x']), float(n['y'])
        ins = msp.add_blockref(blk_name, insert=(nx, ny),
                               dxfattribs={'layer': layer})
        values = (_connector_values(n) if blk_name == 'CONNECTOR'
                  else _node_values(n))
        _add_attribs(ins, blk_name, values, nx, ny)

    # --- SEGMENT：管子的长度块，每分支一个，插在弧长中点，直接放线上 ---
    for b in branches:
        pts = [(float(x), float(y)) for x, y in b['points']]
        mx, my = arc_midpoint(pts)
        ins = msp.add_blockref('SEGMENT', insert=(mx, my),
                               dxfattribs={'layer': 'SEGMENT'})
        _add_attribs(ins, 'SEGMENT', _segment_values(b), mx, my)

    # --- LENGTH：只给多段分支的 piece 放（单段分支的 piece 长度与整管
    # 长度完全相同，放了就是重复表达，用户 2026-11-18 19:03 指出后改掉） ---
    for b in branches:
        if len(b.get('pieces', [])) <= 1:
            continue
        for pc in b.get('pieces', []):
            pts = [(float(x), float(y)) for x, y in pc['pts']]
            ix, iy = _piece_place(pts)
            ins = msp.add_blockref('LENGTH', insert=(ix, iy),
                                   dxfattribs={'layer': 'LENGTH'})
            _add_attribs(ins, 'LENGTH', _length_values(b, pc), ix, iy)

    doc.saveas(out_path)
    return out_path


def _decode_dxf_text(s):
    """解码 DXF 的 \\U+XXXX 转义：R2000 文件不是 UTF-8，ezdxf 写中文时转成
    \\U+XXXX 形式（CAD 打开时自动解码，文件本身是对的），但 ezdxf 读回时
    不反解，核对前须自己解回来。"""
    return re.sub(r'\\U\+([0-9a-fA-F]{4})',
                  lambda m: chr(int(m.group(1), 16)), s)


def _pts_key(pts):
    return tuple((round(float(x), 2), round(float(y), 2)) for x, y in pts)


def _check_attribs(ins, blk_name, want_values, ix, iy, what, max_err):
    """核对一个 INSERT 的全部属性：值、位置（世界坐标）、图层。
    返回 (ok, err_msg_or_None, new_max_err)。"""
    spec = BLOCK_DEFS[blk_name]
    layer = spec['layer']
    atts = {a.dxf.tag: a for a in ins.attribs}
    for tag, (dx, dy), h, c in spec['attdefs']:
        a = atts.get(tag)
        if a is None:
            return False, f"{what} 缺 {tag} 属性", max_err
        if _decode_dxf_text(a.dxf.text) != want_values.get(tag, ''):
            return False, (f"{what} 的 {tag} 属性值不对："
                           f"{_decode_dxf_text(a.dxf.text)!r}，应为 "
                           f"{want_values.get(tag, '')!r}"), max_err
        if a.dxf.layer != layer:
            return False, (f"{what} 的 {tag} 属性图层不对：{a.dxf.layer}，"
                           f"应为 {layer}"), max_err
        perr = math.hypot(a.dxf.insert.x - (ix + dx),
                          a.dxf.insert.y - (iy + dy))
        max_err = max(max_err, perr)
        if perr > DXF_READBACK_TOL_MM:
            return False, (f"{what} 的 {tag} 属性位置不对："
                           f"({a.dxf.insert.x:.1f},{a.dxf.insert.y:.1f})，"
                           f"应在 ({ix + dx:.1f},{iy + dy:.1f})"), max_err
        if abs(a.dxf.height - h) > 1e-6:
            return False, (f"{what} 的 {tag} 属性字高不对：{a.dxf.height}，"
                           f"应为 {h}"), max_err
        if a.dxf.color != c:
            return False, (f"{what} 的 {tag} 属性颜色不对：{a.dxf.color}，"
                           f"应为 {c}"), max_err
        want_flags = 0 if tag in VISIBLE_ATTRS[blk_name] else 1
        if a.dxf.flags != want_flags:
            return False, (f"{what} 的 {tag} 属性显示标记不对："
                           f"flags={a.dxf.flags}，应为 {want_flags}"), max_err
    return True, None, max_err


def verify_dxf(d, dxf_path):
    """交付前验证（回读核对）。返回 (pass, [detail 行])。"""
    import ezdxf
    details = []
    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as e:
        return False, [f"DXF 读回失败：{e}"]
    msp = doc.modelspace()

    # --- 图层：6 层都在，旧层名不应存在 ---
    layer_names = {l.dxf.name for l in doc.layers}
    for name, _c in LAYERS:
        if name not in layer_names:
            return False, [f"缺图层：{name}"]
    for gone in ('CONNECTORS', 'CLAMPS', 'FORKS', 'JOINTS', 'HANGING',
                 'TEXT', 'DIM', 'NODES'):
        if gone in layer_names:
            return False, [f"不应存在的旧图层还在：{gone}"]
    details.append("图层：TUBES/CONNECTOR/NODE/FORK/LENGTH/SEGMENT 6 层齐全，"
                   "无旧层名")

    # --- 块定义：5 个块，圆与 ATTDEF 与源文件逐项一致 ---
    for blk_name, spec in BLOCK_DEFS.items():
        blk = doc.blocks.get(blk_name)
        if blk is None:
            return False, [f"缺块定义：{blk_name}"]
        circles = [e for e in blk if e.dxftype() == 'CIRCLE']
        if spec['circle'] is None:
            if circles:
                return False, [f"块 {blk_name} 不应有圆"]
        else:
            if len(circles) != 1:
                return False, [f"块 {blk_name} 圆数不对：{len(circles)}"]
            r, c = spec['circle']
            if abs(circles[0].dxf.radius - r) > 1e-6:
                return False, [f"块 {blk_name} 圆半径不对："
                               f"{circles[0].dxf.radius}，应为 {r}"]
            if circles[0].dxf.color != c:
                return False, [f"块 {blk_name} 圆颜色不对："
                               f"{circles[0].dxf.color}，应为 {c}"]
        got = {(e.dxf.tag): e for e in blk if e.dxftype() == 'ATTDEF'}
        want_tags = [t for t, _p, _h, _c in spec['attdefs']]
        if sorted(got) != sorted(want_tags):
            return False, [f"块 {blk_name} 属性定义不对：{sorted(got)}，"
                           f"应为 {sorted(want_tags)}"]
        for tag, (px, py), h, c in spec['attdefs']:
            e = got[tag]
            if (abs(e.dxf.insert.x - px) > 1e-6
                    or abs(e.dxf.insert.y - py) > 1e-6):
                return False, [f"块 {blk_name} 的 {tag} 位置不对："
                               f"({e.dxf.insert.x},{e.dxf.insert.y})，"
                               f"应为 ({px},{py})"]
            if abs(e.dxf.height - h) > 1e-6:
                return False, [f"块 {blk_name} 的 {tag} 字高不对："
                               f"{e.dxf.height}，应为 {h}"]
            if e.dxf.color != c:
                return False, [f"块 {blk_name} 的 {tag} 颜色不对："
                               f"{e.dxf.color}，应为 {c}"]
            if e.dxf.layer != spec['layer']:
                return False, [f"块 {blk_name} 的 {tag} 定义图层不对："
                               f"{e.dxf.layer}，应为 {spec['layer']}"]
            want_flags = 0 if tag in VISIBLE_ATTRS[blk_name] else 1
            if e.dxf.flags != want_flags:
                return False, [f"块 {blk_name} 的 {tag} 定义显示标记不对："
                               f"flags={e.dxf.flags}，应为 {want_flags}"]
        texts = [e for e in blk if e.dxftype() == 'TEXT']
        if spec['text'] is None:
            if texts:
                return False, [f"块 {blk_name} 不应有 TEXT"]
        else:
            if len(texts) != 1:
                return False, [f"块 {blk_name} TEXT 数不对：{len(texts)}"]
            txt, (px, py), h, c = spec['text']
            t = texts[0]
            if t.dxf.text != txt:
                return False, [f"块 {blk_name} TEXT 内容不对：{t.dxf.text!r}，"
                               f"应为 {txt!r}"]
            if (abs(t.dxf.insert.x - px) > 1e-6
                    or abs(t.dxf.insert.y - py) > 1e-6):
                return False, [f"块 {blk_name} TEXT 位置不对"]
            if abs(t.dxf.height - h) > 1e-6 or t.dxf.color != c:
                return False, [f"块 {blk_name} TEXT 字高/颜色不对"]
    details.append("块定义：5 个块，圆/ATTDEF/显示标记与源文件逐项一致，"
                   "定义在各自块的图层上")

    # --- 多段线：逐条与布局分支点列比对 ---
    expect = {}
    for i, b in enumerate(d['branches']):
        k = _pts_key(b['points'])
        if k in expect:
            return False, [f"两根管子点列完全相同，无法区分："
                           f"{d['branches'][expect[k]]['key'][:30]} 与 "
                           f"{b['key'][:30]}"]
        expect[k] = i
    polys = list(msp.query('LWPOLYLINE'))
    if len(polys) != len(d['branches']):
        return False, [f"多段线数不对：DXF {len(polys)} vs 布局 "
                       f"{len(d['branches'])}"]
    for poly in polys:
        if poly.dxf.layer != 'TUBES':
            return False, ["有多段线不在 TUBES 图层"]
    seen = set()
    max_err = 0.0
    worst = None
    for poly in polys:
        got = _pts_key(poly.get_points('xy'))
        if got not in expect:
            return False, ["有一条多段线在布局里找不到对应的管子"]
        i = expect[got]
        if i in seen:
            return False, [f"管子重复画了：{d['branches'][i]['key'][:40]}"]
        seen.add(i)
        exp = [(float(x), float(y)) for x, y in d['branches'][i]['points']]
        for (gx, gy), (ex, ey) in zip(
                [(float(x), float(y)) for x, y in poly.get_points('xy')], exp):
            err = math.hypot(gx - ex, gy - ey)
            if err > max_err:
                max_err = err
                worst = d['branches'][i]['key']
    if len(seen) != len(d['branches']):
        return False, [f"多段线缺 {len(d['branches']) - len(seen)} 根管子"]
    if max_err > DXF_READBACK_TOL_MM:
        return False, [f"多段线最大误差 {max_err:.4f}mm，超 0.01mm"]
    details.append(f"多段线：{len(polys)}/{len(d['branches'])} 条，"
                   f"最大误差 {max_err:.4f}mm"
                   + (f"（{worst[:40]}）" if worst else ""))

    # --- INSERT：分 5 类核对数量、位置、属性值与位置、图层 ---
    ins_list = list(msp.query('INSERT'))
    by_block = {}
    for ins in ins_list:
        by_block.setdefault(ins.dxf.name, []).append(ins)
    for name in ('CONNECTOR', 'NODE', 'FORK', 'LENGTH', 'SEGMENT'):
        if name not in by_block:
            return False, [f"缺 {name} 块的 INSERT"]
    extra = set(by_block) - set(BLOCK_DEFS)
    if extra:
        return False, [f"有多余块的 INSERT：{extra}"]

    max_err = 0.0
    # CONNECTOR：按 TAG=编号对节点
    conns = {n['code']: n for n in d['nodes'] if n['type'] == 'connector'}
    if len(by_block['CONNECTOR']) != len(conns):
        return False, [f"CONNECTOR 数不对：DXF {len(by_block['CONNECTOR'])} "
                       f"vs 连接器节点 {len(conns)}"]
    seen = set()
    for ins in by_block['CONNECTOR']:
        atts = {a.dxf.tag: _decode_dxf_text(a.dxf.text) for a in ins.attribs}
        code = atts.get('TAG')
        if code not in conns:
            return False, [f"CONNECTOR 的 TAG 对不上节点：{code}"]
        if code in seen:
            return False, [f"连接器重复插入：{code}"]
        seen.add(code)
        n = conns[code]
        if ins.dxf.layer != 'CONNECTOR':
            return False, [f"节点 {code} 的 INSERT 图层不对：{ins.dxf.layer}"]
        err = math.hypot(ins.dxf.insert.x - n['x'],
                         ins.dxf.insert.y - n['y'])
        max_err = max(max_err, err)
        if err > DXF_READBACK_TOL_MM:
            return False, [f"节点 {code} 的 INSERT 位置不对"]
        ok, msg, max_err = _check_attribs(
            ins, 'CONNECTOR', _connector_values(n),
            n['x'], n['y'], f"CONNECTOR {code}", max_err)
        if not ok:
            return False, [msg]
    details.append(f"CONNECTOR：{len(by_block['CONNECTOR'])}/"
                   f"{len(conns)} 个，TAG/NAME 等 10 个属性值与位置全对")

    # NODE / FORK：按 NAME=编号对节点（分支点单独用 FORK 块）
    for blk_name, pred, label in (
            ('NODE', lambda t: t != 'connector' and t != 'fork',
             '非连接器非分支点'),
            ('FORK', lambda t: t == 'fork', '分支点')):
        nodes_of = {n['code']: n for n in d['nodes'] if pred(n['type'])}
        if len(by_block[blk_name]) != len(nodes_of):
            return False, [f"{blk_name} 数不对：DXF "
                           f"{len(by_block[blk_name])} "
                           f"vs {label}节点 {len(nodes_of)}"]
        seen = set()
        for ins in by_block[blk_name]:
            atts = {a.dxf.tag: _decode_dxf_text(a.dxf.text)
                    for a in ins.attribs}
            code = atts.get('NAME')
            if code not in nodes_of:
                return False, [f"{blk_name} 的 NAME 对不上节点：{code}"]
            if code in seen:
                return False, [f"节点重复插入：{code}"]
            seen.add(code)
            n = nodes_of[code]
            if ins.dxf.layer != blk_name:
                return False, [f"节点 {code} 的 INSERT 图层不对："
                               f"{ins.dxf.layer}"]
            err = math.hypot(ins.dxf.insert.x - n['x'],
                             ins.dxf.insert.y - n['y'])
            max_err = max(max_err, err)
            if err > DXF_READBACK_TOL_MM:
                return False, [f"节点 {code} 的 INSERT 位置不对"]
            ok, msg, max_err = _check_attribs(
                ins, blk_name, _node_values(n),
                n['x'], n['y'], f"{blk_name} {code}", max_err)
            if not ok:
                return False, [msg]
        details.append(f"{blk_name}：{len(by_block[blk_name])}/"
                       f"{len(nodes_of)} 个，NAME/TYPE 属性值与位置全对")

    # SEGMENT（管子的长度块）：按插入点（弧长中点）对分支
    expect_seg = {}
    for b in d['branches']:
        pts = [(float(x), float(y)) for x, y in b['points']]
        mx, my = arc_midpoint(pts)
        k = (round(mx, 2), round(my, 2))
        if k in expect_seg:
            return False, ["两根管子的 SEGMENT 插入点相同，无法区分"]
        expect_seg[k] = b
    if len(by_block['SEGMENT']) != len(d['branches']):
        return False, [f"SEGMENT 数不对：DXF {len(by_block['SEGMENT'])} "
                       f"vs 分支 {len(d['branches'])}"]
    seen = set()
    for ins in by_block['SEGMENT']:
        k = (round(ins.dxf.insert.x, 2), round(ins.dxf.insert.y, 2))
        if k not in expect_seg:
            return False, ["有一个 SEGMENT 在布局里找不到对应的分支"]
        if k in seen:
            return False, ["SEGMENT 重复插入"]
        seen.add(k)
        b = expect_seg[k]
        if ins.dxf.layer != 'SEGMENT':
            return False, [f"分支 {b['key'][:40]} 的 SEGMENT 图层不对："
                           f"{ins.dxf.layer}"]
        pts = [(float(x), float(y)) for x, y in b['points']]
        mx, my = arc_midpoint(pts)
        err = math.hypot(ins.dxf.insert.x - mx, ins.dxf.insert.y - my)
        max_err = max(max_err, err)
        if err > DXF_READBACK_TOL_MM:
            return False, [f"分支 {b['key'][:40]} 的 SEGMENT 位置不对"]
        ok, msg, max_err = _check_attribs(
            ins, 'SEGMENT', _segment_values(b), mx, my,
            f"SEGMENT {b['key'][:40]}", max_err)
        if not ok:
            return False, [msg]
    details.append(f"SEGMENT：{len(by_block['SEGMENT'])}/"
                   f"{len(d['branches'])} 个，L/E1/E2 属性值与位置全对")

    # LENGTH：只核对多段分支的 piece（单段分支不放 LENGTH，见生成侧注释）
    total_pieces = sum(len(b.get('pieces', [])) for b in d['branches']
                       if len(b.get('pieces', [])) > 1)
    expect_len = {}
    for b in d['branches']:
        if len(b.get('pieces', [])) <= 1:
            continue
        for pc in b.get('pieces', []):
            pts = [(float(x), float(y)) for x, y in pc['pts']]
            ix, iy = _piece_place(pts)
            k = (round(ix, 2), round(iy, 2))
            if k in expect_len:
                return False, ["两个 piece 的 LENGTH 插入点相同，无法区分"]
            expect_len[k] = (b, pc)
    if len(by_block['LENGTH']) != total_pieces:
        return False, [f"LENGTH 数不对：DXF {len(by_block['LENGTH'])} "
                       f"vs piece {total_pieces}"]
    seen = set()
    for ins in by_block['LENGTH']:
        k = (round(ins.dxf.insert.x, 2), round(ins.dxf.insert.y, 2))
        if k not in expect_len:
            return False, ["有一个 LENGTH 在布局里找不到对应的 piece"]
        if k in seen:
            return False, ["LENGTH 重复插入"]
        seen.add(k)
        b, pc = expect_len[k]
        if ins.dxf.layer != 'LENGTH':
            return False, [f"piece {pc['seg']} 的 LENGTH 图层不对："
                           f"{ins.dxf.layer}"]
        pts = [(float(x), float(y)) for x, y in pc['pts']]
        ix, iy = _piece_place(pts)
        err = math.hypot(ins.dxf.insert.x - ix, ins.dxf.insert.y - iy)
        max_err = max(max_err, err)
        if err > DXF_READBACK_TOL_MM:
            return False, [f"piece {pc['seg']} 的 LENGTH 位置不对"]
        ok, msg, max_err = _check_attribs(
            ins, 'LENGTH', _length_values(b, pc), ix, iy,
            f"LENGTH {pc['seg']}", max_err)
        if not ok:
            return False, [msg]
    details.append(f"LENGTH：{len(by_block['LENGTH'])}/{total_pieces} 个，"
                   f"L/E1/E2/PART_OF 属性值与位置全对")
    if max_err > DXF_READBACK_TOL_MM:
        return False, [f"INSERT/属性位置最大误差 {max_err:.4f}mm，超 0.01mm"]
    details.append(f"INSERT/属性位置最大误差 {max_err:.4f}mm")

    # --- 模型空间不应有 TEXT（旧纯文字标签已删） ---
    if list(msp.query('TEXT')):
        return False, ["模型空间还有 TEXT（旧纯文字标签没删干净）"]
    details.append("模型空间无 TEXT（旧纯文字标签已删）")

    # --- ezdxf audit ---
    auditor = doc.audit()
    if len(auditor.errors) > 0:
        return False, [f"ezdxf audit 有 {len(auditor.errors)} 个错误："
                       f"{auditor.errors[0]}"]
    details.append("ezdxf audit：0 错误")
    return True, details


def write_excel_from_layout(d, out_path):
    """Excel 配套表（v3 write_excel 的字典版）：2D管子/2D线段/2D节点/验证。"""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '2D管子'
    ws.append(['路径/分支', '起点X', '起点Y', '终点X', '终点Y',
               '3D弧长(mm)', '2D长度(mm)', '误差(mm)', '直径(mm)', '段数', '组成', '备注'])
    for b in sorted(d['branches'], key=lambda x: x['key']):
        pts = b['points']
        l2 = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                 for i in range(len(pts) - 1))
        nseg = len(b.get('pieces', []))
        if 'merged_from' in b:
            comp = ' + '.join(c['key'] for c in b['merged_from'])
            dia = ' / '.join(f"{c['dia']:.1f}" for c in b['merged_from'])
            note = f"合并路径，{len(b['merged_from'])} 根组成"
        else:
            comp = b['key']
            dia = round(b['dia'], 1)
            note = ''
        pt = b.get('partial')
        if isinstance(pt, dict):
            note = (f"部分管段：整管 {pt['total_len_3d']:.1f}mm，本路径含 "
                    f"{'+'.join(pt['segs_here'])}" + (f"；{note}" if note else ''))
        ws.append([b['key'], round(pts[0][0], 2), round(pts[0][1], 2),
                   round(pts[-1][0], 2), round(pts[-1][1], 2),
                   round(b['len_3d'], 1), round(l2, 1),
                   round(l2 - b['len_3d'], 2), dia, nseg, comp, note])
    ws2 = wb.create_sheet('2D线段')
    ws2.append(['SEG', '分支', '起点节点', '终点节点', '起点X', '起点Y',
                '终点X', '终点Y', '长度(mm)', '直径(mm)'])
    for b in sorted(d['branches'], key=lambda x: x['key']):
        comp_dia = {}
        for c in b.get('merged_from', []):
            for sg in c.get('segs', []):
                comp_dia[sg] = c['dia']
        for pc in b.get('pieces', []):
            pts = pc['pts']
            L = sum(math.hypot(pts[i + 1][0] - pts[i][0],
                               pts[i + 1][1] - pts[i][1])
                    for i in range(len(pts) - 1))
            dia = comp_dia.get(pc['seg'], b.get('dia'))
            ws2.append([pc['seg'], b['key'], pc['na'], pc['nb'],
                        round(pts[0][0], 2), round(pts[0][1], 2),
                        round(pts[-1][0], 2), round(pts[-1][1], 2),
                        round(L, 1), round(dia, 1) if dia is not None else ''])
    ws3 = wb.create_sheet('2D节点')
    ws3.append(['节点', '类型', '实例全名', 'X', 'Y'])
    for n in sorted(d['nodes'], key=lambda x: x['code']):
        ws3.append([n['code'], n.get('type', '?'), n.get('name_3d', ''),
                    round(n['x'], 2), round(n['y'], 2)])
    ws4 = wb.create_sheet('验证')
    ws4.append(['项目', '数值'])
    st = d.get('stats', {})
    for k in sorted(st):
        if k in ('len_errs', 'merged_nodes_list'):
            continue
        ws4.append([k, str(st[k])])
    ws4.append(['路径数', len(d['branches'])])
    ws4.append(['节点数', len(d['nodes'])])
    ws4.append(['线段数', sum(len(b.get('pieces', [])) for b in d['branches'])])
    ws4.append(['来源布局', d.get('meta', {}).get('based_on', '')])
    if d.get('meta', {}).get('excluded_branches'):
        ws4.append([])
        ws4.append(['已排除（不过孔零件不画）', '原因'])
        for rec in d['meta']['excluded_branches']:
            ws4.append([rec['key'], rec.get('reason', '')])
    if d.get('hidden_parallel'):
        ws4.append([])
        ws4.append(['平行未单画（§十五）', '隐藏分支/段', '长度', '直径', '只画'])
        for rec in d['hidden_parallel']:
            ws4.append([rec['pair'],
                        f"{rec['hidden_branch']} {rec['hidden_seg']}",
                        rec['hidden_length_mm'], rec['hidden_dia_mm'],
                        f"{rec['kept_branch']} {rec['kept_seg']}"])
    wb.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description='2D 展开布局 layout.json → DXF 工程图（带属性块，R2000）')
    ap.add_argument('layout_json')
    ap.add_argument('out_dxf')
    ap.add_argument('--excel', default=None, help='同时输出配套 Excel')
    args = ap.parse_args()

    with open(args.layout_json, encoding='utf-8') as fh:
        d = json.load(fh)
    print(f"布局：{len(d['branches'])} 路径 / {len(d['nodes'])} 节点，"
          f"来源 {d.get('meta', {}).get('based_on', '—')}")

    # 交付前验证：先写临时文件做回读核对，通过才正式落盘
    tmp_dxf = args.out_dxf + '.tmp'
    write_dxf_from_layout(d, tmp_dxf)
    ok, details = verify_dxf(d, tmp_dxf)
    for line in details:
        print(f"[验证] {line}")
    if not ok:
        try:
            os.remove(tmp_dxf)
        except OSError:
            pass
        print("DXF 回读验证失败，不交付 DXF，退出码 1")
        return 1
    os.replace(tmp_dxf, args.out_dxf)
    print(f"已写 {args.out_dxf}（{os.path.getsize(args.out_dxf)} 字节，"
          f"{DXF_VERSION}）")
    if args.excel:
        write_excel_from_layout(d, args.excel)
        print(f"已写 {args.excel}（{os.path.getsize(args.excel)} 字节）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
