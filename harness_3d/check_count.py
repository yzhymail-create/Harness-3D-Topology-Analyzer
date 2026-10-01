# 检查未匹配body的顶点数量
import re
from collections import defaultdict

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

def decode_step_name(s):
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

# 提取所有body名称
body_names = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',", line)
        if m:
            body_names[int(m.group(1))] = decode_step_name(m.group(2))

# 未匹配的中文body
unmatched_ids = [1300767, 1312056, 1323611, 1340170, 1412135, 1440363, 1481433, 1542905, 1551425, 1559334, 1614567, 1788372, 1814475, 1818824]

print("=== 未匹配的中文body ===")
for eid in unmatched_ids:
    name = body_names.get(eid, "?")
    print(f"#{eid}: {name}")

# 统计OCP里的solid数量
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.collections import Sequence_TDF_Label
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID

doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label(); st.GetShapes(tops)

solid_count = 0
def count_solids(lab, depth=0):
    global solid_count
    if depth > 20:
        return
    shape = st.GetShape_s(lab)
    if shape is not None and not shape.IsNull():
        ex = TopExp_Explorer(shape, TopAbs_SOLID)
        while ex.More():
            solid_count += 1
            ex.Next()
    from OCP.TDF import TDF_ChildIterator
    child_it = TDF_ChildIterator(lab)
    while child_it.More():
        count_solids(child_it.Value(), depth+1)
        child_it.Next()

for i in range(1, tops.Length()+1):
    count_solids(tops.Value(i), 0)

print(f"\nOCP里总共有 {solid_count} 个solid")
print(f"STEP里有 {len(body_names)} 个body")
print(f"差异: {solid_count - len(body_names)}")
