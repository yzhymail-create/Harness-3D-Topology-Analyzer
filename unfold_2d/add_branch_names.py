#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 2D 布局 layout.json 的每条路径加端点对名 route_name。

用法：python3 add_branch_names.py <layout.json> [--out <out.json>]
  不给 --out 时就地改写（先写临时文件、校验通过才落盘）。

命名定义唯一在 pipeline_4step_rules/endpoint_names.py（2026-11-19 用户
语音定规则）：路由名 = 两端节点编号排序后以 _ 连接，如 BN44_CON12；
平行对（同端点对两根真管子）第一根裸名、后续加 #2、#3……后缀。
本脚本只调它，不另写算法；2D 仓库独立检出 import 不到时用下方镜像
副本（须与 endpoint_names.py 逐字一致，改动须同步）。

附带校验：①端点对名 100% 可解析为布局节点、名唯一；②每条 piece 的
na/nb 全部解析为布局节点（LENGTH 端点解析率——2026-11-19 用户令保留
joint 途经点后应为 100%，旧布局 162/980 解析不了）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'pipeline_4step_rules'))
try:
    import endpoint_names
except ImportError:  # 2D 仓库独立检出：镜像副本，须与原版逐字一致
    from collections import defaultdict

    class _Mirror:
        @staticmethod
        def endpoint_pair_name(node0, node1):
            a, b = sorted((node0, node1))
            return f"{a}_{b}"

        @staticmethod
        def assign_route_names(branches, node_codes=None):
            if node_codes is not None:
                node_codes = set(node_codes)
                for b in branches:
                    for e in (b["node0"], b["node1"]):
                        if e not in node_codes:
                            raise ValueError(
                                f"{b['key']} 的端点 {e} 不在节点集里，无法命名")
            groups = defaultdict(list)
            for b in branches:
                groups[_Mirror.endpoint_pair_name(
                    b["node0"], b["node1"])].append(b)
            parallels = {}
            for name, bs in groups.items():
                if len(bs) == 1:
                    bs[0]["route_name"] = name
                else:
                    for i, b in enumerate(sorted(bs, key=lambda x: x["key"])):
                        b["route_name"] = name if i == 0 else f"{name}#{i + 1}"
                    parallels[name] = [b["key"] for b in
                                       sorted(bs, key=lambda x: x["key"])]
            self_loops = [b["key"] for b in branches
                          if b["node0"] == b["node1"]]
            return {"branches": len(branches),
                    "distinct_names": len(groups),
                    "parallels": parallels,
                    "self_loops": self_loops}

        @staticmethod
        def verify_route_names(branches, node_codes):
            node_codes = set(node_codes)
            problems = []
            seen = {}
            for b in branches:
                name = b.get("route_name", "")
                if not name:
                    problems.append(f"{b['key']} 缺 route_name")
                    continue
                base = name.split("#")[0]
                parts = base.split("_")
                if len(parts) != 2:
                    problems.append(f"{b['key']} 路由名 {name} 格式不对")
                    continue
                for e in parts:
                    if e not in node_codes:
                        problems.append(f"{b['key']} 路由名 {name} 的端点 {e} "
                                        "不在节点集里")
                if name in seen:
                    problems.append(f"路由名 {name} 重复：{seen[name]} 与 {b['key']}")
                seen[name] = b["key"]
            return (not problems), problems

    endpoint_names = _Mirror()
    print("警告：import endpoint_names 失败，用镜像副本（须与原版逐字一致）",
          file=sys.stderr)


def main():
    src = sys.argv[1]
    out = src
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    d = json.load(open(src, encoding="utf-8"))
    branches, nodes = d["branches"], d["nodes"]
    node_codes = [n["code"] for n in nodes]

    stats = endpoint_names.assign_route_names(branches, node_codes=node_codes)
    ok, problems = endpoint_names.verify_route_names(branches, node_codes)
    if not ok:
        raise SystemExit("路由名校验失败：" + "；".join(problems[:10]))

    # LENGTH 端点解析率：每条 piece 的 na/nb 是否都是布局节点
    node_set = set(node_codes)
    total = unres = 0
    unres_nodes = set()
    for b in branches:
        for p in b["pieces"]:
            total += 2
            for e in (p["na"], p["nb"]):
                if e not in node_set:
                    unres += 1
                    unres_nodes.add(e)
    rate = 100.0 * (total - unres) / total if total else 100.0

    d.setdefault("meta", {})["route_names"] = (
        "端点对名 route_name（2026-11-19 用户令）：两端节点编号排序后以 _ "
        "连接；平行对加 #2、#3 后缀；定义见 "
        "pipeline_4step_rules/endpoint_names.py")
    d.setdefault("stats", {})["route_names"] = stats["distinct_names"]
    d["stats"]["piece_endpoint_resolution"] = (
        f"{total - unres}/{total}（{rate:.1f}%）")

    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out)

    print(f"路径 {stats['branches']} 条，端点对名 {stats['distinct_names']} 个，"
          f"自环 {len(stats['self_loops'])} 根"
          + (f"，平行对 {len(stats['parallels'])} 组："
             + "、".join(stats['parallels']) if stats['parallels'] else ""))
    print(f"piece 端点解析：{total - unres}/{total}（{rate:.1f}%）"
          + (f"，未解析 {unres} 个：{sorted(unres_nodes)}" if unres else ""))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
