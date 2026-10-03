import json
import numpy as np

print("=" * 70)
print("第5步：合并决策")
print("=" * 70)

# 加载管状实体数据
print("\n加载管状实体数据...")
with open('tube_entities_v9.json', 'r', encoding='utf-8') as f:
    tube_entities = json.load(f)
print(f"  管状实体数: {len(tube_entities)}")

# 加载分段点数据
print("\n加载分段点数据...")
with open('step4_split_points_v9.json', 'r', encoding='utf-8') as f:
    split_points = json.load(f)
print(f"  分段点数: {len(split_points)}")

# 设置合并距离阈值
MERGE_DISTANCE = 10.0  # mm
SPLIT_POINT_THRESHOLD = 15.0  # 分段点距离阈值

print(f"\n合并距离阈值: {MERGE_DISTANCE}mm")
print(f"分段点距离阈值: {SPLIT_POINT_THRESHOLD}mm")

# 收集所有端点
print("\n收集所有端点...")
endpoints = []
for tube in tube_entities:
    endpoints.append({
        'tube': tube['name'],
        'end': 'p0',
        'position': np.array(tube['p0'])
    })
    endpoints.append({
        'tube': tube['name'],
        'end': 'p1',
        'position': np.array(tube['p1'])
    })
print(f"  端点数: {len(endpoints)}")

# 分段点位置
split_positions = [np.array(sp['position']) for sp in split_points]

# 合并决策
print("\n分析合并决策...")
merge_decisions = []

for i, ep1 in enumerate(endpoints):
    for j, ep2 in enumerate(endpoints):
        if j <= i:
            continue
        
        # 跳过同一个管状实体的两个端点
        if ep1['tube'] == ep2['tube']:
            continue
        
        # 计算距离
        dist = np.linalg.norm(ep1['position'] - ep2['position'])
        
        # 如果距离太远，跳过
        if dist > MERGE_DISTANCE:
            continue
        
        # 检查中间是否有分段点
        has_split = False
        split_entity = None
        
        for sp_pos in split_positions:
            # 检查分段点是否在两个端点之间
            # 简化处理：检查分段点到两个端点的距离
            dist_to_ep1 = np.linalg.norm(sp_pos - ep1['position'])
            dist_to_ep2 = np.linalg.norm(sp_pos - ep2['position'])
            
            # 如果分段点离两个端点都很近，说明在中间
            if dist_to_ep1 < SPLIT_POINT_THRESHOLD and dist_to_ep2 < SPLIT_POINT_THRESHOLD:
                has_split = True
                # 找到对应的分段点实体
                for sp in split_points:
                    if np.linalg.norm(np.array(sp['position']) - sp_pos) < 0.1:
                        split_entity = sp['entity']
                        break
                break
        
        # 决策
        if has_split:
            decision = 'NOT_MERGE'
            reason = f"中间有分段点: {split_entity}"
        else:
            decision = 'MERGE'
            reason = "两端点距离近且中间无分段点"
        
        merge_decisions.append({
            'tube_a': ep1['tube'],
            'tube_b': ep2['tube'],
            'end_a': ep1['end'],
            'end_b': ep2['end'],
            'end_distance': dist,
            'has_split_point': has_split,
            'split_entity': split_entity,
            'decision': decision,
            'reason': reason
        })

# 保存合并决策数据
with open('step5_merge_decisions_v9.json', 'w', encoding='utf-8') as f:
    json.dump(merge_decisions, f, indent=2, ensure_ascii=False)

print(f"\n已保存 step5_merge_decisions_v9.json ({len(merge_decisions)} 对)")

# 统计
from collections import Counter
decisions = Counter(d['decision'] for d in merge_decisions)
print(f"\n合并决策统计:")
for decision, count in decisions.items():
    print(f"  {decision}: {count} 对")

# 显示前10个NOT_MERGE的决策
print(f"\n前10个NOT_MERGE的决策:")
not_merge = [d for d in merge_decisions if d['decision'] == 'NOT_MERGE']
for d in not_merge[:10]:
    print(f"  {d['tube_a']}.{d['end_a']} <-> {d['tube_b']}.{d['end_b']}: {d['end_distance']:.1f}mm")
    print(f"    原因: {d['reason']}")

# 显示前10个MERGE的决策
print(f"\n前10个MERGE的决策:")
merge = [d for d in merge_decisions if d['decision'] == 'MERGE']
for d in merge[:10]:
    print(f"  {d['tube_a']}.{d['end_a']} <-> {d['tube_b']}.{d['end_b']}: {d['end_distance']:.1f}mm")
