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
ret = reader.ReadFile(step_path)
print(f"ReadFile返回: {ret}", file=sys.stderr)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label(); st.GetShapes(tops)
print(f"顶层实体数: {tops.Length()}", file=sys.stderr)

# 遍历所有子组件，打印名称和标签
def walk_all(lab, depth=0, max_depth=10):
    if depth > max_depth:
        return
    
    a = TDataStd_Name()
    name = decode_name(a.Get().ToExtString()) if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else "?"
    
    is_asm = XCAFDoc_ShapeTool.IsAssembly_s(lab)
    is_comp = XCAFDoc_ShapeTool.IsComponent_s(lab)
    is_simple = XCAFDoc_ShapeTool.IsSimpleShape_s(lab)
    
    type_str = "ASM" if is_asm else ("COMP" if is_comp else ("SIMPLE" if is_simple else "OTHER"))
    
    # 打印所有实体
    print(f"{'  '*depth}[{type_str}] {name}")
    
    it = TDF_ChildIterator(lab)
    count = 0
    while it.More() and count < 50:
        walk_all(it.Value(), depth + 1, max_depth)
        it.Next()
        count += 1

print("=== 装配结构(前3层) ===", file=sys.stderr)
for i in range(1, min(tops.Length() + 1, 4)):
    walk_all(tops.Value(i), 0, 3)
