#!/usr/bin/env python3
"""仅跑 stage1（实体提取），验证改名后的 STEP 文件可正常加载。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage1_extract

STEP = "/home/hatch/workspace/harness_3d/work_floor/floor_AllCATPart_20260128_V04_Test.stp"
OUT = "/home/hatch/workspace/harness_3d/pipeline_4step_rules/test_floor_renamed"

os.makedirs(OUT, exist_ok=True)
log_file = open(os.path.join(OUT, "stage1_renamed.log"), "w", encoding="utf-8")

def log(msg):
    print(msg, flush=True)
    log_file.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    log_file.flush()

t0 = time.time()
entities, shapes = stage1_extract.extract(STEP, OUT, log, with_wires=False)
log(f"[完成] 总耗时 {time.time()-t0:.1f}s")
log(f"[计数] {entities['counts']}")
log_file.close()
print("COUNTS:", entities["counts"])
