import re

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

def decode_step_name(s):
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

# 提取所有body名称
bodies = []
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',", line)
        if m:
            eid = int(m.group(1))
            raw_name = m.group(2)
            name = decode_step_name(raw_name)
            bodies.append((eid, name))

# 找中文名称的
chinese = [(eid, name) for eid, name in bodies if any('\u4e00' <= c <= '\u9fff' for c in name)]

print(f"=== 中文名称的body: {len(chinese)}个 ===")
for eid, name in chinese:
    print(f"  #{eid}: {name}")
