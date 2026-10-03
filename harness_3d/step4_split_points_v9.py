import json
import numpy as np
from collections import defaultdict

print("=" * 70)
print("第4步：确定分段点")
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

# 收集所有端点
print("\n收集所有端点...")
endpoints = []
for tube in tube_entities:
    endpoints.append({
        'tube': tube['name'],
        'end': 'p0',
        'position': tube['p0']
    })
    endpoints.append({
        'tube': tube['name'],
        'end': 'p1',
        'position': tube['p1']
    })
print(f"  端点数: {len(endpoints)}")

# 分段点列表
split_points = []
split_id = 1

# 1. 卡扣位置作为分段点
print("\n添加卡扣作为分段点...")
clamp_count = 0
for pos in positions:
    if pos['contact_count'] > 0:  # 有接触的实体
        # 判断是否是卡扣（名称中包含"Body"或"CLIP"）
        if 'Body' in pos['name'] or 'CLIP' in pos['name']:
            split_points.append({
                'point_id': f'SP{split_id:03d}',
                'position': pos['position'],
                'split_reason': 'clamp',
                'entity': pos['name'],
                'contact_count': pos['contact_count']
            })
            split_id += 1
            clamp_count += 1
print(f"  卡扣分段点: {clamp_count} 个")

# 2. 连接器位置作为分段点
print("\n添加连接器作为分段点...")
connector_count = 0
for pos in positions:
    if pos['contact_count'] > 0:  # 有接触的实体
        # 判断是否是连接器（名称中包含"Tyton"）
        if 'Tyton' in pos['name']:
            split_points.append({
                'point_id': f'SP{split_id:03d}',
                'position': pos['position'],
                'split_reason': 'connector',
                'entity': pos['name'],
                'contact_count': pos['contact_count']
            })
            split_id += 1
            connector_count += 1
print(f"  连接器分段点: {connector_count} 个")

# 3. 查找多个线束段交汇点（端点距离很近的点）
print("\n查找线束段交汇点...")
MERGE_THRESHOLD = 5.0  # mm
endpoint_positions = np.array([ep['position'] for ep in endpoints])

# 简单的聚类：找到距离很近的端点组
visited = set()
junction_count = 0
for i, ep1 in enumerate(endpoints):
    if i in visited:
        continue
    
    group = [ep1]
    visited.add(i)
    
    for j, ep2 in enumerate(endpoints):
        if j <= i or j in visited:
            continue
        
        dist = np.linalg.norm(np.array(ep1['position']) - np.array(ep2['position']))
        if dist <= MERGE_THRESHOLD:
            group.append(ep2)
            visited.add(j)
    
    # 如果有多个端点汇聚，作为交汇点
    if len(group) >= 2:
        # 计算平均位置
        avg_pos = np.mean([ep['position'] for ep in group], axis=0)
        
        # 构建描述
        desc = []
        for ep in group[:5]:  # 最多显示5个
            desc.append(f"{ep['tube']}.{ep['end']}")
        
        split_points.append({
            'point_id': f'SP{split_id:03d}',
            'position': avg_pos.tolist(),
            'split_reason': 'junction',
            'entity': f"交汇点({len(group)}个端点)",
            'nearby_ends': desc
        })
        split_id += 1
        junction_count += 1

print(f"  交汇点分段点: {junction_count} 个")

# 保存分段点数据
with open('step4_split_points_v9.json', 'w', encoding='utf-8') as f:
    json.dump(split_points, f, indent=2, ensure_ascii=False)

print(f"\n已保存 step4_split_points_v9.json ({len(split_points)} 个)")

# 统计
from collections import Counter
reasons = Counter(sp['split_reason'] for sp in split_points)
print(f"\n分段点类型统计:")
for reason, count in reasons.items():
    print(f"  {reason}: {count} 个")

# 显示前10个
print(f"\n前10个分段点:")
for sp in split_points[:10]:
    print(f"  {sp['point_id']}: {sp['split_reason']} - {sp['entity']}")
    print(f"    位置: {[round(x,1) for x in sp['position']]}")
