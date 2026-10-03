import json
import numpy as np

print("=" * 70)
print("第3步：推理卡扣/连接器的定位坐标")
print("=" * 70)

# 加载接触关系数据
print("\n加载接触关系数据...")
with open('step2_contacts_v9.json', 'r', encoding='utf-8') as f:
    contacts = json.load(f)
print(f"  非管状实体数: {len(contacts)}")

# 加载管状实体数据
print("\n加载管状实体数据...")
with open('tube_entities_v9.json', 'r', encoding='utf-8') as f:
    tube_entities = json.load(f)

# 推理定位坐标
print("\n推理定位坐标...")
positions = []

for contact in contacts:
    entity_name = contact['entity']
    entity_center = contact['center']
    entity_contacts = contact['contacts']
    
    if not entity_contacts:
        # 无接触，用原始中心
        positions.append({
            'name': entity_name,
            'position': entity_center,
            'reason': '无接触，使用原始中心',
            'contact_count': 0
        })
        continue
    
    # 有接触，根据接触点推理定位坐标
    if len(entity_contacts) == 1:
        # 接触1个端点，定位坐标 = 该端点坐标
        contact_point = entity_contacts[0]['contact_point']
        reason = f"接触{entity_contacts[0]['tube']}.{entity_contacts[0]['end']}"
    else:
        # 接触多个端点，用距离倒数加权平均
        weights = []
        points = []
        for c in entity_contacts:
            # 距离越小，权重越大
            weight = 1.0 / (c['distance'] + 0.1)  # 加0.1避免除零
            weights.append(weight)
            points.append(c['contact_point'])
        
        weights = np.array(weights)
        points = np.array(points)
        
        # 加权平均
        position = np.average(points, axis=0, weights=weights)
        
        # 构建原因说明
        contact_desc = []
        for c in entity_contacts[:3]:  # 最多显示3个
            contact_desc.append(f"{c['tube']}.{c['end']}({c['distance']:.1f}mm)")
        reason = f"加权平均: {', '.join(contact_desc)}"
    
    positions.append({
        'name': entity_name,
        'position': position.tolist(),
        'reason': reason,
        'contact_count': len(entity_contacts)
    })

# 保存定位坐标数据
with open('step3_positions_v9.json', 'w', encoding='utf-8') as f:
    json.dump(positions, f, indent=2, ensure_ascii=False)

print(f"\n已保存 step3_positions_v9.json ({len(positions)} 个)")

# 统计
with_contacts = sum(1 for p in positions if p['contact_count'] > 0)
print(f"\n统计:")
print(f"  有接触的: {with_contacts} 个")
print(f"  无接触的: {len(positions) - with_contacts} 个")

# 显示前10个
print(f"\n前10个定位坐标:")
for p in positions[:10]:
    print(f"  {p['name']}:")
    print(f"    位置: {[round(x,1) for x in p['position']]}")
    print(f"    原因: {p['reason']}")

# 检查C-18\Body
c18 = next((p for p in positions if p['name'] == 'C-18\\Body'), None)
if c18:
    print(f"\nC-18\\Body的定位坐标:")
    print(f"  位置: {[round(x,1) for x in c18['position']]}")
    print(f"  原因: {c18['reason']}")
