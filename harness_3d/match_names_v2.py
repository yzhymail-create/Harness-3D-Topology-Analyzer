"""从STEP文件文本解析实体名称，通过几何特征匹配到OCP shape"""
import re
import sys
import numpy as np

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.collections import Sequence_TDF_Label
from OCP.TDF import TDF_Label, TDF_ChildIterator
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

def decode_step_name(s):
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

# 1) 从STEP文本解析body名称
bodies = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',", line)
        if m:
            eid = int(m.group(1))
            name = decode_step_name(m.group(2))
            bodies[eid] = name

print(f"STEP body数: {len(bodies)}", file=sys.stderr)

# 2) OCP读取
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label(); st.GetShapes(tops)

# 3) 收集所有solid的几何特征
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
                cx,cy,cz = (xmin+xmax)/2, (ymin+ymax)/2, (zmin+zmax)/2
                ocp_solids.append({
                    "vol": vol, "center": (cx,cy,cz),
                    "shape": sol
                })
            ex.Next()
    child_it = TDF_ChildIterator(lab)
    while child_it.More():
        collect_solids(child_it.Value(), depth+1)
        child_it.Next()

for i in range(1, tops.Length()+1):
    collect_solids(tops.Value(i), 0)

print(f"OCP solid数: {len(ocp_solids)}", file=sys.stderr)

# 4) 找有中文名称的body（连接器）
chinese_bodies = {eid: name for eid, name in bodies.items() if any('\u4e00' <= c <= '\u9fff' for c in name)}
print(f"\n中文名称body数: {len(chinese_bodies)}", file=sys.stderr)

# 5) 尝试匹配：找体积最大的几个OCP solid，看是否对应连接器
# 连接器通常体积较大
ocp_by_vol = sorted(ocp_solids, key=lambda x: -x["vol"])
print(f"\nOCP体积最大的10个solid:", file=sys.stderr)
for s in ocp_by_vol[:10]:
    print(f"  vol={s['vol']:.1f} center={s['center']}", file=sys.stderr)

# 6) 中文名称的body通常对应连接器，体积应该较大
# 让我们看看中文名称body的体积分布（但STEP文本里没有体积信息）
# 只能靠OCP的体积来推断

print(f"\n=== 匹配结果 ===", file=sys.stderr)
print(f"STEP中文body: {len(chinese_bodies)}", file=sys.stderr)
print(f"OCP大体积solid(>10000): {sum(1 for s in ocp_solids if s['vol'] > 10000)}", file=sys.stderr)

# 暂时无法精确匹配，只能输出统计信息
print(f"\n无法精确匹配，需要更复杂的几何匹配算法", file=sys.stderr)
