import json
import numpy as np
from collections import defaultdict

print("=" * 70)
print("第6步：形成拓扑关系")
print("=" * 70)

# 加载管状实体数据
print("\n加载管状实体数据...")
with open('tube_entities_v9.json', 'r', encoding='utf-8') as f:
    tube_entities = json.load(f)
print(f"  管状实体数: {len(tube_entities)}")

# 加载合并决策数据
print("\n加载合并决策数据...")
with open('step5_merge_decisions_v9.json', 'r', encoding='utf-8') as f:
    merge_decisions = json.load(f)
print(f"  合并决策数: {len(merge_decisions)}")

# 构建图：每个端点是一个节点
# 使用并查集来合并节点
parent = {}

def find(x):
    if parent[x] != x:
        parent[x] = find(parent[x])
    return parent[x]

def union(x, y):
    px, py = find(x), find(y)
    if px != py:
        parent[px] = py

# 初始化：每个端点是一个独立的节点
print("\n初始化节点...")
for tube in tube_entities:
    parent[f"{tube['name']}.p0"] = f"{tube['name']}.p0"
    parent[f"{tube['name']}.p1"] = f"{tube['name']}.p1"

# 根据MERGE决策合并节点
print("\n合并节点...")
merge_count = 0
for decision in merge_decisions:
    if decision['decision'] == 'MERGE':
        node_a = f"{decision['tube_a']}.{decision['end_a']}"
        node_b = f"{decision['tube_b']}.{decision['end_b']}"
        union(node_a, node_b)
        merge_count += 1
print(f"  合并了 {merge_count} 对节点")

# 收集合并后的节点
print("\n收集合并后的节点...")
node_groups = defaultdict(list)
for tube in tube_entities:
    for end in ['p0', 'p1']:
        node_id = f"{tube['name']}.{end}"
        root = find(node_id)
        node_groups[root].append({
            'tube': tube['name'],
            'end': end,
            'position': tube[end]
        })

# 创建节点列表
print("\n创建节点列表...")
nodes = []
node_id_map = {}
for i, (root, members) in enumerate(node_groups.items()):
    node_id = f"N{i+1:03d}"
    node_id_map[root] = node_id
    
    # 计算节点位置（平均位置）
    avg_pos = np.mean([m['position'] for m in members], axis=0)
    
    # 收集连接到这个节点的管状实体
    connected_tubes = list(set(m['tube'] for m in members))
    
    nodes.append({
        'node_id': node_id,
        'position': avg_pos.tolist(),
        'connected_tubes': connected_tubes,
        'member_count': len(members)
    })

# 创建线束段列表（每个管状实体是一个线束段）
print("\n创建线束段列表...")
segments = []
for tube in tube_entities:
    node_start = node_id_map[find(f"{tube['name']}.p0")]
    node_end = node_id_map[find(f"{tube['name']}.p1")]
    
    segments.append({
        'tube': tube['name'],
        'length': tube['length'],
        'cyl_length': tube['cyl_length'],
        'bspline_length': tube['bspline_length'],
        'radius': tube['radius'],
        'p0': tube['p0'],
        'p1': tube['p1'],
        'node_start': node_start,
        'node_end': node_end
    })

# 保存拓扑数据
topology = {
    'nodes': nodes,
    'segments': segments
}

with open('step6_topology_v9.json', 'w', encoding='utf-8') as f:
    json.dump(topology, f, indent=2, ensure_ascii=False)

print(f"\n已保存 step6_topology_v9.json")
print(f"  节点数: {len(nodes)}")
print(f"  线束段数: {len(segments)}")

# 统计
from collections import Counter
member_counts = Counter(n['member_count'] for n in nodes)
print(f"\n节点成员数统计:")
for count, num in sorted(member_counts.items()):
    print(f"  {count}个成员: {num}个节点")

# 显示前10个节点
print(f"\n前10个节点:")
for node in nodes[:10]:
    print(f"  {node['node_id']}: {node['member_count']}个成员, 连接{len(node['connected_tubes'])}个线束段")
    print(f"    位置: {[round(x,1) for x in node['position']]}")
    if len(node['connected_tubes']) <= 3:
        print(f"    线束段: {node['connected_tubes']}")
