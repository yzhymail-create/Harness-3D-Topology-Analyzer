#!/usr/bin/env python3
"""找出地板 TopExp 804 solid 与具名 BREP 803 个之间多出的 1 个。
对比 v1 geometry.json（TopExp 顺序，804 个，位置可信、名字错位）与
管线 entities.json（BREP 枚举，803 个），按几何指纹（包围盒中心）
匹配，报告无匹配的 v1 实体（多出的）与无匹配的管线实体（漏掉的，
应为 0）。
用法：python find_extra_solid.py <v1_geometry.json> <entities.json>
"""
import json
import math
import sys


def center_of_v1_tube(t):
    xs = [p[0] for p in t["polyline"]]
    ys = [p[1] for p in t["polyline"]]
    zs = [p[2] for p in t["polyline"]]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
            (min(zs) + max(zs)) / 2)


def main():
    v1 = json.load(open(sys.argv[1]))
    ent = json.load(open(sys.argv[2]))

    # v1 实体：(s, kind, center, extra)
    v1_items = []
    for t in v1["tubes"]:
        v1_items.append((t["s"], "tube", center_of_v1_tube(t),
                         f"len={t['length']:.1f} dia={t['dia']}"))
    for o in v1["others"]:
        v1_items.append((o["s"], "other", tuple(o["center"]),
                         f"bbox_diag={o.get('bbox_diag')}"))
    print(f"v1 实体：{len(v1_items)}（管 {len(v1['tubes'])}，非管 "
          f"{len(v1['others'])}）")

    # 管线实体：(tag, kind, center)
    pipe_items = []
    for b in ent["branches"]:
        pipe_items.append((b["tag"], "tube", tuple(b["bbox_c"][:3]), b["name"]))
    for d in ent["devices"]:
        pipe_items.append((d["tag"], "device", tuple(d["bbox_c"][:3]), d["name"]))
    print(f"管线实体：{len(pipe_items)}（分支 {len(ent['branches'])}，"
          f"设备 {len(ent['devices'])}）")

    # 按中心匹配（容差 1mm；同中心多实体按种类细分）
    def key(c):
        return (round(c[0]), round(c[1]), round(c[2]))

    from collections import defaultdict
    pipe_by_key = defaultdict(list)
    for tag, kind, c, name in pipe_items:
        pipe_by_key[key(c)].append((tag, kind, name))

    unmatched_v1 = []
    matched_pipe = set()
    for s, kind, c, extra in v1_items:
        cands = [p for p in pipe_by_key.get(key(c), [])
                 if p[0] not in matched_pipe]
        # 同中心有多个时优先同种类
        same_kind = [p for p in cands
                     if (p[1] == "tube") == (kind == "tube")]
        pick = same_kind[0] if same_kind else (cands[0] if cands else None)
        if pick is None:
            unmatched_v1.append((s, kind, c, extra))
        else:
            matched_pipe.add(pick[0])

    unmatched_pipe = [p for p in pipe_items if p[0] not in matched_pipe]
    print(f"\n无匹配的 v1 实体（多出的）：{len(unmatched_v1)}")
    for s, kind, c, extra in unmatched_v1:
        print(f"  v1 S{s} [{kind}] center="
              f"[{c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}] {extra}")
        # 找最近的管线实体，看是近似重复还是彻底没有
        best = None
        for tag, k2, c2, name in pipe_items:
            dd = math.dist(c, c2)
            if best is None or dd < best[0]:
                best = (dd, tag, k2, name)
        print(f"    最近管线实体：{best[1]} [{best[2]}] {best[3]}，"
              f"中心距 {best[0]:.1f}mm")
    print(f"\n无匹配的管线实体（漏掉的，应为 0）：{len(unmatched_pipe)}")
    for tag, kind, c, name in unmatched_pipe[:10]:
        print(f"  {tag} [{kind}] {name} center="
              f"[{c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}]")


if __name__ == "__main__":
    main()
