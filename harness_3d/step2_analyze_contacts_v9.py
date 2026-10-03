import json
import numpy as np

print("=" * 70)
print("第2步：分析接触关系")
print("=" * 70)

# 加载管状实体数据
print("\n加载管状实体数据...")
with open('tube_entities_v9.json', 'r', encoding='utf-8') as f:
    tube_entities = json.load(f)
print(f"  管状实体数: {len(tube_entities)}")

# 加载非管状实体数据
print("\n加载非管状实体数据...")
with open('non_tube_entities_v9.json', 'r', encoding='utf-8') as f:
    non_tube_entities = json.load(f)
print(f"  非管状实体数: {len(non_tube_entities)}")

# 设置接触距离阈值
CONTACT_THRESHOLD = 15.0  # mm

print(f"\n接触距离阈值: {CONTACT_THRESHOLD}mm")

# 分析接触关系
print("\n分析接触关系...")
contacts = []

for entity in non_tube_entities:
    entity_name = entity['name']
    entity_center = np.array(entity['center'])
    
    entity_contacts = []
    
    # 计算到所有管状实体端点的距离
    for tube in tube_entities:
        tube_name = tube['name']
        p0 = np.array(tube['p0'])
        p1 = np.array(tube['p1'])
        
        # 到p0的距离
        dist_p0 = np.linalg.norm(entity_center - p0)
        if dist_p0 <= CONTACT_THRESHOLD:
            entity_contacts.append({
                'tube': tube_name,
                'end': 'p0',
                'distance': dist_p0,
                'contact_point': p0.tolist()
            })
        
        # 到p1的距离
        dist_p1 = np.linalg.norm(entity_center - p1)
        if dist_p1 <= CONTACT_THRESHOLD:
            entity_contacts.append({
                'tube': tube_name,
                'end': 'p1',
                'distance': dist_p1,
                'contact_point': p1.tolist()
            })
    
    # 按距离排序
    entity_contacts.sort(key=lambda x: x['distance'])
    
    contacts.append({
        'entity': entity_name,
        'center': entity['center'],
        'contacts': entity_contacts
    })

# 保存接触关系数据
with open('step2_contacts_v9.json', 'w', encoding='utf-8') as f:
    json.dump(contacts, f, indent=2, ensure_ascii=False)

print(f"\n已保存 step2_contacts_v9.json")

# 统计
total_contacts = sum(len(c['contacts']) for c in contacts)
entities_with_contacts = sum(1 for c in contacts if len(c['contacts']) > 0)

print(f"\n接触关系统计:")
print(f"  总接触记录: {total_contacts} 个")
print(f"  有接触的实体: {entities_with_contacts} 个")
print(f"  无接触的实体: {len(contacts) - entities_with_contacts} 个")

# 显示前10个有接触的实体
print(f"\n前10个有接触的实体:")
count = 0
for c in contacts:
    if c['contacts']:
        print(f"  {c['entity']}: {len(c['contacts'])}个接触")
        for contact in c['contacts'][:3]:
            print(f"    - {contact['tube']}.{contact['end']}: {contact['distance']:.1f}mm")
        count += 1
        if count >= 10:
            break

# 检查C-18\Body的接触关系
c18 = next((c for c in contacts if c['entity'] == 'C-18\\Body'), None)
if c18:
    print(f"\nC-18\\Body的接触关系:")
    print(f"  接触数: {len(c18['contacts'])}")
    for contact in c18['contacts']:
        print(f"    - {contact['tube']}.{contact['end']}: {contact['distance']:.1f}mm")
