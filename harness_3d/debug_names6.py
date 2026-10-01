from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.collections import Sequence_TDF_Label
from OCP.TDF import TDF_Label, TDF_ChildIterator
from OCP.TDataStd import TDataStd_Name
import re

def decode_step_name(s):
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label(); st.GetShapes(tops)

# 遍历所有label，只读取TDataStd_Name
print("=== 所有有TDataStd_Name的label ===")
count = 0

def walk(lab, depth=0):
    global count
    if depth > 15 or count > 1000:
        return
    
    a = TDataStd_Name()
    if lab.FindAttribute(TDataStd_Name.GetID_s(), a):
        name = decode_step_name(a.Get().ToExtString())
        if name and name != "?" and not name.startswith("=>") and name not in ("COMPOUND", "SOLID"):
            print(f"{'  '*depth}{name}")
            count += 1
    
    it = TDF_ChildIterator(lab)
    while it.More():
        walk(it.Value(), depth+1)
        it.Next()

for i in range(1, tops.Length()+1):
    walk(tops.Value(i), 0)

print(f"\n总共: {count}个")
