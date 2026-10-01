from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.collections import Sequence_TDF_Label
from OCP.TDF import TDF_Label, TDF_ChildIterator
from OCP.TDataStd import TDataStd_Name
import re
import sys

def decode_name(s):
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

def label_name(lab):
    a = TDataStd_Name()
    return decode_name(a.Get().ToExtString()) if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else "?"

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

print("读取STEP文件...", file=sys.stderr)
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

# 获取所有label
all_labels = []
def collect_labels(lab, depth=0):
    if depth > 15:
        return
    all_labels.append((depth, lab))
    it = TDF_ChildIterator(lab)
    while it.More():
        collect_labels(it.Value(), depth + 1)
        it.Next()

tops = Sequence_TDF_Label(); st.GetShapes(tops)
for i in range(1, tops.Length() + 1):
    collect_labels(tops.Value(i), 0)

print(f"总label数: {len(all_labels)}", file=sys.stderr)

# 打印所有有名称的label
print("\n=== 所有有名称的实体 ===", file=sys.stderr)
for depth, lab in all_labels:
    name = label_name(lab)
    if name and name != "?" and not name.startswith("=>") and name not in ("COMPOUND", "SOLID"):
        is_simple = XCAFDoc_ShapeTool.IsSimpleShape_s(lab)
        type_str = "SIMPLE" if is_simple else "OTHER"
        print(f"{'  '*depth}[{type_str}] {name}")
