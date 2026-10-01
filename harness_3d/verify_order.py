"""验证OCP读取的shape顺序和STEP文件中的entity顺序是否一致"""
import re
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.collections import Sequence_TDF_Label
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

# 1) 从STEP文本解析body名称（按entity ID排序）
bodies = []
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',", line)
        if m:
            eid = int(m.group(1))
            name = m.group(2)
            bodies.append((eid, name))

bodies.sort(key=lambda x: x[0])  # 按entity ID排序
print(f"STEP body数: {len(bodies)}")
print(f"前10个body (按entity ID):")
for eid, name in bodies[:10]:
    print(f"  #{eid}: {name}")

# 2) OCP读取shape，计算几何特征
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label(); st.GetShapes(tops)

# 收集所有solid
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
                xmin = box.CornerMin().X()
                ymin = box.CornerMin().Y()
                zmin = box.CornerMin().Z()
                xmax = box.CornerMax().X()
                ymax = box.CornerMax().Y()
                zmax = box.CornerMax().Z()
                cx, cy, cz = (xmin+xmax)/2, (ymin+ymax)/2, (zmin+zmax)/2
                ocp_solids.append({
                    "vol": vol, "center": (cx, cy, cz)
                })
            ex.Next()
    from OCP.TDF import TDF_ChildIterator
    child_it = TDF_ChildIterator(lab)
    while child_it.More():
        collect_solids(child_it.Value(), depth+1)
        child_it.Next()

for i in range(1, tops.Length()+1):
    collect_solids(tops.Value(i), 0)

# 去重（按体积和中心点）
unique_solids = []
seen = set()
for s in ocp_solids:
    key = (round(s["vol"], 1), round(s["center"][0], 1), round(s["center"][1], 1), round(s["center"][2], 1))
    if key not in seen:
        seen.add(key)
        unique_solids.append(s)

print(f"\nOCP solid数（去重后）: {len(unique_solids)}")
print(f"前10个solid (按读取顺序):")
for i, s in enumerate(unique_solids[:10]):
    print(f"  {i}: vol={s['vol']:.1f} center={s['center']}")

# 3) 对比数量
print(f"\n=== 对比 ===")
print(f"STEP body: {len(bodies)}")
print(f"OCP solid: {len(unique_solids)}")

if len(bodies) == len(unique_solids):
    print("数量一致！可以尝试按顺序匹配")
else:
    print(f"数量不一致，差异: {abs(len(bodies) - len(unique_solids))}")
