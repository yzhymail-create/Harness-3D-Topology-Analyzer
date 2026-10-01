# 检查未匹配的中文body的顶点坐标
import re

step_path = r"C:\Users\user1\OneDrive\桌面\Ada-WorkSpace\IP-Harness.stp"

def decode_step_name(s):
    return re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',
                  lambda m: ''.join(chr(int(m.group(1)[i:i+4], 16))
                                        for i in range(0, len(m.group(1)), 4)), s)

# 提取STEP body名称
body_names = {}
with open(step_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        m = re.match(r"#(\d+)=MANIFOLD_SOLID_BREP\('([^']+)',", line)
        if m:
            body_names[int(m.group(1))] = decode_step_name(m.group(2))

# 未匹配的中文body
unmatched_ids = [1300767, 1312056, 1323611, 1340170, 1412135, 1440363, 1481433, 1542905, 1551425, 1559334, 1614567, 1788372, 1814475, 1818824]

print("=== 未匹配的中文body ===")
for eid in unmatched_ids[:10]:
    name = body_names.get(eid, "?")
    print(f"#{eid}: {name}")
