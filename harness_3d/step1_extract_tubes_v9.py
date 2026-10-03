import sys
sys.path.insert(0, '.')
import time
import json
import math
import numpy as np
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool, XCAFDoc_Location
from OCP.collections import Sequence_TDF_Label
from OCP.TDF import TDF_Label
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
from OCP.gp import gp_Pnt, gp_Trsf
from OCP.TopLoc import TopLoc_Location
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_BSplineSurface
from OCP.TopoDS import TopoDS
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

def comp_location(lab):
    la = XCAFDoc_Location()
    if lab.FindAttribute(XCAFDoc_Location.GetID_s(), la):
        return la.Get()
    return TopLoc_Location()

step_path = r'C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp'

# 管状实体的合理参数范围
MIN_RADIUS = 2.0  # mm
MAX_RADIUS = 15.0  # mm

print("=" * 70)
print("第1步：提取管状实体（分别计算圆柱面和BSpline面的长度）")
print("=" * 70)
print(f"参数范围: 半径={MIN_RADIUS}-{MAX_RADIUS}mm")

# 加载STEP文件
print("\n加载STEP文件...")
t0 = time.time()
doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
reader = STEPCAFControl_Reader()
reader.ReadFile(step_path)
reader.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

tops = Sequence_TDF_Label()
st.GetShapes(tops)

cands = []
for i in range(1, tops.Length() + 1):
    lab = tops.Value(i)
    if XCAFDoc_ShapeTool.IsAssembly_s(lab):
        shape = XCAFDoc_ShapeTool.GetShape_s(lab)
        ex = TopExp_Explorer(shape, TopAbs_FACE)
        n_faces = 0
        while ex.More():
            n_faces += 1
            ex.Next()
        cands.append((n_faces, lab))

cands.sort(key=lambda t: -t[0])
root = cands[0][1]

leaves = []
def walk(lab, path, parent_trsf):
    ref = TDF_Label()
    is_comp = XCAFDoc_ShapeTool.IsComponent_s(lab)
    if is_comp:
        if not XCAFDoc_ShapeTool.GetReferredShape_s(lab, ref):
            ref = lab
    else:
        ref = lab
    
    if XCAFDoc_ShapeTool.IsAssembly_s(ref):
        cs = Sequence_TDF_Label()
        XCAFDoc_ShapeTool.GetComponents_s(ref, cs)
        for i in range(1, cs.Length() + 1):
            c = cs.Value(i)
            loc = comp_location(c)
            t = loc.Transformation() if not loc.IsIdentity() else gp_Trsf()
            g = gp_Trsf()
            g.Multiply(parent_trsf)
            g.Multiply(t)
            walk(c, path, g)
    else:
        leaves.append({
            "shape": XCAFDoc_ShapeTool.GetShape_s(ref),
            "trsf": parent_trsf
        })

walk(root, [], gp_Trsf())
load_time = time.time() - t0
print(f"  加载完成: {load_time:.1f}s")

# 加载名称映射
print("\n加载名称映射...")
from name_mapper_fast import parse_step_bodies, extract_ocp_solid_info, match_vertices
step_bodies = parse_step_bodies(step_path)
print(f"  STEP body数: {len(step_bodies)}")

# 分析每个实体
print("\n分析实体...")
tube_entities = []
non_tube_entities = []
processed = 0

for lf in leaves:
    shape = lf["shape"]
    trsf = lf["trsf"]
    
    exs = TopExp_Explorer(shape, TopAbs_SOLID)
    while exs.More():
        sol = exs.Current()
        
        info = extract_ocp_solid_info(sol)
        if info is None:
            exs.Next()
            continue
        
        # 查找匹配的STEP body名称
        vert_count = info['vert_count']
        real_name = None
        
        for step_id, step_data in step_bodies.items():
            if len(step_data['vertices']) != vert_count:
                continue
            
            dist = np.linalg.norm(step_data['center'] - info['center'])
            if dist > 1.0:
                continue
            
            if match_vertices(step_data['vertices'], info['vertices']):
                real_name = step_data['name']
                break
        
        if real_name is None:
            exs.Next()
            continue
        
        # 收集所有圆柱面、BSpline面和平面
        cylinder_radii = []
        cylinder_area = 0
        bspline_area = 0
        plane_faces = []
        
        exf = TopExp_Explorer(sol, TopAbs_FACE)
        while exf.More():
            face_shape = exf.Current()
            face = TopoDS.Face(face_shape)
            surf = BRepAdaptor_Surface(face)
            
            surf_type = surf.GetType()
            
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            area = props.Mass()
            
            if surf_type == GeomAbs_Cylinder:
                cyl = surf.Cylinder()
                cylinder_radii.append(cyl.Radius())
                cylinder_area += area
            elif surf_type == GeomAbs_BSplineSurface:
                bspline_area += area
            elif surf_type == GeomAbs_Plane:
                # 计算等效圆半径
                equiv_radius = math.sqrt(area / math.pi)
                
                # 计算端面中心
                center = props.CentreOfMass()
                center_transformed = gp_Pnt(center.X(), center.Y(), center.Z())
                center_transformed.Transform(trsf)
                
                plane_faces.append({
                    'area': area,
                    'equiv_radius': equiv_radius,
                    'center': [center_transformed.X(), 
                               center_transformed.Y(), 
                               center_transformed.Z()]
                })
            
            exf.Next()
        
        # 检查是否有圆柱面
        if len(cylinder_radii) == 0:
            non_tube_entities.append({
                'name': real_name,
                'center': info['center'].tolist()
            })
            exs.Next()
            continue
        
        # 取圆柱面的平均半径
        avg_cyl_radius = sum(cylinder_radii) / len(cylinder_radii)
        
        # 检查半径范围
        if avg_cyl_radius < MIN_RADIUS or avg_cyl_radius > MAX_RADIUS:
            non_tube_entities.append({
                'name': real_name,
                'center': info['center'].tolist()
            })
            exs.Next()
            continue
        
        # 找两个面积相同的圆形端面（等效圆半径与圆柱面半径匹配）
        cap_pair = None
        for i in range(len(plane_faces)):
            for j in range(i + 1, len(plane_faces)):
                r1 = plane_faces[i]['equiv_radius']
                r2 = plane_faces[j]['equiv_radius']
                
                # 检查两个平面的等效圆半径是否相同（2%容差）
                if abs(r1 - r2) / r1 < 0.02:
                    # 检查是否与圆柱面半径匹配（5%容差）
                    if abs(r1 - avg_cyl_radius) / avg_cyl_radius < 0.05:
                        cap_pair = (plane_faces[i], plane_faces[j])
                        break
            if cap_pair:
                break
        
        if cap_pair is None:
            non_tube_entities.append({
                'name': real_name,
                'center': info['center'].tolist()
            })
            exs.Next()
            continue
        
        # 是管状实体
        cap1, cap2 = cap_pair
        radius = (cap1['equiv_radius'] + cap2['equiv_radius']) / 2
        
        # 分别计算圆柱面和BSpline面的长度
        cyl_length = cylinder_area / (2 * math.pi * radius)
        bspline_length = bspline_area / (2 * math.pi * radius)
        total_length = cyl_length + bspline_length
        
        # 端点坐标
        p0 = cap1['center']
        p1 = cap2['center']
        
        tube_entities.append({
            'name': real_name,
            'length': total_length,
            'cyl_length': cyl_length,
            'bspline_length': bspline_length,
            'radius': radius,
            'p0': p0,
            'p1': p1
        })
        
        processed += 1
        if processed % 20 == 0:
            print(f"  已处理: {processed} 个")
        
        exs.Next()

print(f"  完成!")
print(f"  管状实体: {len(tube_entities)} 个")
print(f"  非管状实体: {len(non_tube_entities)} 个")

# 显示前10个管状实体
print(f"\n前10个管状实体:")
for i, e in enumerate(tube_entities[:10], 1):
    print(f"  {i}. {e['name']}: 总长={e['length']:.1f}mm (圆柱={e['cyl_length']:.1f}mm, 弯曲={e['bspline_length']:.1f}mm), 半径={e['radius']:.1f}mm")

# 检查Body.68
body_68 = next((e for e in tube_entities if e['name'] == 'Body.68'), None)
if body_68:
    print(f"\nBody.68验证:")
    print(f"  总长度: {body_68['length']:.1f}mm (CATIA: 36.28mm)")
    print(f"    圆柱部分: {body_68['cyl_length']:.1f}mm")
    print(f"    弯曲部分: {body_68['bspline_length']:.1f}mm")
    print(f"  半径: {body_68['radius']:.1f}mm")
    print(f"  p0: {[round(x,1) for x in body_68['p0']]}")
    print(f"  p1: {[round(x,1) for x in body_68['p1']]}")

# 保存结果
with open('tube_entities_v9.json', 'w', encoding='utf-8') as f:
    json.dump(tube_entities, f, indent=2, ensure_ascii=False)

with open('non_tube_entities_v9.json', 'w', encoding='utf-8') as f:
    json.dump(non_tube_entities, f, indent=2, ensure_ascii=False)

print(f"\n已保存:")
print(f"  tube_entities_v9.json ({len(tube_entities)} 个)")
print(f"  non_tube_entities_v9.json ({len(non_tube_entities)} 个)")
