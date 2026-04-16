# AutoFlex: 面向 FlexOS 的自动化迁移与安全配置搜索

本仓库聚焦 FlexOS 生态中的两类关键问题：

1. 自动化代码迁移：将应用迁移到 FlexOS gate 机制时，如何系统降低人工改写成本。
2. 安全配置搜索：在隔离强度与性能约束之间，如何高效探索大规模配置空间并输出可行前沿。

工程上，自动迁移主线位于 [autoGen](autoGen)，安全配置搜索主线位于 [search](search)。

## 研究背景与目标

FlexOS 通过可组合的隔离机制打开了安全/性能联合优化空间，但也带来两类现实门槛：

1. 迁移门槛：旧代码向 gate 调用范式迁移时，人工改写成本高且容易遗漏。
2. 搜索门槛：配置空间随隔离特征组合指数增长，直接穷举成本极高。

本项目的目标是提供一套可复现、可度量的工程路径：

1. 用规则驱动迁移流水线提升 gate 覆盖率并量化人工工作量下降。
2. 用偏序图与假设驱动搜索降低查询成本，在性能阈值下逼近最强隔离配置。

## 核心创新点

### 1. 规则驱动的自动迁移流水线（autoGen）

基于 [autoGen/flexos_porthelper_py.py](autoGen/flexos_porthelper_py.py) 与规则文档 [autoGen/AUTO_MIGRATION_RULES.md](autoGen/AUTO_MIGRATION_RULES.md)，迁移流程由三层组成：

1. 函数到库映射：结合 cscope 与显式 fallback 映射 gate 目标库。
2. Coccinelle 基础替换：覆盖赋值调用与纯调用两类常见模式。
3. 语句级后处理重写：补齐 if/return/cast 等复杂语法形态。

该设计把“可自动化”的迁移模式显式化，并允许对规则命中与漏改进行版本化统计。

### 2. 偏序建模与期望剪枝搜索（search）

基于 [search/dag_poset_search.py](search/dag_poset_search.py) 与实验说明 [search/EXPERIMENT_BASELINE_GUIDE.md](search/EXPERIMENT_BASELINE_GUIDE.md)，配置空间被建模为 DAG 偏序图：

1. 节点表示一个隔离配置。
2. 有向边表示更强隔离关系。
3. 查询后按祖先/后代闭包进行批量剪枝。

balanced 策略以期望剪枝量为优化目标，核心思想是最大化：

$$
E_i = p\cdot a_i + (1-p)\cdot d_i
$$

其中 $a_i$ 为候选集中祖先规模，$d_i$ 为候选集中后代规模，$p$ 为在线估计的可行概率。

### 3. 统一绘图编排（根目录单入口）

本仓库所有绘图统一由根目录脚本 [generate_figure.py](generate_figure.py) 调度，配置在 [plot-config.yaml](plot-config.yaml)。

说明：历史 Makefile 绘图路径已淘汰，不作为推荐流程。

## 仓库结构

- [autoGen](autoGen): 自动迁移规则、评测脚本、评测结果与工作量分析。
- [search](search): 配置偏序建模、搜索策略、baseline 评估与可视化脚本。
- [asplos22-ae](asplos22-ae): 原始实验准备与运行框架（用于采样与实验执行）。
- [figures](figures): 统一归档的图表输出（svg/png）。
- [PLOTTING_GUIDE.md](PLOTTING_GUIDE.md): 统一绘图流程与图表说明。

## Web 自动化平台（启动、使用、日志与产物）

本仓库提供本地 Web 平台入口：
- 目录： [website](website)
- 作用：将 Stage A（自动迁移）与 Stage B（配置搜索）变为可视化作业流程

### 1. 启动方式

在仓库根目录执行：

```bash
fuser -k 8080/tcp
cd website
/home/tibless/Desktop/auto_flex/.venv/bin/python app.py
```

浏览器访问：

```text
http://127.0.0.1:8080/
```

### 2. 页面功能概览

1. 左侧
- Stage A 提交区：上传原始源码 zip，执行自动迁移。
- Stage B 提交区：上传迁移后源码 zip，选择 test bench 与搜索参数。
- 产物下载区：下载当前选中作业的产物文件。

2. 右侧
- Job Console：查看作业状态，支持查看、单删、批量删除。
- 作业详情：查看 status、return_code、command、params。
- 实时日志：增量日志流（支持 ANSI 颜色显示）。

3. 顶栏
- 刷新按钮。
- 帮助按钮（?）：内置详细使用文档（Markdown 渲染）。

### 3. Stage A 使用流程

1. 上传原始源码压缩包（source_zip）。
2. 点击“开始迁移”。
3. 在 Job Console 选择该作业，查看详情与日志。
4. 成功后从产物区下载 migrated_source.zip（用于 Stage B 输入）。

### 4. Stage B 使用流程

1. 上传 Stage A 产物 migrated_source.zip。
2. 选择 test bench（如 fig06-nginx / fig06-redis）。
3. 根据需要调整参数：baseline_threshold / num_compartments / host_cores / wayfinder_cores / test_iterations / top_k。
4. 点击“开始搜索”。
5. 在日志中观察 build/test/search 过程；完成后下载产物。

### 5. 日志与字段解释

1. 状态
- queued：已入队
- running：执行中
- succeeded：成功
- failed：失败

2. 作业详情核心字段
- command：真实执行命令
- params：本次参数快照
- return_code：脚本返回码（0 通常为成功）
- error：后端捕获异常摘要

3. 日志阅读建议
- 优先看第一条硬错误，不要先看末尾级联错误。
- 结合 command + params + log 一起定位问题。

### 6. 产物说明（重点）

以下是 Stage B（nginx）常见产物：

1. benchmark_nginx.csv
- 基准数据，供后续统计/绘图。

2. build_and_test.log
- 构建与测试详细日志。

3. performance_report.json
- 机器可读结果摘要。

4. performance_report.md
- 人类可读报告文本。

5. search_progress.csv
- 搜索过程轨迹数据。

6. top_images.tar.gz
- 镜像与相关文件打包归档。

7. top_images/task-single/build.log
- 单配置构建日志。

8. top_images/task-single/config
- 运行配置快照。

9. top_images/task-single/kraft.yaml
- Kraftrun/构建关键配置文件。

10. top_images/task-single/nginx_kvm-x86_64(.dbg)
- 产出的二进制与调试版本。

### 7. 网站重启与维护

1. 重启服务

```bash
fuser -k 8080/tcp
cd /home/tibless/Desktop/auto_flex/website
/home/tibless/Desktop/auto_flex/.venv/bin/python app.py
```

2. 重启后行为
- 已完成作业会恢复显示。
- 中断中的 running 作业会被标记为 failed（防止僵尸状态）。

3. 清理作业
- 支持单个清除。
- 支持全选与批量删除。

### 8. 论文 nginx demo 详细流程（推荐）

以下流程用于论文系统展示，且与你当前仓库流程对齐。

1. 启动 Web 服务。
2. Stage A 上传 nginx 源码 zip，提交作业。
3. 观察 Stage A 日志与详情，等待 succeeded。
4. 下载 Stage A 产物 migrated_source.zip。
5. Stage B 上传 migrated_source.zip，选择 test_bench=fig06-nginx。
6. 保持默认参数或按实验设定调整阈值、轮次和 cores。
7. 提交 Stage B 作业，观察实时日志中的 build/test/search。
8. 等待 succeeded 后下载关键产物：
- benchmark_nginx.csv
- performance_report.json
- performance_report.md
- search_progress.csv
- top_images.tar.gz
9. 将 CSV/报告用于图表生成与论文结果说明。
10. 将 command + params + log + artifacts 一并归档，确保后续可复验。

### 9. 常见问题（Web 相关）

1. 页面打开但作业不更新
- 点刷新；确认服务是否运行在 8080。

2. Stage B 失败
- 先看 build_and_test.log 第一硬错误；再核对 command 与 params。

3. 产物为空
- 先确认选中的 job_id；failed 作业可能无完整产物。

## 实验设计

### A. 自动迁移实验设计

数据与评测来自 [autoGen/eval_results/flexos_py_plus_v11](autoGen/eval_results/flexos_py_plus_v11)。

1. 覆盖率口径（gate 对齐）
- expected_calls: manual 中目标 gate 调用数。
- matched_calls: auto 与 manual 对齐命中数。
- unresolved_calls: 未对齐调用数。

2. 人工工作量口径（语义差异）
- total_manual_changed_lines
- remaining_changed_lines
- reduction_pct

3. 应用范围
- nginx, redis, lwip, newlib, iperf

### B. 安全配置搜索实验设计

实验协议与指标定义见 [search/EXPERIMENT_BASELINE_GUIDE.md](search/EXPERIMENT_BASELINE_GUIDE.md)。

1. 数据集
- nginx:REQ
- redis:GET
- redis:SET

2. 对比方法
- exhaustive
- random
- balanced（ours）

3. 指标
- query_ratio: 查询比例（query_count / |V|）
- first_result_query_ratio: 首次命中最优前沿的归一化查询位置

4. 假设验证
- 单调性假设：隔离增强通常导致性能下降。
- 异常配置对统计见 [figures/search/hypothesis_violate_report.md](figures/search/hypothesis_violate_report.md) 与 [figures/search/hypothesis_all_violations.csv](figures/search/hypothesis_all_violations.csv)。

## 关键实验结果

### 1. 自动迁移结果

来自 [autoGen/eval_results/flexos_py_plus_v11/summary.json](autoGen/eval_results/flexos_py_plus_v11/summary.json)：

- expected_calls = 81
- matched_calls = 81
- unresolved_calls = 0

来自 [autoGen/eval_results/flexos_py_plus_v11/manual_effort_diff_stats.csv](autoGen/eval_results/flexos_py_plus_v11/manual_effort_diff_stats.csv)：

- nginx: reduction_pct = 54.80%
- redis: reduction_pct = 74.86%
- newlib: reduction_pct = 62.17%
- lwip: reduction_pct = 30.91%
- iperf: reduction_pct = 100.00%

图示（自动迁移后人工工作量下降）：

![auto migration effort reduction](figures/autogen/fig-auto-manual-effort-reduction/fig-auto-manual-effort-reduction.svg)

### 2. 配置搜索结果

核心图表如下：

1. 配置偏序关系图（图 8a）

![config poset](figures/search/svg/fig08_plot.svg)

2. 假设验证散点（图 8b 示例）

![hypothesis validation nginx req](figures/search/svg/hypothesis_a2b_scatter_nginx_req.svg)

3. Nginx 搜索路径（图 8c）

![nginx search path](figures/search/svg/nginx_search_path.svg)

4. baseline 综合对比（查询比例与首次命中）

![baseline query ratio](figures/search/svg/search_baseline_query_ratio_top5_all.svg)

![baseline first result](figures/search/svg/search_baseline_first_result_top5_all.svg)

### 3. ASPLOS 关键性能图入口

本仓库已整理对应输出目录，示例：

- figure06: [figures/figure06](figures/figure06)
- figure07: [figures/figure07](figures/figure07)
- figure09: [figures/figure09](figures/figure09)

示例图：

![figure07 normalized](figures/figure07/fig-07_nginx-redis-normalized/fig-07_nginx-redis-normalized.svg)

## 复现指南

### 0. 三条工作流的运行方式差异（重要）

1. asplos22-ae
- 通过 Makefile 执行实验准备与采样（dependencies/prepare/run）。
- 本仓库不再使用 Makefile 作为绘图入口。

2. search
- 主要入口是脚本 `search/run_debug_generate.sh`。
- 该脚本是“数据处理 + 搜索评估 + 绘图”一体化流水线，会直接产出 CSV、DOT、SVG、PNG。

3. autoGen
- 运行分两段：先评测，再绘图。
- 评测入口：`autoGen/evaluate_flexos_porthelper_py.py`（生成 projects/*/{raw,manual,auto} 与 summary）。
- 绘图入口：`autoGen/plot_manual_effort_reduction.py`（读取 eval 结果目录后画图）。

4. 统一调度
- 根目录 `generate_figure.py` 负责统一调度各目标。
- 其中 `--target search` 会触发 search 的全流水线；`--target auto_migration_effort` 默认只基于既有 eval 目录绘图。

### 1. asplos22-ae：实验准备与采样（Makefile）

先按 [asplos22-ae/README.md](asplos22-ae/README.md) 准备环境，并在 shell 中设置 token：

```bash
export KRAFT_TOKEN="<your_github_token>"
```

在仓库根目录执行（全量）：

```bash
cd asplos22-ae
make dependencies
make prepare
make run
```

按图号执行（示例）：

```bash
cd asplos22-ae
make prepare-fig-06
make run-fig-06
make prepare-fig-09
make run-fig-09
```

说明：上述流程只负责依赖准备与实验采样，不作为本仓库推荐绘图入口。

### 2. search：一体化搜索实验与绘图（脚本）

在仓库根目录执行（推荐，和当前项目脚本一致）：

```bash
PYTHON_BIN="$PWD/.venv/bin/python" \
PNG_DPI=300 \
OUTPUT_DIR="$PWD/figures/search" \
bash search/run_debug_generate.sh
```

该命令会一次性生成：

1. 偏序图、搜索轨迹、假设验证图（SVG/PNG）。
2. baseline 评估 CSV（detail/agg/focus/top5）及对应对比图。

### 3. autoGen：先评测，再统计，再绘图（两段式）

在仓库根目录执行（评测 + 规则统计 + 工作量图）：

```bash
$PWD/.venv/bin/python autoGen/evaluate_flexos_porthelper_py.py \
	--dataset-root autoGen/dataset \
	--out-dir autoGen/eval_results/flexos_py_plus_v11

$PWD/.venv/bin/python autoGen/compute_rule_match_stats.py \
	--eval-dir autoGen/eval_results/flexos_py_plus_v11

$PWD/.venv/bin/python autoGen/plot_manual_effort_reduction.py \
	--eval-dir $PWD/autoGen/eval_results/flexos_py_plus_v11 \
	--formats svg png \
	--output-root figures/autogen
```

单文件迁移与漏洞扫描（可选）：

```bash
bash autoGen/flexos_migrate_vuln_pipeline.sh \
	--target-file autoGen/third_party/unikraft/lib/uktime/time.c
```

### 4. 根目录统一调度绘图（唯一推荐出图入口）

在仓库根目录执行：

```bash
python3 generate_figure.py --list
python3 generate_figure.py --all
```

按目标分组绘图示例：

```bash
python3 generate_figure.py --target search
python3 generate_figure.py --target auto_migration_effort
python3 generate_figure.py --target figure06 --target figure07 --target figure09
```

如需更高分辨率 PNG，可在配置中调整 dpi，详见 [PLOTTING_GUIDE.md](PLOTTING_GUIDE.md)。

## 结果解读与边界

1. 覆盖完成不等于零人工审阅
- autoGen 的 unresolved_calls=0 表示 gate 覆盖对齐完成。
- 但工程语义层仍可能存在结构、类型、宏风格差异，见 [autoGen/AUTO_POST_MANUAL_WORK.md](autoGen/AUTO_POST_MANUAL_WORK.md)。

2. 单调性并非绝对成立
- 搜索实验中存在少量违反单调性假设的异常点，这些点是分析隔离机制非线性成本的重要证据。

3. 结果对硬件敏感
- 部分性能结论依赖 MPK、核隔离与低噪声运行条件，详见 [asplos22-ae/README.md](asplos22-ae/README.md)。

## 参考与致谢

本仓库建立在 FlexOS ASPLOS'22 工件与方法基础之上，建议同时参考：

- [asplos22-ae/README.md](asplos22-ae/README.md)
- FlexOS 论文（ASPLOS 2022）

如果你基于本仓库发布结果，建议在论文中同时说明：

1. 使用的评测结果目录版本（例如 flexos_py_plus_v11）。
2. 使用的绘图入口与配置版本（generate_figure.py 与 plot-config.yaml）。
3. 是否采用统一复现流程（先 run，再由根目录脚本出图）。
