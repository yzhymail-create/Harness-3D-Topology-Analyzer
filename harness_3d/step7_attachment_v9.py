import json
import numpy as np

print("=" * 70)
print("第7步：定位卡扣/连接器在线束段上的位置")
print("=" * 70)

# 加载管状实体数据
print("\n加载管状实体数据...")
with open('tube_entities_v9.json', 'r', encoding='utf-8') as f:
    tube_entities = json.load(f)
print(f"  管状实体数: {len(tube_entities)}")

# 加载定位坐标数据
print("\n加载定位坐标数据...")
with open('step3_positions_v9.json', 'r', encoding='utf-8') as f:
    positions = json.load(f)
print(f"  非管状实体数: {len(positions)}")

# 加载拓扑数据
print("\n加载拓扑数据...")
with open('step6_topology_v9.json', 'r', encoding='utf-8') as f:
    topology = json.load(f)
print(f"  节点数: {len(topology['nodes'])}")
print(f"  线束段数: {len(topology['segments'])}")

# 定位卡扣/连接器
print("\n定位卡扣/连接器...")
attachments = []

for pos in positions:
    entity_name = pos['name']
    entity_position = np.array(pos['position'])
    
    # 找到最近的线束段
    min_dist = float('inf')
    best_tube = None
    best_t = 0
    best_point = None
    
    for tube in tube_entities:
        p0 = np.array(tube['p0'])
        p1 = np.array(tube['p1'])
        
        # 计算点到线段的投影
        line_vec = p1 - p0
        line_len = np.linalg.norm(line_vec)
        
        if line_len == 0:
            continue
        
        line_unitvec = line_vec / line_len
        point_vec = entity_position - p0
        point_len = np.dot(point_vec, line_unitvec)
        
        t = np.clip(point_len / line_len, 0.0, 1.0)
        nearest = p0 + line_vec * t
        
        dist = np.linalg.norm(entity_position - nearest)
        
        if dist < min_dist:
            min_dist = dist
            best_tube = tube
            best_t = t
            best_point = nearest
    
    if best_tube:
        # 计算距离起点的距离
        distance_from_start = best_t * best_tube['length']
        
        # 判断是卡扣还是连接器
        if 'Tyton' in entity_name:
            entity_type = 'connector'
        else:
            entity_type = 'clamp'
        
        attachments.append({
            'name': entity_name,
            'type': entity_type,
            'position': entity_position.tolist(),
            'attached_segment': best_tube['name'],
            'parameter_t': best_t,
            'distance_from_start': distance_from_start,
            'distance_to_segment': min_dist
        })

# 保存定位数据
with open('step7_attachment_v9.json', 'w', encoding='utf-8') as f:
    json.dump(attachments, f, indent=2, ensure_ascii=False)

print(f"\n已保存 step7_attachment_v9.json ({len(attachments)} 个)")

# 统计
from collections import Counter
types = Counter(a['type'] for a in attachments)
print(f"\n类型统计:")
for t, count in types.items():
    print(f"  {t}: {count} 个")

# 距离统计
distances = [a['distance_to_segment'] for a in attachments]
print(f"\n距离线束段的距离统计:")
print(f"  最小: {min(distances):.1f}mm")
print(f"  最大: {max(distances):.1f}mm")
print(f"  平均: {np.mean(distances):.1f}mm")

# 显示前10个
print(f"\n前10个定位:")
for a in attachments[:10]:
    print(f"  {a['name']} ({a['type']}):")
    print(f"    位置: {[round(x,1) for x in a['position']]}")
    print(f"    挂在线束段: {a['attached_segment']}")
    print(f"    参数t: {a['parameter_t']:.3f}")
    print(f"    距起点: {a['distance_from_start']:.1f}mm")
    print(f"    距线束段: {a['distance_to_segment']:.1f}mm")
