# harness_topology_v7_final.py（名称映射版）

## 版本说明

基于 CODEX v7_final（2026-11-14 两处修改版：连接器端部间隙 5mm + 搭接包围盒预筛）+
名称映射集成。

解决的问题：v7_final 原来只用 XCAF occ/proto 当名字；扁平 STEP（如地板）的 occ
只有编号，拿不到 CATIA 实例真名；name_mapper_fast.py 有真名但没集成进 v7_final
（且全仓库无调用方，grep 已证）。

改动性质：纯增量（新增约 163 行，0 行删除），只改显示名 name_3d；tag、分类、
拓扑逻辑零影响。

## 环境要求（2026-11-14 已逐项核实 PyPI 轮子）

| 项目 | 要求 | 说明 |
|---|---|---|
| Python | 3.12 64 位 | OCP 8.0.1 要求 ≥3.11,<3.15；numpy 2.5.3 要求 ≥3.12；交集取 3.12。Python 3.8 没有轮子，不能用。 |
| cadquery-ocp | 8.0.1.0.0 | 有 cp312 win_amd64 / manylinux 轮子 |
| numpy | 2.5.3 | 要求 Python ≥3.12 |
| vtk | 9.6.2 | 由 cadquery-ocp 自动安装，有 cp312 win_amd64 轮子 |
| 内存 | IP-Harness/X1X：8GB 够 | 地板 732MB 文件 v7_final 会 OOM（Linux 7.7GB 两次 EXIT 137），需 16GB+ 或走四步管线 |

- Windows：Python 3.12 64 位官方安装包（python.org），安装时勾选 Add to PATH。
  32 位 Python 没有轮子。
- Linux：同版本要求；已验证环境 Python 3.12.3 + 上述版本。
- 代码本身跨平台：只依赖 numpy + OCP，无系统调用、无硬编码路径，路径全用
  os.path；JSON 输出用 ensure_ascii，无编码问题。

## 安装

```text
pip install -r requirements_win_20261114_204900.txt
```

或手动安装：

```text
pip install cadquery-ocp==8.0.1.0.0 numpy==2.5.3
```

## 运行

```text
python harness_topology_v7_final.py <STEP文件> 6.0
```

- 第一个参数：STEP 文件路径；第二个参数：端点邻近兜底容差 mm（6.0）。
- 输出：当前目录下 `topology.json`（节点/线段/走线/连接器；节点 name_3d 为
  BREP 真名，S 编号保留在 entity 字段追溯；connectors 列表新增 brep_name 字段）。
- 耗时参考（IP-Harness 126MB，Linux）：原版与映射版双版本共约 7 分钟（428 秒）；
  映射版比原版多一遍读文件（约 90 秒）。

## 实现逻辑（名称映射）

1. 第二遍读文件：STEPControl_Reader 打开 STEP，枚举 MANIFOLD_SOLID_BREP +
   BREP_WITH_VOIDS 实体，逐个 TransferOne 取形状 + ent.Name() 取真名。
2. 建指纹表：每个 BREP 形状算几何指纹（体积 + 局部坐标包围盒中心 + 包围盒尺寸，
   均 0.1 取整）→ [(真名, 实体序号)]。不依赖任何顺序/下标，名字与形状来自
   同一个 STEP 实体，不可能错位。
3. XCAF 侧配对：analyze() 提取完 solid 后，每个 solid 按同样口径算局部指纹查表；
   唯一配对记入 tag→真名表；多义（重复件同形同位）与未配对的不猜，保留原名。
4. 结果组装时替换显示名：build_topology_from_relations 返回后，节点/实体的
   name_3d 按表换真名；组合 tag（如 S7+S8）逐段解析，去实例后缀
   （BMS.1+BMS.2→BMS）后同名取公共件名，不同名用 " + " 连接；纯分支点
   name_3d 为空不动。
5. 为什么不用传输映射反查：OCP 8.0.1 的 STEPCAFControl_Reader 不暴露
   WS()/TransferReader（spike 已证）；为什么不用下标对位：TopExp 顺序与
   representation 顺序不一致（地板 804 vs 803 已证）。

## 测试验证（2026-11-14，本地）

| 数据集 | 拓扑对比 | 配对 | 改名 |
|---|---|---|---|
| X1X | 与原版完全一致（20 线段/15 节点/16 走线） | 22/22，0 多义 0 未配对 | 5 个（CP03–CP06 卡扣 + CONNECTOR\BMS） |
| IP-Harness | 与原版完全一致（116 线段/110 节点/65 走线，连接器 32/卡扣 41/分支点 20/接头 17） | 186/186，0 多义 0 未配对 | 73 个节点，76/76 连接器候选带 brep_name |

- 对比方法：原版与映射版各跑一遍，compare_v7.py 逐项比对（除 name_3d /
  brep_name 外 0 差异）。
- 未在 Windows 上实测：本机无 Windows 环境；轮子矩阵与代码跨平台性已核实，
  第一遍在 Windows 上跑算是验证。

## 文件清单

- `harness_topology_v7_final.py`：名称映射版代码
- `requirements_win_20261114_204900.txt`：依赖（已核实）
- `v7_namemap_diff_20261114_201600.txt`：相对原版的 diff（纯增量）
- `compare_v7.py`：原版/映射版 topology.json 对比脚本
- `out_x1x_orig/`、`out_x1x_namemap/`、`out_iph_orig/`、`out_iph_namemap/`：
  测试输出与运行日志
- `spike_xcaf_name.py`、`spike_xcaf_name2.py`（在 `../work_floor/`）：验证脚本
  （传输映射反查否决、几何指纹配对 186/186）

## 注意事项

- 地板文件（732MB）不要直接用 v7_final 跑，会 OOM；走四步管线
  （`~/workspace/harness_3d/pipeline_4step/`）。
- X1X 回归与用户 VBA 真值仍有已知差异（16 管/1 连接器 vs 10 管/7 连接器，
  死规则冲突，改动前已存在），与本次名称映射无关。
- 本目录代码为本地副本，未提交仓库；是否提交待定夺。
