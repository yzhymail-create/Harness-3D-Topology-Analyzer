# 四步简化管线（Harness 3D Topology Pipeline, 4-Step）

2026-11-14 建。目标：在本机 7.7GB 内存上跑通地板线束（732MB，804 solids），
出完整拓扑结果。原版 v7_final 在本机两次跑到约 14.5 分钟被 OOM 杀
（EXIT 137），根因是网格邻近（`USE_MESH_PROXIMITY`）把 804 个实体全三角化。

**本快照（2026-11-14，Muse 测试，地板线束可用）**：由用户指令推送到仓库。
IP-Harness 与 v7 新版（5mm 规则）基线逐项一致、零差异；地板 480 分支 /
531 线段 / 471 节点 / 322 走线完整跑通（1024 秒，峰值 4.2GB，无 OOM）。
本快照不含搭接优化指令（见“搭接优化指令”节）。

## 环境要求

| 项目 | 要求 | 说明 |
|---|---|---|
| Python | 3.12 64 位 | OCP 8.0.1 要求 ≥3.11,<3.15；numpy 2.5.3 要求 ≥3.12；交集取 3.12 |
| cadquery-ocp | 8.0.1.0.0 | 有 cp312 win_amd64 / manylinux 轮子 |
| numpy | 2.5.3 | 要求 Python ≥3.12 |
| vtk | 9.6.2 | 由 cadquery-ocp 自动安装 |
| 内存 | IP-Harness：2GB 够；地板：8GB 够（峰值 4.2GB） | v7_final 跑地板需 16GB+，本管线不用 |

安装：`pip install cadquery-ocp==8.0.1.0.0 numpy==2.5.3`

## 仓库布局

本管线在仓库里的位置是 `harness_3d/pipeline_4step/`，引用同一目录下的
`../harness_topology_v7_final.py`（仓库里的 v7_final，含 5mm 间隙修改）。
本地开发布局（管线在 `harness_3d/pipeline_4step/`，v7 在
`harness_3d/work_floor/`）同样支持，见 `v7geom.py`。

## 四步设计

| 步 | 做什么 | 输入 → 输出 | 关键点 |
|---|---|---|---|
| 1 | 实体提取 | STEP → entities.json | TransferOne 逐个传 BREP，（真名，形状）同源；管判定 + 中线反推；线框匹配 |
| 2 | 接触分析 | entities + 形状 → relations.json | v7 网格距离法（ShapeProximity + 三角片 numpy 距离），逐设备瞬态网格化、用完即清 |
| 3 | 拓扑组装 | entities + relations → topology.json | 纯数据，直接调 v7 的 build_topology |
| 4 | 输出 | topology → HTML + Excel | 3D 可视化（单文件）+ 报表 |

第 1、2 步在同一个进程里跑（第 2 步需要第 1 步传出的形状做精确距离；
传完即释放 STEP 模型省内存）。第 3、4 步纯数据，可独立重跑
（`--from 3` / `--from 4`）。

## 规则（用户已逐条核对，原样实现，一个不改）

- 管状实体：恰好 2 个平面端面（v7 `is_tube_solid` 死规则，不看长径比/面积）。
- 连接器端部间隙 ≤5mm（END_GAP_TOL，2026-11-14 新定）；中部接触：
  接触面到管中心线最短距离 ≤ 管半径+2mm；管—管端点连接 ≤6mm
  （端面圆心三维欧氏距离）；搭接：分支端头投影到主干中心线，
  距离 ≤ 主干半径+分支半径+2mm 且落点离主干两端均 >5mm。
- 分类：连接器 = 只碰 1 个管端且无中部站位；卡扣 = 有中部站位或碰多个管端。
- 节点命名：有实体用实体真名（CON/CLP），纯分支点 BN 无名。
- 名称只来自 STEP 本身；#S 只做括号追溯。

## 与 v7_final 的关系（语义零偏差的保证）

- 几何判定与拓扑组装**直接 import v7_final 的函数**（见 `v7geom.py`），
  不重写：`is_tube_solid` / `reverse_spine` / `solid_volume_bbox` /
  `chain_all` / `polyline_dist` / `spines_overlap` / `_poly_project` /
  `_split_polyline` / `_cluster_stations` / `build_topology_from_relations`
  （含内部 `_classify_entities` / `_alias_colocated`）。
  引用的 v7 文件被校验：读文件后先归一化行尾（CRLF/CR 一律转 LF）
  再算 MD5，接受两个已知版本——原版
  `3380e6a2968f6c386a9fb1939fb93434` 与 2026-11-14 修改版（5mm 间隙 +
  搭接预筛）`5380b2157753ac366fc5f961e26f666c`；两处修改不涉及此处
  引用的函数，故两版在此等价。文件被改动（MD5 不在列表里）则拒绝运行。
  查找顺序：先找仓库布局的 `../harness_topology_v7_final.py`，再找本地
  布局的 `../work_floor/harness_topology_v7_final.py`。
- 唯一不同是第 1 步的加载方式与第 2 步的网格生命周期：
  - 第 1 步：TransferOne 逐个传实体（名字与几何同源），不用 XCAF 遍历。
    已验证传出的形状就是世界坐标（与 XCAF 对比，体积差 0.00、中心距 0.00mm）。
    注意模型 rank ≠ 文件 #id，必须枚举模型找 BREP 的 rank。
  - 第 2 步：与 v7 同函数、同阈值、同逻辑（`_device_assoc` / `_prox_veto` /
    `_numpy_dist` 逐行一致，含 1.7mm 快速通道记 0.0、中部 q 取重采样
    脊柱最近点），无口径差异。唯一不同：v7 一次性网格化全部实体
    （地板 OOM 根源），本管线一次只网格化一个设备，算完立即
    `BRepTools.Clean` 释放，内存始终有界。
- 方法变更（2026-11-14，实测驱动）：任务书原定“候选对用
  `BRepExtrema_DistShapeShape` 算精确距离、不网格化”，但实测整实体
  单对可达 170 秒、面级单对约 50 秒，IP-Harness 150 个候选对需 2 小时
  以上；且 v7 源码注释写明 v7 自身早在 2026-10-03 就因同一原因弃用
  了 BRepExtrema（单对 ~9s → 0.9s）。故改回 v7 的网格距离法。
  详见 `stage2_contacts.py` 模块说明。
- v7 语义的继承（含“怪”行为，原样保留，不私自“修正”）：
  - 中线反推失败的管、被中线重叠去重的管，按 v7 第 6 步进连接器候选，
    会作为设备参与接触判定（可能产生幽灵卡扣节点；如发生将在报告里明说）。
  - `_alias_colocated` 共位实体合并（包围盒中心 ≤10mm）照搬。

## 适用范围与已知限制

- 针对扁平 STEP（单根装配）：管 proto 均取根装配名；线框只匹配同 proto。
  IP-Harness 与地板文件均为扁平结构，适用。
- S 号按 BREP 枚举顺序编（S0, S1, ...），与 v7 的 TopExp 顺序 S 号不同；
  对比时以真名 + 几何为准，不以 S 号对位。

## 804 vs 803 已查明（2026-11-14，实测验证）

地板 TopExp 数出 804 个 solid，具名 BREP 只有 803 个，差额不是
“多 1 个实体”，而是三项轧差：**803 + 3 − 2 = 804**。

- **+3：多 solid 复合 BREP**（`check_compounds.py` 实测）。
  INLINE-FLH 一个 BREP 内含 3 个 solid（主体 + 两个 0.6×0.6×1.0mm
  碎片）；C080 一个 BREP 内含 2 个 solid。TopExp 按 solid 计数，
  故比 BREP 数多 3。
- **−2：装配之外的孤儿 BREP**。前舱保险盒总成____（S691）与
  前舱保险盒总成________（S695）不在 FLOOR_AllCATPart 装配遍历里
  （v1 几何的 804 条中离它们中心最近的实体也在 33.7mm 外；
  XCAF 顶层形状检查 `check_assemblies.py`：唯一装配即 FLOOR，
  无第二装配）。但它们是 STEP 里真实存在的 BREP，世界坐标正确，
  各以 0.0mm 间隙接触一根管端，是两个合法连接器节点（CON72、CON62）。
  XCAF / v7 遍历装配的办法看不到它们，是 v7 的盲区，不是管线多算。
- 对拓扑的影响：无。两个碎片在连接器内部，不接触管子；C080 的
  第二 solid 属同一逻辑件，管线按整个 BREP 当一个设备处理，正确。

## 地板 +3 连接器已解释（2026-11-14）

管线连接器节点 108，用户参考值 105，差 3；悬空端 28 对 31，差 −3。
三项来源全部有机制解释（若用户方法为 XCAF 遍历 + 旧 2mm 规则，
则 108 − 3 = 105 恰好对上；用户方法至今未答，此为推论非定论）：

1. S691 前舱保险盒总成____（CON72）与 S695 前舱保险盒总成________
   （CON62）：孤儿 BREP，XCAF 遍历看不到（见上节），各 0.0mm 接触一管端。
2. S666 INLINE-FLH_（CON31）：间隙 2.04mm，只在新 5mm 规则下才算
   连接器；旧 2mm 规则下是悬空端。
3. 其余 105 个连接器节点中：102 个是分类为连接器的实体，
   6 个是度数 1 重分类（原卡扣，含两对共位合并实体 S18+S5、S762+S793
   各占 2 个节点），均按用户确认的节点命名规则产生。

## 搭接优化指令（2026-11-14 19:37 用户定规，待定夺，本快照不含）

用户指令：搭接投影只算“无着落”端点——端点已接触设备（连接器/
卡扣）或已与另一管端头端-端相连的，跳过投影；第 2 步顺序改为
先算设备接触再算搭接；四路节点照旧。该指令已在本地实现并验证，
但**不在本快照里**：本快照的 stage2 是跑地板时的 v7 忠实版，
与交付的地板结果完全一致。

**IP-Harness 验证（2026-11-14，本地）：该指令改动搭接语义，
不是纯性能优化**：taps 21→6（跳过 15 处，全部来自已解释端点）、
end_ends 148→117（搭接循环的近端兜底随跳过一并失效，丢 31 对）、
节点 110→113、走线 65→61；terminals 119、tie_stations 3、连接器 32、
线段 116、总长 8449.0 不变。地板是否按新语义重跑，等用户定夺；
定夺后如采用，将另行提交。

## 已交付结果与代码版本对应（2026-11-14）

- 地板交付（`work_floor/pipeline_out/`，时间戳 20261114_120054）：
  topology.json / 3D HTML / Excel 报表。计数：分支 480、线段 531、
  节点 471（连接器 108、卡扣 173、分支点 95、接头 67、悬空 28）、
  走线 322。代码：stage1+stage2 为提交 ee9d076 的 v7 忠实版，
  stage3/4 含真名翻译修复（本提交）。
- IP-Harness 交付（`work_unfold/pipeline_out/`，时间戳 20261114_120102）：
  与 v7 新版（5mm 规则）基线逐项一致，零差异（见验证基线节）。
- 真名翻译修复（2026-11-14）：stage3 组装后把节点 name_3d 由 tag
  翻成 CATIA 实例全名（含共位合并 tag 如 S18+S23，翻成两真名以 +
  连接）；S 编号保留在 entity / secondary.tag 字段追溯。地板 281 个
  有名节点全部翻成真名，0 个残留 S 编号；无名节点（BN/N）name_3d
  为空，符合用户规则。注意：第一次地板运行（11:34）启动时进程已
  导入旧 stage3，运行中途（11:50）的文件修改未生效，故重跑了
  第 3+4 步（`--from 3`）才拿到带真名的交付物。

## 用法

```bash
cd harness_3d/pipeline_4step
# IP-Harness 验证（有线框，不要 --no-wire）
python run_pipeline.py <IP-Harness.stp 路径> --out <工作目录> --reference iph
# 地板（无框分支，跳过线框收集省一次 XCAF 转移）
python run_pipeline.py <floor.stp 路径> --out <工作目录> --no-wire --reference floor
# 只重跑第 3、4 步（改组装/报表时用，不重读 STEP）
python run_pipeline.py <xxx.stp> --out <已有工作目录> --from 3
```

工作目录输出：`entities.json` / `relations.json` / `topology.json`
（中间文件，固定名，可重跑）、`<stem>_topology_YYYYMMDD_HHMMSS.json`、
`<stem>_3D_YYYYMMDD_HHMMSS.html`、`<stem>_报表_YYYYMMDD_HHMMSS.xlsx`、
`run_YYYYMMDD_HHMMSS.log`。

## 验证基线（IP-Harness，v7 新版 5mm 规则，tol=6.0）

管 110、连接器节点 32、卡扣节点 41、分叉 20、接头 17、悬空 0、
线段 116、走线 65、taps 21、end_ends 148、terminals 119、tie_stations 3。
（旧版 2mm 规则：连接器 31、卡扣 38、分叉 21、接头 19、悬空 1、terminals 115。）

## 交付纪律

- 本快照 2026-11-14 由用户指令推送到 GitHub（Muse 测试，地板线束可用）。
- 不要改 `harness_3d/harness_topology_v7_final.py` 的引用函数（v7geom 有 MD5 校验）。
- 文件名带 YYYYMMDD_HHMMSS 时间戳。
