#!/usr/bin/env python3
"""剖析第 2 步精确距离的耗时分布（只传少量实体，快速定位瓶颈）。
用法：python profile_dist.py <entities.json> <step文件> [n_pairs]
输出每对候选的：设备面数、两道筛后幸存面数、面精确调用次数、
按面类型分的耗时、总耗时、最小距离。
"""
import json
import sys
import time
from collections import defaultdict

sys.path.insert(0, ".")
from common import aabb_dist
from stage1_extract import _ascii_str

from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

SURF = {0: "Plane", 1: "Cylinder", 2: "Cone", 3: "Sphere", 4: "Torus",
        5: "Bezier", 6: "BSpline", 7: "Revolution", 8: "Extrusion",
        9: "Offset", 10: "Other"}
BREP_TYPES = {"StepShape_ManifoldSolidBrep", "StepShape_BrepWithVoids",
              "StepShape_FacetedBrep", "StepShape_FacetedBrepAndBrepWithVoids"}


def face_boxes(shape):
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face(ex.Current())
        box = Bnd_Box()
        BRepBndLib.Add_s(f, box)
        typ = int(BRepAdaptor_Surface(f).GetType())
        out.append((f, (box.GetXMin(), box.GetYMin(), box.GetZMin(),
                        box.GetXMax(), box.GetYMax(), box.GetZMax()), typ))
        ex.Next()
    return out


def main():
    entities = json.load(open(sys.argv[1]))
    step_path = sys.argv[2]
    n_pairs = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    branches = entities["branches"]
    devices = entities["devices"]

    # 按第 2 步第一遍顺序找 AABB 候选对（预筛 1：盒间隙 ≤5mm）
    cands = []
    for i, b in enumerate(branches):
        bb = tuple(b["bbox"])
        for ci, d in enumerate(devices):
            if aabb_dist(bb, tuple(d["bbox"])) <= 5.0:
                cands.append((i, ci))
    print(f"候选对（盒间隙≤5mm）：{len(cands)} / {len(branches)*len(devices)}")
    test = cands[:n_pairs]
    print(f"剖析前 {len(test)} 对")

    # 只传这些对涉及的实体
    need_tags = set()
    for i, ci in test:
        need_tags.add(branches[i]["tag"])
        need_tags.add(devices[ci]["tag"])
    tag2name = {}
    for b in branches:
        tag2name[b["tag"]] = b["name"]
    for d in devices:
        tag2name[d["tag"]] = d["name"]
    name2tag = {}
    for t, nm in tag2name.items():
        if t in need_tags:
            name2tag.setdefault(nm, []).append(t)

    reader = STEPControl_Reader()
    assert reader.ReadFile(step_path) == IFSelect_RetDone
    model = reader.Model()
    shapes = {}
    t0 = time.time()
    for r in range(1, model.NbEntities() + 1):
        ent = model.Entity(r)
        if ent.DynamicType().Name() not in BREP_TYPES:
            continue
        try:
            nm = _ascii_str(ent.Name())
        except Exception:
            continue
        if nm not in name2tag:
            continue
        nb0 = reader.NbShapes()
        if reader.TransferOne(r) and reader.NbShapes() == nb0 + 1:
            sh = reader.Shape(nb0 + 1)
            for t in name2tag[nm]:
                if t not in shapes:
                    shapes[t] = sh
                    break
        if len(shapes) >= len(need_tags):
            break
    print(f"传 {len(shapes)}/{len(need_tags)} 个实体，{time.time()-t0:.1f}s")

    fb = {}
    for t, sh in shapes.items():
        fb[t] = face_boxes(sh)

    print(f"\n{'对':4s} {'设备面':>6s} {'筛①后':>6s} {'面调用':>6s} "
          f"{'总耗时':>7s} {'最小距':>7s}  面类型耗时（类型:次数/秒）")
    tot_time = 0.0
    tot_calls = 0
    for k, (i, ci) in enumerate(test):
        b, d = branches[i], devices[ci]
        tf = fb.get(b["tag"], [])
        df = fb.get(d["tag"], [])
        tbox = tuple(b["bbox"])
        t1 = time.time()
        n_s1 = 0
        n_calls = 0
        best = None
        per_type = defaultdict(lambda: [0, 0.0])
        for fd, ab_d, td in df:
            if aabb_dist(ab_d, tbox) > 5.0:
                continue
            n_s1 += 1
            for ft, ab_t, tt in tf:
                if aabb_dist(ab_t, ab_d) > 5.0:
                    continue
                n_calls += 1
                key = f"{SURF.get(td, '?')}x{SURF.get(tt, '?')}"
                tc = time.time()
                try:
                    dd = BRepExtrema_DistShapeShape(fd, ft)
                    dd.Perform()
                    if dd.IsDone():
                        v = float(dd.Value())
                        if best is None or v < best:
                            best = v
                except Exception:
                    pass
                dt = time.time() - tc
                per_type[key][0] += 1
                per_type[key][1] += dt
        dt = time.time() - t1
        tot_time += dt
        tot_calls += n_calls
        top = sorted(per_type.items(), key=lambda kv: -kv[1][1])[:3]
        tops = " ".join(f"{kk}:{vv[0]}/{vv[1]:.2f}s" for kk, vv in top)
        print(f"{k:<4d} {len(df):>6d} {n_s1:>6d} {n_calls:>6d} "
              f"{dt:>7.2f} {str(round(best, 2)) if best is not None else '  >5':>7s}  {tops}")
    print(f"\n合计：{len(test)} 对，{tot_time:.1f}s，面调用 {tot_calls} 次，"
          f"平均每对 {tot_time/max(1, len(test)):.2f}s")


if __name__ == "__main__":
    main()
