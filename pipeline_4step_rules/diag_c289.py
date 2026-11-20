# -*- coding: utf-8 -*-
"""诊断 C289（S794）端面圆拟合失败的原因：端面边界到底是什么形状。
只加载地板 STEP、只传 C289 一个实体。"""
import sys
sys.path.insert(0, "/home/hatch/workspace/harness_3d/pipeline_4step_rules")
import numpy as np
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Plane
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from v7geom import is_tube_solid, face_areas

STEP = "/home/hatch/workspace/harness_3d/work_floor/floor_AllCATPart_20260128_V04.stp"
# 注意：不设 Interface_Static 参数，与 stage1 默认行为完全一致
# （read.step.product.name=1 会改变实体名的读取来源，导致找不到 C289）。
r = STEPControl_Reader()
assert r.ReadFile(STEP) == IFSelect_RetDone
model = r.Model()
print("实体总数:", model.NbEntities())

# 找 C289 的 rank（与 stage1 完全相同的枚举方式：model.Entity + _ascii_str）
from stage1_extract import _ascii_str, BREP_TYPES
matches = []
n_brep = 0
for i in range(1, model.NbEntities() + 1):
    ent = model.Entity(i)
    tn = ent.DynamicType().Name()
    if tn in BREP_TYPES:
        n_brep += 1
        try:
            nm = _ascii_str(ent.Name())
        except Exception:
            nm = "?"
        if nm.startswith("C289"):
            matches.append((i, tn, nm))
print(f"BREP 总数: {n_brep}")
print("C289 匹配:", matches)
assert len(matches) >= 1, "未找到 C289"
# 取恰好名为 C289 的那一个（其余是 C289_、C289__ 等填充变体）
exact = [m for m in matches if m[2] == "C289"]
assert len(exact) == 1, f"恰好 C289 的应有 1 个，实际 {len(exact)} 个"
target = exact[0]
rank = target[0]
r.TransferOne(rank)
shape = r.OneShape()
print("形状为空？", shape.IsNull())

tube = is_tube_solid(shape)
print("is_tube_solid:", "管" if tube else "非管")
if tube:
    print("  dia=%.2f length=%.1f" % (tube["dia"], tube["length"]))
    print("  cap_faces 数量:", len(tube["cap_faces"]))
    for ci, f in enumerate(tube["cap_faces"]):
        p = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, p)
        print(f"  --- 端面 {ci}：面积 {p.Mass():.2f} mm²")
        ex = TopExp_Explorer(f, TopAbs_EDGE)
        n = 0
        while ex.More():
            e = TopoDS.Edge(ex.Current())
            ad = BRepAdaptor_Curve(e)
            ct = ad.GetType()
            try:
                disc = GCPnts_QuasiUniformDeflection(ad, 0.05)
                npts = disc.NbPoints()
            except Exception as ex2:
                npts = f"离散失败 {ex2}"
            print(f"    边 {n}：类型={ct} 长度={ad.LastParameter()-ad.FirstParameter():.2f} "
                  f"离散点数={npts}")
            n += 1
            ex.Next()
        print(f"    边总数: {n}")
