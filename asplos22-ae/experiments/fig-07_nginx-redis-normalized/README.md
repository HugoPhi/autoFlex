# NGINX 与 Redis 标准化性能对比

<img align="right" src="fig-07_nginx-redis-normalized.svg" width="300" />

| 预计准备时间 | 预计运行时间 |
| ----------- | ----------- |
| 无需准备    | 0 小时 1 分钟 |

## 概述

Nginx 与 Redis 标准化性能对比。本图表以散点形式绘制由 [图 6](https://github.com/project-flexos/asplos22-ae/tree/main/experiments/fig-06_nginx-redis-perm) 生成的数据集。

没有 `make prepare` 或 `make run` 步骤，仅有 `make plot`。注意：此图表必须在图 6 之后运行。

## 论文式解说

此图通过散点图展示了 FlexOS 在两个关键应用上的性能隔离成本对比：

**坐标轴定义**：
- **X 轴**：Nginx 性能（标准化为无隔离基线 = 1.0）
- **Y 轴**：Redis 性能（标准化为无隔离基线 = 1.0）

**图例说明**：
- **蓝色点**：特定隔离配置的性能表现  
- **不同位置的点**：表示隔离机制差异（MPK、DSS、EPT 等）
- **曲线或聚集**：显示 Nginx 和 Redis 在隔离成本分布上的相似或差异性
- 越接近右上角 (1.0, 1.0)：隔离开销越小（理想情况）
- 越偏离右上角：隔离机制对应用的影响越大

**关键发现**：
- 大多数配置点聚集在对角线附近，表明 Nginx 和 Redis 受隔离影响程度相近
- 某些异常点（离群值）指示特定隔离机制对某个应用的不对称影响
- 这支持了论文关于"隔离成本可预测性"的论点
