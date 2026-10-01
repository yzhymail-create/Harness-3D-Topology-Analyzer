import re
import sys

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

print("解析STEP文件...", file=sys.stderr)

# 提取所有MANIFOLD_SOLID_BREP的名称
body_names = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        # 匹配 MANIFOLD_SOLID_BREP('Body.190',#934419)
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',", line)
        if m:
            entity_id = int(m.group(1))
            name = m.group(2)
            body_names[entity_id] = name

print(f"找到 {len(body_names)} 个body名称", file=sys.stderr)

# 打印前50个
print("\n=== 前50个body名称 ===", file=sys.stderr)
for i, (eid, name) in enumerate(sorted(body_names.items())[:50]):
    print(f"  #{eid}: {name}")

# 统计名称类型
name_types = {}
for name in body_names.values():
    if name.startswith("Body."):
        name_types["Body"] = name_types.get("Body", 0) + 1
    elif "\\" in name:
        prefix = name.split("\\")[0]
        name_types[prefix] = name_types.get(prefix, 0) + 1
    else:
        name_types[name] = name_types.get(name, 0) + 1

print("\n=== 名称类型统计 ===", file=sys.stderr)
for t, c in sorted(name_types.items(), key=lambda x: -x[1]):
    print(f"  {t}: {c}个")
