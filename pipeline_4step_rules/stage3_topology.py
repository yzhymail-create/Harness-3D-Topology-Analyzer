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


# ---- 退化自环段判定与处理（需求说明 §十八，2026-11-18 用户令） ----
# 根因：管子端头落在卡扣/接头节点 6mm 以内，拓扑按 6mm 规则把端头并进
# 该节点，5mm 管尾两端变同一个节点，拓扑里出现自环段；3D 里没有环。
# 判定与处理必须在代码里明确，清理后做闭环检查 V1–V7，任一项失败即
# raise，不写 topology.json。
STUB_CHORD_RATIO = 0.5   # 弦长/弧长 ≥ 此值判退化短管（直 stub），< 此值判真环
_SHARED_PT_TOL = 0.15    # 两段共点判定的坐标允差 mm（坐标取整到 0.1mm）
_LEN_TOL = 0.11          # 长度守恒允差 mm（长度取整到 0.1mm）


def _chord_ratio(seg):
    """自环段的弦长/弧长比：p0-p1 直线距 / length。真环≈0，直 stub≈1。"""
    L = float(seg.get("length", 0) or 0)
    if L <= 0:
        return 0.0
    return d3(tuple(seg["p0"]), tuple(seg["p1"])) / L


def _is_degenerate_stub(seg):
    """§十八-1 判定：自环段且弦长/弧长 ≥ 0.5 判退化短管。"""
    return seg["na"] == seg["nb"] and _chord_ratio(seg) >= STUB_CHORD_RATIO


def cleanup_degenerate_segments(segments, nodes, branch_info, runs,
                                entities_out, log):
    """§十八-2 处理＋§十八-4 闭环检查 V1–V7。

    原地修改 segments/nodes/branch_info/runs/entities_out，返回报告 dict。
    分支内退化段并入同分支相邻段；整根退化段打 stub 标记（留给展开画
    短线头）；真环不动。任一检查失败即 raise AssertionError。
    """
    node_xyz = {n["code"]: tuple(n["xyz"]) for n in nodes}

    # ---- 快照（验证用，只存判定需要的字段） ----
    seg_before = {s["seg"]: (s["na"], s["nb"], round(float(s["length"]), 1),
                             s["branch"], s.get("run"), _chord_ratio(s))
                  for s in segments}
    branch_len_before = {}
    for s in segments:
        branch_len_before[s["branch"]] = round(
            branch_len_before.get(s["branch"], 0.0) + float(s["length"]), 1)
    node_codes_before = {n["code"] for n in nodes}
    branch_ep_before = {b["key"]: (b["node0"], b["node1"])
                        for b in branch_info}
    run_before = {r["run"]: (tuple(r["segs"]), round(float(r["length"]), 1),
                             r["na"], r["nb"]) for r in runs}
    n_seg_before, n_run_before, n_ent_before = (
        len(segments), len(runs), len(entities_out))

    self_loops = [s for s in segments if s["na"] == s["nb"]]
    report = {"self_loops": len(self_loops),
              "true_rings": [s["seg"] for s in self_loops
                             if not _is_degenerate_stub(s)],
              "absorbed": [], "flagged": [], "removed_runs": []}
    absorbed_ids = set()
    flagged_ids = set()

    # ---- 多遍吸收：退化段并入同分支非退化相邻段 ----
    while True:
        stubs_now = [s for s in segments
                     if _is_degenerate_stub(s)
                     and s["seg"] not in absorbed_ids
                     and s["seg"] not in flagged_ids]
        progress = False
        for stub in sorted(stubs_now, key=lambda s: s["seg"]):
            node = stub["na"]
            nbrs = [s for s in segments
                    if s["branch"] == stub["branch"]
                    and s["seg"] != stub["seg"]
                    and s["seg"] not in absorbed_ids
                    and not _is_degenerate_stub(s)
                    and (s["na"] == node or s["nb"] == node)]
            if not nbrs:
                continue
            nbr = sorted(nbrs, key=lambda s: s["seg"])[0]
            # 两段须共享恰好一个端点（分段点），坐标核对
            sp = [tuple(stub["p0"]), tuple(stub["p1"])]
            np_ = [tuple(nbr["p0"]), tuple(nbr["p1"])]
            shared = [(a, b) for a in sp for b in np_
                      if d3(a, b) <= _SHARED_PT_TOL]
            assert len(shared) == 1, (
                f"{stub['seg']} 与相邻段 {nbr['seg']} 共点 "
                f"{len(shared)} 个 ≠ 1，拒绝合并")
            shared_pt = shared[0][0]
            outer_stub = (sp[0] if d3(sp[1], shared_pt) <= _SHARED_PT_TOL
                          else sp[1])
            outer_nbr = (np_[0] if d3(np_[1], shared_pt) <= _SHARED_PT_TOL
                         else np_[1])
            # 合并段端点取两段外侧端点，按 na/nb 定向（近 na 者为 p0）
            na_xyz = node_xyz[nbr["na"]]
            nb_xyz = node_xyz[nbr["nb"]]
            if d3(outer_stub, na_xyz) + d3(outer_nbr, nb_xyz) <= \
                    d3(outer_stub, nb_xyz) + d3(outer_nbr, na_xyz):
                p0, p1 = outer_stub, outer_nbr
            else:
                p0, p1 = outer_nbr, outer_stub
            nbr["length"] = round(float(nbr["length"])
                                  + float(stub["length"]), 1)
            nbr["p0"] = [round(float(x), 1) for x in p0]
            nbr["p1"] = [round(float(x), 1) for x in p1]
            absorbed_ids.add(stub["seg"])
            report["absorbed"].append(
                {"seg": stub["seg"], "branch": stub["branch"], "node": node,
                 "length": stub["length"], "into": nbr["seg"],
                 "merged_length": nbr["length"]})
            progress = True
        if not progress:
            break

    # ---- 整根退化段：打 stub 标记，留给展开画短线头 ----
    # 注意：已吸收段此时仍在 segments 列表里（清除在后），须排除
    for stub in sorted([s for s in segments
                        if _is_degenerate_stub(s)
                        and s["seg"] not in absorbed_ids],
                       key=lambda s: s["seg"]):
        stub["stub"] = True
        stub["stub_chord_ratio"] = round(_chord_ratio(stub), 3)
        flagged_ids.add(stub["seg"])
        report["flagged"].append(
            {"seg": stub["seg"], "branch": stub["branch"], "node": stub["na"],
             "length": stub["length"],
             "chord_ratio": stub["stub_chord_ratio"]})

    if not absorbed_ids and not flagged_ids:
        log("[§十八] 无退化自环段，清理跳过")
        return report

    # ---- 清除被吸收段的全部引用 ----
    segments[:] = [s for s in segments if s["seg"] not in absorbed_ids]
    for b in branch_info:
        b["segs"] = [sg for sg in b["segs"] if sg not in absorbed_ids]
    for r in runs:
        r["segs"] = [sg for sg in r["segs"] if sg not in absorbed_ids]
    removed_runs = [r["run"] for r in runs if not r["segs"]]
    runs[:] = [r for r in runs if r["segs"]]
    seg_by_id = {s["seg"]: s for s in segments}
    for r in runs:
        r["length"] = round(sum(float(seg_by_id[sg]["length"])
                                for sg in r["segs"]), 1)
    report["removed_runs"] = sorted(removed_runs)
    ent_before = {e["code"] for e in entities_out
                  if e.get("category") == "线段"}
    for sid in absorbed_ids:
        assert sid in ent_before, f"被吸收段 {sid} 在 entities 里无对应条目"
    entities_out[:] = [e for e in entities_out
                       if not (e.get("category") == "线段"
                               and e["code"] in absorbed_ids)]
    # 节点 segments 列表与度数按最终段表重算
    node_segs = {n["code"]: [] for n in nodes}
    node_deg = {n["code"]: 0 for n in nodes}
    for s in segments:
        node_segs[s["na"]].append(s["seg"])
        node_deg[s["na"]] += 1
        node_segs[s["nb"]].append(s["seg"])
        node_deg[s["nb"]] += 1
    for n in nodes:
        n["segments"] = sorted(node_segs[n["code"]])
        n["degree"] = node_deg[n["code"]]

    # ---- 闭环检查 V1–V7 ----
    _verify_cleanup(seg_before, branch_len_before, node_codes_before,
                    branch_ep_before, run_before, n_seg_before,
                    n_run_before, n_ent_before, segments, nodes,
                    branch_info, runs, entities_out, report,
                    absorbed_ids, flagged_ids)
    log(f"[§十八] 退化自环段清理：自环 {len(self_loops)} 段中真环 "
        f"{len(report['true_rings'])} 段不动，吸收 {len(absorbed_ids)} 段"
        f"（{sorted(absorbed_ids)}），打标记 {len(flagged_ids)} 段"
        f"（{sorted(flagged_ids)}），删除退化走线 {len(removed_runs)} 条；"
        f"闭环检查 V1–V7 通过")
    return report


def _verify_cleanup(seg_before, branch_len_before, node_codes_before,
                    branch_ep_before, run_before, n_seg_before,
                    n_run_before, n_ent_before, segments, nodes,
                    branch_info, runs, entities_out, report,
                    absorbed_ids, flagged_ids):
    """§十八-4 闭环检查：任一项失败即 raise。"""
    # V1 判定残留：剩余自环段须是真环或已打标记；标记须有判定依据
    for s in segments:
        if s["na"] != s["nb"]:
            continue
        if s.get("stub"):
            assert _chord_ratio(s) >= STUB_CHORD_RATIO, (
                f"V1：{s['seg']} 打了 stub 标记但弦弧比 "
                f"{_chord_ratio(s):.2f} < {STUB_CHORD_RATIO}")
        else:
            assert _chord_ratio(s) < STUB_CHORD_RATIO, (
                f"V1：{s['seg']} 是退化短管（弦弧比 "
                f"{_chord_ratio(s):.2f}）却未处理")
    # V2 长度守恒：每分支段长之和前后一致
    branch_len_after = {}
    for s in segments:
        branch_len_after[s["branch"]] = round(
            branch_len_after.get(s["branch"], 0.0) + float(s["length"]), 1)
    assert set(branch_len_after) == set(branch_len_before), "V2：分支集变了"
    for k, v in branch_len_before.items():
        assert abs(branch_len_after[k] - v) <= _LEN_TOL, (
            f"V2：分支 {k} 段长之和 {v} → {branch_len_after[k]}，不守恒")
    # V3 拓扑不变：节点集、分支端点不变；非相关段逐项一致
    assert {n["code"] for n in nodes} == node_codes_before, "V3：节点集变了"
    for b in branch_info:
        assert (b["node0"], b["node1"]) == branch_ep_before[b["key"]], (
            f"V3：分支 {b['key']} 端点变了")
    absorbed_into = {}
    for rec in report["absorbed"]:
        absorbed_into.setdefault(rec["into"], []).append(rec["seg"])
    for s in segments:
        old = seg_before.get(s["seg"])
        assert old is not None, f"V3：{s['seg']} 是新增段（不应有）"
        if s["seg"] in absorbed_into:
            expect = round(old[2] + sum(
                seg_before[x][2] for x in absorbed_into[s["seg"]]), 1)
            assert abs(float(s["length"]) - expect) <= _LEN_TOL, (
                f"V3：{s['seg']} 合并后长度 {s['length']} ≠ {expect}")
            assert (s["na"], s["nb"], s["branch"], s.get("run")) == (
                old[0], old[1], old[3], old[4]), f"V3：{s['seg']} 端点变了"
        else:
            assert (s["na"], s["nb"], round(float(s["length"]), 1),
                    s["branch"], s.get("run")) == old[:5], (
                f"V3：{s['seg']} 被意外改动")
    # V4 计数：清除数等于吸收数
    assert n_seg_before - len(segments) == len(absorbed_ids), (
        f"V4：段数 {n_seg_before} → {len(segments)}，清除数 ≠ 吸收数 "
        f"{len(absorbed_ids)}")
    assert n_run_before - len(runs) == len(report["removed_runs"]), (
        f"V4：走线数 {n_run_before} → {len(runs)}，删除数 ≠ "
        f"{len(report['removed_runs'])}")
    assert n_ent_before - len(entities_out) == len(absorbed_ids), (
        f"V4：实体数 {n_ent_before} → {len(entities_out)}，清除数 ≠ 吸收数")
    # V5 节点度数与段列表按最终段表一致
    node_segs = {n["code"]: [] for n in nodes}
    node_deg = {n["code"]: 0 for n in nodes}
    for s in segments:
        node_segs[s["na"]].append(s["seg"])
        node_deg[s["na"]] += 1
        node_segs[s["nb"]].append(s["seg"])
        node_deg[s["nb"]] += 1
    for n in nodes:
        assert sorted(node_segs[n["code"]]) == sorted(n["segments"]), (
            f"V5：节点 {n['code']} 段列表不一致")
        assert node_deg[n["code"]] == n["degree"], (
            f"V5：节点 {n['code']} 度数 {n['degree']} ≠ {node_deg[n['code']]}")
    # V6 走线长度与端点
    seg_by_id = {s["seg"]: s for s in segments}
    for r in runs:
        assert all(sg in seg_by_id for sg in r["segs"]), (
            f"V6：走线 {r['run']} 含不存在的段")
        expect = round(sum(float(seg_by_id[sg]["length"])
                           for sg in r["segs"]), 1)
        assert abs(float(r["length"]) - expect) <= _LEN_TOL, (
            f"V6：走线 {r['run']} 长度 {r['length']} ≠ 段长之和 {expect}")
        old = run_before.get(r["run"])
        assert old is not None and (r["na"], r["nb"]) == (old[2], old[3]), (
            f"V6：走线 {r['run']} 端点变了")
    # V7 报告完整：清理前每个退化段都在报告里有去向
    stubs_before = {sid for sid, v in seg_before.items()
                    if v[0] == v[1] and v[5] >= STUB_CHORD_RATIO}
    reported = {rec["seg"] for rec in report["absorbed"]} | {
        rec["seg"] for rec in report["flagged"]}
    assert reported == stubs_before, (
        f"V7：报告 {sorted(reported)} ≠ 清理前退化段 {sorted(stubs_before)}")
    assert reported == absorbed_ids | flagged_ids, "V7：报告与实际处理不一致"
    assert not (absorbed_ids & flagged_ids), "V7：同一段既被吸收又被标记"


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

    # ---- 退化自环段清理（§十八）：判定＋处理＋闭环检查 V1–V7。
    # 在 CODEX 组装与重命名之后、结果组装之前；检查失败即 raise，不写盘。
    cleanup_report = cleanup_degenerate_segments(
        segments, nodes, branch_info, runs, entities_out, log)

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
    result["cleanup_degenerate"] = cleanup_report  # §十八清理记录（可追溯）
    dump_json(out_path, result)
    log(f"[第 3 步] 完成：{time.time()-t_start:.1f}s，输出 {out_path}")
    return result


def build_from_files(work_dir, out_dir, log, tol=6.0):
    """从 entities.json + relations.json 文件跑第 3 步（可独立重跑）。"""
    entities = load_json(os.path.join(work_dir, "entities.json"))
    relations = load_json(os.path.join(work_dir, "relations.json"))
    return build(entities, relations, out_dir, log, tol=tol)
