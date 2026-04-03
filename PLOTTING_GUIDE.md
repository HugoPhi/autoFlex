# ASPLOS 22 再现工具指南

## 快速开始

### 1. 统一的图表生成脚本

本项目现在提供了一个统一的图表生成脚本 `generate_figure.py`，可从项目根目录直接调用任何实验的图表生成：

```bash
# 查看所有可用的图表
python3 generate_figure.py --list

# 生成单个图表 (以 search 假设验证为例)
python3 generate_figure.py search_hypothesis_validation

# 自定义输出分辨率
python3 generate_figure.py search_dag_poset --png-dpi 300

# 生成所有图表
python3 generate_figure.py --all
```

### 2. 配置文件

所有图表的配置都定义在 `plot-config.yaml` 中，包含：
- **实验元数据**：名称、输出目录、基础目录
- **数据配置**：输入文件、数据源说明
- **绘图脚本**：调用脚本、参数、输出规范

## 项目结构

### Search 实验 (`search/`)

**中文文档**: [README.md](search/README.md)

包含以下图表：
- `search_hypothesis_validation` - 假设验证与A2B散点图
- `search_dag_poset` - 配置分析DAG
- `search_nginx_path` - Nginx搜索路径
- `search_epsilon_stats` - Epsilon统计
- `search_dag_search` - DAG搜索轨迹

**输出结构**:
```
search/result/
├── svg/                    # 可扩展矢量图形
│   ├── fig08_plot.svg
│   ├── nginx_search_path.svg
│   └── hypothesis_a2b_scatter_*.svg
├── png/                    # PNG 栅格图形 (DPI 220)
│   ├── fig08_plot.png
│   ├── nginx_search_path.png
│   └── hypothesis_a2b_scatter_*.png
└── data/                   # CSV/DOT 中间文件
```

### ASPLOS 22 AE 实验

#### 图表 6 - Nginx & Redis 性能 
- **目录**: `asplos22-ae/experiments/fig-06_nginx-redis-perm`
- **ID**: `fig06_nginx_redis`
- **文档**: [README.md](asplos22-ae/experiments/fig-06_nginx-redis-perm/README.md)

#### 图表 7 - 标准化分布
- **目录**: `asplos22-ae/experiments/fig-07_nginx-redis-normalized`
- **ID**: `fig07_normalized`
- **文档**: [README.md](asplos22-ae/experiments/fig-07_nginx-redis-normalized/README.md)

#### 图表 8 - 配置偏序关系
- **目录**: `asplos22-ae/experiments/fig-08_config-poset`
- **ID**: `fig08_poset_config`
- **文档**: [README.md](asplos22-ae/experiments/fig-08_config-poset/README.md)

#### 图表 9 - iPerf 吞吐量
- **目录**: `asplos22-ae/experiments/fig-09_iperf-throughput`
- **ID**: `fig09_iperf`
- **文档**: [README.md](asplos22-ae/experiments/fig-09_iperf-throughput/README.md)

#### 图表 10 - SQLite 执行时间
- **目录**: `asplos22-ae/experiments/fig-10_sqlite-exec-time`
- **ID**: `fig10_sqlite`
- **文档**: [README.md](asplos22-ae/experiments/fig-10_sqlite-exec-time/README.md)

#### 图表 11 - 分配延迟
- **目录**: `asplos22-ae/experiments/fig-11_flexos-alloc-latency`
- **ID**: `fig11_alloc_latency`
- **文档**: [README.md](asplos22-ae/experiments/fig-11_flexos-alloc-latency/README.md)

#### 表 1 - 移植工作量
- **目录**: `asplos22-ae/experiments/tab-01_porting-effort`
- **ID**: `tab01_porting`
- **文档**: [README.md](asplos22-ae/experiments/tab-01_porting-effort/README.md)

## 文档标准

✅ **文档规范**:
- 所有实验文档使用中文
- 每个实验文件夹仅有一个中文 `README.md` 
- 包含论文式解说和关键指标
- 输出文件分为 `svg/` 和 `png/` 两个目录

## 输出文件检查方式

> 重要提示：所有图表验证都基于**文件名检查**，不读取实际图像内容

```bash
# 检查 search 图表
cd search && find result -type f \( -name "*.png" -o -name "*.svg" \)

# 检查所有图表
find . -path "./asplos22-ae/experiments/*/results/*" -type f \( -name "*.png" -o -name "*.svg" \)
```

## 示例工作流

### 重新生成单个图表（比如搜索路径图）
```bash
python3 generate_figure.py search_nginx_path --png-dpi 300
```

### 生成所有图表用于论文
```bash
python3 generate_figure.py --all --png-dpi 300
```

### 修改脚本参数后更新配置
编辑 `plot-config.yaml` 中对应实验的 `plot.args` 部分，然后重新调用脚本。

## 技术细节

### PNG 生成方法

**Search 实验**中的散点图通过 Matplotlib 直接生成 PNG（不是转换）：
- 修改文件: `search/validate_all_hypothesis.py`
- 新增函数: `render_a2b_scatter_png()`
- 参数: `--png-dpi` 可调整输出分辨率

### 工作目录处理

`generate_figure.py` 智能处理工作目录：
- Python 脚本在其所在目录执行（保证相对路径正确）
- Make 目标调用时改变到对应实验目录
- 所有输出路径相对于配置中的 `output_dir`

## 故障排查

### 问题: "找不到数据文件"
**解决**: ensure `python3 generate_figure.py search_hypothesis_validation` 在项目根目录运行

### 问题: PNG 分辨率不符合要求
**解决**: 使用 `--png-dpi` 参数调整：
```bash
python3 generate_figure.py search_dag_poset --png-dpi 300
```

### 问题: 图表已生成但文件列表不显示
**解决**: 等待 matplotlib/graphviz 完全写入文件
```bash
sync  # 刷新文件系统缓存
find result -name "*.png" | wc -l  # 重新检查
```
