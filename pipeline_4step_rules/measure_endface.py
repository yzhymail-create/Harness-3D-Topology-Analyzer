#!/usr/bin/env python3
"""实测端面圆度与两端面尺寸比（2026-11-14 用户定规验证）。

用户规则一：管子端面是近似圆面，且两个端面近似圆大小基本相等。
本脚本对每个恰好 2 平面端面的实体，拟合两端面边界圆，
输出：半径 r1/r2、尺寸比、圆度残差 res1/res2。
用 X1X 的 10 根真管 vs 6 个误判连接器看能否分开；
同时跑 IP-Harness 的 110 根管看真管的数值范围。

复用 stage1 的文本解析 + TransferOne 取形状（与管线同法）。
"""
import sys, os
import numpy as np

sys.path.insert(0, "/home/hatch/workspace/harness_3d/pipeline_4step_opt")
from v7geom import v7, face_areas, is_tube_solid
import stage1_extract as s1

from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_QuasiUniformDeflection

circle_center_3d = v7.circle_center_3d


def log(msg):
    print(msg, flush=True)


def face_boundary_points(face):
    """取平面端面的最长一条边环离散点。"""
    best = None
    ex = TopExp_Explorer(face, TopAbs_EDGE)
    while ex.More():
        e = TopoDS.Edge(ex.Current())
        try:
            ad = BRepAdaptor_Curve(e)
            disc = GCPnts_QuasiUniformDeflection(ad, 0.05)
            pts = []
            for i in range(1, disc.NbPoints() + 1):
                p = disc.Value(i)
                pts.append((p.X(), p.Y(), p.Z()))
            if len(pts) >= 8 and (best is None or len(pts) > len(best)):
                best = pts
        except Exception:
            pass
        ex.Next()
    return np.array(best) if best is not None else None


def fit_circle(pts):
    """拟合圆，返回 (半径, 相对残差 std/mean)。"""
    if pts is None or len(pts) < 8:
        return None, None
    c = circle_center_3d(pts)
    dist = np.linalg.norm(pts - c, axis=1)
    r = float(np.mean(dist))
    res = float(np.std(dist) / max(r, 1e-9))
    return r, res


def measure(step_path, label):
    print(f"===== {label}: {os.path.basename(step_path)} =====", flush=True)
    id2name, root_name = s1.parse_step_text(step_path, log)
    reader = STEPControl_Reader()
    if reader.ReadFile(step_path) != IFSelect_RetDone:
        raise RuntimeError(f"无法读取 STEP 文件: {step_path}")
    model = reader.Model()
    n_model = model.NbEntities()
    brep_ranks = []
    for i in range(1, n_model + 1):
        ent = model.Entity(i)
        tn = ent.DynamicType().Name()
        if tn in s1.BREP_TYPES:
            try:
                nm = s1._ascii_str(ent.Name())
            except Exception:
                nm = "?"
            brep_ranks.append((i, tn, nm))
    print(f"BREP 数: {len(brep_ranks)}", flush=True)
    rows = []
    for idx, (rank, typ, nm) in enumerate(brep_ranks):
        nb_before = reader.NbShapes()
        try:
            ok = reader.TransferOne(rank)
        except Exception:
            continue
        nb_after = reader.NbShapes()
        shape = None
        if ok and nb_after == nb_before + 1:
            try:
                shape = reader.Shape(nb_after)
            except Exception:
                shape = None
        if shape is None or shape.IsNull():
            continue
        tube = is_tube_solid(shape)
        fa = face_areas(shape)
        nplanar = sum(1 for pl, a, f in fa if pl)
        if nplanar != 2:
            continue
        planar_faces = [f for pl, a, f in fa if pl]
        r1, res1 = fit_circle(face_boundary_points(planar_faces[0]))
        r2, res2 = fit_circle(face_boundary_points(planar_faces[1]))
        if r1 is None or r2 is None:
            print(f"  {nm[:40]:40s} 判管={bool(tube)} 端面拟合失败", flush=True)
            continue
        ratio = min(r1, r2) / max(r1, r2)
        dia = tube["dia"] if tube else 0.0
        length = tube["length"] if tube else 0.0
        rows.append((nm, bool(tube), r1, r2, ratio, res1, res2, dia, length))
    print(f"\n  {'实体名':40s} {'判管':4s} {'r1':>7s} {'r2':>7s} {'尺寸比':>6s} {'残差1':>7s} {'残差2':>7s} {'直径':>7s} {'长度':>8s} {'长径比':>6s}")
    for nm, istube, r1, r2, ratio, res1, res2, dia, length in sorted(rows, key=lambda x: (not x[1], x[4])):
        ar = length / dia if dia > 0 else 0
        print(f"  {nm[:40]:40s} {'管' if istube else '非管':4s} {r1:7.2f} {r2:7.2f} {ratio:6.3f} {res1:7.4f} {res2:7.4f} {dia:7.2f} {length:8.1f} {ar:6.1f}")
    ntube = sum(1 for r in rows if r[1])
    print(f"\n  恰好 2 平面端面的实体: {len(rows)} 个，其中判管 {ntube} 个", flush=True)
    return rows


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("x1x", "both"):
        measure("/home/hatch/workspace/user/files/X1X-DRD_AllCATPart.stp", "X1X")
    if which in ("iph", "both"):
        measure("/home/hatch/workspace/harness_3d/work_unfold/IP-Harness.stp", "IP-Harness")
