"""从STEP文本中提取每个body的顶点坐标集合，与OCP的solid对比"""
import re
import sys
import numpy as np

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

print("第1步: 解析STEP文件的所有实体...", file=sys.stderr)

# 解析所有实体
entities = {}  # {entity_id: (type, args_str)}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    in_data = False
    for line in f:
        if line.startswith("DATA;"):
            in_data = True
            continue
        if line.startswith("ENDSEC;"):
            in_data = False
            continue
        if not in_data:
            continue
        
        # 解析 #123=TYPE(args)
        m = re.match(r"#(\d+)=(\w+)\((.+)\)\s*;", line)
        if m:
            eid = int(m.group(1))
            etype = m.group(2)
            args = m.group(3)
            entities[eid] = (etype, args)

print(f"总实体数: {len(entities)}", file=sys.stderr)

# 统计类型
from collections import Counter
type_count = Counter(t for t, _ in entities.values())
print(f"MANIFOLD_SOLID_BREP: {type_count.get('MANIFOLD_SOLID_BREP', 0)}", file=sys.stderr)
print(f"CLOSED_SHELL: {type_count.get('CLOSED_SHELL', 0)}", file=sys.stderr)
print(f"ADVANCED_FACE: {type_count.get('ADVANCED_FACE', 0)}", file=sys.stderr)
print(f"VERTEX_POINT: {type_count.get('VERTEX_POINT', 0)}", file=sys.stderr)
print(f"CARTESIAN_POINT: {type_count.get('CARTESIAN_POINT', 0)}", file=sys.stderr)

# 第2步: 提取每个body的引用链
print("\n第2步: 提取每个body的引用链...", file=sys.stderr)

# MANIFOLD_SOLID_BREP('name', #shell_ref)
body_to_shell = {}
body_names = {}
for eid, (etype, args) in entities.items():
    if etype == "MANIFOLD_SOLID_BREP":
        m = re.match(r"'([^']*)',#(\d+)", args)
        if m:
            name = m.group(1)
            shell_ref = int(m.group(2))
            body_to_shell[eid] = shell_ref
            body_names[eid] = name

print(f"body数: {len(body_to_shell)}", file=sys.stderr)

# CLOSED_SHELL(#face1, #face2, ...)
shell_to_faces = {}
for eid, (etype, args) in entities.items():
    if etype == "CLOSED_SHELL":
        refs = [int(x) for x in re.findall(r"#(\d+)", args)]
        shell_to_faces[eid] = refs

# ADVANCED_FACE('name', (#loop1, ...), #surface, .T./.F.)
# 我们只需要找到face引用的edge_loop
face_to_loops = {}
for eid, (etype, args) in entities.items():
    if etype == "ADVANCED_FACE":
        # 提取face bound引用
        refs = [int(x) for x in re.findall(r"#(\d+)", args)]
        face_to_loops[eid] = refs

# FACE_OUTER_BOUND / FACE_BOUND: (#loop_ref, ...)
bound_to_loop = {}
for eid, (etype, args) in entities.items():
    if etype in ("FACE_OUTER_BOUND", "FACE_BOUND"):
        refs = [int(x) for x in re.findall(r"#(\d+)", args)]
        if refs:
            bound_to_loop[eid] = refs[0]

# EDGE_LOOP(#edge1, #edge2, ...)
loop_to_edges = {}
for eid, (etype, args) in entities.items():
    if etype == "EDGE_LOOP":
        refs = [int(x) for x in re.findall(r"#(\d+)", args)]
        loop_to_edges[eid] = refs

# ORIENTED_EDGE(..., #edge_curve)
oriented_to_edge = {}
for eid, (etype, args) in entities.items():
    if etype == "ORIENTED_EDGE":
        refs = [int(x) for x in re.findall(r"#(\d+)", args)]
        if len(refs) >= 2:
            oriented_to_edge[eid] = refs[-1]  # 最后一个引用是edge_curve

# EDGE_CURVE(#vertex1, #vertex2, ...)
edge_to_vertices = {}
for eid, (etype, args) in entities.items():
    if etype == "EDGE_CURVE":
        refs = [int(x) for x in re.findall(r"#(\d+)", args)]
        if len(refs) >= 2:
            edge_to_vertices[eid] = (refs[0], refs[1])

# VERTEX_POINT('name', #cartesian_point)
vertex_to_point = {}
for eid, (etype, args) in entities.items():
    if etype == "VERTEX_POINT":
        m = re.search(r"#(\d+)", args)
        if m:
            vertex_to_point[eid] = int(m.group(1))

# CARTESIAN_POINT('name', (X, Y, Z))
point_coords = {}
for eid, (etype, args) in entities.items():
    if etype == "CARTESIAN_POINT":
        m = re.search(r"\(([^)]+)\)", args)
        if m:
            coords_str = m.group(1)
            try:
                coords = tuple(float(x.strip().rstrip('*')) for x in coords_str.split(','))
                if len(coords) == 3:
                    point_coords[eid] = coords
            except:
                pass

print(f"point_coords数: {len(point_coords)}", file=sys.stderr)

# 第3步: 对每个body，提取所有顶点坐标
print("\n第3步: 提取每个body的顶点坐标...", file=sys.stderr)

def get_body_points(body_id):
    """获取一个body的所有顶点坐标"""
    shell_ref = body_to_shell.get(body_id)
    if shell_ref is None:
        return set()
    
    face_refs = shell_to_faces.get(shell_ref, [])
    points = set()
    
    for face_ref in face_refs:
        bound_refs = face_to_loops.get(face_ref, [])
        for bound_ref in bound_refs:
            loop_ref = bound_to_loop.get(bound_ref)
            if loop_ref is None:
                continue
            edge_refs = loop_to_edges.get(loop_ref, [])
            for edge_ref in edge_refs:
                edge_curve_ref = oriented_to_edge.get(edge_ref)
                if edge_curve_ref is None:
                    continue
                verts = edge_to_vertices.get(edge_curve_ref)
                if verts is None:
                    continue
                for v in verts:
                    pt_ref = vertex_to_point.get(v)
                    if pt_ref is not None and pt_ref in point_coords:
                        points.add(point_coords[pt_ref])
    
    return points

body_points = {}
for body_id in body_to_shell:
    pts = get_body_points(body_id)
    body_points[body_id] = pts

# 统计
sizes = [len(pts) for pts in body_points.values()]
print(f"body顶点数统计: min={min(sizes)}, max={max(sizes)}, avg={sum(sizes)/len(sizes):.0f}", file=sys.stderr)

# 打印几个body的信息
print("\n=== 部分body信息 ===", file=sys.stderr)
for body_id in sorted(body_to_shell.keys())[:5]:
    name = body_names[body_id]
    pts = body_points[body_id]
    if pts:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        zs = [p[2] for p in pts]
        print(f"  #{body_id} '{name}': {len(pts)}个顶点, X=[{min(xs):.1f},{max(xs):.1f}] Y=[{min(ys):.1f},{max(ys):.1f}] Z=[{min(zs):.1f},{max(zs):.1f}]", file=sys.stderr)

# 第4步: 用OCP读取，提取每个solid的顶点坐标
print("\n第4步: OCP读取solid顶点...", file=sys.stderr)

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
            sol = ex.Current()
            
            # 提取顶点
            verts = set()
            vex = TopExp_Explorer(sol, TopAbs_VERTEX)
            while vex.More():
                v = TopoDS.Vertex_s(vex.Current())
                p = BRep_Tool.Pnt_s(v)
                verts.add((round(p.X(), 4), round(p.Y(), 4), round(p.Z(), 4)))
                vex.Next()
            
            # 体积
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(sol, props)
            vol = props.Mass()
            
            ocp_solids.append({
                "vol": vol,
                "verts": verts,
                "n_verts": len(verts)
            })
            ex.Next()
    child_it = TDF_ChildIterator(lab)
    while child_it.More():
        collect_solids(child_it.Value(), depth+1)
        child_it.Next()

for i in range(1, tops.Length()+1):
    collect_solids(tops.Value(i), 0)

# 去重
unique_solids = []
seen = set()
for s in ocp_solids:
    key = (round(s["vol"], 1), s["n_verts"])
    if key not in seen:
        seen.add(key)
        unique_solids.append(s)

print(f"OCP solid数: {len(ocp_solids)}, 去重后: {len(unique_solids)}", file=sys.stderr)

# 第5步: 尝试匹配
print("\n第5步: 匹配...", file=sys.stderr)

# 对每个OCP solid，找STEP body中顶点集合最接近的
matched = 0
for i, ocp_s in enumerate(unique_solids[:5]):
    ocp_pts = ocp_s["verts"]
    best_body = None
    best_overlap = 0
    
    for body_id, step_pts in body_points.items():
        if not step_pts:
            continue
        # 计算重叠率
        overlap = len(ocp_pts & step_pts)
        if overlap > best_overlap:
            best_overlap = overlap
            best_body = body_id
    
    if best_body:
        name = body_names[best_body]
        print(f"  OCP solid {i}: vol={ocp_s['vol']:.1f} {ocp_s['n_verts']}顶点 -> #{best_body} '{name}' (重叠{best_overlap}个顶点)", file=sys.stderr)
        matched += 1

print(f"\n匹配了 {matched}/{min(5, len(unique_solids))} 个", file=sys.stderr)
