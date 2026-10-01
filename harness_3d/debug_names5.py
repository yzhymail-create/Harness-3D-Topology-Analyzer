from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopoDS import TopoDS
import sys

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

print("读取STEP文件...", file=sys.stderr)
reader = STEPControl_Reader()
ret = reader.ReadFile(step_path)
print(f"ReadFile返回: {ret}", file=sys.stderr)

if ret == IFSelect_ReturnStatus.IFSelect_RetDone:
    reader.TransferRoots()
    
    # 遍历所有solid
    ex = TopExp_Explorer(reader.OneShape(), TopAbs_SOLID)
    count = 0
    while ex.More() and count < 20:
        solid = ex.Current()
        print(f"Solid {count}: {solid}", file=sys.stderr)
        ex.Next()
        count += 1
    
    print(f"\n总共找到 {count} 个solid", file=sys.stderr)
else:
    print(f"读取失败: {ret}", file=sys.stderr)
