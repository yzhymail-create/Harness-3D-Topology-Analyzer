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

tops = Sequence_TDF_Label(); st.GetShapes(tops)

# 遍历所有label，包括没有名称的
def walk_all(lab, depth=0, max_depth=20):
    if depth > max_depth:
        return
    
    name = label_name(lab)
    is_asm = XCAFDoc_ShapeTool.IsAssembly_s(lab)
    is_comp = XCAFDoc_ShapeTool.IsComponent_s(lab)
    is_simple = XCAFDoc_ShapeTool.IsSimpleShape_s(lab)
    
    # 打印所有label
    type_str = "ASM" if is_asm else ("COMP" if is_comp else ("SIMPLE" if is_simple else "OTHER"))
    print(f"{'  '*depth}[{type_str}] name='{name}'")
    
    it = TDF_ChildIterator(lab)
    count = 0
    while it.More() and count < 100:
        walk_all(it.Value(), depth + 1, max_depth)
        it.Next()
        count += 1

print("=== 所有label(前5层) ===", file=sys.stderr)
for i in range(1, min(tops.Length() + 1, 4)):
    walk_all(tops.Value(i), 0, 5)
