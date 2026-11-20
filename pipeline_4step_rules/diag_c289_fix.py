# -*- coding: utf-8 -*-
"""用修复后的规则一检查 C289 与 3 个 RSD 实体，验证修复效果。"""
import sys
sys.path.insert(0, "/home/hatch/workspace/harness_3d/pipeline_4step_rules")
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from stage1_extract import _ascii_str, BREP_TYPES, _check_endfaces_circular
from v7geom import is_tube_solid

STEP = "/home/hatch/workspace/harness_3d/work_floor/floor_AllCATPart_20260128_V04.stp"
r = STEPControl_Reader()
assert r.ReadFile(STEP) == IFSelect_RetDone
model = r.Model()
targets = {"C289", "RSD2M0429.1______", "RSD2M0429.1_______",
           "RSD2M0429.1________"}
found = {}
for i in range(1, model.NbEntities() + 1):
    ent = model.Entity(i)
    if ent.DynamicType().Name() in BREP_TYPES:
        try:
            nm = _ascii_str(ent.Name())
        except Exception:
            continue
        if nm in targets:
            found[nm] = i
print("找到:", sorted(found))
for nm, rank in sorted(found.items()):
    nb_before = r.NbShapes()
    r.TransferOne(rank)
    # 注意：用 Shape(NbShapes) 取新传的形状，不用 OneShape()
    # （多实体转移后 OneShape 返回复合体，会张冠李戴——stage1 注释）。
    shape = r.Shape(r.NbShapes())
    assert r.NbShapes() == nb_before + 1
    tube = is_tube_solid(shape)
    if not tube:
        print(f"{nm}: 非管（is_tube_solid）")
        continue
    ok, reason = _check_endfaces_circular(tube)
    print(f"{nm}: dia={tube['dia']:.1f} len={tube['length']:.1f} "
          f"规则一={'通过' if ok else '不通过：' + reason}")
