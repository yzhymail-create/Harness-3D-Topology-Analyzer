# -*- coding: utf-8 -*-
"""第 1 步：读 STEP，一次性导出实体清单、管子、连接器基础数据。

做法（2026-11-14 定）：
  1) STEPControl_Reader 读文件，枚举模型实体找全部 BREP 的 rank
     （注意：模型 rank ≠ 文件 #id，必须枚举；实测 IP-Harness 1.7M 实体枚举 3.2s）。
  2) 对每个 BREP 用 TransferOne(rank) 逐个传出形状，同时取真名
     （ent.Name()，OCCT 已解码 \\X2\\ 转义）。名字与几何同源，
     不做下标对位——这就是 2026-11-08 地板名字错位的根治。
     已验证：TransferOne 传出的形状就是世界坐标（与 XCAF 对比，
     体积差 0.00、中心距 0.00mm）。
  3) 每个形状：is_tube_solid 判定（恰好 2 平面端面，v7 死规则）；
     再过三条用户新规则（2026-11-14 22:50/22:55）：
     规则三命名交叉验证（明确非管名优先于几何，直接降级）→
     规则一端面近似圆 + 两端面等大（圆拟合残差 + 尺寸比 + 面积一致）→
     管子 reverse_spine 反推中心线；非管记体积/包围盒/面数。
     规则二（末端绝对判定）在驱动里拓扑后做，见 run_pipeline.py。
  4) 管去重：中线重叠 ≥60% 只保留最长（v7 同款 spines_overlap；
     被去重的管实体按 v7 语义仍进连接器候选，见 stage3 说明）。
  5) 线框（可选，--no-wire 可跳过）：XCAF 遍历找无面只有边的叶产品，
     成链后按 v7 规则匹配到管（同 proto、长度 0.5~1.6 倍、平均距离
     < max(2.0, 0.25×管径)），命中则用线框当中线。IP-Harness 有 10 条
     线框分支，地板经 v7 实跑验证为 0 条。
  6) 传完释放 reader/model（省内存），只保留形状 + 几何数据供第 2 步用。

输出 entities.json（第 2/3/4 步的输入）与进程内 shapes 字典。
内存纪律：本步峰值内存由驱动记录；严禁开网格（USE_MESH_PROXIMITY
不在本管线里出现）。
"""
import gc
import math
import os
import re
import time

import numpy as np

from common import (aabb_dist, aabb_from_points, bbox_c_from_box,
                    decode_step_name, dump_json)
from v7geom import v7
from v7geom import (chain_all, count_topo, edge_length, is_tube_solid,
                    polyline_dist, reverse_spine, sample_edge,
                    solid_volume_bbox, spines_overlap, xform_pts,
                    WIRE_MIN_LEN)

from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Plane
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SOLID
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Trsf
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp

# ---- 规则一阈值（2026-11-14 用户定规，阈值按 X1X/IP 实测数据定） ----
# X1X/IP 实测：全部 128 个恰好 2 平面端面的实体（真管与误判连接器）
# 端面圆拟合残差均为 0.0000~0.0001、尺寸比均为 1.000——规则一在现有
# 数据上不改判任何实体，是面向未来数据的守门条件。阈值取宽松值：
# 残差 <5%（实测最大值的 500 倍）、尺寸比 >0.90、面积一致 0.75~1.25
# （面积一致用于排除直线边拟出的巨大圆：真圆盘面积=πr²）。
RULE1_RES_MAX = 0.05
RULE1_RATIO_MIN = 0.90
RULE1_AREA_MIN = 0.75
RULE1_AREA_MAX = 1.25

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _tube_signal(name):
    """管子命名信号（只用于标记/确认，不用于强行改判为管）。
    多分支（地板 474/481 个多分支实体是管）/ Multi-branchable / HAR\\（X1X 10/10）。"""
    if "多分支" in name:
        return "多分支"
    if "Multi-branchable" in name:
        return "Multi-branchable"
    if name.upper().startswith("HAR\\"):
        return "HAR\\前缀"
    return None


def _non_tube_signal(name):
    """明确非管命名信号（规则三：明确命名优先于几何，直接降级）。
    管子信号优先：含多分支/Multi-branchable 的不判非管（地板 474 根管子
    名含中文“多分支”，若先判中文名会误杀全部——2026-11-14 实测教训）。
    其余：CONNECTOR\\/SUPPORT\\ 前缀（X1X）、C数字\\ / Tyton / CLIP（卡扣）、
    纯中文名（IP 23/23、地板 91/91 个纯中文名实体全是非管）。"""
    if _tube_signal(name):
        return None
    up = name.upper()
    if up.startswith("CONNECTOR\\"):
        return "CONNECTOR\\前缀"
    if up.startswith("SUPPORT\\"):
        return "SUPPORT\\前缀"
    if re.match(r"^C\d+\\", name):
        return "C数字\\前缀"
    if "tyton" in name.lower():
        return "Tyton"
    if "clip" in name.lower():
        return "CLIP"
    if CJK_RE.search(name):
        return "纯中文名"
    return None


def _face_boundary_points(face, deflection=0.05):
    """平面端面全部边界边的离散点（拼接）。
    注意：端面边界可能被拆成多条弧（如 C289 端面 0 是 4 条 BSpline
    四分之一弧，每条只离散出 5 个点）——只取最长单条边会因点数 <8
    误判拟合失败；拼接全部边后 C289 得 20 个点，拟合正常。
    若拼接后仍 <8 个点（如极小端面），用更细的离散重试一次。"""
    all_pts = []
    ex = TopExp_Explorer(face, TopAbs_EDGE)
    while ex.More():
        e = TopoDS.Edge(ex.Current())
        try:
            ad = BRepAdaptor_Curve(e)
            disc = GCPnts_QuasiUniformDeflection(ad, deflection)
            for i in range(1, disc.NbPoints() + 1):
                p = disc.Value(i)
                all_pts.append((p.X(), p.Y(), p.Z()))
        except Exception:
            pass
        ex.Next()
    if len(all_pts) >= 8:
        return np.array(all_pts)
    if deflection > 0.011:
        return _face_boundary_points(face, deflection=0.01)
    return None


def _fit_circle(pts):
    """拟合圆，返回 (半径, 相对残差 std/mean)；拟合失败返回 (None, None)。"""
    if pts is None or len(pts) < 8:
        return None, None
    c = v7.circle_center_3d(pts)
    dist = np.linalg.norm(pts - c, axis=1)
    r = float(np.mean(dist))
    res = float(np.std(dist) / max(r, 1e-9))
    return r, res


def _face_area(face):
    """平面面积（BRepGProp 面积分）。"""
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, p)
    return float(p.Mass())


def _check_endfaces_circular(tube):
    """规则一：两端面近似圆 + 两端面圆大小基本相等。
    返回 (通过?, 原因字符串)。拟合失败按不通过处理（无法验证是圆就不认是管）。"""
    caps = tube.get("cap_faces") or []
    if len(caps) != 2:
        return False, "端面不是 2 个"
    rs = []
    for f in caps:
        r, res = _fit_circle(_face_boundary_points(f))
        if r is None or res is None:
            return False, "端面边界圆拟合失败"
        if res > RULE1_RES_MAX:
            return False, f"端面圆拟合残差 {res:.3f} > {RULE1_RES_MAX}"
        area = _face_area(f)
        ratio_area = area / (math.pi * r * r) if r > 0 else 0.0
        if not (RULE1_AREA_MIN <= ratio_area <= RULE1_AREA_MAX):
            return False, f"端面面积/πr²={ratio_area:.2f} 超出范围"
        rs.append(r)
    ratio = min(rs) / max(rs) if max(rs) > 0 else 0.0
    if ratio < RULE1_RATIO_MIN:
        return False, f"两端面尺寸比 {ratio:.3f} < {RULE1_RATIO_MIN}"
    return True, ""

BREP_TYPES = ("StepShape_ManifoldSolidBrep", "StepShape_BrepWithVoids")
IDENTITY = gp_Trsf()

BREP_RE = re.compile(
    r"#(\d+)\s*=\s*(MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS)\s*\(\s*'((?:[^']|'')*)'")
REPR_RE = re.compile(
    r"ADVANCED_BREP_SHAPE_REPRESENTATION\s*\(\s*'([^']*)'")


def _ascii_str(h):
    """TCollection_HAsciiString -> str（OCCT 8.0.1 无 ToString，用 ToCString）。"""
    try:
        val = h.ToCString()
        return val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
    except Exception:
        return str(h)


def parse_step_text(step_path, log):
    """文本解析：BREP #id->名字（追溯用）与根装配名（proto）。"""
    id2name = {}
    root_name = None
    with open(step_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = BREP_RE.match(line)
            if m:
                id2name[int(m.group(1))] = decode_step_name(m.group(3))
                continue
            if root_name is None:
                m2 = REPR_RE.match(line)
                if m2:
                    root_name = decode_step_name(m2.group(1))
    log(f"[文本] BREP {len(id2name)} 个，根装配名={root_name}")
    return id2name, root_name


def _count_faces_planar(shape):
    """一次遍历数面：总面数 + 平面数（只判面类型，不算面积）。
    面类型判定与 v7 face_areas 一致：BRepAdaptor_Surface(f).GetType()
    == GeomAbs_Plane。供管判定预筛用（见 extract 内说明）。"""
    n = 0
    nplanar = 0
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        n += 1
        try:
            if (BRepAdaptor_Surface(TopoDS.Face(ex.Current())).GetType()
                    == GeomAbs_Plane):
                nplanar += 1
        except Exception:
            pass
        ex.Next()
    return n, nplanar


def _has_topo(shp, t):
    """形状是否含某类子拓扑（找到第一个即停，不用数完）。
    等价于 count_topo(shp, t) > 0，但对几千面的复杂实体快得多；
    只用于“有没有”的判断，不用于需要确切数目的地方。"""
    ex = TopExp_Explorer(shp, t)
    return ex.More()


def collect_wire_chains(step_path, root_name, log):
    """XCAF 遍历收集线框链（v7 analyze 第 3 步同款逻辑）。
    返回 (chains, xcaf_root_name)：chains 为 [{proto, pts, len, n_seg}]
    （链长 >= 20mm 的才保留）；xcaf_root_name 为 XCAF 根装配名，
    供调用方统一 proto 口径（文本解析的根名可能与 XCAF 根名不同）。
    注意：本函数只为找线框而做一次 XCAF 转移；形状本身不用，
    转移完立即释放 doc。"""
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.collections import Sequence_TDF_Label
    from OCP.TDF import TDF_Label

    S = v7.S
    t0 = time.time()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    if reader.ReadFile(step_path) is None:
        raise RuntimeError(f"无法读取 STEP 文件: {step_path}")
    reader.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    tops = Sequence_TDF_Label()
    st.GetShapes(tops)
    cands = []
    for i in range(1, tops.Length() + 1):
        lab = tops.Value(i)
        if S.IsAssembly_s(lab):
            cands.append(lab)
    if not cands:
        raise RuntimeError("STEP 中没有找到装配结构")
    if len(cands) == 1:
        # 只有一个顶层装配就是根，不用数它全部面数（原逻辑是按面数取最大，
        # 单候选时等价，省一次全装配面遍历）
        root_lab = cands[0]
    else:
        scored = [(count_topo(S.GetShape_s(lab), TopAbs_FACE), lab)
                  for lab in cands]
        scored.sort(key=lambda t: -t[0])
        root_lab = scored[0][1]

    from collections import defaultdict
    wire_by_proto = defaultdict(lambda: {"curves": [], "wire_len": 0.0})

    def walk(lab, parent_trsf, proto_ctx):
        ref = TDF_Label()
        is_comp = S.IsComponent_s(lab)
        if is_comp:
            if not S.GetReferredShape_s(lab, ref):
                ref = lab
        else:
            ref = lab
        ref_name = v7.label_name(ref)
        if v7.is_real_name(ref_name):
            proto_ctx = ref_name
        if S.IsAssembly_s(ref):
            cs = Sequence_TDF_Label()
            S.GetComponents_s(ref, cs)
            for i in range(1, cs.Length() + 1):
                c = cs.Value(i)
                loc = v7.comp_location(c)
                t = loc.Transformation() if not loc.IsIdentity() else gp_Trsf()
                g = gp_Trsf()
                g.Multiply(parent_trsf)
                g.Multiply(t)
                walk(c, g, proto_ctx)
        else:
            shp = S.GetShape_s(ref)
            # 线框叶产品：无面、有边。只判“有没有”，不用数完
            # （count_topo 全数对几千面实体是浪费；_has_topo 找到第一个即停）
            if not _has_topo(shp, TopAbs_FACE) and _has_topo(shp, TopAbs_EDGE):
                pd = wire_by_proto[proto_ctx]
                ex = TopExp_Explorer(shp, TopAbs_EDGE)
                while ex.More():
                    e = TopoDS.Edge(ex.Current())
                    length = edge_length(e)
                    pd["wire_len"] += length
                    pd["curves"].append(
                        {"len": length,
                         "pts": xform_pts(sample_edge(e), parent_trsf)})
                    ex.Next()

    walk(root_lab, gp_Trsf(), v7.label_name(root_lab))
    chains = []
    for proto, pd in wire_by_proto.items():
        if pd["wire_len"] < WIRE_MIN_LEN:
            continue
        for ch in chain_all(pd["curves"]):
            if ch["len"] >= WIRE_MIN_LEN:
                chains.append({"proto": proto, "pts": ch["pts"],
                               "len": ch["len"], "n_seg": ch["n_seg"]})
    # 注意：root_lab 属于 doc，必须在 del doc 之前取名字；删 doc 后再碰
    # 标签会解引用已释放内存导致段错误（2026-11-14 实测 exit=139）。
    xcaf_root = v7.label_name(root_lab)
    del doc, reader
    gc.collect()
    log(f"[线框] XCAF 遍历 {time.time()-t0:.1f}s，线框链 {len(chains)} 条")
    return chains, xcaf_root


def extract(step_path, out_dir, log, with_wires=True):
    """第 1 步主函数。返回 (entities, shapes)。
    entities：可 JSON 序列化的实体数据；shapes：{tag: TopoDS_Shape} 供第 2 步用。"""
    t_start = time.time()
    id2name, root_name = parse_step_text(step_path, log)
    if root_name is None:
        root_name = os.path.splitext(os.path.basename(step_path))[0]
        log(f"[文本] 未解析到根装配名，用文件名代替：{root_name}")

    # ---- 读 STEP，枚举 BREP ----
    t0 = time.time()
    reader = STEPControl_Reader()
    if reader.ReadFile(step_path) != IFSelect_RetDone:
        raise RuntimeError(f"无法读取 STEP 文件: {step_path}")
    log(f"[读文件] {time.time()-t0:.1f}s")
    model = reader.Model()
    n_model = model.NbEntities()
    t0 = time.time()
    brep_ranks = []  # (rank, type, name)
    for i in range(1, n_model + 1):
        ent = model.Entity(i)
        tn = ent.DynamicType().Name()
        if tn in BREP_TYPES:
            try:
                nm = _ascii_str(ent.Name())
            except Exception:
                nm = "?"
            brep_ranks.append((i, tn, nm))
    log(f"[枚举] 模型 {n_model} 个实体，BREP {len(brep_ranks)} 个，"
        f"{time.time()-t0:.1f}s")

    # ---- TransferOne 逐个传，提几何 ----
    tube_solids = []   # {tag, step_id, name, proto, vol, bbox, bbox_c, faces, tube, spine, spine_len}
    devices = []       # {tag, step_id, name, proto, vol, bbox, bbox_c, faces}
    shapes = {}        # tag -> TopoDS_Shape（第 2 步用精确距离）
    failures = []      # {tag, name, reason}
    spine_failed = []
    rule1_demoted = []  # 规则一降级：{tag, name, reason}
    rule3_demoted = []  # 规则三降级：{tag, name, signal}
    name_flagged = []   # 命名-几何不一致标记（几何非管但名字是管）：{tag, name, signal}
    name2step = {}
    for sid, nm in id2name.items():
        name2step.setdefault(nm, []).append(sid)
    t0 = time.time()
    for idx, (rank, typ, nm) in enumerate(brep_ranks):
        tag = f"S{idx}"
        step_ids = name2step.get(nm, [])
        step_id = step_ids[0] if len(step_ids) == 1 else None
        nb_before = reader.NbShapes()
        try:
            ok = reader.TransferOne(rank)
        except Exception as e:
            failures.append({"tag": tag, "name": nm, "reason": f"TransferOne 异常 {e}"})
            continue
        nb_after = reader.NbShapes()
        shape = None
        if ok and nb_after == nb_before + 1:
            try:
                shape = reader.Shape(nb_after)
            except Exception:
                shape = None
        if shape is None or shape.IsNull():
            # 注意：不用 OneShape() 兜底——多实体转移后 OneShape 会返回复合体，
            # 形状就张冠李戴了。取不到就记失败，不静默凑数。
            failures.append({"tag": tag, "name": nm,
                             "reason": f"TransferOne 返回 {ok}，"
                                       f"NbShapes {nb_before}->{nb_after}，形状为空"})
            continue
        try:
            vol, bc = solid_volume_bbox(shape, IDENTITY)
            nfaces, nplanar = _count_faces_planar(shape)
            bbox = (float(bc[0] - bc[3] / 2), float(bc[1] - bc[4] / 2),
                    float(bc[2] - bc[5] / 2), float(bc[0] + bc[3] / 2),
                    float(bc[1] + bc[4] / 2), float(bc[2] + bc[5] / 2))
            bbox_c = [float(x) for x in bc]
        except Exception as e:
            failures.append({"tag": tag, "name": nm, "reason": f"体积/包围盒失败 {e}"})
            continue
        shapes[tag] = shape
        base = {"tag": tag, "step_id": step_id, "name": nm, "proto": root_name,
                "vol": float(vol), "bbox": [float(x) for x in bbox],
                "bbox_c": bbox_c, "faces": int(nfaces)}
        # 管判定预筛（2026-11-14 优化，结果不变）：is_tube_solid 的判定是
        # “恰好 2 个平面端面且有侧壁面且体积 > 0”，但它内部 face_areas 要对
        # 每个面做面积分——几千面的连接器很贵（IP 实测 is_tube 合计 31.9s）。
        # 此处先只按面类型数平面（不做面积分）：平面数 ≠2、或无侧壁面、
        # 或体积 ≤0 时，is_tube_solid 必返回 None，直接判非管，不调原函数；
        # 只有 2 平面 + 有侧壁 + 体积 >0 才调原函数（此时它必返回管字典，
        # dia/length 与原来逐行一致；原函数内若抛异常仍按原来走 tube=None）。
        if vol > 0 and nplanar == 2 and nfaces - nplanar > 0:
            try:
                tube = is_tube_solid(shape)
            except Exception:
                tube = None
        else:
            tube = None
        if tube:
            # 规则三（命名交叉验证，2026-11-14 用户定）：明确非管名优先于几何。
            sig = _non_tube_signal(nm)
            if sig:
                rule3_demoted.append({"tag": tag, "name": nm, "signal": sig})
                devices.append(base)
                continue
            # 规则一（端面近似圆 + 两端面等大，2026-11-14 用户定）。
            ok1, reason1 = _check_endfaces_circular(tube)
            if not ok1:
                rule1_demoted.append({"tag": tag, "name": nm, "reason": reason1})
                devices.append(base)
                continue
        elif _tube_signal(nm):
            # 几何判非管但名字明确是管：只标记、不强行改判（用户定）。
            name_flagged.append({"tag": tag, "name": nm,
                                 "signal": _tube_signal(nm)})
        if tube:
            try:
                r = reverse_spine(tube, IDENTITY)
            except Exception:
                r = None
            if r:
                pts, slen = r
                base["tube"] = {"dia_cap": float(tube["dia"]),
                                "length_vol": float(tube["length"])}
                base["spine"] = [[float(x) for x in p] for p in pts]
                base["spine_len"] = float(slen)
                tube_solids.append(base)
            else:
                # 管但反推中线失败：按 v7 语义进连接器候选（见 stage3 说明）
                spine_failed.append({"tag": tag, "name": nm})
                devices.append(base)
        else:
            devices.append(base)
        if (idx + 1) % 100 == 0:
            log(f"[提取] {idx+1}/{len(brep_ranks)}，管 {len(tube_solids)}，"
                f"非管 {len(devices)}，{time.time()-t0:.0f}s")
    log(f"[提取] TransferOne+几何 {time.time()-t0:.1f}s：BREP {len(brep_ranks)}，"
        f"管实体 {len(tube_solids)}，非管 {len(devices)}，"
        f"传失败 {len(failures)}，中线失败 {len(spine_failed)}")
    for f in failures:
        log(f"[提取] 失败：{f['tag']} {f['name']}：{f['reason']}")
    for f in spine_failed:
        log(f"[提取] 中线反推失败（按 v7 进连接器候选）：{f['tag']} {f['name']}")
    for f in rule3_demoted:
        log(f"[规则三] 命名降级（{f['signal']}）：{f['tag']} {f['name']}")
    for f in rule1_demoted:
        log(f"[规则一] 端面降级（{f['reason']}）：{f['tag']} {f['name']}")
    for f in name_flagged:
        log(f"[规则三] 标记：几何非管但名字是管（{f['signal']}），不强行改判："
            f"{f['tag']} {f['name']}")
    log(f"[规则] 规则三命名降级 {len(rule3_demoted)} 个，规则一端面降级 "
        f"{len(rule1_demoted)} 个，命名-几何不一致标记 {len(name_flagged)} 个")

    # ---- 释放 STEP 模型（省内存；形状已独立） ----
    del reader, model
    gc.collect()

    # ---- 管去重：中线重叠 ≥60% 只保留最长（v7 同款；扁平文件单 proto 即全局） ----
    # 包围盒预筛（2026-11-14 优化，结果不变）：spines_overlap(tol=2.0) 判定
    # 两条中线是否大面积重叠——短中线采样点到长中线距离 <2.0mm 的占比 ≥60%。
    # 若两中线包围盒间隙 > 2.0mm，则每个采样点到长中线的距离都 > 2.0mm，
    # 占比必为 0 < 0.6，spines_overlap 必为 False，可安全跳过。
    # 实测地板：114960 对中 114271 对（99.4%）可跳过，只实算 689 对。
    spine_boxes = {}
    for it in tube_solids:
        _p = np.array(it["spine"])
        spine_boxes[it["tag"]] = (
            float(_p[:, 0].min()), float(_p[:, 1].min()),
            float(_p[:, 2].min()), float(_p[:, 0].max()),
            float(_p[:, 1].max()), float(_p[:, 2].max()))
    kept = []
    deduped = []
    n_overlap_calls = 0
    n_dedup_skip = 0
    for it in sorted(tube_solids, key=lambda x: -x["spine_len"]):
        pts = np.array(it["spine"])
        bi = spine_boxes[it["tag"]]
        dup = False
        for k in kept:
            if aabb_dist(bi, spine_boxes[k["tag"]]) > 2.0:
                n_dedup_skip += 1
                continue
            n_overlap_calls += 1
            if spines_overlap(pts, np.array(k["spine"])):
                dup = True
                break
        if dup:
            deduped.append({"tag": it["tag"], "name": it["name"]})
            # 被去重的管实体按 v7 语义进连接器候选（v7 analyze 第 6 步）
            devices.append({k: v for k, v in it.items()
                            if k in ("tag", "step_id", "name", "proto", "vol",
                                     "bbox", "bbox_c", "faces")})
            continue
        kept.append(it)
    log(f"[去重] 管 {len(tube_solids)} -> {len(kept)}（去重 {len(deduped)} 个；"
        f"重叠实算 {n_overlap_calls} 次，包围盒跳过 {n_dedup_skip} 次）")
    for d in deduped:
        log(f"[去重] 中线重叠去重（进连接器候选）：{d['tag']} {d['name']}")

    # ---- 线框匹配（v7 analyze 第 4 步同款） ----
    wire_chains = []
    if with_wires:
        wire_chains, xcaf_root = collect_wire_chains(step_path, root_name, log)
        # proto 必须与 v7 的 XCAF 口径一致：文本解析的根名（如 IP-Harness）
        # 与 XCAF 根装配名（如 IP_AllCATPart）可能不同；线框匹配按 proto
        # 分组，用错根名会导致匹配全失效、线框链被误当成纯线框分支
        # （2026-11-14 实测：143 分支 bug 的根因）。
        if xcaf_root and xcaf_root != root_name:
            log(f"[文本] 文本根名 {root_name} ≠ XCAF 根名 {xcaf_root}，"
                f"proto 统一用 XCAF 根名")
            root_name = xcaf_root
            for it in tube_solids + devices:
                it["proto"] = root_name
    branches = []
    for it in kept:
        pts_rev = np.array(it["spine"])
        l_rev = it["spine_len"]
        vol = it["vol"]
        dia_est = 2 * math.sqrt(vol / (math.pi * l_rev)) if l_rev > 0 else 0.0
        wire_hit = None
        if not with_wires:
            pass
        else:
            for wc in wire_chains:
                if wc["proto"] != it["proto"]:
                    continue
                if not (0.5 * l_rev <= wc["len"] <= 1.6 * l_rev):
                    continue
                d = polyline_dist(
                    wc["pts"][::max(1, len(wc["pts"]) // 60)], pts_rev)
                if np.mean(d) < max(2.0, 0.25 * dia_est):
                    wire_hit = wc
                    break
        if wire_hit:
            pts = [[float(x) for x in p] for p in wire_hit["pts"]]
            length = float(wire_hit["len"])
            src = "wireframe"
            n_seg = int(wire_hit["n_seg"])
        else:
            pts = it["spine"]
            length = l_rev
            src = "reversed"
            n_seg = 0
        dia = round(2 * math.sqrt(vol / (math.pi * length)), 2) if vol and length > 0 else None
        branches.append({
            "tag": it["tag"], "step_id": it["step_id"], "name": it["name"],
            "proto": it["proto"], "length": length, "vol": vol, "dia": dia,
            "p0": pts[0], "p1": pts[-1], "pts": pts, "src": src, "n_seg": n_seg,
            "bbox": it["bbox"], "bbox_c": it["bbox_c"], "has_shape": True,
            "faces": it.get("faces"),
        })
    # 纯线框分支（v7 第 5 步：无实体、只有长线框的产品 -> 分支；扁平文件不触发）。
    # v7 语义：每个无实体 proto 只取最长一条链成一个分支（chain_curves），
    # 不是每条链都成分支。
    protos_with_solids = {it["proto"] for it in kept} | {d["proto"] for d in devices}
    chains_by_proto = {}
    for wc in wire_chains:
        chains_by_proto.setdefault(wc["proto"], []).append(wc)
    for proto, wcs in chains_by_proto.items():
        if proto in protos_with_solids:
            continue
        wc = max(wcs, key=lambda c: c["len"])
        branches.append({
            "tag": f"WIRE-{wc['proto']}", "step_id": None,
            "name": wc["proto"], "proto": wc["proto"],
            "length": float(wc["len"]), "vol": None, "dia": None,
            "p0": [float(x) for x in wc["pts"][0]],
            "p1": [float(x) for x in wc["pts"][-1]],
            "pts": [[float(x) for x in p] for p in wc["pts"]],
            "src": "wireframe", "n_seg": int(wc["n_seg"]),
            "bbox": list(aabb_from_points([[float(x) for x in p] for p in wc["pts"]])),
            "bbox_c": bbox_c_from_box(
                aabb_from_points([[float(x) for x in p] for p in wc["pts"]])),
            "has_shape": False,
        })
    n_wire = sum(1 for b in branches if b["src"] == "wireframe")
    log(f"[分支] {len(branches)} 条（线框中线 {n_wire} 条，实体反推 {len(branches)-n_wire} 条）")

    # ---- 分支唯一键（v7 同款：同名分支用 #S 区分；本管线 key 用真名） ----
    from collections import Counter
    cnt = Counter(b["name"] for b in branches)
    for b in branches:
        b["key"] = b["name"] if cnt[b["name"]] == 1 else f"{b['name']}#{b['tag']}"
        b["occ"] = b["name"]  # 输出里的名称用真名（用户硬规则）

    entities = {
        "file": os.path.basename(step_path),
        "proto_root": root_name,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "counts": {
            "brep": len(brep_ranks),
            "transfer_fail": len(failures),
            "tube_solids": len(tube_solids),
            "spine_failed": len(spine_failed),
            "deduped": len(deduped),
            "branches": len(branches),
            "devices": len(devices),
            "wire_chains": len(wire_chains),
            "rule1_demoted": len(rule1_demoted),
            "rule3_demoted": len(rule3_demoted),
            "name_flagged": len(name_flagged),
        },
        "failures": failures,
        "spine_failed": spine_failed,
        "deduped": deduped,
        "rule1_demoted": rule1_demoted,
        "rule3_demoted": rule3_demoted,
        "name_flagged": name_flagged,
        "branches": branches,
        "devices": devices,
    }
    out_path = os.path.join(out_dir, "entities.json")
    dump_json(out_path, entities)
    log(f"[第 1 步] 完成：{time.time()-t_start:.1f}s，输出 {out_path}")
    return entities, shapes
