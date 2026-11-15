# -*- coding: utf-8 -*-
"""把单个连接器 STP 转成轻量 JS 网格文件。
用法: python step_to_js.py <input.stp> <output.js> [deflection] [name]
- 加载 STEP，取全部实体，三角化，导出顶点+三角索引。
- JS 格式: window.CONNECTOR_MESH = {name, positions:[x,y,z,...], indices:[a,b,c,...]}
- 坐标做中心化（减包围盒中心），避免大坐标丢精度；bbox_center 单独保存。
- name 参数：网格内部名，必须等于拓扑节点名 name_3d（弹窗按名匹配的依据）；
  不给则沿用 STP 文件名（不含扩展名）。
"""
import sys, os, json, time
from OCP.STEPControl import STEPControl_Reader
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_REVERSED
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopLoc import TopLoc_Location
from OCP.BRep import BRep_Tool
from OCP.TopoDS import TopoDS
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

def main():
    stp_path = sys.argv[1]
    js_path = sys.argv[2]
    deflection = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1

    t0 = time.time()
    r = STEPControl_Reader()
    assert r.ReadFile(stp_path) == 1, "STEP 读取失败"
    r.TransferRoots()
    shape = r.OneShape()
    print(f"load: {time.time()-t0:.1f}s")

    # 实体数
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    solids = []
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    print(f"solids: {len(solids)}")

    # 包围盒（用于中心化）
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    cmin = box.CornerMin()
    cmax = box.CornerMax()
    xmin, ymin, zmin = cmin.X(), cmin.Y(), cmin.Z()
    xmax, ymax, zmax = cmax.X(), cmax.Y(), cmax.Z()
    cx, cy, cz = (xmin+xmax)/2, (ymin+ymax)/2, (zmin+zmax)/2
    print(f"bbox: X[{xmin:.1f},{xmax:.1f}] Y[{ymin:.1f},{ymax:.1f}] Z[{zmin:.1f},{zmax:.1f}]")
    print(f"size: {(xmax-xmin):.1f} x {(ymax-ymin):.1f} x {(zmax-zmin):.1f} mm")

    # 三角化并收集顶点/索引（全局去重按坐标+法向近似：直接拼，不去重，JS 里 Three.js 可处理）
    all_pos = []
    all_idx = []
    total_tris = 0
    for s in solids:
        BRepMesh_IncrementalMesh(s, deflection, False, 0.3, True)
        fe = TopExp_Explorer(s, TopAbs_FACE)
        while fe.More():
            face = TopoDS.Face(fe.Current())
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(face, loc)
            if tri is None:
                fe.Next()
                continue
            trsf = loc.Transformation()
            # 反向面必须翻转三角绕向，否则法向朝内、Three.js 单面渲染时看不见 → 满屏窟窿
            # （2026-11-15 BMS 实测：1823 个面里 455 个是 REVERSED，约 25%）
            rev = (face.Orientation() == TopAbs_REVERSED)
            base = len(all_pos) // 3
            for i in range(1, tri.NbNodes()+1):
                p = tri.Node(i).Transformed(trsf)
                all_pos.extend([round(p.X()-cx, 3), round(p.Y()-cy, 3), round(p.Z()-cz, 3)])
            for i in range(1, tri.NbTriangles()+1):
                a, b, c = tri.Triangle(i).Get()
                # OCC 三角形索引从 1 开始；反向面交换 b/c 翻转绕向
                if rev:
                    all_idx.extend([base+a-1, base+c-1, base+b-1])
                else:
                    all_idx.extend([base+a-1, base+b-1, base+c-1])
                total_tris += 1
            fe.Next()

    name = sys.argv[4] if len(sys.argv) > 4 else os.path.splitext(os.path.basename(stp_path))[0]
    data = {
        "name": name,
        "bbox_center": [round(cx, 3), round(cy, 3), round(cz, 3)],
        "bbox_size": [round(xmax-xmin, 3), round(ymax-ymin, 3), round(zmax-zmin, 3)],
        "positions": all_pos,
        "indices": all_idx,
    }
    js = "window.CONNECTOR_MESH = " + json.dumps(data, ensure_ascii=False) + ";\n"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js)
    size_kb = os.path.getsize(js_path) / 1024
    print(f"triangles: {total_tris}, vertices: {len(all_pos)//3}")
    print(f"JS: {js_path} ({size_kb:.0f} KB)")
    print(f"total: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
