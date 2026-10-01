"""优化版名称映射：用体积和包围盒中心快速筛选"""
import re
import numpy as np
from collections import defaultdict

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.collections import Sequence_TDF_Label
from OCP.TDF import TDF_ChildIterator
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

def decode_step_name(s):
    """解码STEP文件中的Unicode转义"""
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

def parse_step_bodies(step_path):
    """从STEP文件文本提取所有body的名称和顶点坐标"""
    # 解析CARTESIAN_POINT
    points = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=CARTESIAN_POINT\('([^']*)',\(([^)]+)\)\)", line)
            if m:
                eid = int(m.group(1))
                coords = tuple(float(x.strip()) for x in m.group(3).split(','))
                points[eid] = coords

    # 解析VERTEX_POINT → CARTESIAN_POINT
    vertex_to_point = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=VERTEX_POINT\('[^']*',#(\d+)\)", line)
            if m:
                vertex_to_point[int(m.group(1))] = int(m.group(2))

    # 解析EDGE_CURVE → VERTEX_POINT1, VERTEX_POINT2
    edge_curve_to_vertices = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=EDGE_CURVE\('[^']*',#(\d+),#(\d+),", line)
            if m:
                edge_curve_to_vertices[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))

    # 解析ORIENTED_EDGE → EDGE_CURVE
    oriented_edge_to_curve = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=ORIENTED_EDGE\('[^']*',\*,\*,#(\d+),", line)
            if m:
                oriented_edge_to_curve[int(m.group(1))] = int(m.group(2))

    # 解析EDGE_LOOP → ORIENTED_EDGE列表
    edge_loop_to_edges = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=EDGE_LOOP\('[^']*',\(([^)]+)\)\)", line)
            if m:
                refs = [int(x.strip().replace('#', '')) for x in m.group(2).split(',')]
                edge_loop_to_edges[int(m.group(1))] = refs

    # 解析FACE_OUTER_BOUND → EDGE_LOOP
    face_bound_to_loop = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=FACE_OUTER_BOUND\('[^']*',#(\d+),", line)
            if m:
                face_bound_to_loop[int(m.group(1))] = int(m.group(2))

    # 解析FACE → FACE_OUTER_BOUND
    face_to_bounds = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=ADVANCED_FACE\('[^']*',\(([^)]+)\),", line)
            if m:
                refs = [int(x.strip().replace('#', '')) for x in m.group(2).split(',')]
                face_to_bounds[int(m.group(1))] = refs

    # 解析CLOSED_SHELL → FACE
    shell_to_faces = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=CLOSED_SHELL\('[^']*',\(([^)]+)\)\)", line)
            if m:
                refs = [int(x.strip().replace('#', '')) for x in m.group(2).split(',')]
                shell_to_faces[int(m.group(1))] = refs

    # 解析MANIFOLD_SOLID_BREP → CLOSED_SHELL
    body_to_shell = {}
    body_names = {}
    with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',#(\d+)\)", line)
            if m:
                body_id = int(m.group(1))
                body_names[body_id] = decode_step_name(m.group(2))
                body_to_shell[body_id] = int(m.group(3))

    # 为每个body提取顶点坐标集合
    step_bodies = {}
    for body_id, shell_id in body_to_shell.items():
        vertices = set()
        for face_id in shell_to_faces.get(shell_id, []):
            for bound_id in face_to_bounds.get(face_id, []):
                loop_id = face_bound_to_loop.get(bound_id)
                if loop_id:
                    for edge_id in edge_loop_to_edges.get(loop_id, []):
                        curve_id = oriented_edge_to_curve.get(edge_id)
                        if curve_id:
                            v1, v2 = edge_curve_to_vertices.get(curve_id, (None, None))
                            for v in (v1, v2):
                                if v:
                                    point_id = vertex_to_point.get(v)
                                    if point_id:
                                        coords = points.get(point_id)
                                        if coords:
                                            vertices.add(coords)
        
        if vertices:
            verts_array = np.array(sorted(vertices))
            # 计算包围盒中心
            center = verts_array.mean(axis=0)
            step_bodies[body_id] = {
                "name": body_names[body_id],
                "vertices": verts_array,
                "center": center,
                "vert_count": len(vertices)
            }

    return step_bodies

def extract_ocp_solid_info(solid):
    """从OCP solid提取顶点和几何信息"""
    vertices = set()
    vexp = TopExp_Explorer(solid, TopAbs_VERTEX)
    while vexp.More():
        vertex = TopoDS.Vertex(vexp.Current())
        p = BRep_Tool.Pnt_s(vertex)
        vertices.add((round(p.X(), 4), round(p.Y(), 4), round(p.Z(), 4)))
        vexp.Next()
    
    if not vertices:
        return None
    
    verts_array = np.array(sorted(vertices))
    center = verts_array.mean(axis=0)
    
    # 计算体积
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, props)
    vol = props.Mass()
    
    return {
        "vertices": verts_array,
        "center": center,
        "vol": vol,
        "vert_count": len(vertices)
    }

def match_vertices(step_verts, ocp_verts, tol=0.01):
    """用容差匹配顶点集合"""
    if len(step_verts) != len(ocp_verts):
        return False
    
    # 暴力匹配
    max_dist_sq = tol * tol
    for sv in step_verts:
        min_dist_sq = float('inf')
        for ov in ocp_verts:
            dx = sv[0] - ov[0]
            dy = sv[1] - ov[1]
            dz = sv[2] - ov[2]
            dist_sq = dx*dx + dy*dy + dz*dz
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
        if min_dist_sq > max_dist_sq:
            return False
    
    return True

def build_name_mapping_fast(step_path, ocp_solids):
    """快速建立名称映射：先用体积和中心点筛选，再用顶点匹配"""
    step_bodies = parse_step_bodies(step_path)
    
    # 提取所有OCP solid的信息
    ocp_infos = []
    for solid in ocp_solids:
        info = extract_ocp_solid_info(solid)
        if info:
            ocp_infos.append((solid, info))
    
    # 建立映射
    mapping = {}
    matched_ocp = set()
    
    for step_id, step_data in step_bodies.items():
        step_verts = step_data["vertices"]
        step_name = step_data["name"]
        step_center = step_data["center"]
        step_vert_count = step_data["vert_count"]
        
        # 快速筛选：顶点数量相同
        candidates = [(sol, info) for sol, info in ocp_infos 
                      if info["vert_count"] == step_vert_count and id(sol) not in matched_ocp]
        
        # 进一步筛选：中心点接近
        center_tol = 1.0  # mm
        filtered = []
        for sol, info in candidates:
            dist = np.linalg.norm(step_center - info["center"])
            if dist <= center_tol:
                filtered.append((sol, info))
        
        # 如果筛选后还有多个，用顶点匹配
        for sol, info in filtered:
            if match_vertices(step_verts, info["vertices"]):
                mapping[id(sol)] = step_name
                matched_ocp.add(id(sol))
                break
    
    return mapping

if __name__ == "__main__":
    # 测试
    import time
    step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"
    
    print("=== 解析STEP文件 ===")
    t0 = time.time()
    step_bodies = parse_step_bodies(step_path)
    print(f"提取到 {len(step_bodies)} 个body, 耗时 {time.time()-t0:.1f}s")
    
    chinese = {k: v for k, v in step_bodies.items() if any('\u4e00' <= c <= '\u9fff' for c in v["name"])}
    print(f"其中中文名称: {len(chinese)} 个")
    
    print("\n=== 读取OCP ===")
    t0 = time.time()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    reader.ReadFile(step_path)
    reader.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    
    tops = Sequence_TDF_Label(); st.GetShapes(tops)
    
    ocp_solids = []
    def collect_solids(lab, depth=0):
        if depth > 20:
            return
        shape = st.GetShape_s(lab)
        if shape is not None and not shape.IsNull():
            ex = TopExp_Explorer(shape, TopAbs_SOLID)
            while ex.More():
                ocp_solids.append(ex.Current())
                ex.Next()
        child_it = TDF_ChildIterator(lab)
        while child_it.More():
            collect_solids(child_it.Value(), depth+1)
            child_it.Next()
    
    for i in range(1, tops.Length()+1):
        collect_solids(tops.Value(i), 0)
    
    print(f"OCP读取到 {len(ocp_solids)} 个solid, 耗时 {time.time()-t0:.1f}s")
    
    print("\n=== 建立映射 ===")
    t0 = time.time()
    mapping = build_name_mapping_fast(step_path, ocp_solids)
    print(f"成功映射: {len(mapping)} 个, 耗时 {time.time()-t0:.1f}s")
    
    # 显示映射结果
    print("\n映射结果示例:")
    for i, solid in enumerate(ocp_solids[:20]):
        name = mapping.get(id(solid), "(未匹配)")
        print(f"  {i}: {name}")
