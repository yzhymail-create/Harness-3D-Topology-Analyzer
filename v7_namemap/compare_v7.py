"""对比原版与名称映射版 v7_final 的 topology.json：
- 拓扑数（线段/节点/走线/各类型节点数）必须完全一致（只改名，不改拓扑）；
- 节点 name_3d：映射版应为 BREP 真名，原版为 tag；
- 除 name_3d / brep_name 外，其余字段必须一致。
用法：python compare_v7.py <原版topology.json> <映射版topology.json>
"""
import json
import sys
from collections import Counter


def load(p):
    with open(p) as f:
        return json.load(f)


def main():
    a = load(sys.argv[1])
    b = load(sys.argv[2])
    print("== 拓扑数对比（原版 vs 映射版）==")
    for k in ("segments", "nodes", "runs"):
        print(f"  {k}: {len(a[k])} vs {len(b[k])} "
              f"{'OK' if len(a[k]) == len(b[k]) else 'DIFF!'}")
    ca = Counter(n["type"] for n in a["nodes"])
    cb = Counter(n["type"] for n in b["nodes"])
    print(f"  节点类型: {dict(ca)} vs {dict(cb)} "
          f"{'OK' if ca == cb else 'DIFF!'}")
    # relations 关键数
    for k in ("taps", "end_ends", "terminals", "tie_stations"):
        va = len(a["relations"].get(k, []))
        vb = len(b["relations"].get(k, []))
        print(f"  relations.{k}: {va} vs {vb} "
              f"{'OK' if va == vb else 'DIFF!'}")
    # 节点除 name_3d 外逐个比对（按 code 对齐）
    na = {n["code"]: n for n in a["nodes"]}
    nb = {n["code"]: n for n in b["nodes"]}
    diff_other = 0
    renamed = 0
    for code in na:
        if code not in nb:
            print(f"  节点 {code} 在映射版缺失！")
            diff_other += 1
            continue
        xa = {k: v for k, v in na[code].items() if k != "name_3d"}
        xb = {k: v for k, v in nb[code].items() if k != "name_3d"}
        if xa != xb:
            diff_other += 1
            if diff_other <= 3:
                print(f"  节点 {code} 除名字外有差异：{xa} vs {xb}")
        if na[code].get("name_3d") != nb[code].get("name_3d"):
            renamed += 1
    print(f"== 节点：除名字外差异 {diff_other} 个，改名 {renamed} 个 ==")
    print("  改名取样（code: 原名 -> 真名）：")
    shown = 0
    for code in na:
        if (code in nb and na[code].get("name_3d") != nb[code].get("name_3d")
                and shown < 10):
            print(f"    {code}: {na[code].get('name_3d')} -> "
                  f"{nb[code].get('name_3d')}")
            shown += 1
    # connectors 的 brep_name
    n_brep = sum(1 for c in b.get("connectors", []) if c.get("brep_name"))
    print(f"== connectors 带 brep_name：{n_brep}/{len(b.get('connectors', []))} ==")


if __name__ == "__main__":
    main()
