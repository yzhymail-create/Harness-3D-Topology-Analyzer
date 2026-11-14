#!/usr/bin/env python3
"""验证 804 vs 803 之谜：指定名字的 BREP 传出后内含几个 solid？
若某 BREP 是多 solid 复合体，TopExp 会比 BREP 数多计。
用法：python check_compounds.py <step> <名字1> <名字2> ...
名字用 entities.json 里的真名（支持前缀匹配，如 INLINE-FLH）。
"""
import sys
import time

sys.path.insert(0, ".")
from stage1_extract import _ascii_str, BREP_TYPES

from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib


def main():
    step_path = sys.argv[1]
    wants = sys.argv[2:]
    reader = STEPControl_Reader()
    assert reader.ReadFile(step_path) == IFSelect_RetDone
    model = reader.Model()
    print(f"模型实体 {model.NbEntities()} 个")
    t0 = time.time()
    found = {}
    for r in range(1, model.NbEntities() + 1):
        ent = model.Entity(r)
        if ent.DynamicType().Name() not in BREP_TYPES:
            continue
        try:
            nm = _ascii_str(ent.Name())
        except Exception:
            continue
        for w in wants:
            if nm.startswith(w) and w not in found:
                nb0 = reader.NbShapes()
                if reader.TransferOne(r) and reader.NbShapes() == nb0 + 1:
                    found[w] = (nm, reader.Shape(nb0 + 1))
                break
        if len(found) == len(wants):
            break
    print(f"找到 {len(found)}/{len(wants)}，{time.time()-t0:.1f}s")
    for w, (nm, sh) in found.items():
        ex = TopExp_Explorer(sh, TopAbs_SOLID)
        subs = []
        while ex.More():
            s = ex.Current()
            box = Bnd_Box()
            BRepBndLib.Add_s(s, box)
            subs.append((round((box.GetXMin() + box.GetXMax()) / 2, 1),
                         round((box.GetYMin() + box.GetYMax()) / 2, 1),
                         round((box.GetZMin() + box.GetZMax()) / 2, 1),
                         round(box.GetXMax() - box.GetXMin(), 1),
                         round(box.GetYMax() - box.GetYMin(), 1),
                         round(box.GetZMax() - box.GetZMin(), 1)))
            ex.Next()
        print(f"\n{nm!r}：内含 {len(subs)} 个 solid")
        for i, (cx, cy, cz, dx, dy, dz) in enumerate(subs):
            print(f"  sub[{i}] center=[{cx}, {cy}, {cz}] "
                  f"size=[{dx} x {dy} x {dz}]")


if __name__ == "__main__":
    main()
