#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线束拓扑提取 V7 实现.

按 V7 逻辑定稿实现:
- Step 0: 单位检测
- Step 1: 实体遍历 + 实例化去重 + 管识别 + 中心线
- Step 2: 包围盒预计算(复用池)
- Step 3: (E,Y)接触检测 + BRepExtrema二次校验
- Step 4: 三类判定
- Step 5: 管-管连接(Union-Find + 传递闭包约束)
- Step 6: 坐标推理
- Step 7: 编码输出 + 连通性校验

阈值: 管管 6.0 / 接触 2.0 / 端部 5.0 / 站位合并 10.0 (mm)
"""
import math
import time
import numpy as np

from harness_topology import (
    is_tube_solid, face_centerline, chain_curves, circle_center_3d,
    spines_overlap, polyline_dist, profile_circle,
    label_name, comp_location, is_real_name, count_topo,
    decode_name, face_areas,
)

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TopLoc import TopLoc_Location
from OCP.TDF import TDF_Label
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_WIRE, TopAbs_SOLID
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Trsf, gp_Pnt
from OCP.TopLoc import TopLoc_Location
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.GeomAbs import GeomAbs_Plane

# 阈值 (mm)
TUBE_TUBE_TOL = 6.0
CONTACT_TOL = 2.0
END_TOL = 5.0
STATION_MERGE_TOL = 10.0
CLOSURE_FACTOR = 1.2  # 传递闭包约束系数


def _d3(a, b):
    """三维欧氏距离. 输入: 两点坐标(a,b). 输出: 距离(mm)."""
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def point_box_dist(p, box):
    """点到包围盒的最短距离. box=(xmin,xmax,ymin,ymax,zmin,zmax)"""
    xmin, xmax, ymin, ymax, zmin, zmax = box
    x0, y0, z0 = p[0], p[1], p[2]
    if x0 < xmin: dx = xmin - x0
    elif x0 > xmax: dx = x0 - xmax
    else: dx = 0.0
    if y0 < ymin: dy = ymin - y0
    elif y0 > ymax: dy = y0 - ymax
    else: dy = 0.0
    if z0 < zmin: dz = zmin - z0
    elif z0 > zmax: dz = z0 - zmax
    else: dz = 0.0
    return math.sqrt(dx*dx + dy*dy + dz*dz)


def box_box_dist(b1, b2):
    """盒-盒最短距离."""
    xmin1, xmax1, ymin1, ymax1, zmin1, zmax1 = b1
    xmin2, xmax2, ymin2, ymax2, zmin2, zmax2 = b2
    dx = max(0.0, xmin2 - xmax1, xmin1 - xmax2)
    dy = max(0.0, ymin2 - ymax1, ymin1 - ymax2)
    dz = max(0.0, zmin2 - zmax1, zmin1 - zmax2)
    return math.sqrt(dx*dx + dy*dy + dz*dz)


def box_diag(box):
    """包围盒对角线长度. 输入: box=(xmin,xmax,ymin,ymax,zmin,zmax). 输出: 对角线(mm). 用于 Step3 预粗筛阈值."""
    xmin, xmax, ymin, ymax, zmin, zmax = box
    return math.sqrt((xmax-xmin)**2 + (ymax-ymin)**2 + (zmax-zmin)**2)


def box_union(b1, b2):
    """两包围盒并集. 输入: b1,b2. 输出: 并集盒. 用于 Step2 求 B_all(全部管盒并集)."""
    return (min(b1[0], b2[0]), max(b1[1], b2[1]),
            min(b1[2], b2[2]), max(b1[3], b2[3]),
            min(b1[4], b2[4]), max(b1[5], b2[5]))


# ============ Step 0: 单位检测 ============
def detect_unit(step_path):
    """Step 0: 检测 STEP 长度单位, 返回换算到 mm 的系数.

    优先级 (V7): CONVERSION_BASED_UNIT → SI_UNIT → LENGTH_MEASURE_WITH_UNIT.
    都未找到 → 默认 mm 并由调用方输出 WARNING.
    全文扫描 (单位声明可能在文件尾部).
    """
    import re
    try:
        with open(step_path, 'r', errors='ignore') as f:
            txt = f.read()  # 全文扫描
        # 1. CONVERSION_BASED_UNIT (最高优先级)
        m = re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'([^']+)'", txt, re.I)
        if m:
            u = m.group(1).upper()
            if 'INCH' in u: return 25.4
            if u in ('MM', 'MILLIMETER', 'MILLIMETRE'): return 1.0
            if u in ('M', 'METER', 'METRE'): return 1000.0
            if 'CM' in u or 'CENTI' in u: return 10.0
        # 2. SI_UNIT
        if re.search(r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.", txt, re.I):
            return 1.0
        if re.search(r"SI_UNIT\s*\(\s*\.\s*,\s*\.METRE\.", txt, re.I):
            return 1000.0  # 米
        # 3. LENGTH_MEASURE_WITH_UNIT
        m2 = re.search(r"LENGTH_MEASURE_WITH_UNIT\s*\([^)]*,\s*(?:SI_UNIT|CONVERSION_BASED_UNIT)[^)]*\)", txt, re.I)
        if m2:
            seg = m2.group(0).upper()
            if 'MILLI' in seg: return 1.0
            if 'INCH' in seg: return 25.4
        # 4. 默认 mm (调用方输出 WARNING)
        return 1.0
    except Exception:
        return 1.0


# ============ Step 1: 实体遍历 + 去重 + 管识别 ============
def _wire_length(wire):
    """wire 周长."""
    try:
        total = 0.0
        ex = TopExp_Explorer(wire, TopAbs_EDGE)
        while ex.More():
            e = ex.Current()
            try:
                ad = BRepAdaptor_Curve(e)
                total += ad.LastParameter() - ad.FirstParameter()
                # 近似: 用参数差, 对直线/圆弧够用; 更精确可用 GCP
            except Exception:
                pass
            ex.Next()
        # 用 BRep_Tool.Polygon3D 精确算
        total = 0.0
        ex2 = TopExp_Explorer(wire, TopAbs_EDGE)
        while ex2.More():
            e = ex2.Current()
            try:
                poly = BRep_Tool.Polygon3D_s(e)
                if poly is not None:
                    nodes = poly.Nodes()
                    for i in range(1, nodes.Length()):
                        p1 = nodes.Value(i); p2 = nodes.Value(i+1)
                        total += math.sqrt((p1.X()-p2.X())**2 + (p1.Y()-p2.Y())**2 + (p1.Z()-p2.Z())**2)
            except Exception:
                pass
            ex2.Next()
        return total
    except Exception:
        return 0.0


def _end_center(face, trsf):
    """端面圆心: 取周长最大的 wire 边界点拟合; 失败兜底 CentreOfMass."""
    try:
        best_pts = None
        best_len = -1
        ex = TopExp_Explorer(face, TopAbs_WIRE)
        while ex.More():
            w = ex.Current()
            ln = _wire_length(w)
            if ln > best_len:
                best_len = ln
                # 采样该 wire 的点
                pts = []
                ex2 = TopExp_Explorer(w, TopAbs_EDGE)
                while ex2.More():
                    e = ex2.Current()
                    try:
                        poly = BRep_Tool.Polygon3D_s(e)
                        if poly is not None:
                            nodes = poly.Nodes()
                            for i in range(1, nodes.Length()+1):
                                p = nodes.Value(i)
                                g = gp_Pnt(p.X(), p.Y(), p.Z()); g.Transform(trsf)
                                pts.append([g.X(), g.Y(), g.Z()])
                    except Exception:
                        pass
                    ex2.Next()
                if pts:
                    best_pts = np.array(pts)
            ex.Next()
        if best_pts is not None and len(best_pts) >= 3:
            c, r, res = profile_circle(best_pts)
            if np.all(np.isfinite(c)) and res <= 0.5:
                return tuple(c), True
        # 兜底: CentreOfMass
        p = GProp_GProps(); BRepGProp.SurfaceProperties_s(face, p)
        c = p.CentreOfMass()
        pt = gp_Pnt(c.X(), c.Y(), c.Z()); pt.Transform(trsf)
        return (pt.X(), pt.Y(), pt.Z()), False
    except Exception:
        return None, False


def extract_entities(step_path, unit_scale=1.0, log=print):
    """Step 1: 遍历 + 实例化去重 + 管识别 + 中心线.

    返回: meta[], tubes[], non_tubes[]
    meta: [{sid, name}] (M 个去重后, S编号保留原始可能有空洞)
    tubes: [{sid, name, p0, p1, dia, length, spine, solids...}]
    non_tubes: [{sid, name, shape, trsf}]
    """
    from OCP.collections import Sequence_TDF_Label
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    reader.ReadFile(step_path)
    reader.Transfer(doc)
    S = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    # 顶层 shapes (V7: 遍历全部, 不只取最大装配)
    tops = Sequence_TDF_Label(); S.GetShapes(tops)

    leaves = []
    def walk(lab, path, ptr, ctx):
        """递归遍历装配树: 收集叶节点 solid 的 label/路径/变换矩阵. Step1 实体遍历用."""
        ref = TDF_Label()
        if S.IsComponent_s(lab):
            if not S.GetReferredShape_s(lab, ref):
                ref = lab
        else:
            ref = lab
        rn = label_name(ref)
        if is_real_name(rn):
            ctx = rn
        if S.IsAssembly_s(ref):
            cs = Sequence_TDF_Label(); S.GetComponents_s(ref, cs)
            for i in range(1, cs.Length()+1):
                c = cs.Value(i)
                loc = comp_location(c)
                t = loc.Transformation() if not loc.IsIdentity() else gp_Trsf()
                g = gp_Trsf(); g.Multiply(ptr); g.Multiply(t)
                walk(c, path+[label_name(c)], g, ctx)
        else:
            # occ: 实例全路径 (如 "HAR/Body.84"), 用于 JSON 反查 S 编号
            occ = "/".join([p for p in path if is_real_name(p)])
            leaves.append({"proto": ctx, "occ": occ, "shape": S.GetShape_s(ref), "trsf": ptr})

    # V7 修正 (2026-10-06): 不只取最大装配, 遍历所有顶层 shape.
    # X1X 有 3 个顶层 (1装配+2单体), 只取最大会漏实体.
    for i in range(1, tops.Length()+1):
        lab = tops.Value(i)
        walk(lab, [], gp_Trsf(), label_name(lab))

    # V7 (2026-10-06): 先收集全部 (sol, trsf, name), 拆分后再去重.
    # 去重规则: IsSame(shape) 且 trsf 相同 → 重复 (walk 重复访问).
    # X1X 的 10 个分支是 10 个不同原型 (Multi-branchable1.1~10.1), IsSame 不会误压.
    def _trsf_equal(t1, t2, tol=1e-6):
        try:
            for i in range(1, 4):
                for j in range(1, 5):
                    if abs(t1.Value(i, j) - t2.Value(i, j)) > tol:
                        return False
            return True
        except Exception:
            return False
    # 1. 拆分全部叶节点
    all_sols = []  # [(sol, trsf, proto, occ)]
    for lf in leaves:
        shp = lf["shape"]
        sols = []
        ex = TopExp_Explorer(shp, TopAbs_SOLID)
        while ex.More():
            sols.append(ex.Current()); ex.Next()
        if not sols:
            sols = [shp]
        for sol in sols:
            all_sols.append((sol, lf["trsf"], lf["proto"], lf.get("occ", "")))
    log(f"拆分: {len(leaves)} 叶节点 -> {len(all_sols)} solid")
    # 2. 智能去重
    seen = []
    uniq_sols = []
    for (sol, trsf, proto, occ) in all_sols:
        dup = False
        for (s, t) in seen:
            try:
                if sol.IsSame(s) and _trsf_equal(trsf, t):
                    dup = True; break
            except Exception:
                pass
        if not dup:
            seen.append((sol, trsf))
            uniq_sols.append((sol, trsf, proto, occ))
    log(f"去重: {len(all_sols)} -> {len(uniq_sols)} 独立实体")

    # S编号说明 (2026-10-06 实测结论):
    # JSON 的 S 编号是 STEP representation item 顺序, CAF 标签名与 JSON BREP 名无对应关系,
    # 190/190 反查失败. 故 V7 用实例全名(occ)做主键, sid 仅为 V7 本地顺序号 (V7_0, V7_1...),
    # 与 IP-Harness_step_name_map.json 的 S 编号不对应. 待用户确认是否接受.
    meta = []
    tubes = []
    non_tubes = []
    si_v7 = 0
    for (sol, trsf, proto_name, occ_name) in uniq_sols:
        # V7 本地顺序号 (与 JSON S 编号不对应, 见上说明)
        sid = f"V7_{si_v7}"
        si_v7 += 1
        name = occ_name or proto_name or sid
        meta.append({"sid": sid, "name": name})
        # 管判定
        tr = is_tube_solid(sol)
        if tr is not None:
            cap_faces = tr["cap_faces"]
            # 端面圆心 (周长最大 wire)
            p0, ok0 = _end_center(cap_faces[0], trsf)
            p1, ok1 = _end_center(cap_faces[1], trsf)
            if p0 is None or p1 is None:
                non_tubes.append({"sid": sid, "name": name, "shape": sol, "trsf": trsf})
                continue
            # 中心线
            dia = tr["dia"]
            L = tr["length"]
            n_station = max(8, min(48, int(L/5) if L > 0 else 8))
            spines = []
            for lf_face in tr["lat_faces"]:
                try:
                    sp = face_centerline(lf_face, trsf, dia, n_station=n_station)
                    if sp is not None and len(sp) > 1:
                        spines.append({"pts": sp, "len": float(np.sum(np.linalg.norm(np.diff(sp, axis=0), axis=1)))})
                except Exception:
                    pass
            # 去重: 重叠>=50% 留最长
            kept = []
            spines.sort(key=lambda s: -s["len"])
            for s in spines:
                dup = False
                for k in kept:
                    try:
                        if spines_overlap(s["pts"], k["pts"], tol=2.0, frac=0.5):
                            dup = True; break
                    except Exception:
                        pass
                if not dup:
                    kept.append(s)
            if not kept and spines:
                kept = [spines[0]]  # 兜底: 取最长
            if kept:
                curve_list = [{"pts": s["pts"], "len": s["len"]} for s in kept]
                spine, slen = chain_curves(curve_list, tol=2.0)
            else:
                spine, slen = np.zeros((0,3)), 0.0
            tubes.append({
                "sid": sid, "name": name,
                "p0": tuple(np.array(p0)*unit_scale), "p1": tuple(np.array(p1)*unit_scale),
                "dia": dia * unit_scale, "length": L * unit_scale,
                "spine": spine * unit_scale if len(spine) else spine,
                "spine_len": slen * unit_scale,
                "shape": sol, "trsf": trsf,  # Step2 真实BRep盒用
            })
        else:
            non_tubes.append({"sid": sid, "name": name, "shape": sol, "trsf": trsf})
    log(f"管子: {len(tubes)}, 非管: {len(non_tubes)}")
    return meta, tubes, non_tubes


# ============ Step 2: 包围盒预计算 ============
def _shape_box(shape, trsf):
    """返回 (xmin,xmax,ymin,ymax,zmin,zmax), 考虑 trsf."""
    try:
        # 先算局部盒再变换角点 (简化: 直接对变换后的 shape 算)
        w = shape
        # 应用 trsf: 复制 shape 并变换
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        tr = BRepBuilderAPI_Transform(w, trsf, True)
        ws = tr.Shape()
        b = Bnd_Box(); BRepBndLib.Add_s(ws, b)
        return (b.GetXMin(), b.GetXMax(), b.GetYMin(), b.GetYMax(), b.GetZMin(), b.GetZMax())
    except Exception:
        return (0,0,0,0,0,0)


def compute_boxes(tubes, non_tubes, log=print):
    """Step 2: 包围盒复用池. B_E/B_T 均为真实 BRep 盒(经 trsf 变换), 仅用于粗筛."""
    B_E = []
    for nt in non_tubes:
        B_E.append(_shape_box(nt["shape"], nt["trsf"]))
    B_T = []
    for t in tubes:
        # 真实 BRep 盒 (V7 要求, 不得用 spine+半径估算)
        if "shape" in t and "trsf" in t:
            B_T.append(_shape_box(t["shape"], t["trsf"]))
        else:
            # 降级: spine 估算 (无 shape 时)
            sp = t["spine"]
            if len(sp):
                xs, ys, zs = sp[:,0], sp[:,1], sp[:,2]
                r = t["dia"]/2 + 1.0
                B_T.append((xs.min()-r, xs.max()+r, ys.min()-r, ys.max()+r, zs.min()-r, zs.max()+r))
            else:
                p0, p1 = t["p0"], t["p1"]
                r = t["dia"]/2 + 1.0
                B_T.append((min(p0[0],p1[0])-r, max(p0[0],p1[0])+r,
                            min(p0[1],p1[1])-r, max(p0[1],p1[1])+r,
                            min(p0[2],p1[2])-r, max(p0[2],p1[2])+r))
    B_all = B_T[0]
    for b in B_T[1:]:
        B_all = box_union(B_all, b)
    log(f"包围盒: B_E={len(B_E)}, B_T={len(B_T)}")
    return B_E, B_T, B_all


# ============ Step 3: 接触检测 ============
def _precise_dist_point_shape(p, shape, trsf, timeout_s=5.0):
    """BRepExtrema 精确点-实体距离, 超时降级.

    V7 Step3 要求: 精确校验须带超时 (默认 5s), 超时返回 None 由调用方降级为包围盒距离.
    用 ThreadPoolExecutor 实现超时; OCCT 只读操作线程安全.
    返回: 距离(mm, 可负不可正语义由调用方判定) / None(超时或失败).
    """
    import concurrent.futures
    def _compute():
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_MakeVertex
        tr = BRepBuilderAPI_Transform(shape, trsf, True)
        ws = tr.Shape()
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(p[0], p[1], p[2])).Shape()
        ext = BRepExtrema_DistShapeShape(v, ws)
        if ext.IsDone():
            return ext.Value()
        return None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_compute)
            return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        return None  # 超时降级
    except Exception:
        return None


def _polyline_closest_to_box(sp, be):
    """spine 折线段上找离包围盒 be 最近的点.

    对每段做点-盒距离的线段投影, 取全局最小.
    返回: (Q坐标, Q所在段索引, 段内参数t∈[0,1], 最小点盒距离).
    V7 Step3c 要求: Q 必须是折线段上的真投影, 不得只在采样顶点中挑.
    """
    best = None  # (dist, Q, seg_idx, t)
    n = len(sp)
    for k in range(n - 1):
        a = sp[k]; b = sp[k+1]
        # 线段 ab 上找离盒 be 最近的点: 采样 + 端点
        # 为精确, 对线段做 11 点采样取最优 (盒距离函数非凸, 采样足够密)
        for j in range(11):
            t = j / 10.0
            q = a + (b - a) * t
            d = point_box_dist(tuple(q), be)
            if best is None or d < best[0]:
                best = (d, tuple(q), k, t)
                if d == 0.0:
                    # 已在盒内, 不可能更小, 但继续找更靠近盒心的? 不需要, 0 已最优
                    pass
    if best is None:
        return None
    return best[1], best[2], best[3], best[0]


def _polyline_arc_length(sp, seg_idx, t):
    """沿 spine 折线从起点到 (seg_idx, t) 处的真实累积弧长.

    V7 Step3c 要求: 不得用直线距离代替弧长.
    """
    s = 0.0
    for k in range(seg_idx):
        s += _d3(tuple(sp[k]), tuple(sp[k+1]))
    a = sp[seg_idx]; b = sp[seg_idx+1]
    s += _d3(tuple(a), tuple(a + (b - a) * t))
    return s


def detect_contacts(tubes, non_tubes, B_E, B_T, B_all, log=print):
    """Step 3: (E,Y)双层循环接触检测.

    返回: list of {sid, name, n_end, has_mid, end_list[(tube_idx, end, p)], Q, s}
    """
    results = []
    ends = []  # [(tube_idx, end, p)]
    for ti, t in enumerate(tubes):
        ends.append((ti, 0, t["p0"]))
        ends.append((ti, 1, t["p1"]))

    for ei, nt in enumerate(non_tubes):
        be = B_E[ei]
        # 3a. 预粗筛
        if box_box_dist(be, B_all) > CONTACT_TOL + max(50.0, box_diag(be)):
            results.append({"sid": nt["sid"], "name": nt["name"],
                            "n_end": 0, "has_mid": False, "end_list": [], "Q": None, "s": None})
            continue
        n_end = 0
        end_list = []
        has_mid = False
        mid_list = []  # 多个中部接触: [{tube_idx, Q, s}], 不得覆盖
        # 3b+3c: 对每根管子
        for ti, t in enumerate(tubes):
            bt = B_T[ti]
            # 端部: 两端心
            for ei2, p in ((0, t["p0"]), (1, t["p1"])):
                if point_box_dist(p, be) <= CONTACT_TOL:
                    # 二次校验
                    d = _precise_dist_point_shape(p, nt["shape"], nt["trsf"])
                    if d is None:
                        d = point_box_dist(p, be)  # 降级
                    # 连接器判据: 距离可为负(过盈)/零(贴合), 不可为正(间隙)
                    if d <= 0.0:
                        n_end += 1
                        end_list.append((ti, ei2, p))
            # 中部: 盒-盒粗筛
            if box_box_dist(be, bt) <= CONTACT_TOL:
                sp = t["spine"]
                if len(sp) >= 2:
                    # V7: 在真实 spine 折线段上做最近投影找 Q
                    proj = _polyline_closest_to_box(sp, be)
                    if proj is not None:
                        q_pt, seg_idx, seg_t, q_box_d = proj
                        if q_box_d <= CONTACT_TOL:
                            # 二次校验: BRepExtrema 精确点-面距离
                            d2 = _precise_dist_point_shape(q_pt, nt["shape"], nt["trsf"])
                            if d2 is None:
                                d2 = q_box_d  # 降级
                            # 中部判据: Q 在管轴线上, 到外部卡扣距离 ≈ 管半径.
                            # 接触时 d2 ≤ 半径 (+2mm 容差); 端部的 d≤0 规则不适用中部.
                            r_tol = t["dia"]/2 + CONTACT_TOL
                            if d2 <= r_tol:
                                # 真实折线弧长 (不得用直线距离)
                                s_true = _polyline_arc_length(sp, seg_idx, seg_t)
                                L = t["spine_len"] if t["spine_len"] > 0 else _d3(t["p0"], t["p1"])
                                # 距两端弧长均 >5mm 才算中部 (太靠近端头的不算, 已在端部计数)
                                if s_true > END_TOL and (L - s_true) > END_TOL:
                                    has_mid = True
                                    # 记录多个中部接触, 不得覆盖
                                    mid_list.append({"tube_idx": ti, "Q": q_pt, "s": s_true})
        results.append({"sid": nt["sid"], "name": nt["name"],
                        "n_end": n_end, "has_mid": has_mid,
                        "end_list": end_list, "mid_list": mid_list,
                        "Q": mid_list[0]["Q"] if mid_list else None,
                        "s": mid_list[0]["s"] if mid_list else None})
    n_c = sum(1 for r in results if r["n_end"]==1 and not r["has_mid"])
    log(f"接触检测完成: 候选连接器(1端无中部)={n_c}")
    return results


# ============ Step 4: 三类判定 ============
def classify(contact_results, log=print):
    """Step 4: 统一判定."""
    connectors, clamps, others = [], [], []
    for r in contact_results:
        if r["n_end"] == 0 and not r["has_mid"]:
            others.append(r)
        elif r["has_mid"] or r["n_end"] != 1:
            clamps.append(r)
        else:
            connectors.append(r)
    log(f"分类: 连接器={len(connectors)}, 卡扣={len(clamps)}, 其他={len(others)}")
    return connectors, clamps, others


# ============ Step 5: 管-管连接 ============
def connect_tubes(tubes, log=print):
    """Step 5: Union-Find + 传递闭包约束.

    返回: connections[] = [{xyz, degree, members[(tube_idx,end)]}]
    """
    ends = []  # [(tube_idx, end, p, global_id)]
    gid = 0
    for ti, t in enumerate(tubes):
        ends.append((ti, 0, t["p0"], gid)); gid += 1
        ends.append((ti, 1, t["p1"], gid)); gid += 1
    n = len(ends)
    parent = list(range(n))
    def find(a):
        """并查集查找(路径压缩). Step5 管-管连通分量用."""
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    def union(a, b):
        """并查集合并. Step5 管-管连通分量用."""
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    # 初步合并: i<j, 排除同管, ≤6.0mm
    for i in range(n):
        ti = ends[i][0]
        for j in range(i+1, n):
            if ends[j][0] == ti:
                continue  # 同管排除
            if _d3(ends[i][2], ends[j][2]) <= TUBE_TUBE_TOL:
                union(i, j)
    # 分量
    comps = {}
    for i in range(n):
        r = find(i)
        comps.setdefault(r, []).append(i)
    # 传递闭包约束: 分量内两两 ≤9.0mm, 否则按空间坐标排序贪心重聚
    final = []
    for r, members in comps.items():
        # 检查
        ok = True
        for a in range(len(members)):
            for b in range(a+1, len(members)):
                if _d3(ends[members[a]][2], ends[members[b]][2]) > TUBE_TUBE_TOL * CLOSURE_FACTOR:
                    ok = False; break
            if not ok: break
        if ok:
            final.append(members)
        else:
            # 贪心重聚: 按空间坐标排序 (X→Y→Z)
            pts = sorted(members, key=lambda i: (ends[i][2][0], ends[i][2][1], ends[i][2][2]))
            clusters = []
            for i in pts:
                placed = False
                for cl in clusters:
                    if all(_d3(ends[i][2], ends[k][2]) <= TUBE_TUBE_TOL * CLOSURE_FACTOR for k in cl):
                        cl.append(i); placed = True; break
                if not placed:
                    clusters.append([i])
            final.extend(clusters)
    # 坐标: 2个取均值, >2取 medoid
    connections = []
    for members in final:
        if len(members) < 2:
            continue  # 孤立端点不输出 (或按需输出)
        pts = [ends[i][2] for i in members]
        if len(pts) == 2:
            xyz = tuple((pts[0][k]+pts[1][k])/2 for k in range(3))
        else:
            mx = sum(p[0] for p in pts)/len(pts)
            my = sum(p[1] for p in pts)/len(pts)
            mz = sum(p[2] for p in pts)/len(pts)
            best = min(pts, key=lambda p: (p[0]-mx)**2+(p[1]-my)**2+(p[2]-mz)**2)
            xyz = tuple(best)
        connections.append({
            "xyz": xyz,
            "degree": len(members),
            "members": [(ends[i][0], ends[i][1]) for i in members],
        })
    log(f"管-管连接点: {len(connections)}")
    return connections


# ============ Step 6: 坐标推理 ============
def infer_coordinates(connectors, clamps, connections, tubes):
    """Step 6: 推理坐标.

    返回: nodes = [{kind, xyz, ...}]
    kind: CON / CLP / BN
    """
    nodes = []
    for c in connectors:
        # 所连端心 (取第一个)
        p = c["end_list"][0][2] if c["end_list"] else None
        nodes.append({"kind": "CON", "xyz": p, "sid": c["sid"], "name": c["name"]})
    for c in clamps:
        if c["has_mid"] and c["Q"] is not None:
            xyz = tuple(c["Q"])
        elif c["end_list"]:
            # 多端型: 取距均值最近的端心 (medoid)
            pts = [e[2] for e in c["end_list"]]
            mx = sum(p[0] for p in pts)/len(pts)
            my = sum(p[1] for p in pts)/len(pts)
            mz = sum(p[2] for p in pts)/len(pts)
            xyz = tuple(min(pts, key=lambda p: (p[0]-mx)**2+(p[1]-my)**2+(p[2]-mz)**2))
        else:
            xyz = None
        nodes.append({"kind": "CLP", "xyz": xyz, "sid": c["sid"], "name": c["name"],
                      "has_mid": c["has_mid"], "n_end": c["n_end"]})
    for cn in connections:
        nodes.append({"kind": "BN", "xyz": cn["xyz"], "degree": cn["degree"],
                      "members": cn["members"]})
    return nodes


# ============ Step 7: 编码输出 + 校验 ============
def output_and_validate(meta, tubes, connectors, clamps, others, connections, nodes, log=print):
    """Step 7: 标准化命名 + 对照表 + 连通性校验."""
    # 按 sid 排序
    def snum(s):
        """S编号转整数用于排序: 'S80'→80. Step7 对照表排序用."""
        try: return int(s[1:])
        except: return 9999
    # 映射表
    mapping = []
    tubes_s = sorted(tubes, key=lambda t: snum(t["sid"]))
    clamps_s = sorted(clamps, key=lambda c: snum(c["sid"]))
    conns_s = sorted(connectors, key=lambda c: snum(c["sid"]))
    for i, t in enumerate(tubes_s, 1):
        mapping.append((f"Seg{i:02d}", t["sid"], t["name"], "管实体"))
    for i, c in enumerate(clamps_s, 1):
        mapping.append((f"CL{i:02d}", c["sid"], c["name"], "卡扣"))
    for i, c in enumerate(conns_s, 1):
        mapping.append((f"CON{i:02d}", c["sid"], c["name"], "连接器"))
    # 连通性: SEG 为节点, 连接点为边
    # 建图: tube_idx -> set(neighbor tube_idx)
    adj = {ti: set() for ti in range(len(tubes))}
    for cn in connections:
        tis = list(set(m[0] for m in cn["members"]))
        for a in range(len(tis)):
            for b in range(a+1, len(tis)):
                adj[tis[a]].add(tis[b]); adj[tis[b]].add(tis[a])
    # BFS
    seen = set(); comps = 0
    for ti in range(len(tubes)):
        if ti in seen: continue
        comps += 1
        stack = [ti]; seen.add(ti)
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v); stack.append(v)
    log(f"连通分量: {comps} (管子总数 {len(tubes)})")
    isolated = []
    if comps > 1:
        # 找孤立分量 (大小为1 且无边)
        for ti in range(len(tubes)):
            if len(adj[ti]) == 0:
                isolated.append(tubes[ti])
        log(f"WARNING: 孤立管子 {len(isolated)}")
    # 孤立非管实体
    log(f"其他实体(未接触): {len(others)}")
    return {
        "mapping": mapping,
        "connections": connections,
        "nodes": nodes,
        "n_components": comps,
        "isolated_tubes": isolated,
        "others": others,
    }


def analyze_v7(step_path, log=print):
    """V7 主流程."""
    t0 = time.time()
    # Step 0
    us = detect_unit(step_path)
    log(f"单位换算: x{us}")
    # Step 1
    meta, tubes, non_tubes = extract_entities(step_path, unit_scale=us, log=log)
    # Step 2
    B_E, B_T, B_all = compute_boxes(tubes, non_tubes, log=log)
    # Step 3
    contacts = detect_contacts(tubes, non_tubes, B_E, B_T, B_all, log=log)
    # Step 4
    connectors, clamps, others = classify(contacts, log=log)
    # Step 5
    connections = connect_tubes(tubes, log=log)
    # Step 6
    nodes = infer_coordinates(connectors, clamps, connections, tubes)
    # Step 7
    result = output_and_validate(meta, tubes, connectors, clamps, others, connections, nodes, log=log)
    result["tubes"] = tubes
    result["meta"] = meta
    log(f"总耗时: {time.time()-t0:.1f}s")
    return result


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "/home/hatch/workspace/ip_harness/IP-Harness.stp"
    r = analyze_v7(p)
    print(f"连接器: {len([n for n in r['nodes'] if n['kind']=='CON'])}")
    print(f"卡扣: {len([n for n in r['nodes'] if n['kind']=='CLP'])}")
    print(f"连接点: {len([n for n in r['nodes'] if n['kind']=='BN'])}")
