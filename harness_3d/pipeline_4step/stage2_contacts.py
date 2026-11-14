# -*- coding: utf-8 -*-
"""第 2 步：接触分析。

对应 v7_final 的 compute_relations。判定口径与 v7 完全一致（阈值一个不改）：

  管-管端-端：端面圆心三维欧氏距离 ≤2mm（compute_relations 内口径；
              6mm 兜底在第 3 步开头做，与 v7 analyze() 顺序一致）。
  管-管搭接：分支端头投影到主干中心线，偏差 ≤ 主干半径+分支半径+2mm，
              且落点离主干两端均 >5mm；近端改按端-端。另有 2b 四路节点。
              搭接循环加包围盒预筛（与 2026-11-14 推送的修改同款公式，
              已证明不漏真实搭接，只省时间不改结果）。
  管-设备：包围盒预筛 → 区域判定（设备包围盒中心投影到中线，
            端部 5mm 窗口）→ v7 的网格距离法（端部 ≤5mm，2026-11-14 新定
            END_GAP_TOL；中部 ≤2mm）：ShapeProximity 找重叠面 →
            取面三角片 → numpy 点-三角 vs 重采样脊柱，减管半径。
            直接 import v7 的 _mesh_shape_ok / _face_tris_world /
            _pt_tri_d2_closest / _resample_polyline，逻辑（含 1.7mm 快速
            通道记 0.0、中部 q 取重采样脊柱最近点）与 v7 新版（5mm 规则）
            逐行一致，无口径差异。

方法变更记录（2026-11-14，实测驱动，非主观换方案）：
  任务书原定“候选对用 BRepExtrema_DistShapeShape 算精确 BREP 距离，
  不网格化”，依据是旧版 harness_topology.py:488 的 _shape_contact。
  但实测证明此路走不通——整实体 BRepExtrema 单对可达 170 秒，面级
  （面 AABB 两步筛 + 面对面精确）单对仍约 50 秒，IP-Harness 150 个
  候选对需 2 小时以上，地板根本跑不完。且 v7 源码注释写明：v7 自身
  早在 2026-10-03 就因同一原因弃用了 BRepExtrema（“单对从 ~9s 降到
  ~0.9s，距离差 0.1mm”），旧版 _shape_contact 在旧代码里零调用，
  从未被验证过。故改回 v7 的网格距离法。
  与 v7 的唯一不同是网格生命周期：v7 一次性网格化全部实体（地板
  804 实体全三角化正是 OOM 根源）；本管线一次只网格化一个设备，
  算完立即 BRepTools.Clean 释放三角化，三角缓存也按设备清空，
  内存始终有界。管子面数少（约 6 面/根），一次性网格化常驻。
  这不是 v7 的 USE_MESH_PROXIMITY“全量常驻网格”——无持久网格、
  无全量邻近结构；阈值一个不改。

输出 relations.json，schema 与 v7 的 relations 字典一致
（taps / end_ends / terminals / tie_stations / side_sides）。
"""
import math
import os
import time

import numpy as np

from common import aabb_dist, dump_json
from v7geom import d3, poly_project
from v7geom import face_tris_world, mesh_shape_ok, pt_tri_d2_closest
from v7geom import resample_polyline
from v7geom import CONTACT_TOL, END_TOL, PROX_TOL, STATION_END_TOL

from OCP.BRepExtrema import BRepExtrema_ShapeProximity
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer

# 2026-11-14 用户定规：连接器端部间隙 ≤5mm（v7 新版常量 END_GAP_TOL）。
END_GAP_TOL = 5.0
# v7 新版同款：端部窄相候选裕量（=5.5）；真实接触（≤5.0mm）的三角化
# 间隙 ≤ 5.0+2×0.15 = 5.3 < 5.5，数学上不漏检。
END_PROX_TOL = END_GAP_TOL + 0.5


def _spine_len(pts):
    return sum(d3(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _branch_radius(vol, length):
    """v7 同款：半径 = sqrt(体积 / (π×中线长))；无体积（纯线框分支）时 5.0。"""
    if vol and length and length > 0:
        return math.sqrt(vol / (math.pi * length))
    return 5.0


def compute(entities, shapes, out_dir, log):
    """第 2 步主函数。返回 relations 字典，并写 relations.json。"""
    t_start = time.time()
    branches = entities["branches"]
    devices = entities["devices"]
    n = len(branches)
    rel = {"taps": [], "end_ends": [], "terminals": [], "tie_stations": [],
           "side_sides": []}

    # ---- 每分支核心参数（v7 同款） ----
    spines, spine_lens, branch_radius, ends = [], [], [], []
    spine_boxes = []   # 中线包围盒外扩管半径（搭接预筛用）
    solid_boxes = []   # 实体包围盒（设备预筛用；纯线框分支用中线盒代替）
    has_shape = []
    for b in branches:
        pts = [tuple(float(x) for x in p) for p in b["pts"]]
        spines.append(pts)
        length = _spine_len(pts)
        spine_lens.append(length)
        r = _branch_radius(b.get("vol"), length)
        branch_radius.append(r)
        ends.append((tuple(float(x) for x in b["p0"]),
                     tuple(float(x) for x in b["p1"])))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        zs = [p[2] for p in pts]
        spine_boxes.append((min(xs) - r, min(ys) - r, min(zs) - r,
                            max(xs) + r, max(ys) + r, max(zs) + r))
        solid_boxes.append(tuple(float(x) for x in b["bbox"]))
        has_shape.append(bool(b.get("has_shape", True)))

    # ---- 1) 管-管端-端：端点坐标比对（≤2mm） ----
    t0 = time.time()
    seen_ee = set()
    for i in range(n):
        if not has_shape[i]:
            continue
        for j in range(i + 1, n):
            if not has_shape[j]:
                continue
            for ei in (0, 1):
                for ej in (0, 1):
                    d = d3(ends[i][ei], ends[j][ej])
                    if d <= CONTACT_TOL and (i, ei, j, ej) not in seen_ee:
                        seen_ee.add((i, ei, j, ej))
                        rel["end_ends"].append((i, ei, j, ej))
                        log(f"接触: {branches[i]['key']}端 <-> "
                            f"{branches[j]['key']}端 ({d:.1f}mm)")
    log(f"[端-端] {time.time()-t0:.1f}s，{len(seen_ee)} 对")

    # ---- 2) 管-管搭接：分支端点 -> 他分支中线投影 ----
    t0 = time.time()
    tap_seen = set()
    n_proj = 0
    n_skip = 0
    for i in range(n):
        if not has_shape[i]:
            continue
        ri = branch_radius[i]
        for ei in (0, 1):
            c = ends[i][ei]
            for j in range(n):
                if j == i or not has_shape[j]:
                    continue
                # 包围盒预筛（2026-11-14 推送修改同款）：盒间隙 > 阈值则
                # 端点到中线距离一定 > 阈值，不可能是搭接，可安全跳过。
                gap = aabb_dist(spine_boxes[i], spine_boxes[j])
                if gap > branch_radius[j] + ri + CONTACT_TOL:
                    n_skip += 1
                    continue
                n_proj += 1
                s, q, dev = poly_project(c, spines[j])
                lj = spine_lens[j]
                if dev > branch_radius[j] + ri + CONTACT_TOL:
                    continue
                if s <= STATION_END_TOL or s >= lj - STATION_END_TOL:
                    ej = 0 if s < lj / 2 else 1
                    a, b = (i, j) if i < j else (j, i)
                    ea, eb = (ei, ej) if i < j else (ej, ei)
                    key = (a, ea, b, eb)
                    if key not in seen_ee:
                        seen_ee.add(key)
                        rel["end_ends"].append(key)
                        log(f"接触(近端按端点连接): {branches[i]['key']} <-> "
                            f"{branches[j]['key']}端")
                elif (j, i, ei) not in tap_seen:
                    tap_seen.add((j, i, ei))
                    rel["taps"].append({"main": j, "s": s, "xyz": q, "tap": i,
                                        "tap_end": ei, "dev": dev})
                    log(f"搭接: {branches[i]['key']} -> {branches[j]['key']} "
                        f"站位{s:.1f}mm 偏差{dev:.1f}mm")
    log(f"[搭接] {time.time()-t0:.1f}s，{len(tap_seen)} 处"
        f"（投影 {n_proj} 次，预筛跳过 {n_skip} 次）")

    # ---- 2b) 接头落在第三管（四路节点） ----
    # 包围盒预筛（2026-11-14 优化，结果不变）：spine_boxes[k] 是 k 管中线
    # 包围盒外扩管半径，中线必在盒内，故接头到中线距离 ≥ 接头点到盒的距离。
    # 若该距离 > branch_radius[i]+branch_radius[k]+CONTACT_TOL，则投影偏差
    # dev 一定超阈值，不可能是四路节点，可安全跳过 poly_project。
    t0 = time.time()
    jtap_seen = set()
    n_2b_proj = 0
    n_2b_skip = 0
    for (i, ei, j, ej) in list(rel["end_ends"]):
        pe_i, pe_j = ends[i][ei], ends[j][ej]
        joint = ((pe_i[0] + pe_j[0]) / 2, (pe_i[1] + pe_j[1]) / 2,
                 (pe_i[2] + pe_j[2]) / 2)
        joint_box = (joint[0], joint[1], joint[2],
                     joint[0], joint[1], joint[2])
        for k in range(n):
            if k == i or k == j or not has_shape[k]:
                continue
            if aabb_dist(joint_box, spine_boxes[k]) > (
                    branch_radius[i] + branch_radius[k] + CONTACT_TOL):
                n_2b_skip += 1
                continue
            n_2b_proj += 1
            s, q, dev = poly_project(joint, spines[k])
            lk = spine_lens[k]
            if (dev <= branch_radius[i] + branch_radius[k] + CONTACT_TOL
                    and STATION_END_TOL < s < lk - STATION_END_TOL
                    and (k, i, j) not in jtap_seen):
                jtap_seen.add((k, i, j))
                rel["taps"].append({"main": k, "s": s, "xyz": q, "tap": i,
                                    "tap_end": ei, "dev": dev})
                log(f"接头搭接(四路节点): {branches[i]['key']}+{branches[j]['key']}接头 -> "
                    f"{branches[k]['key']} 站位{s:.1f}mm 偏差{dev:.1f}mm")
                break
    log(f"[四路] {time.time()-t0:.1f}s，{len(jtap_seen)} 处"
        f"（投影 {n_2b_proj} 次，预筛跳过 {n_2b_skip} 次）")

    # ---- 3) 管-设备：v7 网格距离（逐设备瞬态网格化，用完即清） ----
    # 与 v7 新版（5mm 规则）的 _device_assoc / _prox_veto / _numpy_dist
    # 逐行一致；唯一不同是网格生命周期（见模块说明）。
    t0 = time.time()
    dev_boxes = [tuple(float(x) for x in d["bbox"]) for d in devices]
    dev_centers = [tuple(float(x) for x in d["bbox_c"][:3]) for d in devices]
    dev_tags = [d["tag"] for d in devices]
    dev_diag = [math.sqrt(sum(float(x) ** 2 for x in d["bbox_c"][3:]))
                for d in devices]
    dev_r = [float(np.linalg.norm([float(x) for x in d["bbox_c"][3:]])) / 2.0
             for d in devices]

    # 管侧常驻网格（面数少，一次网格化；v7 bw 同款结构）
    t_mesh_tube = time.time()
    tube_world = []
    n_tube_mok = 0
    n_tube_sh = 0
    for bi, b in enumerate(branches):
        if not has_shape[bi]:
            tube_world.append(None)
            continue
        sh = shapes.get(b["tag"])
        if sh is None:
            tube_world.append(None)
            continue
        n_tube_sh += 1
        bc = b["bbox_c"]
        mok = mesh_shape_ok(sh)
        if mok:
            n_tube_mok += 1
        tube_world.append({
            "w": sh, "c": tuple(float(x) for x in bc[:3]),
            "r": float(np.linalg.norm([float(x) for x in bc[3:]])) / 2.0,
            "mok": mok})
    log(f"[管网格] {time.time()-t_mesh_tube:.1f}s，"
        f"{n_tube_mok}/{n_tube_sh} 成功")

    def broad(c1, r1, c2, r2):
        """v7 同款球形粗筛：中心距 ≤ 半径和 + 2mm。"""
        return d3(c1, c2) <= r1 + r2 + CONTACT_TOL

    spine_cache = {}
    tri_cache = {}   # (ci, 面序号) -> 三角片；每设备算完清空
    n_prox = 0
    n_numpy = 0
    t_mesh_dev = 0.0
    n_dev_mok = 0
    n_dev_mesh_fail = 0

    def branch_spine(i):
        if i not in spine_cache:
            spine_cache[i] = resample_polyline(
                [tuple(p) for p in spines[i]])
        return spine_cache[i]

    def prox_veto(i, ci, tol, dev):
        """v7 _prox_veto 同款：网格 boolean 否决。True=在 tol 内；
        False=明确不在；None=未网格化/异常（无法否决）。"""
        nonlocal n_prox
        tw = tube_world[i]
        if tw is None:
            return False
        if not broad(tw["c"], tw["r"], dev["c"], dev["r"]):
            return False
        if aabb_dist(solid_boxes[i], dev_boxes[ci]) > tol:
            return False
        if tw["mok"] and dev["mok"]:
            try:
                n_prox += 1
                prox = BRepExtrema_ShapeProximity(tw["w"], dev["w"], tol)
                prox.Perform()
                if prox.IsDone():
                    return True
            except Exception:
                return None
        else:
            return None
        return False

    def numpy_dist(i, ci, tol, dev):
        """v7 _numpy_dist 同款（新版 tol 参数）：返回 (dist, q_spine) 或 None。
        dist = 设备重叠面三角片到重采样脊柱的最短距离 - 管半径。"""
        nonlocal n_numpy, n_prox
        tw = tube_world[i]
        if tw is None:
            return None
        if not broad(tw["c"], tw["r"], dev["c"], dev["r"]):
            return None
        if aabb_dist(solid_boxes[i], dev_boxes[ci]) > tol:
            return None
        if not (tw["mok"] and dev["mok"]):
            return None
        try:
            n_prox += 1
            prox = BRepExtrema_ShapeProximity(tw["w"], dev["w"], tol + 0.5)
            prox.Perform()
            if not prox.IsDone():
                return None
            om = prox.OverlapSubShapes2()
            ex = TopExp_Explorer(dev["w"], TopAbs_FACE)
            nf = 0
            while ex.More():
                nf += 1
                ex.Next()
            tris = []
            for k in range(nf):
                if not om.IsBound(k):
                    continue
                key = (ci, k)
                ft = tri_cache.get(key)
                if ft is None:
                    ft = face_tris_world(prox.GetSubShape2(k))
                    tri_cache[key] = ft
                if ft is not None and len(ft):
                    tris.append(ft)
            if not tris:
                return None
            TRIS = np.vstack(tris)
            S = branch_spine(i)
            radius = branch_radius[i]
            best2 = np.inf
            bj = 0
            with np.errstate(divide="ignore", invalid="ignore"):
                for ti in range(len(TRIS)):
                    ta, tb_, tc_ = TRIS[ti]
                    d2v, clo = pt_tri_d2_closest(S, ta, tb_, tc_)
                    jj = int(np.argmin(d2v))
                    if d2v[jj] < best2:
                        best2 = d2v[jj]
                        bj = jj
            if not np.isfinite(best2):
                return None
            n_numpy += 1
            return (math.sqrt(best2) - radius,
                    tuple(float(x) for x in S[bj]))
        except Exception:
            return None

    def device_assoc(i, ci, dev):
        """v7 _device_assoc 同款（新版 5mm 端部规则）。
        返回 ('end', end_idx, dist) | ('mid', s, xyz, dist) | None。"""
        ptsi = spines[i]
        Li = spine_lens[i]
        s_bc, _, _ = poly_project(dev_centers[ci], ptsi)
        is_end = s_bc <= END_TOL or s_bc >= Li - END_TOL
        pre_tol = END_GAP_TOL if is_end else CONTACT_TOL
        tw = tube_world[i]
        pre = False
        if tw is not None:
            if (broad(tw["c"], tw["r"], dev["c"], dev["r"])
                    and aabb_dist(solid_boxes[i], dev_boxes[ci]) <= pre_tol):
                pre = True
        if not pre:
            return None
        if is_end:
            v25 = prox_veto(i, ci, END_PROX_TOL, dev)
            if v25 is not False:
                if prox_veto(i, ci, 1.7, dev) is True:
                    return ("end", 0 if s_bc < Li / 2 else 1, 0.0)
                r = numpy_dist(i, ci, END_GAP_TOL, dev)
                if r and r[0] <= END_GAP_TOL:
                    return ("end", 0 if s_bc < Li / 2 else 1, r[0])
        else:
            v25 = prox_veto(i, ci, PROX_TOL, dev)
            if v25 is not False:
                r = numpy_dist(i, ci, CONTACT_TOL, dev)
                if r and r[0] <= CONTACT_TOL:
                    dist, q = r
                    s_q, _, _ = poly_project(q, ptsi)
                    return ("mid", s_q, q, dist)
        return None

    # 逐设备瞬态网格化：一次只留一个设备的三角化在内存里，算完 Clean。
    # _device_assoc 对 (管, 设备) 是纯函数，先算出全部非空结果存 assoc，
    # 两遍（端部/中部）只读 assoc，不再碰形状。
    assoc = {}
    for ci, dv in enumerate(devices):
        sh_dev = shapes.get(dv["tag"])
        bc = dv["bbox_c"]
        dev = {"w": sh_dev, "c": tuple(float(x) for x in bc[:3]),
               "r": dev_r[ci], "mok": False}
        if sh_dev is not None:
            t1 = time.time()
            dev["mok"] = mesh_shape_ok(sh_dev)
            t_mesh_dev += time.time() - t1
            if dev["mok"]:
                n_dev_mok += 1
            else:
                n_dev_mesh_fail += 1
                log(f"[网格] 设备 {dv['tag']} {dv['name']} 网格化失败，"
                    f"该设备不参与窄相判定")
        for i in range(n):
            if not has_shape[i] or tube_world[i] is None:
                continue
            # 粗筛：盒间隙 > 5.0（最宽松区域阈值）则端部/中部都不可能
            if aabb_dist(solid_boxes[i], dev_boxes[ci]) > END_GAP_TOL:
                continue
            r = device_assoc(i, ci, dev)
            if r is not None:
                assoc[(i, ci)] = r
        if sh_dev is not None:
            try:
                BRepTools.Clean_s(sh_dev)
            except Exception:
                pass
        tri_cache.clear()
    log(f"[设备关联] {time.time()-t0:.1f}s，设备网格成功 {n_dev_mok}，"
        f"失败 {n_dev_mesh_fail}；ShapeProximity 调用 {n_prox} 次，"
        f"numpy 距离 {n_numpy} 次，非空关联 {len(assoc)} 对")

    # 第一遍：端部（连接器坐标按定义取管端圆心）
    t0 = time.time()
    term_xyz = []
    for i in range(n):
        if not has_shape[i]:
            continue
        for ci in range(len(devices)):
            r = assoc.get((i, ci))
            if not r or r[0] != "end":
                continue
            _, end, dist = r
            rel["terminals"].append({"branch": i, "end": end,
                                     "tag": dev_tags[ci],
                                     "kind": "entity", "dist": dist})
            exyz = ends[i][end]
            term_xyz.append((dev_tags[ci], i, exyz, dev_diag[ci]))
            log(f"端部接触: {branches[i]['key']}[{end}] <-> 实体 "
                f"{dev_tags[ci]} {devices[ci]['name']} ({dist:.1f}mm)")
    log(f"[端部] {time.time()-t0:.1f}s，{len(rel['terminals'])} 条")

    # 第二遍：中部（同刚体去重；定位到端部的补记为端部）
    t0 = time.time()
    for i in range(n):
        if not has_shape[i]:
            continue
        li = spine_lens[i]
        for ci in range(len(devices)):
            r = assoc.get((i, ci))
            if not r or r[0] != "mid":
                continue
            _, s, q, dist = r
            if s <= END_TOL or s >= li - END_TOL:
                end = 0 if s < li / 2 else 1
                if not any(t["branch"] == i and t["end"] == end
                           and t["tag"] == dev_tags[ci]
                           for t in rel["terminals"]):
                    rel["terminals"].append(
                        {"branch": i, "end": end, "tag": dev_tags[ci],
                         "kind": "entity", "dist": dist})
                    term_xyz.append((dev_tags[ci], i, ends[i][end],
                                     dev_diag[ci]))
                    log(f"端部接触(补记): {branches[i]['key']}[{end}] <-> 实体 "
                        f"{dev_tags[ci]} {devices[ci]['name']}")
                continue
            dup = next((t for t in term_xyz
                        if t[0] == dev_tags[ci] and t[1] == i
                        and d3(q, t[2]) <= t[3]), None)
            if dup is not None:
                log(f"同体接触(跳过): {branches[i]['key']} 站位{s:.1f}mm <-> 实体 "
                    f"{dev_tags[ci]} (距已命名端部{d3(q, dup[2]):.1f}mm, 同一刚体)")
                continue
            rel["tie_stations"].append(
                {"branch": i, "s": s, "xyz": q, "tag": dev_tags[ci],
                 "kind": "entity", "dev": dist})
            log(f"中部固定: {branches[i]['key']} 站位{s:.1f}mm <-> 实体 "
                f"{dev_tags[ci]} {devices[ci]['name']} ({dist:.1f}mm)")
    log(f"[中部] {time.time()-t0:.1f}s，tie_stations {len(rel['tie_stations'])} 条")
    log(f"[第 2 步] 完成：{time.time()-t_start:.1f}s，"
        f"端-端 {len(rel['end_ends'])}，搭接 {len(rel['taps'])}，"
        f"端部 {len(rel['terminals'])}，中部 {len(rel['tie_stations'])}")

    out = {
        "taps": rel["taps"],
        "end_ends": [list(t) for t in rel["end_ends"]],
        "terminals": rel["terminals"],
        "tie_stations": rel["tie_stations"],
        "side_sides": [],
        "stats": {"mesh_tube_ok": n_tube_mok, "mesh_dev_ok": n_dev_mok,
                  "mesh_dev_fail": n_dev_mesh_fail,
                  "mesh_dev_time": round(t_mesh_dev, 1),
                  "prox_calls": n_prox, "numpy_calls": n_numpy,
                  "assoc_pairs": len(assoc),
                  "tap_projections": n_proj,
                  "tap_prescreen_skips": n_skip},
    }
    out_path = os.path.join(out_dir, "relations.json")
    dump_json(out_path, out)
    log(f"[第 2 步] 输出 {out_path}")
    # 返回 v7 兼容的 relations（end_ends 为 tuple，供第 3 步直接用）
    return rel
