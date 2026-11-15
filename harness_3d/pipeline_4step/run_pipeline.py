#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四步简化管线驱动：STEP -> 实体提取 -> 接触分析 -> 拓扑组装 -> HTML/Excel。

用法：
  python run_pipeline.py <xxx.stp> --out <工作目录> [--tol 6.0] [--no-wire]
                       [--reference floor|iph] [--from 3]

  --tol       端点邻近兜底容差（默认 6.0mm，用户定规）。
  --no-wire   跳过线框收集（地板经 v7 实跑验证无框分支，用此项省一次
              XCAF 转移；IP-Harness 有 10 条线框分支，不要跳过）。
  --reference 报表里附参考值对比：floor（用户口径 480/471/105/173/95/67/31）
              或 iph（v7 新规则 110/110/32/41/20/17/0）。
  --from N    从第 N 步开始重跑（N=3/4 时直接读工作目录里的
              entities.json / relations.json，不重读 STEP）。

输出（工作目录）：
  entities.json / relations.json / topology.json（中间文件，固定名，可重跑）
  <stem>_topology_YYYYMMDD_HHMMSS.json（最终拓扑，带时间戳）
  <stem>_3D_YYYYMMDD_HHMMSS.html（3D 可视化）
  <stem>_报表_YYYYMMDD_HHMMSS.xlsx（Excel 报表）
  run_YYYYMMDD_HHMMSS.log（运行日志，含每步耗时与内存峰值）

内存纪律：每步记录峰值内存；某步 OOM 就停下来报告卡在哪一步，
不要私自换方案绕过。

本快照 2026-11-14 由用户指令推送到 GitHub（Muse 测试，地板线束可用）。
本地开发仍只做本地提交，不要从本地仓库 git push（本地与远程历史已分叉）。
"""
import argparse
import gc
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import StageTimer, load_json, make_log, peak_rss_mb, timestamp
import stage1_extract
import stage2_contacts
import stage3_topology
import stage4_outputs

# 规则二新规（2026-11-15 用户定）：悬空端不再降级管子，悬空端在第 3 步
# 默认为连接器节点（见 stage3_topology），故此处不再有降级迭代循环。

REFERENCES = {
    "floor": {"管": 480, "节点": 471, "连接器": 105, "卡扣": 173,
              "分支点": 95, "接头": 67, "悬空": 31},
    "iph": {"管": 110, "节点": 110, "连接器": 32, "卡扣": 41,
            "分支点": 20, "接头": 17, "悬空": 0},
}


def main():
    ap = argparse.ArgumentParser(description="四步简化管线")
    ap.add_argument("step", help="STEP 文件路径")
    ap.add_argument("--out", required=True, help="工作目录（输出）")
    ap.add_argument("--tol", type=float, default=6.0, help="端点邻近兜底容差 mm")
    ap.add_argument("--no-wire", action="store_true", help="跳过线框收集")
    ap.add_argument("--reference", choices=["floor", "iph"], default=None,
                    help="报表参考值对比")
    ap.add_argument("--from", dest="from_stage", type=int, default=1,
                    choices=[1, 3, 4], help="从第 N 步开始重跑")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    ts = timestamp()
    stem = os.path.splitext(os.path.basename(args.step))[0]
    log_path = os.path.join(args.out, f"run_{ts}.log")
    log_file = open(log_path, "w", encoding="utf-8")
    base_log = make_log()

    def log(msg):
        base_log(msg)
        log_file.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        log_file.flush()

    log(f"四步管线启动：{args.step}")
    log(f"工作目录：{args.out}，tol={args.tol}，线框={'跳过' if args.no_wire else '收集'}")
    log(f"起始内存：{peak_rss_mb():.0f} MB")
    t_all = time.time()

    entities = relations = topology = None
    shapes = None

    if args.from_stage <= 1:
        with StageTimer("第 1 步 实体提取", log):
            entities, shapes = stage1_extract.extract(
                args.step, args.out, log, with_wires=not args.no_wire)
    else:
        entities = load_json(os.path.join(args.out, "entities.json"))
        log(f"[第 1 步] 跳过，读入 entities.json（分支 {len(entities['branches'])}，"
            f"设备 {len(entities['devices'])}）")

    if args.from_stage <= 2:
        # 第 2+3 步各跑一遍（2026-11-15 新规：规则二不再降级迭代，
        # 悬空端在第 3 步默认为连接器节点，见 stage3_topology）。
        with StageTimer("第 2 步 接触分析", log):
            relations = stage2_contacts.compute(
                entities, shapes, args.out, log)
        with StageTimer("第 3 步 拓扑组装", log):
            topology = stage3_topology.build(
                entities, relations, args.out, log, tol=args.tol)
        # 释放形状（第 4 步纯数据，不需要形状）
        del shapes
        gc.collect()
        log(f"[内存] 释放形状后：{peak_rss_mb():.0f} MB")
    else:
        relations = load_json(os.path.join(args.out, "relations.json"))
        log("[第 2 步] 跳过，读入 relations.json")

    if args.from_stage == 3:
        with StageTimer("第 3 步 拓扑组装", log):
            topology = stage3_topology.build(entities, relations, args.out,
                                             log, tol=args.tol)
    elif args.from_stage > 3:
        topology = load_json(os.path.join(args.out, "topology.json"))
        log("[第 3 步] 跳过，读入 topology.json")

    with StageTimer("第 4 步 HTML+Excel", log):
        html_path = os.path.join(args.out, f"{stem}_3D_{ts}.html")
        xlsx_path = os.path.join(args.out, f"{stem}_报表_{ts}.xlsx")
        stage4_outputs.build_html(topology, entities, html_path, log)
        ref = REFERENCES.get(args.reference) if args.reference else None
        stage4_outputs.build_excel(topology, entities, relations, xlsx_path,
                                   log, reference=ref)

    # 最终拓扑带时间戳的副本
    final_topo = os.path.join(args.out, f"{stem}_topology_{ts}.json")
    shutil.copy(os.path.join(args.out, "topology.json"), final_topo)
    log(f"[交付] {final_topo}")

    log(f"全部完成：{time.time()-t_all:.1f}s，峰值内存 {peak_rss_mb():.0f} MB")
    log(f"运行日志：{log_path}")
    log_file.close()


if __name__ == "__main__":
    main()
