"""通过顶点坐标集合匹配STEP body和OCP solid"""
import re
from collections import defaultdict

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

# 1) 从STEP文本提取每个body的顶点坐标集合
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

print(f"提取到 {len(points)} 个CARTESIAN_POINT")

# 解析VERTEX_POINT → CARTESIAN_POINT
vertex_to_point = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=VERTEX_POINT\('[^']*',#(\d+)\)", line)
        if m:
            vertex_id = int(m.group(1))
            point_id = int(m.group(2))
            vertex_to_point[vertex_id] = point_id

print(f"提取到 {len(vertex_to_point)} 个VERTEX_POINT")

# 解析EDGE_CURVE → VERTEX_POINT1, VERTEX_POINT2
edge_curve_to_vertices = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=EDGE_CURVE\('[^']*',#(\d+),#(\d+),", line)
        if m:
            edge_id = int(m.group(1))
            v1 = int(m.group(2))
            v2 = int(m.group(3))
            edge_curve_to_vertices[edge_id] = (v1, v2)

print(f"提取到 {len(edge_curve_to_vertices)} 个EDGE_CURVE")

# 解析ORIENTED_EDGE → EDGE_CURVE
oriented_edge_to_curve = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=ORIENTED_EDGE\('[^']*',\*,\*,#(\d+),", line)
        if m:
            edge_id = int(m.group(1))
            curve_id = int(m.group(2))
            oriented_edge_to_curve[edge_id] = curve_id

print(f"提取到 {len(oriented_edge_to_curve)} 个ORIENTED_EDGE")

# 解析EDGE_LOOP → ORIENTED_EDGE列表
edge_loop_to_edges = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=EDGE_LOOP\('[^']*',\(([^)]+)\)\)", line)
        if m:
            loop_id = int(m.group(1))
            refs_str = m.group(2)
            # 提取所有#数字
            refs = [int(x.strip().replace('#', '')) for x in refs_str.split(',')]
            edge_loop_to_edges[loop_id] = refs

print(f"提取到 {len(edge_loop_to_edges)} 个EDGE_LOOP")

# 解析FACE_OUTER_BOUND → EDGE_LOOP
face_bound_to_loop = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=FACE_OUTER_BOUND\('[^']*',#(\d+),", line)
        if m:
            bound_id = int(m.group(1))
            loop_id = int(m.group(2))
            face_bound_to_loop[bound_id] = loop_id

print(f"提取到 {len(face_bound_to_loop)} 个FACE_OUTER_BOUND")

# 解析FACE → FACE_OUTER_BOUND
face_to_bounds = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=ADVANCED_FACE\('[^']*',\(([^)]+)\),", line)
        if m:
            face_id = int(m.group(1))
            refs_str = m.group(2)
            refs = [int(x.strip().replace('#', '')) for x in refs_str.split(',')]
            face_to_bounds[face_id] = refs

print(f"提取到 {len(face_to_bounds)} 个ADVANCED_FACE")

# 解析CLOSED_SHELL → FACE
shell_to_faces = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=CLOSED_SHELL\('[^']*',\(([^)]+)\)\)", line)
        if m:
            shell_id = int(m.group(1))
            refs_str = m.group(2)
            refs = [int(x.strip().replace('#', '')) for x in refs_str.split(',')]
            shell_to_faces[shell_id] = refs

print(f"提取到 {len(shell_to_faces)} 个CLOSED_SHELL")

# 解析MANIFOLD_SOLID_BREP → CLOSED_SHELL
body_to_shell = {}
body_names = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',#(\d+)\)", line)
        if m:
            body_id = int(m.group(1))
            name = m.group(2)
            shell_id = int(m.group(3))
            body_to_shell[body_id] = shell_id
            body_names[body_id] = name

print(f"提取到 {len(body_to_shell)} 个MANIFOLD_SOLID_BREP")

# 2) 为每个body提取顶点坐标集合
print("\n=== 为每个body提取顶点坐标集合 ===")

body_vertices = {}
for body_id, shell_id in body_to_shell.items():
    vertices = set()
    faces = shell_to_faces.get(shell_id, [])
    for face_id in faces:
        bounds = face_to_bounds.get(face_id, [])
        for bound_id in bounds:
            loop_id = face_bound_to_loop.get(bound_id)
            if loop_id:
                edge_ids = edge_loop_to_edges.get(loop_id, [])
                for edge_id in edge_ids:
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
        # 排序后转为tuple，便于比较
        sorted_verts = tuple(sorted(vertices))
        body_vertices[body_id] = (body_names[body_id], sorted_verts)

print(f"成功提取 {len(body_vertices)} 个body的顶点集合")

# 3) 统计unique的顶点集合
unique_vertex_sets = defaultdict(list)
for body_id, (name, verts) in body_vertices.items():
    unique_vertex_sets[verts].append((body_id, name))

print(f"\nUnique顶点集合数: {len(unique_vertex_sets)}")

# 显示前10个
print("\n前10个unique顶点集合:")
for i, (verts, bodies) in enumerate(list(unique_vertex_sets.items())[:10]):
    print(f"  集合{i}: {len(verts)}个顶点, 对应{len(bodies)}个body")
    for body_id, name in bodies[:3]:
        print(f"    #{body_id}: {name}")
    if len(bodies) > 3:
        print(f"    ... 还有{len(bodies)-3}个")
