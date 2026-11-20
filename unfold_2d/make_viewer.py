#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成仪表线束 2D 展开网页查看器（单文件 HTML，内嵌 layout.json，SVG 渲染，无 CDN）。
用法：python3 make_viewer.py <layout.json> <out.html>
2026-11-17 手机端修复：初始适配按可见视口铺满（100dvh + 底部导航预留 64px，
viewBox 边距约 8%）、窄屏图例改顶部可折叠（默认收起）、标签加白晕 + 放大时变大。
2026-11-17 v5：标题/版本号取 layout.json meta 的 version；顶部新增主干路径行
（端点/总长/分支数/关节数/直线跨度）；主干路径分支画红色加粗 + 图例项；
点管子弹窗显示其在主干路径中的序号。旧版 layout.json（无 trunk_path）兼容。
2026-11-17 点按再修（用户真机反馈）：①终端节点圆点屏幕半径 12px（旧公式漏乘
viewBox→屏幕 base 比例，实际仅约 1.5px），同类型统一尺寸；②点按按距离取最近，
节点不再无条件优先，点线中部弹管子；③点按判定放宽到 700ms / 位移 12px，适应真人
手指；④点节点时相连的线不变色，点管子时端点不高亮，选中什么只亮什么；⑤线粗
统一 8px（= 终端节点直径 24px 的 1/3，与圆点协调），选中 12px，选线容差 20px；
⑥每根管子中点上方标长度（3D 弧长四舍五入取整，放大 1.5 倍后显示，字号统一 11px）。
另修：nearestTubeDist 须把 viewBox 坐标逆变换到 vp 局部坐标再算距离，否则视图
平移/缩放后距离全错。
2026-11-17 统稿（用户 22:30 令一次做好再发）：①字号统一——长度标记、节点编号
标签、连接器真名标签全部同一字号（屏幕恒定 11px），三种标签放大到 1.5 倍后才
显示（全图时 110 个标签按可读尺寸会糊成一片）；新增真名标签（连接器 22 个 +
2026-11-18 地板图自查（用户令：必须用放大+截图自查，只数元素验不出视觉问题）：
圆点半径自适应——节点数>150 时按 sqrt 缩放（396 节点→7px，110 节点以下仍 12px，
IP 不变）；线粗随圆点成比例（直径的 1/3）；点按热区不变（18/12px）。
扎带 39 个有真名的，编号下方一行；只有 Body 编号的不加；扎带名去 "Copy (n) of "
复制标记，弹窗仍显全名）；名称标签紧贴各自圆点（右缘 + 3px，屏幕恒定），不许错
位到别的点旁边；②长度标签按画出折线的弧长中点定位（_midpoint_perp
沿折线走一半长度，不按端点连线中点；折线管/多段管已实测核对）；③平行管弹窗：
被保留的平行段点开后另列被隐藏那根平行管的长度/直径（parallel_hidden /
hidden_segs），注明“平行管”。
2026-11-17 v6p2 过路点合并 + 自环符号 + 标签下拉（用户 22:44/22:49/22:51/22:52 令）：
只连两个地方的点就是过路点，合并（17 个 N + BN01 + BN04，共 19 处，节点 110→91，
路径 108→91；段级合并，同根管子先配，剩下的一对配一起；BN04–N04 成链成
CLP01→CLP11，Body.113 的 SEG02 另成 CLP01→CLP23）；合并路径的 key 为组成管子以
+ 连接，弹窗列出每根组成管子（编号、直径、长度、段），搜组成管子编号也能定位
到合并路径（Body.113 本身仍有独立路径，不走别名）；自环 3 处改画小环符号（屏幕
恒定半径 8px，圆心距节点 20px，方向取最大无管空角）；标签下拉菜单四开关默认全
开；全部管子统一深蓝 #2c5f8a，红色不许再用在管子上。单根分支行为一律不动。
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unfold_2d_v3 import (seg_proper_intersect, seg_collinear_overlap,
                          seg_seg_dist, pt_eq)

TYPE_CN = {'connector': '连接器', 'clamp': '卡扣', 'fork': '分支点', 'joint': '接头'}
TYPE_COL = {'connector': '#e03131', 'clamp': '#2f9e44', 'fork': '#f08c00', 'joint': '#868e96'}

import re as _re
_COPY_PREFIX = _re.compile(r'^(Copy \(\d+\) of )+')
def _label_name(s):
    """图面标签用名：去掉 CATIA 复制标记 "Copy (n) of " 前缀（复制标记不是名字本身），其余照实。弹窗仍显示完整 3D 全名。"""
    return _COPY_PREFIX.sub('', s)


def _disp_name(nodes_by_code, code):
    """§二十八端点显示名（唯一定义：查看器弹窗、DXF、Excel 三处复用同一
    函数，不各写一份）。连接器端点显示真名（name_3d，去 Copy 前缀）；
    无真名（空、Body. 开头）或占位名（默认连接器）时仍用编号；卡扣/
    分支点/接头一律编号；查不到的编号原样返回。
    注：须与 make_dxf._node_fullname 对连接器名的结果一致（现行两套数据
    里连接器名均无反斜杠、无 Copy 前缀，两者相等）；DXF 路由检查回读
    核对显示名与节点块 NAME/TAG，口径漂移会被检查拦住。"""
    n = nodes_by_code.get(code)
    if n is None:
        return code
    if n.get('type') == 'connector':
        nm = n.get('name_3d') or ''
        if nm and not nm.startswith('Body.') and nm != '默认连接器':
            return _label_name(nm)
    return code


def _label_flip_set(branches, nodes):
    """名签放左边的节点集合（2026-11-18：BN02 区 CLP01 长名签穿小环）。

    规则：名签默认放圆点右边；若右边名签带（两条水平线：圆点下方
    13mm 与 18mm 处，名签文字带的上下缘）穿过 ≥2 处别人的管子或圆点、
    而左边同一条带完全干净，就把该节点的编号+名签一起翻到左边。
    只看名签：编号签短（5~6 字），很少穿线；两签一起翻，保持成对。
    参考缩放 k=8（约 0.88px/mm，常用看图缩放）；字宽按 11px 字号估：
    西文 6.5px、中文 11px；本节点的管子不算（名签贴自家管子不算穿）。
    阈值（≥2 处、左边 0 处）是我定的默认值，用户可改。
    """
    import math as _m
    PXMM = 0.88
    node_br = {}
    for b in branches:
        touched = set()
        for pc in b.get('pieces', []):
            if pc.get('na'):
                touched.add(pc['na'])
            if pc.get('nb'):
                touched.add(pc['nb'])
        touched.add(b['node0'])
        touched.add(b['node1'])
        for c in touched:
            node_br.setdefault(c, set()).add(b['key'])
    segs = []
    for b in branches:
        pts = b['points']
        for i in range(len(pts) - 1):
            segs.append((b['key'], pts[i], pts[i + 1]))

    def ray_hits(y, x0, x1, own):
        hit = set()
        for k, (bk, (ax, ay), (bx, by)) in enumerate(segs):
            if bk in own:
                continue
            if min(ay, by) <= y <= max(ay, by):
                if abs(by - ay) < 1e-9:
                    if not (max(ax, bx) < x0 or min(ax, bx) > x1):
                        hit.add(k)
                else:
                    t = (y - ay) / (by - ay)
                    if x0 <= ax + t * (bx - ax) <= x1:
                        hit.add(k)
        return hit

    def text_w(s):
        return sum(11.0 if ord(ch) > 127 else 6.5 for ch in s) / PXMM

    flips = set()
    for n in nodes:
        nm = n.get('name_3d')
        if not nm or nm.startswith('Body.'):
            continue
        lab = _label_name(nm)
        w = text_w(lab)
        x = n['x']
        own = node_br.get(n['code'], set())
        rh, lh = set(), set()
        rn = ln = 0
        for dy in (13, 18):
            y = n['y'] - dy
            rh |= ray_hits(y, x + 6, x + 6 + w, own)
            lh |= ray_hits(y, x - 6 - w, x - 6, own)
        for o in nodes:
            if o['code'] == n['code']:
                continue
            if any(abs(o['y'] - (n['y'] - dy)) < 8 for dy in (13, 18)):
                if x + 6 <= o['x'] <= x + 6 + w:
                    rn += 1
                if x - 6 - w <= o['x'] <= x - 6:
                    ln += 1
        if len(rh) + rn >= 2 and len(lh) + ln == 0:
            flips.add(n['code'])
    return flips

def main():
    lj_path, out_path = sys.argv[1], sys.argv[2]
    # 第 3/4 可选参数：页面短名与代号（如“地板线束”“FLOOR”），默认仪表线束 IP 版
    # 注：变量名须用 page_name/page_code——本文件另有分支弹窗用的 title 变量（第 108 行）
    page_name = sys.argv[3] if len(sys.argv) > 3 else '仪表线束'
    page_code = sys.argv[4] if len(sys.argv) > 4 else 'IP-Harness'
    # --showcase：对外展示版（展示站 FR-25）：页头只留标题与使用提示，不显示
    # 计数/总长/质检指标；弹窗单项工程数据保留真实值；标题固定为“线束 2D 展开图”
    showcase = '--showcase' in sys.argv
    d = json.load(open(lj_path, encoding='utf-8'))
    stats = d['stats']
    branches, nodes = d['branches'], d['nodes']
    bends, warnings = d['bends'], d['warnings']
    flip_left = _label_flip_set(branches, nodes)
    print(f"[标签] {len(flip_left)} 处名签翻左：{sorted(flip_left)}", flush=True)
    version = d.get('meta', {}).get('version', 'v3')
    trunk_path = d.get('meta', {}).get('trunk_path')  # v5：主干路径（旧版无则不显示）
    from datetime import date as _date
    today = _date.today().isoformat()
    xmin, ymin, xmax, ymax = stats['bbox']
    # 边距：约 8%（各边取总尺寸的 4%），初始适配时图占满视口约 92%
    M = round(0.04 * max(xmax - xmin, ymax - ymin), 1)
    # SVG 坐标：X = x，Y = -y（y 轴翻转）
    vb_x, vb_y = xmin - M, -ymax - M
    vb_w, vb_h = (xmax - xmin) + 2*M, (ymax - ymin) + 2*M

    def Y(y):
        return -y

    def _midpoint_perp(pts):
        """折线按弧长的中点 + 该处单位法向（SVG 坐标，取屏幕上方一侧）。
        返回 (mx, my_svg, px, py)：中点与法向，供长度标签定位。"""
        import math
        total = 0.0
        seg_lens = []
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            L = math.hypot(x2 - x1, y2 - y1)
            seg_lens.append(L)
            total += L
        half, acc = total / 2, 0.0
        for (x1, y1), (x2, y2), L in zip(pts, pts[1:], seg_lens):
            if L > 0 and acc + L >= half:
                t = (half - acc) / L
                mx = x1 + (x2 - x1) * t
                my = y1 + (y2 - y1) * t
                dx, dy = (x2 - x1) / L, (y2 - y1) / L  # 布局坐标系方向
                # SVG 坐标 y 翻转：法向候选 (dy, dx) 与 (-dy, -dx)，取屏幕上方（SVG y 更小）
                px, py = dy, dx
                if py > 0 or (py == 0 and px < 0):
                    px, py = -px, -py
                return mx, -my, px, py
            acc += L
        mx, my = pts[len(pts) // 2]
        return mx, -my, 0.0, -1.0

    # ---- 静态 SVG 内容（Python 生成，便于离线核对元素数） ----
    parts = []
    nodes_by_code = {n['code']: n for n in nodes}
    # §二十七防御：自环布局（旧版）直接报错不出图——自环须先过合并处理去掉
    _loop_b = [b['key'] for b in branches
               if b['node0'] == b['node1'] or 'loop' in b]
    assert not _loop_b, (
        f'布局含自环路径/loop 条目（须先过合并处理去掉）：{_loop_b[:5]}')
    # §二十八：端点显示名（连接器真名，其余编号）——Python 侧算好放进
    # DATA，JS 只读 disp，不另写判定（名称只在一处定义）
    for n in nodes:
        n['disp'] = _disp_name(nodes_by_code, n['code'])
    # 管子折线（v6p2：用户 22:51 定，全部管子统一深蓝 #2c5f8a，不用红，
    # 主干/分支颜色区分取消；线宽统一由 applyView 按屏幕像素定）
    for b in branches:
        pts = ' '.join(f"{x:.2f},{Y(y):.2f}" for x, y in b['points'])
        stroke, sw = '#2c5f8a', '1.6'
        # v6p2：合并路径的 title 列组成管子（直径可能不同，不写单一 Φ）
        if b.get('merged_from'):
            title = b['key'] + ' L=' + str(b['len_3d']) + '（' + ' + '.join(
                f"{m['key']} Φ{m['dia']}" for m in b['merged_from']) + '）'
        else:
            title = f"{b['key']} Φ{b['dia']} L={b['len_3d']}"
        parts.append(
            f'<polyline class="tube" data-key="{b["key"]}" points="{pts}" '
            f'fill="none" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round" '
            f'stroke-linecap="round"><title>{title}</title></polyline>')
        # 长度标签（2026-11-17 用户要求）：3D 弧长四舍五入取整，居中放中点上方，不压线；
        # 字号/位置由 applyView 按视图定（放大后显示），data-* 存中点与法向
        if len(b['points']) >= 2:
            mx, my, px, py = _midpoint_perp(b['points'])
            lab = int(b['len_3d'] + 0.5)
            # v6p2：纯自环分支（Body.96）折线退化为一点，长度标签沿环方向外放
            # data-loff-dir 为布局坐标系角度（y 朝上），applyView 换算到 SVG 坐标系
            loff = ''
            if b.get('label_offset'):
                loff = (f' data-loff-dir="{b["label_offset"]["dir_deg"]}" '
                        f'data-loff-dist="{b["label_offset"]["dist_px"]}"')
            parts.append(
                f'<text class="lenlbl" data-key="{b["key"]}" data-mx="{mx:.2f}" data-my="{my:.2f}" '
                f'data-px="{px:.3f}" data-py="{py:.3f}"{loff} x="{mx:.2f}" y="{my:.2f}">{lab}</text>')
    # 自环符号（v6p2：BN02 两处 + BN03 一处，改画统一小环；位置/大小由 applyView
    # 按屏幕恒定值定：半径 8px，圆心距节点 20px；data-dir 为布局坐标系角度，
    # applyView 换算到 SVG 坐标系（y 朝下，取负角）；点小环弹出对应管子详情）
    for b in branches:
        for lp in b.get('loop', []):
            nn = nodes_by_code[lp['node']]
            if lp.get('kind') == 'chord':
                # 环弦符号（2026-11-18）：连接两节点的短管，段长<端点距，
                # 画小环符号于一端；title 写明另一端。
                title = (f"环弦 {lp['branch']} {lp['seg']} "
                         f"{lp['length_mm']}mm（连接 {lp['node']}—{lp['far']}）")
            else:
                title = (f"自环 {lp['branch']} {lp['seg']} "
                         f"{lp['length_mm']}mm")
            # 引线（2026-11-18 用户反馈：小环离节点 30px、放大后看像无连接的
            # 空圆；细虚线连节点中心与小环边缘，位置由 applyView 每帧定；
            # pointer-events=none 不干扰点按）
            parts.append(
                f'<line class="loopline" data-node="{lp["node"]}" '
                f'data-dir="{lp["dir_deg"]}" data-seg="{lp["seg"]}" '
                f'x1="0" y1="0" x2="0" y2="0" stroke="#2c5f8a" '
                f'stroke-width="1" stroke-dasharray="3 2" '
                f'pointer-events="none" />')
            parts.append(
                f'<circle class="loopring" data-key="{b["key"]}" data-node="{lp["node"]}" '
                f'data-dir="{lp["dir_deg"]}" data-seg="{lp["seg"]}" '
                f'cx="{nn["x"]:.2f}" cy="{Y(nn["y"]):.2f}" r="8" fill="none" '
                f'stroke="#2c5f8a" stroke-width="3">'
                f'<title>{title}</title></circle>')
    # 节点圆 + 编号（终端节点连接器/卡扣圆点画大：静态 r=DOT_R，applyView 按类型
    # 覆写为屏幕恒定 DOT_R；分支点/接头 r=DOT_R/2。2026-11-17 用户真机反馈终端节点点太小点不到）
    # 圆点半径自适应（2026-11-18 地板图自查：396 节点时 12px 圆点在手机全图糊成一片，
    # 线都看不见；半径按 sqrt 缩放，总面积大致恒定；110 节点以下仍 12px，IP 不变）
    n_nodes = len(nodes)
    dot_r = 12 if n_nodes <= 150 else max(5, round(12 * (150 / n_nodes) ** 0.5))
    fork_r = max(3, round(dot_r / 2))
    import html as _html
    for n in nodes:
        c = TYPE_COL.get(n['type'], '#000')
        term = n['type'] in ('connector', 'clamp')
        r_dot = str(dot_r) if term else str(fork_r)
        r_hit = '40' if term else '30'
        # 真名标签（2026-11-17 统稿 + 用户补充令）：连接器（22 个）与扎带（39 个）
        # 有真名的都加，放在编号标签下方一行；只有 Body 编号的（连接器 10 个、
        # 扎带 2 个）不编造、不加。data-nx/data-ny 存节点中心（SVG 坐标），applyView
        # 据此把标签紧贴在各自圆点旁边（右缘 + 3px），不许错位到别的点旁边。
        nm = ''
        side = ' data-nside="L"' if n['code'] in flip_left else ''
        if term and n.get('name_3d') and not n['name_3d'].startswith('Body.'):
            disp = _label_name(n['name_3d'])
            nm = (f'<text class="nmlbl" data-nx="{n["x"]:.2f}" data-ny="{Y(n["y"]):.2f}"{side} '
                  f'x="{n["x"] + 6:.2f}" y="{Y(n["y"]) + 3:.2f}" fill="{c}">{_html.escape(disp)}</text>')
        parts.append(
            f'<g class="node" data-code="{n["code"]}">'
            f'<circle class="ndot" cx="{n["x"]:.2f}" cy="{Y(n["y"]):.2f}" r="{r_dot}" fill="{c}" '
            f'stroke="#fff" stroke-width="1.2"/>'
            f'<circle class="nhit" cx="{n["x"]:.2f}" cy="{Y(n["y"]):.2f}" r="{r_hit}" fill="transparent"/>'
            f'<text class="lbl" data-nx="{n["x"]:.2f}" data-ny="{Y(n["y"]):.2f}"{side} x="{n["x"] + 6:.2f}" y="{Y(n["y"]) + 3:.2f}" fill="{c}">{n["code"]}</text>'
            f'{nm}</g>')
    # X 交叉点标记（v4 新增：红色 ✕，臂长 ±5mm；title 显示相交的两根分支）
    for x in d.get('crossings', []):
        cx, cy = x['x'], Y(x['y'])
        pair = ' × '.join(x.get('branches', []))
        parts.append(
            f'<g class="xmark"><title>X 交叉：{pair}</title>'
            f'<line class="xline" x1="{cx - 5:.2f}" y1="{cy - 5:.2f}" '
            f'x2="{cx + 5:.2f}" y2="{cy + 5:.2f}" stroke="#e03131" stroke-width="2.0" '
            f'stroke-linecap="round"/>'
            f'<line class="xline" x1="{cx - 5:.2f}" y1="{cy + 5:.2f}" '
            f'x2="{cx + 5:.2f}" y2="{cy - 5:.2f}" stroke="#e03131" stroke-width="2.0" '
            f'stroke-linecap="round"/></g>')
    svg_inner = '\n'.join(parts)

    # 节点连接关系（供弹窗用；node0==node1 的短线头路径去重）
    node_branches = {}
    for b in branches:
        for code in (b['node0'], b['node1']):
            lst = node_branches.setdefault(code, [])
            if b['key'] not in lst:
                lst.append(b['key'])

    data_json = json.dumps({
        'stats': stats, 'branches': branches, 'nodes': nodes,
        'bends': bends, 'warnings': warnings,
        'node_branches': node_branches,
        'checklist': None if showcase else d.get('checklist'),
        'crossings': d.get('crossings', []),
        'trunk': d.get('meta', {}).get('trunk'),
        'trunk_path': trunk_path,
        'tilt_deg': d.get('meta', {}).get('tilt_deg'),
        'version': version,
    }, ensure_ascii=False).replace('<', '\\u003c')

    n_seg = sum(len(b['pieces']) for b in branches)
    total_len = stats['total_len_3d']
    w_mm = round(xmax - xmin, 1)
    h_mm = round(ymax - ymin, 1)
    # 干涉分类（从 layout.json 几何重算，不硬编码）
    subs = []  # (p1, p2, branch, seg, skip_dist)
    for b in branches:
        for pc in b['pieces']:
            pts = pc['pts']
            sd = (pc['na'] == pc['nb'])  # 自环三角不计间距
            for a, c in zip(pts, pts[1:]):
                subs.append((tuple(a), tuple(c), b['key'], pc['seg'], sd))
    n_x = n_near = n_ov = 0
    for i in range(len(subs)):
        for j in range(i + 1, len(subs)):
            if subs[i][2] == subs[j][2] and subs[i][3] == subs[j][3]:
                continue
            a1, a2, b1, b2 = subs[i][0], subs[i][1], subs[j][0], subs[j][1]
            shared = (pt_eq(a1, b1) or pt_eq(a1, b2)
                      or pt_eq(a2, b1) or pt_eq(a2, b2))
            if seg_proper_intersect(a1, a2, b1, b2):
                n_x += 1
            elif seg_collinear_overlap(a1, a2, b1, b2):
                n_ov += 1
            elif (not shared and not (subs[i][4] or subs[j][4])
                    and seg_seg_dist(a1, a2, b1, b2) < 5.0):
                n_near += 1

    # §二十九 DRC：交叉/压着画卡口——合并已全过，这里是最后一道防线
    # （布局若绕过合并直接拿来出图，有交叉也不许画出来）
    assert n_x == 0 and n_ov == 0, (
        f'交叉 {n_x} 对、压着画 {n_ov} 对，不过不出图')

    # ---- 检查清单（v3 修正版 layout.json 才有；旧版 layout.json 无则不显示） ----
    ck = d.get('checklist')
    ck_header = ''   # 顶部统计区第二行（手机也可见）
    ck_verify = ''   # 右下验证信息区一行
    if ck and not showcase:
        hard = ck.get('hard', [])
        n_pass = sum(1 for c in hard if c.get('pass'))
        tc = stats.get('trunk_center', {})
        h1 = next((c for c in hard if c.get('id') == 'H1'), None)
        h1_mark = '✓' if (h1 and h1.get('pass')) else '✗'
        all_mark = '✓' if ck.get('all_hard_pass') else '✗'
        # v4：主干居中横竖两方向分别显示；v3 旧版只有单值，兼容回退
        if tc.get('dev_x_pct') is not None:
            dev_txt = (f"横 {tc['dev_x_mm']} mm（{tc['dev_x_pct']}%）/ "
                       f"竖 {tc['dev_y_mm']} mm（{tc['dev_y_pct']}%）")
        else:
            dev_txt = f"{tc.get('dev_mm')} mm（{tc.get('dev_pct')}%）"
        ck_header = (f'<div class="stats">主干居中偏差 <b>{dev_txt}</b> {h1_mark} '
                     f'· 硬规则 <b>{n_pass}/{len(hard)} 通过</b> {all_mark} '
                     f'· 压着画 <b>{n_ov} 对</b> · X 交叉 <b>{n_x} 对</b>（红 ✕ 标记）</div>')
        # v4 第三行：正交符合率 + 翻转统计（v3 layout.json 无此字段则不显示）
        if stats.get('ortho_rate_pct') is not None:
            ck_header += (
                f'<div class="stats">正交符合率 <b>{stats["ortho_rate_pct"]}%</b> '
                f'（{stats["ortho_passed"]}/{stats["ortho_checked"]} 根） '
                f'· 翻转 放置 {stats.get("flips_placement", 0)} / '
                f'居中 {stats.get("flips_center", 0)} / '
                f'消交叉 {stats.get("flips_untangle", 0)} '
                f'· 投影侧符合 {stats.get("side_match", 0)}/{stats.get("side_total", 0)}</div>')
        ck_verify = (f'<br>主干居中偏差 {dev_txt}{h1_mark} · '
                     f'硬规则 {n_pass}/{len(hard)} 通过 {all_mark}')

    # ---- 主干路径行（v5：顶部显示路径端点/总长/分支数；旧版 layout.json 无则不显示） ----
    trunk_header = ''
    if trunk_path and not showcase:
        ep = trunk_path['endpoints']
        trunk_header = (
            f'<div class="stats">主干路径 <b>{ep[0]} → {ep[1]}</b> · '
            f'总长 <b>{trunk_path["length_mm"]} mm</b> · '
            f'<b>{trunk_path["branches"]} 根分支</b> · {trunk_path["joints"]} 个关节 · '
            f'直线跨度 {trunk_path["span_mm"]} mm</div>')
    # v6p2：主干/分支颜色区分取消，图例里红主干行删掉；接头节点已全并掉，
    # 接头图例项只在还有接头节点时显示；自环符号加一行说明
    joint_item = ('<i style="background:#868e96"></i>接头 ' if any(
        n['type'] == 'joint' for n in nodes) else '')
    n_loop = stats.get('loop_symbols', 0)
    loop_note = (f'<br><span style="color:#2c5f8a;font-weight:700">○</span> 自环符号（{n_loop} 处，不按比例）' if n_loop else '')
    # 环弦符号（2026-11-18）：连接两节点的短管，段长<端点距，画小环符号于一端
    n_chord = stats.get('chord_symbols', 0)
    chord_note = (f'<br><span style="color:#2c5f8a;font-weight:700">○</span> 环弦符号（{n_chord} 处，连接两节点，不按比例）' if n_chord else '')
    # 平行管说明（v6p1：平行对只画一根，被隐藏的段数来自 stats，不硬编码）
    n_hp = stats.get('hidden_parallel_segs', 0)
    hidden_note = (f'<br><span style="color:#868e96">平行管 {n_hp} 段未单画，点保留的管子看详情</span>' if n_hp else '')
    # v6p2：过路点合并说明 + 顶部统计行（“分支”数是已画路径数，另标管子总数，
    # 避免误读为丢管子；无合并的旧版 layout.json 走原格式）
    n_mj = stats.get('merged_nodes', stats.get('merged_joints', 0))
    merged_note = (f'<br><span style="color:#868e96">过路点合并 {n_mj} 处，点合并的管子看各根详情</span>' if n_mj else '')
    # §二十二：已排除分支（过孔零件，不画）——页头明标，不藏数
    excluded = d.get('meta', {}).get('excluded_branches', [])
    excluded_note = (f'<br><span style="color:#868e96">已排除过孔零件 '
                     + '、'.join(e['key'] for e in excluded)
                     + '（不是路径，不画）</span>') if excluded else ''
    # §二十七：掉落的自环段——页头明标，不藏数（与过孔零件分开列）
    _dropped = d.get('meta', {}).get('dropped_loop_segments', [])
    _dropped_whole = d.get('meta', {}).get('dropped_loop_branches', [])
    dropped_note = (f'<br><span style="color:#868e96">自环段去掉 {len(_dropped)} 处'
                    + (f'（整根去掉 {len(_dropped_whole)} 根）' if _dropped_whole else '')
                    + '（§二十七，不画）</span>') if _dropped else ''
    # 展示版：图例里的计数说明（平行管/过路点合并/符号数）也不显示
    if showcase:
        hidden_note = merged_note = loop_note = chord_note = ''
    # 搜索框示例用图里真实存在的编号（写死的 CLP01 被 §二十二删了就搜不到）
    _codes = sorted(n['code'] for n in nodes)
    _ex_con = next((c for c in _codes if c.startswith('CON')), 'CON01')
    _ex_clp = next((c for c in _codes if c.startswith('CLP')), 'CLP01')
    _ex_bn = next((c for c in _codes if c.startswith('BN')), 'BN02')
    search_example = f"搜编号，如 {_ex_con} / {_ex_clp} / {_ex_bn} / Body.123"
    if showcase:
        stats_line = "拖动平移，滚轮缩放，点任意管子或节点查看详情"
    elif n_mj:
        stats_line = (f"路径 <b>{stats['branches_placed']}</b>（{stats['branches_total']} 根管子，"
                      f"{n_mj} 处过路点合并） · 节点 <b>{stats['nodes_placed']}/{stats['nodes_total']}</b> · "
                      f"线段 <b>{n_seg}</b> · 展开总长 <b>{total_len:.1f} mm</b> · 图纸 <b>{w_mm} × {h_mm} mm</b>{excluded_note}{dropped_note}")
    else:
        stats_line = (f"分支 <b>{stats['branches_placed']}/{stats['branches_total']}</b> · 节点 <b>{stats['nodes_placed']}/{stats['nodes_total']}</b> · "
                      f"线段 <b>{n_seg}</b> · 展开总长 <b>{total_len:.1f} mm</b> · 图纸 <b>{w_mm} × {h_mm} mm</b>{excluded_note}{dropped_note}")

    # 展示版标题固定，不带版本号与日期；验证信息区整个去掉；页头加 3D 视图链接
    disp_title = '线束 2D 展开图' if showcase else f'{page_name} 2D展开图 {version}（{today}）'
    disp_h1 = '线束 2D 展开图' if showcase else f'{page_name}（{page_code}）2D 展开图 · {version}'
    verify_div = '' if showcase else (
        f'<div id="verify">拐弯 {stats["bends"]} 次 · 残留干涉 {stats["residual_interference_pairs"]} 对<br>'
        f'（X 交叉 {n_x} 对 · 间距&lt;5mm {n_near} 对 · 压着画 {n_ov} 对）<br>'
        f'最大长度误差 {stats["max_len_err_mm"]} mm · 无真实几何环{ck_verify}</div>')
    home_link = ('<a href="viewer.html" target="_blank" rel="noopener">3D 视图 →</a>' if showcase else '')

    html_doc = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>{disp_title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f1f3f5; color: #212529; height: 100vh; height: -webkit-fill-available; height: 100dvh; display: flex; flex-direction: column; overflow: hidden; }}
header {{ background: #1c3d5a; color: #fff; padding: 8px 12px; flex: none; }}
header h1 {{ font-size: 16px; font-weight: 600; }}
.stats {{ font-size: 12px; color: #ced4da; margin-top: 2px; line-height: 1.5; }}
.stats b {{ color: #fff; }}
.bar {{ display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }}
.bar input {{ flex: 1 1 140px; padding: 6px 8px; font-size: 14px; border: none; border-radius: 4px; }}
.bar button {{ padding: 6px 10px; font-size: 13px; border: none; border-radius: 4px; background: #2c5f8a; color: #fff; cursor: pointer; }}
.bar a {{ padding: 6px 10px; font-size: 13px; border: none; border-radius: 4px; background: #2c5f8a; color: #fff; cursor: pointer; text-decoration: none; }}
.bar button:active {{ background: #1f4566; }}
.dd {{ position: relative; }}
.dd-panel {{ position: absolute; top: calc(100% + 4px); left: 0; background: #fff; border: 1px solid #adb5bd; border-radius: 6px; box-shadow: 0 4px 16px rgba(0,0,0,.18); padding: 4px 0; display: none; z-index: 10; min-width: 140px; }}
.dd-panel.open {{ display: block; }}
.dd-panel label {{ display: flex; align-items: center; gap: 8px; padding: 10px 14px; font-size: 14px; color: #212529; cursor: pointer; min-height: 44px; }}
.dd-panel input {{ width: 18px; height: 18px; flex: none; }}
#wrap {{ flex: 1; position: relative; overflow: hidden; background: #fff; }}
#svg {{ width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }}
#svg.dragging {{ cursor: grabbing; }}
.tube {{ cursor: pointer; }}
.tube.sel {{ stroke: #f08c00 !important; }}
.loopring {{ cursor: pointer; }}
.loopring.sel {{ stroke: #f08c00 !important; }}
.node.sel .ndot {{ stroke: #f08c00; }}
.node.hl .ndot {{ stroke: #ffd43b; stroke-width: 3; }}
.lbl {{ font-size: 14px; font-weight: 600; pointer-events: none; user-select: none; paint-order: stroke; stroke: rgba(255,255,255,.9); }}
.nmlbl {{ font-weight: 600; pointer-events: none; user-select: none; paint-order: stroke; stroke: rgba(255,255,255,.9); }}
.lenlbl {{ font-weight: 600; fill: #495057; pointer-events: none; user-select: none; paint-order: stroke; stroke: rgba(255,255,255,.95); text-anchor: middle; }}
.legend {{ position: absolute; left: 8px; bottom: 8px; bottom: calc(8px + env(safe-area-inset-bottom, 0px)); background: rgba(255,255,255,.92); border: 1px solid #dee2e6; border-radius: 6px; padding: 6px 9px; font-size: 12px; line-height: 1.7; color: #495057; z-index: 4; }}
#legendToggle {{ display: none; border: none; background: none; font-size: 13px; color: #495057; cursor: pointer; padding: 2px 4px; }}
.legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }}
.legend .ln {{ display: inline-block; width: 16px; height: 0; border-top: 2px solid #2c5f8a; margin-right: 5px; vertical-align: middle; }}
#popup {{ position: absolute; left: 8px; right: 8px; bottom: 8px; bottom: calc(8px + env(safe-area-inset-bottom, 0px)); background: #fff; border: 1px solid #adb5bd; border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,.18); padding: 10px 12px; font-size: 13px; line-height: 1.65; display: none; max-height: 45%; overflow-y: auto; z-index: 5; }}
#popup h2 {{ font-size: 14px; margin-bottom: 2px; word-break: break-all; }}
#popup .x {{ float: right; border: none; background: none; font-size: 18px; color: #868e96; cursor: pointer; line-height: 1; }}
#popup table {{ border-collapse: collapse; }}
#popup td {{ padding: 1px 8px 1px 0; vertical-align: top; }}
#popup td.k {{ color: #868e96; white-space: nowrap; }}
#popup .mono {{ font-family: monospace; word-break: break-all; }}
#toast {{ position: absolute; top: 10px; left: 50%; transform: translateX(-50%); background: #343a40; color: #fff; padding: 6px 14px; border-radius: 20px; font-size: 13px; display: none; z-index: 6; }}
#verify {{ position: absolute; right: 8px; bottom: 8px; bottom: calc(8px + env(safe-area-inset-bottom, 0px)); background: rgba(255,255,255,.92); border: 1px solid #dee2e6; border-radius: 6px; padding: 6px 9px; font-size: 11px; color: #868e96; text-align: right; line-height: 1.6; }}
@media (max-width: 640px) {{
  #verify {{ display: none; }}
  header h1 {{ font-size: 14px; }}
  /* 窄屏：#wrap 底部预留 Muse 底部导航高度，SVG 适配框 = 实际可见区 */
  #wrap {{ padding-bottom: 64px; padding-bottom: calc(64px + env(safe-area-inset-bottom, 0px)); }}
  /* 窄屏：图例移到顶部，可折叠，默认收起，绝不贴底被导航遮住 */
  .legend {{ top: 8px; bottom: auto; padding: 4px 8px; }}
  #legendToggle {{ display: inline-block; }}
  .legend-body {{ display: none; }}
  .legend.open .legend-body {{ display: block; }}
  .legend.open #legendToggle {{ margin-bottom: 2px; }}
  /* 窄屏：详情弹窗抬起，避开底部导航 */
  #popup {{ bottom: 72px; bottom: calc(72px + env(safe-area-inset-bottom, 0px)); max-height: 60%; }}
}}
</style>
</head>
<body>
<header>
<h1>{disp_h1}</h1>
<div class="stats">{stats_line}</div>
{trunk_header}
{ck_header}
<div class="bar">
<input id="search" type="text" placeholder="{search_example}" autocomplete="off">
<button id="btnSearch">定位</button>
<button id="btnFit">全图</button>
<button id="btnClear">清除</button>
{home_link}
<div class="dd" id="labelDD">
<button id="btnLabels" type="button">标签 4/4 ▾</button>
<div class="dd-panel" id="labelPanel">
<label><input type="checkbox" data-lbl="conn" checked> 连接器名</label>
<label><input type="checkbox" data-lbl="clamp" checked> 扎带名</label>
<label><input type="checkbox" data-lbl="node" checked> 节点名</label>
<label><input type="checkbox" data-lbl="len" checked> 长度</label>
</div>
</div>
</div>
</header>
<div id="wrap">
<svg id="svg" viewBox="{vb_x:.1f} {vb_y:.1f} {vb_w:.1f} {vb_h:.1f}" preserveAspectRatio="xMidYMid meet">
<g id="vp">
{svg_inner}
</g>
</svg>
<div class="legend" id="legend"><button id="legendToggle" type="button">图例 ▸</button><div class="legend-body"><span class="ln"></span>管子（分支）<br><i style="background:#e03131"></i>连接器 <i style="background:#2f9e44"></i>卡扣 <i style="background:#f08c00"></i>分支点 {joint_item}<br><span style="color:#e03131;font-weight:700">✕</span> X 交叉点{loop_note}{chord_note}<br><span style="color:#868e96">放大后显示编号、名称与长度（mm）</span>{hidden_note}{merged_note}</div></div>
{verify_div}
<div id="popup"><button class="x" id="btnClose">×</button><div id="popBody"></div></div>
<div id="toast"></div>
</div>
<script>
var DATA = {data_json};
var TYPE_CN = {{"connector":"连接器","clamp":"卡扣","fork":"分支点","joint":"接头"}};
var svg = document.getElementById('svg');
var vp = document.getElementById('vp');
var popup = document.getElementById('popup');
var popBody = document.getElementById('popBody');
var toastEl = document.getElementById('toast');
var nodesByCode = {{}};
DATA.nodes.forEach(function(n) {{ nodesByCode[n.code] = n; }});
var branchesByKey = {{}};
DATA.branches.forEach(function(b) {{ branchesByKey[b.key] = b; }});
// v6p2：合并路径的组成管子编号也指向合并路径，搜 Body.78 能找到它所在的合并管子；
// 但组成编号本身已有独立路径时不覆盖（如 Body.113：SEG02 另成一条线，搜它应定位到那条线）
DATA.branches.forEach(function(b) {{
  (b.merged_from || []).forEach(function(m) {{ if (!(m.key in branchesByKey)) branchesByKey[m.key] = b; }});
}});
// v6p2：标签下拉菜单四开关，默认全开（applyView 按此决定三类标签显隐）
var labelVis = {{ conn: true, clamp: true, node: true, len: true }};
var trunkIdx = {{}};
if (DATA.trunk_path && DATA.trunk_path.branch_list) {{
  DATA.trunk_path.branch_list.forEach(function(k, i) {{ trunkIdx[k] = i + 1; }});
}}

// ---- 视图变换（平移 + 缩放） ----
var view = {{ x: 0, y: 0, k: 1 }};
function applyView() {{
  vp.setAttribute('transform', 'translate(' + view.x + ',' + view.y + ') scale(' + view.k + ')');
  // SVG 单位→屏幕像素的总缩放 = viewBox→屏幕 base 比例 × view.k
  // （注意：旧公式 r=5/k 漏乘 base 比例，手机全图时圆点实际只有约 1.5px，
  //  2026-11-17 22:18 核实；必须除以总缩放才是真正的屏幕恒定尺寸）
  var baseScale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
  var scale = baseScale * view.k;
  // 标签字号统一（2026-11-17 用户要求：长度标记、节点编号、真名标签全部同一字号）：
  // 三种标签一律屏幕恒定 11px；k<1.5 时全图 110 个标签按可读尺寸会糊成一片，
  // 故放大到 1.5 倍后才显示（全图时它们只有约 2px，本来也看不清）
  var showLbl = view.k >= 1.5;
  var lblFs = 11 / scale, lblSw = 2.5 / scale, lblGap = 13 / scale;
  // 节点圆点：终端节点（连接器/卡扣）屏幕半径 DOT_R，手指可点；分支点/接头 DOT_R/2
  // （2026-11-17 用户真机反馈：终端节点点太小点不到，原实际约 1.5px）
  // 圆点半径自适应（2026-11-18 地板图自查：396 节点时 12px 圆点在手机全图糊成一片，
  // 线都看不见；半径按 sqrt 缩放，总面积大致恒定；110 节点以下仍 12px，IP 不变）
  var nNodes = Object.keys(nodesByCode).length;
  var DOT_R = nNodes <= 150 ? 12 : Math.max(5, Math.round(12 * Math.sqrt(150 / nNodes)));
  var DOT_R_FORK = Math.max(3, Math.round(DOT_R / 2));
  var dots = document.querySelectorAll('.ndot');
  for (var i = 0; i < dots.length; i++) {{
    var nt = nodesByCode[dots[i].parentNode.getAttribute('data-code')];
    var r = (nt && (nt.type === 'connector' || nt.type === 'clamp')) ? DOT_R : DOT_R_FORK;
    dots[i].setAttribute('r', r / scale);
    // 选中描边屏幕 3px，未选中 1.2px（CSS 只定颜色，宽度这里定，避免单位制混淆）
    var ring = dots[i].parentNode.classList.contains('sel') ? 3.0 : 1.2;
    dots[i].setAttribute('stroke-width', ring / scale);
  }}
  // 点按热区：终端节点屏幕约 18px 半径，其余约 12px
  var hits = document.querySelectorAll('.nhit');
  for (var h = 0; h < hits.length; h++) {{
    var ht = nodesByCode[hits[h].parentNode.getAttribute('data-code')];
    var hr = (ht && (ht.type === 'connector' || ht.type === 'clamp')) ? 18 : 12;
    hits[h].setAttribute('r', hr / scale);
  }}
  // 编号标签：紧贴各自圆点——x = 圆点右缘 + 3px（屏幕），y = 圆心 + 4px（基线略低于圆心），
  // 位置按圆点半径动态算，不许错位到别的点旁边（2026-11-17 用户补充令）
  // data-nside="L" 的节点（名签右边穿线、左边干净，见 _label_flip_set）翻到左边，右对齐
  var lbls = document.querySelectorAll('.lbl');
  for (var j = 0; j < lbls.length; j++) {{
    var lb = lbls[j];
    var showLb = showLbl && labelVis.node;
    lb.style.display = showLb ? '' : 'none';
    if (!showLb) continue;
    var nt = nodesByCode[lb.parentNode.getAttribute('data-code')];
    var dr = (nt && (nt.type === 'connector' || nt.type === 'clamp')) ? DOT_R : DOT_R_FORK;
    var flipLb = lb.getAttribute('data-nside') === 'L';
    lb.setAttribute('x', parseFloat(lb.getAttribute('data-nx')) + (flipLb ? -1 : 1) * (dr + 3) / scale);
    lb.setAttribute('y', parseFloat(lb.getAttribute('data-ny')) + 4 / scale);
    lb.style.textAnchor = flipLb ? 'end' : 'start';
    lb.style.fontSize = lblFs + 'px';
    lb.style.strokeWidth = lblSw + 'px';
  }}
  // 真名标签：与编号标签同一字号、同一 x，y 在编号标签下方一行（13px 屏幕行距）
  var nmlbls = document.querySelectorAll('.nmlbl');
  for (var nm = 0; nm < nmlbls.length; nm++) {{
    var nel = nmlbls[nm];
    var nt2 = nodesByCode[nel.parentNode.getAttribute('data-code')];
    var showNm = showLbl && (nt2 && nt2.type === 'connector' ? labelVis.conn : labelVis.clamp);
    nel.style.display = showNm ? '' : 'none';
    if (!showNm) continue;
    var dr2 = (nt2 && (nt2.type === 'connector' || nt2.type === 'clamp')) ? DOT_R : DOT_R_FORK;
    var flipNm = nel.getAttribute('data-nside') === 'L';
    nel.setAttribute('x', parseFloat(nel.getAttribute('data-nx')) + (flipNm ? -1 : 1) * (dr2 + 3) / scale);
    nel.setAttribute('y', parseFloat(nel.getAttribute('data-ny')) + 4 / scale + lblGap);
    nel.style.textAnchor = flipNm ? 'end' : 'start';
    nel.style.fontSize = lblFs + 'px';
    nel.style.strokeWidth = lblSw + 'px';
  }}
  var tubes = document.querySelectorAll('.tube');
  for (var t = 0; t < tubes.length; t++) {{
    // 线粗与圆点直径成比例（= 终端节点直径的 1/3，与圆点尺寸协调；不按直径/主干分层级，
    // 2026-11-17 用户要求：线粗统一，不要有的大有的小）；选中时为 DOT_R
    var wpx = tubes[t].classList.contains('sel') ? DOT_R : Math.max(3, Math.round(DOT_R * 2 / 3));
    tubes[t].setAttribute('stroke-width', wpx / scale);
  }}
  // 长度标签：与编号/真名标签同一字号（屏幕 11px），居中放在弧长中点上方 10px 处，不压线
  var lenOff = 10 / scale, lenSw = 3 / scale;
  var lenlbls = document.querySelectorAll('.lenlbl');
  for (var q = 0; q < lenlbls.length; q++) {{
    var el = lenlbls[q];
    var showLn = showLbl && labelVis.len;
    el.style.display = showLn ? '' : 'none';
    if (!showLn) continue;
    var mx = parseFloat(el.getAttribute('data-mx')), my = parseFloat(el.getAttribute('data-my'));
    var px = parseFloat(el.getAttribute('data-px')), py = parseFloat(el.getAttribute('data-py'));
    var lx = mx + px * lenOff, ly = my + py * lenOff;
    // v6p2：纯自环分支（Body.96）长度标签沿环方向外放（data-loff-dir 为布局坐标系角度，取负角换算到 SVG）
    var loffDir = el.getAttribute('data-loff-dir');
    if (loffDir !== null) {{
      var la = -parseFloat(loffDir) * Math.PI / 180;
      var ld = parseFloat(el.getAttribute('data-loff-dist')) / scale;
      lx += Math.cos(la) * ld;
      ly += Math.sin(la) * ld;
    }}
    el.setAttribute('x', lx);
    el.setAttribute('y', ly);
    el.style.fontSize = lblFs + 'px';
    el.style.strokeWidth = lenSw + 'px';
  }}
  // 自环符号（v6p2）：屏幕恒定半径 8px，圆心距节点 30px；data-dir 为布局坐标系角度（y 朝上），SVG 坐标系 y 朝下故取负角；选中时线宽 5px
  // （环距 30px 而非 20px：20px 时与 BN02 旁主干短管的长度标签重合——Body.71/Body.74 的标签距节点约 18px，2026-11-17 实测；30px 实测无重叠）
  var rings = document.querySelectorAll('.loopring');
  var loopLines = {{}};
  document.querySelectorAll('.loopline').forEach(function(ln) {{ loopLines[ln.getAttribute('data-seg')] = ln; }});
  for (var rg = 0; rg < rings.length; rg++) {{
    var ring = rings[rg];
    var rn = nodesByCode[ring.getAttribute('data-node')];
    if (!rn) continue;
    var ra = -parseFloat(ring.getAttribute('data-dir')) * Math.PI / 180;
    ring.setAttribute('cx', rn.x + Math.cos(ra) * 30 / scale);
    ring.setAttribute('cy', -rn.y + Math.sin(ra) * 30 / scale);
    ring.setAttribute('r', 8 / scale);
    ring.setAttribute('stroke-width', (ring.classList.contains('sel') ? 5 : 3) / scale);
    // 引线（2026-11-18）：节点中心 → 小环边缘（环半径 8px，止于 21px 处，
    // 即环外缘内 1px，视觉上接上）；节点圆点后画，盖住线头；1px 细虚线，
    // 不与管子混淆
    var ln = loopLines[ring.getAttribute('data-seg')];
    if (ln) {{
      ln.setAttribute('x1', rn.x);
      ln.setAttribute('y1', -rn.y);
      ln.setAttribute('x2', rn.x + Math.cos(ra) * 21 / scale);
      ln.setAttribute('y2', -rn.y + Math.sin(ra) * 21 / scale);
      ln.setAttribute('stroke-width', 1 / scale);
      ln.setAttribute('stroke-dasharray', (3 / scale) + ' ' + (2 / scale));
    }}
  }}
  var xlines = document.querySelectorAll('.xline');
  for (var m = 0; m < xlines.length; m++) {{ xlines[m].setAttribute('stroke-width', (2.0 / view.k)); }}
}}
function svgPoint(cx, cy) {{
  var pt = svg.createSVGPoint();
  pt.x = cx; pt.y = cy;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}}
function zoomAt(cx, cy, factor) {{
  var p = svgPoint(cx, cy);
  var k2 = Math.max(0.15, Math.min(40, view.k * factor));
  var f = k2 / view.k;
  view.x = p.x - (p.x - view.x) * f;
  view.y = p.y - (p.y - view.y) * f;
  view.k = k2;
  applyView();
}}
function centerOn(x, y, k, ax, ay) {{
  if (k) view.k = k;
  applyView();
  var r = svg.getBoundingClientRect();
  // 注意：getScreenCTM() 的逆变换要的是屏幕（client）坐标，必须加 r.left/r.top；
  // 旧版只用 r.width/2、r.height/2（元素相对坐标），目标会落在 header 下方被遮住
  // （2026-11-17 实测：BN02 应在 SVG 中心 y=521，实际落在 y=259）
  // 2026-11-19：搜索定位时目标要落在弹窗上方可见区的中央，ax/ay 指定屏幕锚点；
  // 不传则仍用 SVG 中心（点按定位等沿用旧行为）
  var pt = svg.createSVGPoint();
  pt.x = (ax !== undefined) ? ax : (r.left + r.width / 2);
  pt.y = (ay !== undefined) ? ay : (r.top + r.height / 2);
  var c = pt.matrixTransform(svg.getScreenCTM().inverse());
  // c 为锚点对应的 viewBox 点；要让图上点 (x,y) 落到锚点：
  // x*k + t = c，故 t = c - x*k（直接赋值，一步到位）
  view.x = c.x - x * view.k;
  view.y = c.y - y * view.k;
  applyView();
}}
// 搜索定位专用：弹窗先开，再把目标放到弹窗上方可见区的中央
// （2026-11-19 用户反馈：定位只放到 2 倍，目标淹没在标签堆里找不到；弹窗高时还会盖住目标）
function locateOn(x, y, k) {{
  var r = svg.getBoundingClientRect();
  var ax = r.left + r.width / 2, ay = r.top + r.height / 2;
  if (popup.style.display === 'block') {{
    var pr = popup.getBoundingClientRect();
    if (pr.top > r.top + 40) ay = (r.top + pr.top) / 2;
  }}
  centerOn(x, y, k, ax, ay);
}}
function locateZoom(spanMm) {{
  // spanMm：目标跨度（mm）；可见宽度取跨度 1.6 倍 + 100mm 余量；节点默认按 500mm 窗口
  var vw = svg.viewBox.baseVal.width;
  var want = spanMm ? (spanMm * 1.6 + 100) : 500;
  return Math.max(2, Math.min(40, vw / want));
}}
function fitAll() {{ view = {{ x: 0, y: 0, k: 1 }}; applyView(); }}

// ---- 指针交互：拖动 / 缩放 / 点按 ----
var pointers = {{}};
var pinchDist = 0, pinchMid = null;
var downX = 0, downY = 0, downT = 0, moved = false, dragging = false;
svg.addEventListener('pointerdown', function(e) {{
  svg.setPointerCapture(e.pointerId);
  pointers[e.pointerId] = {{ x: e.clientX, y: e.clientY }};
  var ids = Object.keys(pointers);
  if (ids.length === 1) {{
    downX = e.clientX; downY = e.clientY; downT = Date.now(); moved = false; dragging = true;
    svg.classList.add('dragging');
  }} else if (ids.length === 2) {{
    dragging = false;
    var a = pointers[ids[0]], b = pointers[ids[1]];
    pinchDist = Math.hypot(a.x - b.x, a.y - b.y);
    pinchMid = {{ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }};
  }}
  e.preventDefault();
}});
svg.addEventListener('pointermove', function(e) {{
  if (!pointers[e.pointerId]) return;
  var prev = pointers[e.pointerId];
  pointers[e.pointerId] = {{ x: e.clientX, y: e.clientY }};
  var ids = Object.keys(pointers);
  if (ids.length === 2) {{
    var a = pointers[ids[0]], b = pointers[ids[1]];
    var d = Math.hypot(a.x - b.x, a.y - b.y);
    var mid = {{ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }};
    if (pinchDist > 0) {{
      zoomAt(mid.x, mid.y, d / pinchDist);
      var p0 = svgPoint(pinchMid.x, pinchMid.y);
      var p1 = svgPoint(mid.x, mid.y);
      view.x += (p1.x - p0.x); view.y += (p1.y - p0.y);
      applyView();
    }}
    pinchDist = d; pinchMid = mid;
    moved = true;
  }} else if (dragging) {{
    var dx = e.clientX - downX, dy = e.clientY - downY;
    // 位移容差 12px：真人手指点按有轻微抖动，6px 太严会被判成拖动（2026-11-17 用户真机反馈）
    if (Math.abs(dx) + Math.abs(dy) > 12) moved = true;
    if (moved) {{
      var p0 = svgPoint(prev.x, prev.y);
      var p1 = svgPoint(e.clientX, e.clientY);
      view.x += (p1.x - p0.x); view.y += (p1.y - p0.y);
      applyView();
    }}
  }}
}});
function endPointer(e) {{
  // 点按判定放宽到 700ms：真人慢点（>400ms）原先会被判成拖动而不弹窗（2026-11-17 用户真机反馈）
  var wasTap = dragging && !moved && (Date.now() - downT) < 700;
  delete pointers[e.pointerId];
  if (Object.keys(pointers).length === 0) {{
    dragging = false;
    svg.classList.remove('dragging');
    pinchDist = 0;
    if (wasTap) handleTap(e);
  }}
}}
svg.addEventListener('pointerup', endPointer);
svg.addEventListener('pointercancel', function(e) {{ delete pointers[e.pointerId]; dragging = false; svg.classList.remove('dragging'); pinchDist = 0; }});
svg.addEventListener('wheel', function(e) {{
  e.preventDefault();
  zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.15 : 1 / 1.15);
}}, {{ passive: false }});
svg.addEventListener('dblclick', function(e) {{ zoomAt(e.clientX, e.clientY, 1.6); }});

// ---- 点按详情 ----
function clearSel() {{
  document.querySelectorAll('.sel').forEach(function(el) {{ el.classList.remove('sel'); }});
  document.querySelectorAll('.node.hl').forEach(function(el) {{ el.classList.remove('hl'); }});
  applyView();  // 选中状态变了，线宽/描边跟着变
}}
function esc(s) {{ return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }}
// §二十八端点显示名：连接器显示真名（disp），其余显示编号；disp 由 Python
// 侧算好放进 DATA，JS 只读 disp，不另写判定（查不到的编号原样返回）
function dispNode(code) {{ var n = nodesByCode[code]; return (n && n.disp) ? n.disp : code; }}
function dispRoute(rn) {{ if (!rn) return '-'; return rn.split('_').map(function(c) {{ var m = c.match(/^(.*)#(\\d+)$/); var base = m ? m[1] : c; var suf = m ? '#' + m[2] : ''; return dispNode(base) + suf; }}).join('_'); }}
function showNode(code) {{
  var n = nodesByCode[code];
  if (!n) return;
  clearSel();
  var g = document.querySelector('.node[data-code="' + code + '"]');
  if (g) g.classList.add('sel');
  // 选中节点时相连的线不许变色：节点选中与线选中完全分开，只亮节点本身
  // （2026-11-17 用户要求：选中什么就亮什么；旧版会把相连管子也标橙）
  var conns = DATA.node_branches[code] || [];  // 只用于弹窗里列出连接管子，不再高亮
  // 标题：连接器有真名时显示真名（n.disp，§二十八口径），无真名时仍用编号
  // （2026-11-20 用户定：要“实际名字 · 连接器”这种展示；标题改真名后编号另起一行，不丢）
  var titleName = n.disp || code;
  var rows = (titleName !== code ? '<tr><td class="k">编号</td><td class="mono">' + esc(code) + '</td></tr>' : '')
    + '<tr><td class="k">类型</td><td>' + esc(TYPE_CN[n.type] || n.type) + '</td></tr>'
    + '<tr><td class="k">3D 全名</td><td class="mono">' + esc(n.name_3d || '（无实体名）') + '</td></tr>'
    + '<tr><td class="k">2D 坐标</td><td>(' + n.x.toFixed(1) + ', ' + n.y.toFixed(1) + ') mm</td></tr>'
    + '<tr><td class="k">连接管子</td><td class="mono">' + esc(conns.join(', ') || '—') + '</td></tr>';
  popBody.innerHTML = '<h2>' + esc(titleName) + ' · ' + esc(TYPE_CN[n.type] || n.type) + '</h2><table>' + rows + '</table>';
  popup.style.display = 'block';
  applyView();  // 选中描边加粗
}}
function showBranch(key) {{
  var b = branchesByKey[key];
  if (!b) return;
  clearSel();
  // v6p2：用解析后的 b.key 找管子元素（搜组成管子编号时 key 是组成编号，元素上是合并 key）
  var pl = document.querySelector('.tube[data-key="' + b.key + '"]');
  if (pl) pl.classList.add('sel');
  // v6p2：该管子有自环符号时小环一起亮（选中什么亮什么，小环是管子的一部分）
  document.querySelectorAll('.loopring[data-key="' + b.key + '"]').forEach(function(rg) {{ rg.classList.add('sel'); }});
  // 选中管子时端点节点不许高亮：只亮管子本身（同上，选中什么亮什么）
  var bs = DATA.bends.filter(function(x) {{ return x.branch === key; }});
  var bendTxt = bs.length ? bs.map(function(x) {{ return x.seg + ' @' + x.at + ' ' + (typeof x.delta === 'number' ? (x.delta > 0 ? '+' : '') + x.delta + '°' : x.delta) + '（' + x.note + '）'; }}).join('<br>') : '无';
  var segs = b.pieces.map(function(p) {{ return p.seg + ' ' + dispNode(p.na) + '→' + dispNode(p.nb); }}).join('<br>');
  // 平行管（v6p1：平行对只画一根，被隐藏那根的数据列在这里，不丢数据）
  var parRows = '';
  (b.parallel_hidden || []).forEach(function(h) {{
    parRows += '<tr><td class="k">平行管</td><td class="mono">' + esc(h.hidden_branch) + ' Φ' + h.hidden_dia_mm + ' · ' + h.hidden_length_mm + ' mm（' + esc(h.pair) + (h.merged_via ? '，经 ' + esc(h.merged_via) + ' 合并' : '') + '，未单画）</td></tr>';
  }});
  (b.hidden_segs || []).forEach(function(h) {{
    parRows += '<tr><td class="k">平行段</td><td class="mono">' + esc(h.seg) + ' ' + h.length_mm + ' mm · Φ' + h.dia_mm + '（与 ' + esc(h.kept_branch) + ' ' + esc(h.kept_seg) + ' 平行，未单画）</td></tr>';
  }});
  var trunkRow = '';
  if (b.trunk_positions && b.trunk_positions.length) {{
    // v6p2：合并的主干路径占连续多根，显示序号范围
    var tps = b.trunk_positions.slice().sort(function(a, c) {{ return a - c; }});
    var rng = tps.length > 1 ? ('第 ' + tps[0] + '–' + tps[tps.length - 1]) : ('第 ' + tps[0]);
    trunkRow = '<tr><td class="k">主干路径</td><td>是 · ' + rng + ' / ' + DATA.trunk_path.branches + ' 根</td></tr>';
  }} else if (trunkIdx[key]) {{
    trunkRow = '<tr><td class="k">主干路径</td><td>是 · 第 ' + trunkIdx[key] + ' / ' + DATA.trunk_path.branches + ' 根</td></tr>';
  }}
  // v6p2：合并路径列出每根组成管子（编号、直径、长度、段），直径不同时也分开列，不丢数据；
  // 部分管子（Body.113 的 SEG01 在链里、SEG02 另成线）标“（部分）”
  var diaRows = '';
  if (b.merged_from && b.merged_from.length) {{
    diaRows = b.merged_from.map(function(m) {{
      var sg = (m.segs && m.segs.length) ? ' · ' + m.segs.join('+') : '';
      var pt = m.partial ? '（部分）' : '';
      return '<tr><td class="k">组成管子</td><td class="mono">' + esc(m.key) + pt + ' · Φ' + m.dia + ' · ' + m.len_3d + ' mm' + sg + '</td></tr>';
    }}).join('');
  }} else {{
    diaRows = '<tr><td class="k">直径</td><td>Φ' + b.dia + ' mm</td></tr>';
  }}
  // v6p2：单根但被拆开的管子（Body.113 余段），说明另一部分在哪
  var partialRow = '';
  if (b.partial) {{
    partialRow = '<tr><td class="k">部分管段</td><td>本管仅含 ' + esc(b.partial.segs_here.join('+')) + '（' + b.len_3d + ' mm）；其余段在 ' + esc(b.partial.other_paths.join('、')) + ' 中（整管 ' + b.partial.total_len_3d + ' mm）</td></tr>';
  }}
  // v6p2：自环说明（图上画为小环符号，不按比例，真值在此）
  // 2026-11-18：环弦符号（kind=chord）另写一行，注明连接的两节点
  var loopRows = '';
  (b.loop || []).forEach(function(lp) {{
    if (lp.kind === 'chord') {{
      loopRows += '<tr><td class="k">环弦</td><td class="mono">' + esc(lp.seg) + ' ' + lp.length_mm + ' mm · Φ' + lp.dia_mm + '（连接 ' + esc(lp.node) + '—' + esc(lp.far) + '，图上画为小环符号，不按比例；§六环优先待实现）</td></tr>';
    }} else {{
      loopRows += '<tr><td class="k">自环</td><td class="mono">' + esc(lp.seg) + ' ' + lp.length_mm + ' mm · Φ' + lp.dia_mm + '（图上画为小环符号，不按比例）</td></tr>';
    }}
  }});
  var rows = trunkRow + diaRows + partialRow
    + '<tr><td class="k">3D 弧长</td><td>' + b.len_3d + ' mm</td></tr>'
    + '<tr><td class="k">2D 长度</td><td>' + b.len_2d + ' mm</td></tr>'
    + '<tr><td class="k">端点</td><td class="mono">' + esc(dispNode(b.node0)) + ' → ' + esc(dispNode(b.node1)) + '</td></tr>'
    + '<tr><td class="k">路由名</td><td class="mono">' + esc(dispRoute(b.route_name)) + '</td></tr>'
    + '<tr><td class="k">线段</td><td class="mono">' + segs + '</td></tr>' + parRows + loopRows
    + '<tr><td class="k">拐弯</td><td>' + bendTxt + '</td></tr>';
  popBody.innerHTML = '<h2>管子 ' + esc(b.key) + '</h2><table>' + rows + '</table>';
  popup.style.display = 'block';
  applyView();  // 选中线加粗
}}
// 点按命中辅助：屏幕坐标 (cx,cy) 到最近节点的距离（像素），返回 {{code, d}}，无节点则 null
function nearestNodeDist(cx, cy) {{
  var best = null, bd = Infinity;
  var dots = document.querySelectorAll('.node .ndot');
  for (var i = 0; i < dots.length; i++) {{
    var r = dots[i].getBoundingClientRect();
    var d = Math.hypot(cx - (r.left + r.width / 2), cy - (r.top + r.height / 2));
    if (d < bd) {{ bd = d; best = dots[i].parentNode.getAttribute('data-code'); }}
  }}
  return best ? {{ code: best, d: bd }} : null;
}}
function distToSeg(px, py, x1, y1, x2, y2) {{
  var dx = x2 - x1, dy = y2 - y1;
  var len2 = dx * dx + dy * dy;
  var t = len2 ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / len2)) : 0;
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}}
// 屏幕坐标到最近管子的距离（像素，点到折线段最短距离），返回 {{key, d}}，无则 null
function nearestTubeDist(cx, cy) {{
  var p = svgPoint(cx, cy);
  // 注意：svgPoint 得出的是 viewBox 坐标，须先逆变换到 vp 局部坐标（管子折线点
  // 的坐标系），否则视图平移/缩放后距离全错（2026-11-17 实测：平移后中点距管子 70px）
  var px = (p.x - view.x) / view.k, py = (p.y - view.y) / view.k;
  var scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width * view.k;
  var best = null, bd = Infinity;
  var tubes = document.querySelectorAll('.tube');
  for (var i = 0; i < tubes.length; i++) {{
    var pts = tubes[i].points;
    for (var j = 0; j + 1 < pts.numberOfItems; j++) {{
      var a = pts.getItem(j), b = pts.getItem(j + 1);
      var d = distToSeg(px, py, a.x, a.y, b.x, b.y) * scale;
      if (d < bd) {{ bd = d; best = tubes[i].getAttribute('data-key'); }}
    }}
  }}
  return best ? {{ key: best, d: bd }} : null;
}}
// 屏幕坐标到最近自环符号圆心的距离（像素），返回 {{key, d}}，无则 null
function nearestRingDist(cx, cy) {{
  var best = null, bd = Infinity;
  var rings = document.querySelectorAll('.loopring');
  for (var i = 0; i < rings.length; i++) {{
    var r = rings[i].getBoundingClientRect();
    var d = Math.hypot(cx - (r.left + r.width / 2), cy - (r.top + r.height / 2));
    if (d < bd) {{ bd = d; best = rings[i].getAttribute('data-key'); }}
  }}
  return best ? {{ key: best, d: bd }} : null;
}}
function handleTap(e) {{
  // 注意：pointerdown 里 svg.setPointerCapture 会把 pointerup 的 e.target
  // 重定向到 svg 本身，故不能用 e.target / elementFromPoint 判断点中了什么，
  // 改按坐标算距离命中（2026-11-17 实测：未修前点任意节点 e.target 恒为 svg）。
  // 优先级按距离取最近：落点到节点中心与到管子折线谁近选谁，节点不再无条件
  // 优先——否则点在线中部也会弹连接器（2026-11-17 用户真机反馈）。
  var cx = e.clientX, cy = e.clientY;
  var nd = nearestNodeDist(cx, cy);
  var td = nearestTubeDist(cx, cy);
  var rd = nearestRingDist(cx, cy);
  // 容差：弹窗关闭时节点 24px / 管子 20px；弹窗已开时收紧（节点 12px / 管子 10px），
  // 否则图上到处是节点/管子，点空白关不掉弹窗；小环与管子同容差
  var open = popup.style.display === 'block';
  var nodeTol = open ? 12 : 24, tubeTol = open ? 10 : 20;
  var nodeOk = nd && nd.d <= nodeTol;
  var tubeOk = td && td.d <= tubeTol;
  var ringOk = rd && rd.d <= tubeTol;
  if (nodeOk && (!tubeOk || nd.d <= td.d) && (!ringOk || nd.d <= rd.d)) {{ showNode(nd.code); return; }}
  if (ringOk && (!tubeOk || rd.d <= td.d)) {{ showBranch(rd.key); return; }}
  if (tubeOk) {{ showBranch(td.key); return; }}
  popup.style.display = 'none';
  clearSel();
}}
document.getElementById('btnClose').addEventListener('click', function() {{ popup.style.display = 'none'; clearSel(); }});
document.getElementById('btnFit').addEventListener('click', fitAll);
document.getElementById('btnClear').addEventListener('click', function() {{
  popup.style.display = 'none'; clearSel();
  document.getElementById('search').value = '';
}});
function toast(msg) {{
  toastEl.textContent = msg;
  toastEl.style.display = 'block';
  setTimeout(function() {{ toastEl.style.display = 'none'; }}, 2200);
}}
function doSearch() {{
  var q = document.getElementById('search').value.trim().toUpperCase();
  if (!q) return;
  if (nodesByCode[q]) {{
    var n = nodesByCode[q];
    showNode(q);
    locateOn(n.x, -n.y, locateZoom(0));
    return;
  }}
  var key = q;
  if (/^B\\d+$/.test(q)) key = 'Body.' + q.slice(1);
  if (/^BODY\\.?\\d+$/.test(q)) key = 'Body.' + q.replace(/^BODY\\.?/, '');
  if (branchesByKey[key]) {{
    var b = branchesByKey[key];
    var mx = 0, my = 0, x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    b.points.forEach(function(p) {{ mx += p[0]; my += p[1]; if (p[0] < x0) x0 = p[0]; if (p[0] > x1) x1 = p[0]; if (p[1] < y0) y0 = p[1]; if (p[1] > y1) y1 = p[1]; }});
    mx /= b.points.length; my /= b.points.length;
    showBranch(key);
    locateOn(mx, -my, locateZoom(Math.max(x1 - x0, y1 - y0)));
    return;
  }}
  toast('没找到 ' + q);
}}
document.getElementById('btnSearch').addEventListener('click', doSearch);
document.getElementById('search').addEventListener('keydown', function(e) {{ if (e.key === 'Enter') doSearch(); }});
// ---- 图例折叠（窄屏默认收起，点开才展开） ----
document.getElementById('legendToggle').addEventListener('click', function() {{
  var lg = document.getElementById('legend');
  var open = lg.classList.toggle('open');
  this.textContent = open ? '图例 ▾' : '图例 ▸';
}});
// ---- 标签下拉菜单（v6p2：图面字太多显乱，四开关默认全开，点选即时生效，不重载；点面板外关闭） ----
var labelBtn = document.getElementById('btnLabels');
var labelPanel = document.getElementById('labelPanel');
function updateLabelBtn() {{
  var n = (labelVis.conn ? 1 : 0) + (labelVis.clamp ? 1 : 0) + (labelVis.node ? 1 : 0) + (labelVis.len ? 1 : 0);
  labelBtn.textContent = '标签 ' + n + '/4 ▾';
}}
labelBtn.addEventListener('click', function(e) {{
  e.stopPropagation();
  labelPanel.classList.toggle('open');
}});
document.addEventListener('click', function(e) {{
  if (!document.getElementById('labelDD').contains(e.target)) labelPanel.classList.remove('open');
}});
labelPanel.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {{
  cb.addEventListener('change', function() {{
    labelVis[cb.getAttribute('data-lbl')] = cb.checked;
    updateLabelBtn();
    applyView();
  }});
}});
// ---- 旧浏览器无 100dvh 时，用 visualViewport 实际高度定 body 高 ----
if (!window.CSS || !CSS.supports('height', '100dvh')) {{
  var fixH = function() {{
    var vh = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    document.body.style.height = vh + 'px';
  }};
  fixH();
  window.addEventListener('resize', fixH);
  if (window.visualViewport) window.visualViewport.addEventListener('resize', fixH);
}}
applyView();
</script>
</body>
</html>
'''
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    print(f'wrote {out_path} ({len(html_doc)/1024:.0f} KB)')
    print(f'branches={len(branches)} nodes={len(nodes)} segments={n_seg}')
    print(f'viewBox {vb_x:.1f} {vb_y:.1f} {vb_w:.1f} {vb_h:.1f}')

if __name__ == '__main__':
    main()
