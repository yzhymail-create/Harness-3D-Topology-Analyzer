from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.collections import Sequence_TDF_Label
from OCP.TDF import TDF_Label, TDF_ChildIterator, TDF_AttributeIterator
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.TDataStd import TDataStd_Name
import re

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

print(f"STEP body数: {len(bodies)}")

# 2) OCP读取
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label(); st.GetShapes(tops)

# 3) 遍历所有label，打印所有属性和名称
print("\n=== 遍历所有label的属性 ===")
count = 0

def walk_labels(lab, depth=0):
    global count
    if depth > 10 or count > 500:
        return
    
    # 获取所有属性
    attrs = []
    attr_it = TDF_AttributeIterator(lab)
    while attr_it.More():
        attr = attr_it.Value()
        attrs.append(type(attr).__name__)
        attr_it.Next()
    
    # 获取名称
    a = TDataStd_Name()
    name = decode_step_name(a.Get().ToExtString()) if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else "?"
    
    # 只打印有属性的label
    if attrs and name != "?":
        print(f"{'  '*depth}attrs={attrs}  name={name}")
        count += 1
    
    child_it = TDF_ChildIterator(lab)
    while child_it.More():
        walk_labels(child_it.Value(), depth+1)
        child_it.Next()

for i in range(1, tops.Length()+1):
    walk_labels(tops.Value(i), 0)

print(f"\n总共找到 {count} 个有名称的label")
