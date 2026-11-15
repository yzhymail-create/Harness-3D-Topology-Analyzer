# -*- coding: utf-8 -*-
"""第 3 步：节点、线段、拓扑组装（纯数据，不碰 OCP、不读 STEP）。

输入 entities.json + relations.json，输出 topology.json。
组装逻辑直接调用 v7_final 的 build_topology_from_relations（站位聚类
10mm、主干在内部站位处切段、搭接分支挂站位节点、节点合并 D1/D2/D3、
度数≥2 卡扣主导 / 度数=1 连接器优先、degree=1 卡扣重分类为连接器、
走线在度数≠2 处截断），与 v7 零偏差。

另做 v7 analyze() 里的端点邻近兜底：端点距离 ≤ tol（默认 6.0mm，
用户定规）即视为相连，补进 end_ends。顺序与 v7 一致：兜底在
compute_relations（第 2 步）之后、build_topology 之前。
"""
import os
import time

from common import dump_json, load_json
from v7geom import build_topology_from_relations, d3


def build(entities, relations, out_dir, log, tol=6.0):
    """第 3 步主函数。返回 result 字典（与 v7 analyze() 的结果同 schema）。"""
    t_start = time.time()
    branches = entities["branches"]
    devices = entities["devices"]

    # ---- v7 兼容的 branch_data / conn_candidates ----
    branch_data = []
    for b in branches:
        branch_data.append({
            "key": b["key"], "proto": b["proto"], "occ": b["occ"],
            "n_seg": b.get("n_seg", 0),
            "length": b["length"], "vol": b.get("vol"), "dia": b.get("dia"),
            "p0": tuple(float(x) for x in b["p0"]),
            "p1": tuple(float(x) for x in b["p1"]),
            "pts": [tuple(float(x) for x in p) for p in b["pts"]],
            "src": b["src"],
        })
    conn_candidates = []
    for dv in devices:
        conn_candidates.append({
            "tag": dv["tag"], "proto": dv["proto"],
            "bbox_c": [float(x) for x in dv["bbox_c"]],
        })

    # ---- 端点邻近兜底（v7 analyze 同款）：端点距离 ≤ tol 即相连 ----
    rel = {
        "taps": [dict(t) for t in relations["taps"]],
        "end_ends": [tuple(t) for t in relations["end_ends"]],
        "terminals": [dict(t) for t in relations["terminals"]],
        "tie_stations": [dict(t) for t in relations["tie_stations"]],
        "side_sides": [],
    }
    seen_ee = set()
    for (i, ei, j, ej) in rel["end_ends"]:
        seen_ee.add((i, ei, j, ej))
        seen_ee.add((j, ej, i, ei))
    n_fallback = 0
    for i in range(len(branch_data)):
        for j in range(i + 1, len(branch_data)):
            for ei, ej in ((0, 0), (0, 1), (1, 0), (1, 1)):
                if (i, ei, j, ej) in seen_ee:
                    continue
                pi = branch_data[i]["p0" if ei == 0 else "p1"]
                pj = branch_data[j]["p0" if ej == 0 else "p1"]
                if d3(tuple(pi), tuple(pj)) <= tol:
                    rel["end_ends"].append((i, ei, j, ej))
                    n_fallback += 1
    log(f"[兜底] 端点 ≤{tol}mm 补进 end_ends {n_fallback} 对，"
        f"总计 {len(rel['end_ends'])} 对")

    # ---- 拓扑组装（v7 原函数） ----
    segments, nodes, entities_out, runs, branch_info = \
        build_topology_from_relations(branch_data, rel, tol,
                                      conn_candidates, log)

    # ---- 规则二新规（2026-11-15 用户定，替代 2026-11-14 的降级版）：
    # 悬空分支端不再降级管子本身；悬空端默认为连接器节点。
    # 做法：type hanging -> connector，编码 Nxx -> CONxx（从现有最大 CON
    # 序号续编，不动已有连接器编码），name_3d 记为“默认连接器”，并打
    # default_connector=true 标记（非实体连接器）。坐标仍为管端面圆心
    # （v7 已算好，nd["xyz"] 不动）。同步更新 segments/runs/branch_info/
    # entities 里对该节点编码的引用。其他节点类型判定一律不动。
    import re
    hanging_nodes = [nd for nd in nodes if nd["type"] == "hanging"]
    if hanging_nodes:
        max_con = 0
        for nd in nodes:
            m = re.fullmatch(r"CON(\d+)", nd["code"])
            if m:
                max_con = max(max_con, int(m.group(1)))
            for sc in nd.get("secondary", []):
                m = re.fullmatch(r"CON(\d+)", sc["code"])
                if m:
                    max_con = max(max_con, int(m.group(1)))
        code_map = {}
        for nd in sorted(hanging_nodes, key=lambda r: r["id"]):
            max_con += 1
            new_code = f"CON{max_con:02d}"
            code_map[nd["code"]] = new_code
            nd["code"] = new_code
            nd["type"] = "connector"
            nd["name_3d"] = "默认连接器"
            nd["default_connector"] = True
        for sg in segments:
            if sg["na"] in code_map:
                sg["na"] = code_map[sg["na"]]
            if sg["nb"] in code_map:
                sg["nb"] = code_map[sg["nb"]]
        for r in runs:
            if r["na"] in code_map:
                r["na"] = code_map[r["na"]]
            if r["nb"] in code_map:
                r["nb"] = code_map[r["nb"]]
        for bi in branch_info:
            if bi["node0"] in code_map:
                bi["node0"] = code_map[bi["node0"]]
            if bi["node1"] in code_map:
                bi["node1"] = code_map[bi["node1"]]
        for e in entities_out:
            if e["code"] in code_map:
                e["code"] = code_map[e["code"]]
                e["category"] = "连接器"
                e["name_3d"] = "默认连接器"
                e["note"] = ("默认连接器（悬空端推断，非实体连接器）; "
                             + e["note"].replace("自动命名; ", ""))
        log(f"[规则二] 悬空端默认连接器 {len(hanging_nodes)} 个："
            f"{', '.join(code_map.values())}（管子不降级）")

    # ---- 端点重命名（2026-11-14 用户定规）：节点 name_3d 按接触实体取真名。
    # v7 原函数输出的 name_3d 是设备 tag（S 编号）；此处按 devices 表换成
    # CATIA 实例全名，S 编号保留在 entity 字段做追溯。纯分支点（BN）
    # name_3d 为空，不动。端点类型判断（connector/clamp/fork/joint/
    # hanging）由 v7 原函数已给出，不在此改。
    tag_to_name = {dv["tag"]: dv["name"] for dv in devices}

    def _true_name(tag):
        """tag（单个或共位合并的 S18+S23 形式）-> 真名；无真名时原样返回。"""
        if not tag:
            return ""
        names = []
        for part in tag.split("+"):
            nm = tag_to_name.get(part)
            if nm and nm not in names:
                names.append(nm)
        return "+".join(names) if names else tag

    n_renamed = 0
    for nd in nodes:
        new = _true_name(nd.get("name_3d"))
        if new != nd.get("name_3d"):
            n_renamed += 1
        nd["name_3d"] = new
        # secondary 是 [{"code","kind","tag"}]，tag 是追溯标识，原样保留。
    for e in entities_out:
        if e.get("category") != "线段":
            e["name_3d"] = _true_name(e.get("name_3d"))
    log(f"[重命名] 节点 name_3d 换真名 {n_renamed} 个"
        f"（S 编号保留在 entity / secondary.tag 字段）")
    log(f"[组装] 拓扑线段 {len(segments)}，拓扑节点 {len(nodes)}，"
        f"走线 {len(runs)}")
    from collections import Counter
    log(f"[组装] 节点类型：{dict(Counter(n['type'] for n in nodes))}")

    # ---- 结果组装（与 v7 analyze() 的 result 同 schema） ----
    result = {
        "file": entities["file"], "node_tol": tol,
        "branches": [], "segments": segments, "nodes": nodes,
        "entities": entities_out, "runs": runs, "connectors": [],
        "relations": {
            "taps": rel["taps"],
            "end_ends": [list(t) for t in rel["end_ends"]],
            "terminals": rel["terminals"],
            "tie_stations": rel["tie_stations"],
            "side_sides": [],
            "_tag_alias": rel.get("_tag_alias", {}),
            "_entity_kind": rel.get("_entity_kind", {}),
        },
        "ignored_contacts": [],
    }
    for bi, b in enumerate(branch_data):
        pts = b["pts"]
        step = max(1, len(pts) // 120)
        result["branches"].append({
            "key": b["key"], "proto": b["proto"], "occ": b["occ"],
            "n_seg": b["n_seg"],
            "length": round(b["length"], 1), "dia": b["dia"], "src": b["src"],
            "p0": [round(float(x), 1) for x in b["p0"]],
            "p1": [round(float(x), 1) for x in b["p1"]],
            "polyline": [[round(float(x), 1) for x in p] for p in pts[::step]],
            "segs": branch_info[bi]["segs"],
            "node0": branch_info[bi]["node0"],
            "node1": branch_info[bi]["node1"]})
    result["connectors"] = [
        {"occ": dv["tag"], "proto": dv["proto"],
         "name": next((d["name"] for d in devices if d["tag"] == dv["tag"]), ""),
         "center": [round(float(x), 1) for x in dv["bbox_c"][:3]],
         "bbox": [round(float(x), 1) for x in dv["bbox_c"][3:]]}
        for dv in conn_candidates]

    out_path = os.path.join(out_dir, "topology.json")
    dump_json(out_path, result)
    log(f"[第 3 步] 完成：{time.time()-t_start:.1f}s，输出 {out_path}")
    return result


def build_from_files(work_dir, out_dir, log, tol=6.0):
    """从 entities.json + relations.json 文件跑第 3 步（可独立重跑）。"""
    entities = load_json(os.path.join(work_dir, "entities.json"))
    relations = load_json(os.path.join(work_dir, "relations.json"))
    return build(entities, relations, out_dir, log, tol=tol)
