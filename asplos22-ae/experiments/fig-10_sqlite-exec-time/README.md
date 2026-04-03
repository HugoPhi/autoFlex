# SQLite 性能对比

<img align="right" src="fig-10_sqlite-exec-time.svg" width="300" />

| 预计准备时间 | 预计运行时间 |
| ----------- | ----------- |
| 0 小时 40 分 | 0 小时 9 分  |

## 概述

在 Unikraft、FlexOS、Linux、SeL4（配合 Genode 系统）和 CubicleOS 上使用 SQLite 执行 5000 个 INSERT 查询的耗时。隔离配置文件显示在 x 轴上（NONE：无隔离，MPK3：MPK 配合三个隔离间隔，EPT2：EPT 配合两个隔离间隔，PT2/3：页表隔离配合两个/三个隔离间隔）。

## 论文式解说与图例说明

### 图表结构
柱状分组图，展示跨越不同操作系统和隔离机制的 SQLite 性能对比

### Y 轴 - 执行时间
- **单位**：毫秒（ms）
- **测试工作量**：5000 条数据库 INSERT 操作
- **越低越好**：更短的执行时间表示更强的性能

### X 轴 - 系统与隔离配置

**操作系统分组**：
- **Unikraft NONE**：无隔离的纯 Unikraft 基线
- **Unikraft MPK3**：Unikraft + MPK 隔离（3 个隔离间隔）
- **Unikraft EPT2**：Unikraft + EPT 隔离（2 个隔离间隔）
- **Unikraft PT2/PT3**：Unikraft + 页表隔离
- **FlexOS (各种配置)**：展示 FlexOS 在不同隔离级别的性能
- **Linux (baseline)**：传统 Linux 系统参考基线
- **SeL4 + Genode**：高安全性微核架构
- **CubicleOS**：另一个隔离系统实现

**图例说明**：
- **不同颜色的柱子**：代表不同的系统/隔离配置
- **柱子高度**：表示 INSERT 操作的耗时
- **柱子之间的对比**：展示隔离开销和系统效率

### 关键发现指标
1. **Unikraft 基线**：通常是最快的（无 OS 开销）
2. **隔离开销**：观察从 NONE 到 MPK3/EPT/PT 配置的性能下降
3. **系统对比**：
   - Unikraft < Linux（清晰的字节码编译优势）
   - FlexOS 与 Unikraft 相当（灵活性 vs 性能）
   - SeL4/CubicleOS 通常明显较慢（强安全保证的代价）

### 性能阶梯
- **绿色区域（<5ms）**：优秀性能（Unikraft 基线）
- **黄色区域（5-15ms）**：良好性能（轻量级隔离）
- **红色区域（>15ms）**：显著开销（强隔离或完整 OS）

### 图表

图表包含一些硬编码的数据。如果你想为新运行生成图表，你将需要编辑绘图脚本。你想要调整的值是延迟图表中的标签（以及可能的它们的位置）。

## 故障排除

- **问题**：运行脚本在对 CubicleOS 进行基准测试时挂起，显示如下消息：
   ```
   cannot allocate memory for SQLITE
   ```

  **解决方案**：这是一个已知的 CubicleOS 错误。在这种情况下，只需使用 `CTRL-C` 终止当前运行；此运行的结果将不会在最终平均值中考虑。
