"""从STEP文件文本解析实体名称，通过几何特征匹配到OCP shape"""
import re
import sys
import numpy as np

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.collections import Sequence_TDF_Label
from OCP.TDF import TDF_Label
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

# 1) 从STEP文本解析body名称
print("解析STEP文本...", file=sys.stderr)
bodies = {}  # {entity_id: name}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',", line)
        if m:
            bodies[int(m.group(1))] = m.group(2)

print(f"STEP文本中找到 {len(bodies)} 个body", file=sys.stderr)

# 2) 用OCP读取，获取所有solid的几何特征
print("OCP读取STEP...", file=sys.stderr)
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label(); st.GetShapes(tops)

# 收集所有solid及其几何特征
ocp_solids = []
def collect_solids(lab, depth=0):
    if depth > 20:
        return
    shape = st.GetShape_s(lab)
    if shape is not None and not shape.IsNull():
        ex = TopExp_Explorer(shape, TopAbs_SOLID)
        while ex.More():
            sol = ex.Current()
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(sol, props)
            vol = props.Mass()
            box = Bnd_Box()
            BRepBndLib.Add_s(sol, box)
            if not box.IsVoid():
                xmin, ymin, zmin = box.CornerMin().X(), box.CornerMin().Y(), box.CornerMin().Z()
                xmax, ymax, zmax = box.CornerMax().X(), box.CornerMax().Y(), box.CornerMax().Z()
                cx,cy,cz = (xmin+xmax)/2, (ymin+ymax)/2, (zmin+zmax)/2
                dx,dy,dz = xmax-xmin, ymax-ymin, zmax-zmin
                ocp_solids.append({
                    "vol": vol, "center": (cx,cy,cz), "size": (dx,dy,dz),
                    "depth": depth
                })
            ex.Next()
    it = TDF_Label()
    # 手动遍历子label
    from OCP.TDF import TDF_ChildIterator
    child_it = TDF_ChildIterator(lab)
    while child_it.More():
        collect_solids(child_it.Value(), depth+1)
        child_it.Next()

for i in range(1, tops.Length()+1):
    collect_solids(tops.Value(i), 0)

print(f"OCP找到 {len(ocp_solids)} 个solid", file=sys.stderr)

# 3) 对比
print(f"\n=== 对比 ===", file=sys.stderr)
print(f"STEP body数: {len(bodies)}", file=sys.stderr)
print(f"OCP solid数: {len(ocp_solids)}", file=sys.stderr)

# 按体积排序看分布
step_vols = sorted(bodies.keys())
ocp_vols = sorted(ocp_solids, key=lambda x: -x["vol"])
print(f"\nOCP前10个solid(按体积):", file=sys.stderr)
for s in ocp_vols[:10]:
    print(f"  vol={s['vol']:.1f} center={s['center']} size={s['size']}", file=sys.stderr)
