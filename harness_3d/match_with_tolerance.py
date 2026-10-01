"""尝试用更大容差匹配中文body"""
import re
from collections import defaultdict
import numpy as np

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

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

def decode_step_name(s):
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

# ========== 第一部分：从STEP文本提取顶点坐标 ==========
print("=== 从STEP文本提取顶点坐标 ===")

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
        step_bodies[body_id] = {
            "name": body_names[body_id],
            "vertices": np.array(sorted(vertices))
        }

print(f"STEP: 提取到 {len(step_bodies)} 个body")

# 找中文名称的body
chinese_bodies = {k: v for k, v in step_bodies.items() if any('\u4e00' <= c <= '\u9fff' for c in v["name"])}
print(f"其中中文名称: {len(chinese_bodies)} 个")

# ========== 第二部分：用OCP提取顶点坐标 ==========
print("\n=== 用OCP提取顶点坐标 ===")

doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label(); st.GetShapes(tops)

# 收集所有solid的顶点坐标
ocp_solids = []
def collect_solids(lab, depth=0):
    if depth > 20:
        return
    shape = st.GetShape_s(lab)
    if shape is not None and not shape.IsNull():
        ex = TopExp_Explorer(shape, TopAbs_SOLID)
        while ex.More():
            sol = ex.Current()
            # 提取所有顶点
            vertices = set()
            vexp = TopExp_Explorer(sol, TopAbs_VERTEX)
            while vexp.More():
                vertex = TopoDS.Vertex(vexp.Current())
                p = BRep_Tool.Pnt_s(vertex)
                vertices.add((round(p.X(), 4), round(p.Y(), 4), round(p.Z(), 4)))
                vexp.Next()
            
            if vertices:
                props = GProp_GProps()
                BRepGProp.VolumeProperties_s(sol, props)
                vol = props.Mass()
                ocp_solids.append({
                    "vertices": np.array(sorted(vertices)),
                    "vol": vol
                })
            ex.Next()
    child_it = TDF_ChildIterator(lab)
    while child_it.More():
        collect_solids(child_it.Value(), depth+1)
        child_it.Next()

for i in range(1, tops.Length()+1):
    collect_solids(tops.Value(i), 0)

print(f"OCP: 提取到 {len(ocp_solids)} 个solid")

# 去重（按顶点数量）
unique_ocp = {}
for s in ocp_solids:
    key = len(s["vertices"])
    if key not in unique_ocp:
        unique_ocp[key] = []
    unique_ocp[key].append(s)

print(f"OCP: 按顶点数量分组，有 {len(unique_ocp)} 个不同的顶点数量")

# ========== 第三部分：用更大容差匹配中文body ==========
print("\n=== 用更大容差匹配中文body ===")

def match_vertices(step_verts, ocp_verts, tol=0.1):
    """用更大容差匹配顶点集合"""
    if len(step_verts) != len(ocp_verts):
        return False
    
    # 计算两个集合之间的最小距离
    # 对于每个STEP顶点，找最近的OCP顶点
    max_dist = 0
    for sv in step_verts:
        min_dist = float('inf')
        for ov in ocp_verts:
            dist = np.linalg.norm(sv - ov)
            if dist < min_dist:
                min_dist = dist
        if min_dist > max_dist:
            max_dist = min_dist
    
    return max_dist <= tol

# 尝试不同容差
for tol in [0.01, 0.1, 0.5, 1.0]:
    matched = 0
    for step_id, step_data in chinese_bodies.items():
        step_verts = step_data["vertices"]
        step_name = step_data["name"]
        
        # 在OCP中查找匹配的solid
        candidates = unique_ocp.get(len(step_verts), [])
        for ocp_data in candidates:
            if match_vertices(step_verts, ocp_data["vertices"], tol):
                matched += 1
                break
    
    print(f"容差 {tol}mm: 匹配 {matched} / {len(chinese_bodies)}")
