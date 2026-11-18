#!/usr/bin/env python3
"""IP-Harness V7 线束拓扑提取（按 ENGINEERING_SPEC_FOR_CODEX.md 从零重写）.

与 harness_v7.py 的区别：本文件严格按工程说明书实现，不继承旧代码的历史包袱。
Step 0-7 见 ENGINEERING_SPEC_FOR_CODEX.md。
"""

import math
import re
import numpy as np

# ============ 全局阈值（见说明书 §2） ============
TUBE_TUBE_DIST = 6.0       # 管—管端点连接
CONTACT_COARSE = 2.0       # 实体接触粗筛（包围盒）
CONNECTOR_END_TOL = 5.0    # 连接器端部精确确认（BRepExtrema）
CLAMP_MID_TOL_EXTRA = 2.0  # 卡扣中部：半径 + 2.0
END_EXCLUDE_ARC = 5.0      # 中部判定：Q 距两端弧长 >5mm
COMPONENT_SPLIT = 7.2      # 管—管连通分量拆分
PRESREEN_SKIP_EXTRA = 50.0 # 预粗筛
BREP_TIMEOUT = 5.0         # BRepExtrema 超时（秒）

# OCP 导入（延迟到函数内，避免无 OCP 环境 import 失败）
# 见各函数内 import


# ============ 几何工具 ============

def _d3(a, b):
    """三维欧氏距离."""
    dx, dy, dz = a[0]-b[0], a[1]-b[1], a[2]-b[2]
    return math.sqrt(dx*dx + dy*dy + dz*dz)


def point_box_dist(p, box):
    """点到 AABB 盒距离。点在盒内返回 0。
    box = (xmin,xmax,ymin,ymax,zmin,zmax).
    """
    dx = max(box[0]-p[0], 0.0, p[0]-box[1])
    dy = max(box[2]-p[1], 0.0, p[1]-box[3])
    dz = max(box[4]-p[2], 0.0, p[2]-box[5])
    return math.sqrt(dx*dx + dy*dy + dz*dz)


def box_box_dist(b1, b2):
    """盒—盒距离。相交返回 0."""
    dx = max(b1[0]-b2[1], b2[0]-b1[1], 0.0)
    dy = max(b1[2]-b2[3], b2[2]-b1[3], 0.0)
    dz = max(b1[4]-b2[5], b2[4]-b1[5], 0.0)
    return math.sqrt(dx*dx + dy*dy + dz*dz)


def box_diag(box):
    """包围盒对角线长度."""
    return math.sqrt((box[1]-box[0])**2 + (box[3]-box[2])**2 + (box[5]-box[4])**2)


def box_union(b1, b2):
    """两盒并集."""
    return (min(b1[0],b2[0]), max(b1[1],b2[1]),
            min(b1[2],b2[2]), max(b1[3],b2[3]),
            min(b1[4],b2[4]), max(b1[5],b2[5]))


# ============ Step 0：单位检测 ============

def detect_unit(step_path):
    """Step 0：检测 STEP 长度单位，返回换算到 mm 的系数.
    优先级：CONVERSION_BASED_UNIT → SI_UNIT → LENGTH_MEASURE_WITH_UNIT。
    未找到返回 1.0（调用方输出 WARNING）。
    """
    try:
        with open(step_path, 'r', errors='ignore') as f:
            txt = f.read()
        m = re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'([^']+)'", txt, re.I)
        if m:
            u = m.group(1).upper()
            if 'INCH' in u:
                return 25.4
            if u in ('MM', 'MILLIMETER', 'MILLIMETRE'):
                return 1.0
            if u in ('M', 'METER', 'METRE'):
                return 1000.0
            if 'CENTI' in u or u.strip() == 'CM':
                return 10.0
        if re.search(r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.", txt, re.I):
            return 1.0
        if re.search(r"SI_UNIT\s*\(\s*\.\s*,\s*\.METRE\.", txt, re.I):
            return 1000.0
        m2 = re.search(r"LENGTH_MEASURE_WITH_UNIT\s*\([^)]*\)", txt, re.I)
        if m2:
            seg = m2.group(0).upper()
            if 'MILLI' in seg:
                return 1.0
            if 'INCH' in seg:
                return 25.4
        return 1.0
    except Exception:
        return 1.0


# ============ Step 1：实体遍历 ============
# 说明书 §4。依赖 harness_topology 的 is_tube_solid / face_centerline 等几何函数。

def _get_ocp():
    """延迟导入 OCP，避免顶层 import 失败."""
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDF import TDF_Label
    from OCP.collections import Sequence_TDF_Label
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    return locals()


def _trsf_equal(t1, t2, tol=1e-6):
    """比较两变换矩阵是否相同（容差）."""
    try:
        for i in range(1, 4):
            for j in range(1, 5):
                if abs(t1.Value(i, j) - t2.Value(i, j)) > tol:
                    return False
        return True
    except Exception:
        return False


def _shape_box(shape, trsf):
    """真实 BRep 包围盒（经 trsf 变换）。返回 (xmin,xmax,ymin,ymax,zmin,zmax)."""
    O = _get_ocp()
    try:
        tr = O['BRepBuilderAPI_Transform'](shape, trsf, True)
        ws = tr.Shape()
    except Exception:
        ws = shape
    box = O['Bnd_Box']()
    try:
        O['BRepBndLib'].Add_s(ws, box, True)
    except Exception:
        return (0, 0, 0, 0, 0, 0)
    try:
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    except Exception:
        return (0, 0, 0, 0, 0, 0)
    return (xmin, xmax, ymin, ymax, zmin, zmax)


def _precise_dist(p, shape, trsf, timeout_s=BREP_TIMEOUT):
    """BRepExtrema 点—实体精确距离。超时/失败返回 None."""
    import concurrent.futures
    O = _get_ocp()

    def _compute():
        tr = O['BRepBuilderAPI_Transform'](shape, trsf, True)
        ws = tr.Shape()
        v = O['BRepBuilderAPI_MakeVertex'](O['gp_Pnt'](p[0], p[1], p[2])).Shape()
        ext = O['BRepExtrema_DistShapeShape'](v, ws)
        if ext.IsDone():
            return ext.Value()
        return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_compute).result(timeout=timeout_s)
    except Exception:
        return None


def extract_entities(step_path, unit_scale=1.0, log=print):
    """Step 1：遍历装配、拆分 solid、去重、管判定、端面圆心、中心线.
    返回 (meta, tubes, non_tubes).
    tube: {sid,name,p0,p1,dia,length,spine,spine_len,shape,trsf}
    non_tube: {sid,name,shape,trsf}
    """
    O = _get_ocp()
    from harness_topology import (
        is_tube_solid, face_centerline, chain_curves,
        spines_overlap, label_name, comp_location, is_real_name,
    )

    doc = O['TDocStd_Document'](O['TCollection_ExtendedString']("XmlOcaf"))
    reader = O['STEPCAFControl_Reader']()
    reader.ReadFile(step_path)
    reader.Transfer(doc)
    S = O['XCAFDoc_DocumentTool'].ShapeTool_s(doc.Main())

    tops = O['Sequence_TDF_Label']()
    S.GetShapes(tops)

    leaves = []

    def walk(lab, path, ptr, ctx):
        """递归遍历装配树，收集叶节点."""
        ref = O['TDF_Label']()
        if S.IsComponent_s(lab):
            if not S.GetReferredShape_s(lab, ref):
                ref = lab
        else:
            ref = lab
        rn = label_name(ref)
        if is_real_name(rn):
            ctx = rn
        if S.IsAssembly_s(ref):
            cs = O['Sequence_TDF_Label']()
            S.GetComponents_s(ref, cs)
            for i in range(1, cs.Length() + 1):
                c = cs.Value(i)
                loc = comp_location(c)
                t = loc.Transformation() if not loc.IsIdentity() else O['gp_Trsf']()
                g = O['gp_Trsf']()
                g.Multiply(ptr)
                g.Multiply(t)
                walk(c, path + [label_name(c)], g, ctx)
        else:
            occ = "/".join([p for p in path if is_real_name(p)])
            leaves.append({"proto": ctx, "occ": occ,
                           "shape": S.GetShape_s(ref), "trsf": ptr})

    # 说明书 §4：遍历全部顶层 shape，不只取最大装配
    for i in range(1, tops.Length() + 1):
        walk(tops.Value(i), [], O['gp_Trsf'](), label_name(tops.Value(i)))

    # 拆分 + 去重（说明书 §4.1）
    all_sols = []
    for lf in leaves:
        sols = []
        ex = O['TopExp_Explorer'](lf["shape"], O['TopAbs_SOLID'])
        while ex.More():
            sols.append(ex.Current())
            ex.Next()
        if not sols:
            sols = [lf["shape"]]
        for sol in sols:
            all_sols.append((sol, lf["trsf"], lf["proto"], lf.get("occ", "")))
    log(f"拆分: {len(leaves)} 叶节点 -> {len(all_sols)} solid")

    seen = []
    uniq = []
    for (sol, trsf, proto, occ) in all_sols:
        dup = False
        for (s, t) in seen:
            try:
                if sol.IsSame(s) and _trsf_equal(trsf, t):
                    dup = True
                    break
            except Exception:
                pass
        if not dup:
            seen.append((sol, trsf))
            uniq.append((sol, trsf, proto, occ))
    log(f"去重: {len(all_sols)} -> {len(uniq)} 独立实体")

    meta, tubes, non_tubes = [], [], []
    for idx, (sol, trsf, proto, occ) in enumerate(uniq):
        sid = f"V7_{idx}"
        name = occ or proto or sid
        meta.append({"sid": sid, "name": name})

        tr = is_tube_solid(sol)
        if tr is None:
            non_tubes.append({"sid": sid, "name": name, "shape": sol, "trsf": trsf})
            continue

        # 端面圆心（说明书 §4.3）：用 harness_topology 的 _end_center 逻辑，
        # 此处内联简化版——周长最大 wire、20 点采样、残差兜底由 is_tube_solid 附带函数处理。
        # 为严格按说明书，此处调用独立实现的 _end_center_v7。
        p0, ok0 = _end_center_v7(tr["cap_faces"][0], trsf)
        p1, ok1 = _end_center_v7(tr["cap_faces"][1], trsf)
        if p0 is None or p1 is None:
            non_tubes.append({"sid": sid, "name": name, "shape": sol, "trsf": trsf})
            continue

        dia = tr["dia"]
        L = tr["length"]
        n_station = max(8, min(48, int(L / 5) if L > 0 else 8))
        spines = []
        for lf_face in tr["lat_faces"]:
            try:
                sp = face_centerline(lf_face, trsf, dia, n_station=n_station)
                if sp is not None and len(sp) > 1:
                    ln = float(np.sum(np.linalg.norm(np.diff(sp, axis=0), axis=1)))
                    spines.append({"pts": sp, "len": ln})
            except Exception:
                pass
        spines.sort(key=lambda s: -s["len"])
        kept = []
        for s in spines:
            if not any(spines_overlap(s["pts"], k["pts"], tol=2.0, frac=0.5) for k in kept):
                kept.append(s)
        if not kept and spines:
            kept = [spines[0]]
        if kept:
            spine, slen = chain_curves([{"pts": s["pts"], "len": s["len"]} for s in kept], tol=2.0)
        else:
            spine, slen = np.zeros((0, 3)), 0.0

        p0s = tuple(np.array(p0) * unit_scale)
        p1s = tuple(np.array(p1) * unit_scale)
        tubes.append({
            "sid": sid, "name": name, "p0": p0s, "p1": p1s,
            "dia": dia * unit_scale, "length": L * unit_scale,
            "spine": spine * unit_scale if len(spine) else spine,
            "spine_len": slen * unit_scale,
            "shape": sol, "trsf": trsf,
        })

    log(f"管子: {len(tubes)}, 非管: {len(non_tubes)}")
    return meta, tubes, non_tubes


def _end_center_v7(face, trsf):
    """说明书 §4.3：端面圆心。周长最大 wire，每 edge 20 点采样拟合，
    残差>0.5 用面质心兜底。返回 (p, ok)。"""
    O = _get_ocp()
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_WIRE, TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    try:
        tr = BRepBuilderAPI_Transform(face, trsf, True)
        wf = tr.Shape()
    except Exception:
        wf = face

    def _sample_edge(e, n=20):
        """edge 按参数均匀采样 n 点（face 已预变换，直接是世界坐标）.
        注意 OCP 绑定约束：BRepAdaptor_Curve 只接受 TopoDS_Edge，
        explorer 给的是 TopoDS_Shape，必须先 TopoDS.Edge() 向下转型；
        GCPnts_AbscissaPoint 在此构建里没有 (curve, npts) 重载，改用参数采样折线。
        失败返回 []。"""
        try:
            ad = BRepAdaptor_Curve(TopoDS.Edge(e))
            u0, u1 = ad.FirstParameter(), ad.LastParameter()
            if not (math.isfinite(u0) and math.isfinite(u1)) or u1 <= u0:
                return []
            out = []
            for k in range(n):
                p = ad.Value(u0 + (u1 - u0) * k / (n - 1))
                out.append([p.X(), p.Y(), p.Z()])
            return out
        except Exception:
            return []

    # 找周长最大的 wire（20 点/edge 折线近似周长）
    best_wire, best_len = None, -1.0
    exw = TopExp_Explorer(wf, TopAbs_WIRE)
    while exw.More():
        w = exw.Current()
        total = 0.0
        exe = TopExp_Explorer(w, TopAbs_EDGE)
        while exe.More():
            pe = _sample_edge(exe.Current())
            for a, b in zip(pe, pe[1:]):
                total += math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)
            exe.Next()
        if total > best_len:
            best_len, best_wire = total, w
        exw.Next()
    if best_wire is None:
        return None, False

    # 20 点/edge 采样
    pts = []
    exe = TopExp_Explorer(best_wire, TopAbs_EDGE)
    while exe.More():
        pts.extend(_sample_edge(exe.Current()))
        exe.Next()
    if len(pts) < 3:
        return None, False
    pts = np.array(pts)

    # 最小二乘拟合圆心（平面）
    c = pts.mean(axis=0)
    u, s_vals, vt = np.linalg.svd(pts - c, full_matrices=False)
    nrm = vt[-1]
    # 投影到平面后拟合圆
    basis_u = vt[0]
    basis_v = vt[1]
    q2 = np.stack([(pts - c) @ basis_u, (pts - c) @ basis_v], axis=1)
    # 代数拟合圆：x^2+y^2+Dx+Ey+F=0
    A = np.column_stack([q2[:, 0], q2[:, 1], np.ones(len(q2))])
    b = -(q2[:, 0] ** 2 + q2[:, 1] ** 2)
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except Exception:
        return None, False
    D, E, F = sol
    cc2 = np.array([-D / 2, -E / 2])
    r = math.sqrt(max(cc2 @ cc2 - F, 0))
    resid = np.abs(np.linalg.norm(q2 - cc2, axis=1) - r).mean()
    center = c + basis_u * cc2[0] + basis_v * cc2[1]
    if resid > 0.5 or r <= 0:
        # 兜底：面质心
        try:
            pr = GProp_GProps()
            BRepGProp.SurfaceProperties_s(wf, pr)
            g = pr.CentreOfMass()
            return (g.X(), g.Y(), g.Z()), False
        except Exception:
            return tuple(center), False
    return tuple(center), True


# ============ Step 2：包围盒 ============

def compute_boxes(tubes, non_tubes, log=print):
    """Step 2：真实 BRep 包围盒复用池。返回 (B_E, B_T, B_all)."""
    B_E = [_shape_box(nt["shape"], nt["trsf"]) for nt in non_tubes]
    B_T = [_shape_box(t["shape"], t["trsf"]) for t in tubes]
    B_all = B_T[0]
    for b in B_T[1:]:
        B_all = box_union(B_all, b)
    log(f"包围盒: B_E={len(B_E)}, B_T={len(B_T)}")
    return B_E, B_T, B_all


# ============ Step 3：接触检测 ============

def _polyline_proj(sp, be):
    """spine 折线段上离包围盒 be 最近的投影点。
    返回 (Q, seg_idx, t, d_box)。"""
    best = None
    n = len(sp)
    for k in range(n - 1):
        a = np.array(sp[k])
        b = np.array(sp[k + 1])
        for j in range(11):
            t = j / 10.0
            q = a + (b - a) * t
            d = point_box_dist(tuple(q), be)
            if best is None or d < best[0]:
                best = (d, tuple(q), k, t)
    if best is None:
        return None
    return best[1], best[2], best[3], best[0]


def _polyline_arc(sp, seg_idx, t):
    """沿折线从起点到 (seg_idx,t) 的真实累积弧长."""
    s = 0.0
    for k in range(seg_idx):
        s += _d3(tuple(sp[k]), tuple(sp[k + 1]))
    a = np.array(sp[seg_idx])
    b = np.array(sp[seg_idx + 1])
    s += _d3(tuple(a), tuple(a + (b - a) * t))
    return s


def detect_contacts(tubes, non_tubes, B_E, B_T, B_all, log=print):
    """Step 3：(E,Y) 双层循环接触检测.
    返回 list[{sid,name,n_end,has_mid,end_list,mid_list,Q,s}].
    端部：d ≤ 5.0mm（说明书 §6.2）；中部：d ≤ 半径+2mm（§6.3）。
    """
    results = []
    for ei, nt in enumerate(non_tubes):
        be = B_E[ei]
        if box_box_dist(be, B_all) > CONTACT_COARSE + max(PRESREEN_SKIP_EXTRA, box_diag(be)):
            results.append({"sid": nt["sid"], "name": nt["name"], "n_end": 0,
                            "has_mid": False, "end_list": [], "mid_list": [],
                            "Q": None, "s": None})
            continue
        n_end, end_list = 0, []
        has_mid, mid_list = False, []
        for ti, t in enumerate(tubes):
            bt = B_T[ti]
            # 端部
            for eidx, p in ((0, t["p0"]), (1, t["p1"])):
                if point_box_dist(p, be) <= CONTACT_COARSE:
                    d = _precise_dist(p, nt["shape"], nt["trsf"])
                    if d is None:
                        d = point_box_dist(p, be)
                    if d <= CONNECTOR_END_TOL:
                        n_end += 1
                        end_list.append((ti, eidx, p))
            # 中部
            if box_box_dist(be, bt) <= CONTACT_COARSE:
                sp = t["spine"]
                if len(sp) >= 2:
                    proj = _polyline_proj(sp, be)
                    if proj and proj[3] <= CONTACT_COARSE:
                        q_pt, seg_idx, seg_t, _ = proj
                        d2 = _precise_dist(q_pt, nt["shape"], nt["trsf"])
                        if d2 is None:
                            d2 = proj[3]
                        if d2 <= t["dia"] / 2 + CLAMP_MID_TOL_EXTRA:
                            s_true = _polyline_arc(sp, seg_idx, seg_t)
                            L = t["spine_len"] if t["spine_len"] > 0 else _d3(t["p0"], t["p1"])
                            if s_true > END_EXCLUDE_ARC and (L - s_true) > END_EXCLUDE_ARC:
                                has_mid = True
                                mid_list.append({"tube_idx": ti, "Q": q_pt, "s": s_true})
        results.append({"sid": nt["sid"], "name": nt["name"], "n_end": n_end,
                        "has_mid": has_mid, "end_list": end_list, "mid_list": mid_list,
                        "Q": mid_list[0]["Q"] if mid_list else None,
                        "s": mid_list[0]["s"] if mid_list else None})
    log(f"接触检测完成: {len(results)} 实体")
    return results


# ============ Step 4：分类 ============

def classify(contact_results, log=print):
    """Step 4：三类判定。只用接触结果。
    n_end==1 且无中部 → 连接器；有中部 或 n_end!=1 → 卡扣；否则其他。
    """
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


# ============ Step 5：管—管连接 ============

def connect_tubes(tubes, log=print):
    """Step 5：端心两两 ≤6mm 连接；连通分量内 >7.2mm 确定性拆分。
    返回 connections: [{ends:[(ti,ei,p)], xyz, degree}].
    """
    ends = []
    for ti, t in enumerate(tubes):
        ends.append((ti, 0, t["p0"]))
        ends.append((ti, 1, t["p1"]))
    n = len(ends)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            ti, ei, pi = ends[i]
            tj, ej, pj = ends[j]
            if ti == tj:
                continue
            if _d3(pi, pj) <= TUBE_TUBE_DIST:
                union(i, j)

    comps = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(i)

    connections = []
    for members in comps.values():
        if len(members) < 2:
            continue
        # >7.2mm 确定性拆分：按坐标排序后贪心分组
        pts = [(ends[m][2], m) for m in members]
        pts.sort(key=lambda x: (x[0][0], x[0][1], x[0][2]))
        groups, cur = [], [pts[0]]
        for p, m in pts[1:]:
            if all(_d3(p, q) <= COMPONENT_SPLIT for q, _ in cur):
                cur.append((p, m))
            else:
                groups.append(cur)
                cur = [(p, m)]
        groups.append(cur)
        for g in groups:
            if len(g) < 2:
                continue
            eidx = [m for _, m in g]
            coords = [ends[m][2] for m in eidx]
            if len(coords) == 2:
                xyz = tuple((coords[0][k] + coords[1][k]) / 2 for k in range(3))
            else:
                mean = [sum(c[k] for c in coords) / len(coords) for k in range(3)]
                xyz = min(coords, key=lambda c: _d3(c, mean))
            connections.append({
                "ends": [(ends[m][0], ends[m][1], ends[m][2]) for m in eidx],
                "xyz": xyz, "degree": len(eidx),
            })
    log(f"管—管连接点: {len(connections)}")
    return connections


# ============ Step 6：推理坐标 ============

def infer_coordinates(connectors, clamps, connections, tubes):
    """Step 6：推理坐标。连接器→端心；中部卡扣→Q；多端卡扣→medoid；
    管—管节点→均值/medoid。禁止用实体包围盒中心。
    返回 {sid: xyz}。
    """
    coords = {}
    for c in connectors:
        ti, ei, p = c["end_list"][0]
        coords[c["sid"]] = p
    for c in clamps:
        if c["mid_list"]:
            coords[c["sid"]] = c["mid_list"][0]["Q"]
        elif c["end_list"]:
            pts = [p for _, _, p in c["end_list"]]
            mean = [sum(q[k] for q in pts) / len(pts) for k in range(3)]
            coords[c["sid"]] = min(pts, key=lambda q: _d3(q, mean))
    for i, cn in enumerate(connections):
        coords[f"NODE_{i}"] = cn["xyz"]
    return coords


# ============ Step 7：命名输出 + 连通性 ============

def analyze(step_path, log=print):
    """全流程：Step 0→7。返回 dict 结果."""
    unit = detect_unit(step_path)
    if abs(unit - 1.0) > 1e-9:
        log(f"单位换算系数: {unit}")
    else:
        log("单位: mm（默认，WARNING：未在文件中定位到单位声明）")

    meta, tubes, non_tubes = extract_entities(step_path, unit_scale=unit, log=log)

    # Body.84 回归（说明书 §4.5）
    for t in tubes:
        if "Body.84" in t["name"]:
            d0 = min(_d3(t["p0"], [613.807, 628.868, 464.371]),
                     _d3(t["p0"], [638.170, 647.292, 453.866]))
            d1 = min(_d3(t["p1"], [613.807, 628.868, 464.371]),
                     _d3(t["p1"], [638.170, 647.292, 453.866]))
            log(f"Body.84 回归: 误差 {d0:.3f}/{d1:.3f} mm -> "
                f"{'通过' if d0 < 0.1 and d1 < 0.1 else '未通过'}")
            break

    B_E, B_T, B_all = compute_boxes(tubes, non_tubes, log=log)
    contacts = detect_contacts(tubes, non_tubes, B_E, B_T, B_all, log=log)
    connectors, clamps, others = classify(contacts, log=log)
    connections = connect_tubes(tubes, log=log)
    coords = infer_coordinates(connectors, clamps, connections, tubes)

    # 标准化命名
    names = {}
    for i, t in enumerate(tubes):
        names[t["sid"]] = f"Seg{i+1:02d}"
    for i, c in enumerate(clamps):
        names[c["sid"]] = f"CL{i+1:02d}"
    for i, c in enumerate(connectors):
        names[c["sid"]] = f"CON{i+1:02d}"

    # 连通性 BFS（说明书 §10.3）
    # 图：CON 节点经 end_list 关联到 SEG；SEG 经 connections 互联
    adj = {}
    def link(a, b):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    seg_of_tube = {t["sid"]: names[t["sid"]] for t in tubes}
    tube_idx_to_sid = {i: t["sid"] for i, t in enumerate(tubes)}
    for c in connectors:
        cn = names[c["sid"]]
        ti, _, _ = c["end_list"][0]
        link(cn, seg_of_tube[tube_idx_to_sid[ti]])
    # 管—管连接：同一连接点内的管两两相连
    for cn in connections:
        segs = [seg_of_tube[tube_idx_to_sid[ti]] for ti, _, _ in cn["ends"]]
        for a in range(len(segs)):
            for b in range(a + 1, len(segs)):
                link(segs[a], segs[b])

    con_names = [names[c["sid"]] for c in connectors]
    bfs_result = None
    if con_names:
        start = con_names[0]
        seen, stack = {start}, [start]
        while stack:
            cur = stack.pop()
            for nb in adj.get(cur, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        reached = [c for c in con_names if c in seen]
        missing = [c for c in con_names if c not in seen]
        # 反查实例名
        sid_of = {v: k for k, v in names.items()}
        meta_of = {m["sid"]: m["name"] for m in meta}
        bfs_result = {
            "start": start,
            "reached": len(reached), "total": len(con_names),
            "missing_names": [meta_of.get(sid_of.get(m, ""), m) for m in missing],
            "pass": len(missing) == 0,
        }
        log(f"连通性: 起点 {start}, 到达 {len(reached)}/{len(con_names)}, "
            f"{'PASS' if bfs_result['pass'] else 'FAIL'}")

    return {
        "tubes": tubes, "non_tubes": non_tubes,
        "connectors": connectors, "clamps": clamps, "others": others,
        "connections": connections, "coords": coords, "names": names,
        "meta": meta, "bfs": bfs_result,
    }


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/hatch/workspace/ip_harness/IP-Harness.stp"
    r = analyze(path)
    print(f"管{len(r['tubes'])} 连接器{len(r['connectors'])} "
          f"卡扣{len(r['clamps'])} 其他{len(r['others'])}")
