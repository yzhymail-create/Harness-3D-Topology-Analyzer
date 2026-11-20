#!/usr/bin/env python3
"""列出 STEP 里全部顶层装配（验证 S691/S695 是否在主装配之外）。
用法：python check_assemblies.py <step>
输出每个顶层装配的面数、solid 数；对非主装配列出叶产品名。
"""
import sys
import time

sys.path.insert(0, ".")
from v7geom import v7

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.collections import Sequence_TDF_Label
from OCP.TDF import TDF_Label
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID

S = v7.S


def main():
    step_path = sys.argv[1]
    t0 = time.time()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    if reader.ReadFile(step_path) is None:
        print("读文件失败")
        sys.exit(1)
    reader.Transfer(doc)
    print(f"Transfer {time.time()-t0:.1f}s")
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    tops = Sequence_TDF_Label()
    st.GetShapes(tops)
    print(f"顶层形状 {tops.Length()} 个")
    for i in range(1, tops.Length() + 1):
        lab = tops.Value(i)
        name = v7.label_name(lab)
        shp = S.GetShape_s(lab)
        nf = v7.count_topo(shp, TopAbs_FACE)
        ns = v7.count_topo(shp, TopAbs_SOLID)
        print(f"top[{i}] {name!r} assembly={S.IsAssembly_s(lab)} "
              f"faces={nf} solids={ns}")
        if S.IsAssembly_s(lab) and nf < 100000:
            # 小装配：列出叶产品名
            leaves = []

            def walk(lab2):
                ref = TDF_Label()
                if S.IsComponent_s(lab2):
                    if not S.GetReferredShape_s(lab2, ref):
                        ref = lab2
                else:
                    ref = lab2
                if S.IsAssembly_s(ref):
                    cs = Sequence_TDF_Label()
                    S.GetComponents_s(ref, cs)
                    for j in range(1, cs.Length() + 1):
                        walk(cs.Value(j))
                else:
                    leaves.append(v7.label_name(ref))
            walk(lab)
            print(f"  叶产品 {len(leaves)} 个：{leaves[:20]}")


if __name__ == "__main__":
    main()
