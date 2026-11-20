# -*- coding: utf-8 -*-
"""引用 CODEX v7_final 的几何/拓扑函数（只读 import，不复制、不修改）。

四步管线与 v7_final 共用同一套几何判定与拓扑组装语义，唯一不同的是：
  第 1 步用 TransferOne 逐个传实体取（真名，形状），不用 XCAF 遍历；
  第 2 步用坐标法 + BRepExtrema 精确距离做接触，不用网格邻近。
为保证语义零偏差，下列函数直接从 v7_final 源码 import，不在本管线里重写：
  几何：is_tube_solid / reverse_spine / solid_volume_bbox / face_centerline
  纯数学：_d3 / _poly_project / _spine_point_at / _cluster_stations /
          _split_polyline / chain_all / chain_curves / polyline_dist /
          spines_overlap / sample_edge / edge_length / xform_pts
  网格距离（第 2 步）：_mesh_shape_ok / _face_tris_world /
          _pt_tri_d2_closest / _resample_polyline（v7 2026-10-03 定稿的
          “网格三角 + numpy 点-三角 vs 脊柱”法；BRepExtrema 太慢已被
          v7 自身弃用，见 stage2 模块说明）
  拓扑组装：build_topology_from_relations（含内部 _classify_entities /
          _alias_colocated / _merge_entity_tag）
  常量：CONTACT_TOL / END_TOL / STATION_END_TOL / STATION_MERGE_TOL /
        WIRE_MIN_LEN / MESH_DEFL / PROX_TOL（阈值原样，不许改；
        端部间隙 5mm 见 stage2 的 END_GAP_TOL）

引用的 v7 文件（按顺序找，第一个存在的文件）：
  (1) 仓库布局：../harness_topology_v7_final.py（管线在
      harness_3d/pipeline_4step/，v7 在 harness_3d/，即仓库里的版本）；
  (2) 本地布局：../work_floor/harness_topology_v7_final.py
      （CODEX 原版 pristine 副本）。
校验：读文件后先归一化行尾（CRLF/CR 一律转 LF）再算 MD5，接受两个
已知版本——原版 3380e6a2968f6c386a9fb1939fb93434 与 2026-11-14 修改版
（5mm 间隙 + 搭接预筛）5380b2157753ac366fc5f961e26f666c；两处修改不
涉及此处引用的函数，故两版在此等价。行尾归一化后 Windows/Linux
检出结果一致，校验不受 git autocrlf 影响。
"""
import hashlib
import importlib.util
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V7_CANDIDATES = [
    os.path.join(_HERE, "harness_topology_v7_final.py"),
    os.path.join(_HERE, "work_floor", "harness_topology_v7_final.py"),
]
# 归一化 MD5（去 CR 后）：原版 + 2026-11-14 修改版
V7_MD5_ACCEPTED = {
    "3380e6a2968f6c386a9fb1939fb93434",  # 原版（pristine）
    "5380b2157753ac366fc5f961e26f666c",  # 2026-11-14 修改版（5mm+预筛）
}


def _load():
    for path in V7_CANDIDATES:
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            raw = f.read()
        norm = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        md5 = hashlib.md5(norm).hexdigest()
        if md5 not in V7_MD5_ACCEPTED:
            raise RuntimeError(
                f"v7_final 文件已被改动（{path}，归一化 MD5 {md5} 不在"
                "已知版本列表里），管线拒绝运行：几何语义来源必须唯一且可追溯。")
        spec = importlib.util.spec_from_file_location("v7_final_ref", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise RuntimeError(
        "找不到 v7_final 文件，已尝试："
        + "；".join(V7_CANDIDATES))


v7 = _load()

# --- 几何判定（第 1 步用） ---
is_tube_solid = v7.is_tube_solid
reverse_spine = v7.reverse_spine
solid_volume_bbox = v7.solid_volume_bbox
face_areas = v7.face_areas

# --- 纯数学（第 1/2 步用） ---
d3 = v7._d3
poly_project = v7._poly_project
spine_point_at = v7._spine_point_at
cluster_stations = v7._cluster_stations
split_polyline = v7._split_polyline
chain_all = v7.chain_all
chain_curves = v7.chain_curves
polyline_dist = v7.polyline_dist
spines_overlap = v7.spines_overlap
sample_edge = v7.sample_edge
edge_length = v7.edge_length
xform_pts = v7.xform_pts
count_topo = v7.count_topo

# --- 网格距离（第 2 步用；v7 原函数，2026-10-03 定稿） ---
mesh_shape_ok = v7._mesh_shape_ok
face_tris_world = v7._face_tris_world
pt_tri_d2_closest = v7._pt_tri_d2_closest
resample_polyline = v7._resample_polyline

# --- 拓扑组装（第 3 步用；内部含 _classify_entities / _alias_colocated） ---
build_topology_from_relations = v7.build_topology_from_relations
classify_entities = v7._classify_entities
alias_colocated = v7._alias_colocated

# --- 常量（原样引用，不许改） ---
CONTACT_TOL = v7.CONTACT_TOL          # 2.0：中部接触 / 搭接 / 管-管 2mm 端接
END_TOL = v7.END_TOL                  # 5.0：端部区域轴向窗口
STATION_END_TOL = v7.STATION_END_TOL  # 5.0：搭接投影近端改按端-端
STATION_MERGE_TOL = v7.STATION_MERGE_TOL  # 10.0：站位聚类
WIRE_MIN_LEN = v7.WIRE_MIN_LEN        # 20.0：可用线框最小总长
MESH_DEFL = v7.MESH_DEFL              # 0.15：网格化线性偏差 mm
PROX_TOL = v7.PROX_TOL                # 2.5：网格邻近判定距离 mm
