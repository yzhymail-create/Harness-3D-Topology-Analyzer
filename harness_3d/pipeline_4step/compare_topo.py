#!/usr/bin/env python3
"""对比管线 topology.json 与 v7 基线 topology.json。
匹配按几何指纹（不按 S 号——两边 S 号顺序不同）：
  分支：(p0, p1, length) 取整；
  设备：包围盒中心取整；
  端部接触：(分支指纹, 端, 设备中心)；搭接：(主干指纹, 分支指纹, 端)。
用法：python compare_topo.py <管线topology.json> <v7基线topology.json>
"""
import json
import sys
from collections import Counter

def fp_branch(b):
    return (tuple(round(x) for x in b["p0"]),
            tuple(round(x) for x in b["p1"]),
            round(b["length"]))

def fp_center(c):
    return tuple(round(x) for x in c)

def main():
    pipe = json.load(open(sys.argv[1]))
    base = json.load(open(sys.argv[2]))

    print("=== 计数对比（管线 vs v7基线）===")
    rows = [
        ("分支", len(pipe["branches"]), len(base["branches"])),
        ("线段", len(pipe["segments"]), len(base["segments"])),
        ("节点", len(pipe["nodes"]), len(base["nodes"])),
        ("走线", len(pipe["runs"]), len(base["runs"])),
        ("taps", len(pipe["relations"]["taps"]), len(base["relations"]["taps"])),
        ("end_ends", len(pipe["relations"]["end_ends"]), len(base["relations"]["end_ends"])),
        ("terminals", len(pipe["relations"]["terminals"]), len(base["relations"]["terminals"])),
        ("tie_stations", len(pipe["relations"]["tie_stations"]), len(base["relations"]["tie_stations"])),
    ]
    for name, a, b in rows:
        mark = "OK " if a == b else "DIFF"
        print(f"  [{mark}] {name}: {a} vs {b}")
    pn = Counter(n["type"] for n in pipe["nodes"])
    bn = Counter(n["type"] for n in base["nodes"])
    for t in ("connector", "clamp", "fork", "joint", "hanging"):
        mark = "OK " if pn.get(t, 0) == bn.get(t, 0) else "DIFF"
        print(f"  [{mark}] 节点-{t}: {pn.get(t,0)} vs {bn.get(t,0)}")
    pk = Counter(pipe["relations"].get("_entity_kind", {}).values())
    bk = Counter(base["relations"].get("_entity_kind", {}).values())
    for t in ("connector", "clamp"):
        mark = "OK " if pk.get(t, 0) == bk.get(t, 0) else "DIFF"
        print(f"  [{mark}] 实体分类-{t}: {pk.get(t,0)} vs {bk.get(t,0)}")

    # 分支集合（几何指纹）
    pf = Counter(fp_branch(b) for b in pipe["branches"])
    bf = Counter(fp_branch(b) for b in base["branches"])
    only_p = list((pf - bf).elements())
    only_b = list((bf - pf).elements())
    print(f"=== 分支集合：管线独有 {len(only_p)}，基线独有 {len(only_b)} ===")
    for f in only_p[:5]:
        print("  管线独有:", f)
    for f in only_b[:5]:
        print("  基线独有:", f)

    # 设备中心集合（v7 connectors occ->center；管线 devices 在 entities 里无，
    # 用 topology.json 的 connectors 字段）
    pc = Counter(fp_center(c["center"]) for c in pipe["connectors"])
    bc = Counter(fp_center(c["center"]) for c in base["connectors"])
    print(f"=== 设备候选：管线 {sum(pc.values())}，基线 {sum(bc.values())}，"
          f"中心独有 管线{len(list((pc-bc).elements()))}/基线{len(list((bc-pc).elements()))} ===")

    # 端部接触：(分支指纹, 端， 设备中心）
    def term_keys(topo):
        out = Counter()
        bmap = {i: fp_branch(b) for i, b in enumerate(topo["branches"])}
        cmap = {c["occ"]: fp_center(c["center"]) for c in topo["connectors"]}
        for t in topo["relations"]["terminals"]:
            out[(bmap[t["branch"]], t["end"], cmap.get(t["tag"], ("?",)))] += 1
        return out
    pt = term_keys(pipe)
    bt = term_keys(base)
    print(f"=== 端部接触：管线独有 {sum((pt-bt).values())}，基线独有 {sum((bt-pt).values())} ===")
    for k in list((pt - bt).elements())[:5]:
        print("  管线独有:", k)
    for k in list((bt - pt).elements())[:5]:
        print("  基线独有:", k)

    # 搭接：(主干指纹， 分支指纹， 端）
    def tap_keys(topo):
        out = Counter()
        bmap = {i: fp_branch(b) for i, b in enumerate(topo["branches"])}
        for t in topo["relations"]["taps"]:
            out[(bmap[t["main"]], bmap[t["tap"]], t["tap_end"])] += 1
        return out
    ptk = tap_keys(pipe)
    btk = tap_keys(base)
    print(f"=== 搭接：管线独有 {sum((ptk-btk).values())}，基线独有 {sum((btk-ptk).values())} ===")
    for k in list((ptk - btk).elements())[:5]:
        print("  管线独有:", k)
    for k in list((btk - ptk).elements())[:5]:
        print("  基线独有:", k)

    # 线段总长与走线总长
    pl = round(sum(s["length"] for s in pipe["segments"]), 1)
    bl = round(sum(s["length"] for s in base["segments"]), 1)
    print(f"=== 线段总长：管线 {pl} vs 基线 {bl}（差 {round(pl-bl,1)}）===")

if __name__ == "__main__":
    main()
