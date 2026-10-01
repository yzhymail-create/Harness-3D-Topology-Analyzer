import re

def decode_step_name(s):
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

bodies = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',", line)
        if m:
            eid = int(m.group(1))
            raw_name = m.group(2)
            name = decode_step_name(raw_name)
            bodies[eid] = name

# 打印所有中文名称的body
print("=== 中文名称的实体 ===")
for eid, name in sorted(bodies.items()):
    if any('\u4e00' <= c <= '\u9fff' for c in name):
        print(f"  #{eid}: {name}")

print("\n=== 所有body名称(去重后) ===")
unique_names = sorted(set(bodies.values()))
for n in unique_names:
    count = sum(1 for v in bodies.values() if v == n)
    print(f"  {n} ({count}个)")
