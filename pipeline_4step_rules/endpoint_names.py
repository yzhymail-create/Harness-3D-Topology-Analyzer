#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管子端点对名（路由标识）——唯一定义（2026-11-19 用户语音定规则）。

用户规则（MEMORY.md 已记，2026-11-19 语音）：
  1. 节点是独立实体、管子是管子；管子按两端端点命名。
  2. 一端连连接器就用连接器的名字；两管相接点上有卡扣时，管子端点
     用卡扣的名字替代（与 2026-11-14 卡扣主导规则一致——拓扑里节点
     编码已是卡扣/连接器主导，此处直接取节点编号）。
  3. 两管端-端相接、两端点实为同一点时合并为一个点、只显示一处
     （3D 侧 stage2/3 的 6mm 并点已满足，见 README.md；此处只验证）。
  4. 目的：按名字一段一段串起路由算长度（A→B→C→D）。

实施口径（主代理定，汇报时须明说）：
  - 机器名（路由标识）= 端点编号对，按编号排序后以 _ 连接，如 BN44_CON12；
    编号唯一稳定，真名只作显示。CATIA 全名 key 保留作追溯，不许丢。
  - 自环分支（node0 == node1）：名 = 节点_节点，如 BN02_BN02。
  - 平行对（同端点对两根真管子）：保留两根，第一根用裸名，后续按 key
    排序加 #2、#3……后缀区分，如 BN44_CLP163 与 BN44_CLP163#2。
    地板唯一平行对 BN44–CLP163 是两根真管子（S483/S434，不同长度、
    不同路径），不许删，见 README.md；后缀方案待用户定夺。
  - 本模块是端点对名的唯一定义：3D 管线（run_pipeline 接线）与 2D 布局
    （unfold_2d/add_branch_names.py）都调这里，不在两处各写一份算法。
    2D 仓库独立检出时若 import 不到，用 add_branch_names.py 里的镜像
    副本（须与这里逐字一致，改动须同步）。

注意：3D 名与 2D 名在同一根管子上可能不一样——地板 2D 布局用的
fix20261118 版拓扑（493 节点）与 3D 现行 renamed_full 版（469 节点）
节点编号不同。统一拓扑版本待用户定夺（见 README.md）。
"""
from collections import defaultdict, deque


def endpoint_pair_name(node0, node1):
    """端点对名：两端编号排序后以 _ 连接（无向，稳定）。

    节点编号是零填充的（BN01、CLP163、CON12、N01），字典序即数值序，
    排序结果与管子方向无关，同一根管子永远得到同一个名。
    """
    a, b = sorted((node0, node1))
    return f"{a}_{b}"


def assign_route_names(branches, node_codes=None):
    """给分支列表加路由名（就地写 b['route_name']），返回统计 dict。

    branches: topology.json 的 branches（每项有 key/node0/node1）。
    node_codes: 节点编号集（给出时校验端点 100% 可解析为节点）。
    平行对按 key 排序：第一根裸名，后续加 #2、#3……。
    """
    if node_codes is not None:
        node_codes = set(node_codes)
        for b in branches:
            for e in (b["node0"], b["node1"]):
                if e not in node_codes:
                    raise ValueError(
                        f"{b['key']} 的端点 {e} 不在节点集里，无法命名")
    groups = defaultdict(list)
    for b in branches:
        groups[endpoint_pair_name(b["node0"], b["node1"])].append(b)
    parallels = {}
    for name, bs in groups.items():
        if len(bs) == 1:
            bs[0]["route_name"] = name
        else:
            for i, b in enumerate(sorted(bs, key=lambda x: x["key"])):
                b["route_name"] = name if i == 0 else f"{name}#{i + 1}"
            parallels[name] = [b["key"] for b in
                               sorted(bs, key=lambda x: x["key"])]
    self_loops = [b["key"] for b in branches if b["node0"] == b["node1"]]
    return {"branches": len(branches),
            "distinct_names": len(groups),
            "parallels": parallels,
            "self_loops": self_loops}


def verify_route_names(branches, node_codes):
    """校验路由名：端点 100% 可解析、名唯一。返回 (ok, problems)。"""
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


def find_route(branches, start, end):
    """按路由名串路由：BFS 找 start→end 的最短管子链（按管子数）。

    返回 (names, total_len_3d)：names 是路由名列表（按行走方向），
    total_len_3d 是各管 3D 弧长之和；不连通时返回 (None, None)。
    供自测与后续路由计算用，不进管线主流程。
    """
    adj = defaultdict(list)
    for b in branches:
        n0, n1 = b["node0"], b["node1"]
        if n0 == n1:
            continue  # 自环不连向别处
        adj[n0].append((n1, b))
        adj[n1].append((n0, b))
    if start not in adj or end not in adj:
        return None, None
    prev = {start: None}
    via = {}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == end:
            break
        for nxt, b in adj[cur]:
            if nxt not in prev:
                prev[nxt] = cur
                via[nxt] = b
                q.append(nxt)
    if end not in prev:
        return None, None
    names = []
    total = 0.0
    cur = end
    while cur != start:
        b = via[cur]
        names.append(b.get("route_name", endpoint_pair_name(
            b["node0"], b["node1"])))
        total += b.get("length", b.get("len_3d", 0.0))
        cur = prev[cur]
    names.reverse()
    return names, round(total, 1)
