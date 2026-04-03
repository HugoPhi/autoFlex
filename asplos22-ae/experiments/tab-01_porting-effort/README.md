# 移植工作量

| 预计准备时间 | 预计运行时间    |
| ----------- | -------------- |
| 0 小时 2 分  | 0 小时 25 分（手动）|

## 数据表：FlexOS 的移植工作量

| 库/应用        | 补丁大小   | 共享变量 |
| -------------- | ---------- | ------- |
| lwip           | +542/-275  | 23      |
| uksched + ukschedcoop | +48/-8  | 5       |
| ramfs + vfscore | +148/-37   | 12      |
| uktime         | +10/-9     | 0       |
| redis          | +279/-90   | 16      |
| nginx          | +470/-85   | 36      |
| sqlite         | +199/-145  | 24      |
| iperf          | +15/-14    | 4       |

## 论文式解说与表格图例

### 表格结构与含义

本表展示了将各个库和应用从基线 Unikraft 移植到 FlexOS 所需的代码修改工作量：

### 列说明

**1. 库/应用名称**
- **核心库**（上半部分）：FlexOS 系统库（网络栈、调度器、文件系统、时间管理）
- **应用程序**（下半部分）：测试应用（redis、nginx、sqlite、iperf）

**2. 补丁大小 (格式: +新增/-删除)**
- **+数字**：为支持灵活隔离而新增的代码行数
  - 包括隔离边界标记、门声明、共享变量声明
  - 包括自动门替换工具生成的代码
  - 代表"隔离改造"的直接成本
- **-数字**：移除的代码行数（通常为冗余或过时代码）
- **净变化**：(+新增) + (-删除) = 总体代码增长

**3. 共享变量数**
- **含义**：该库/应用中需要在隔离间隔间共享的全局变量数量
- **重要性指标**：
  - 共享变量越多 → 隔离粒度越粗糙 → 安全边界越大
  - 例如：nginx 有 36 个共享变量（相对较多），暗示其内部隔离机会有限
  - 示例：iperf 仅 4 个共享变量（相对较少），隔离友好
- **应用指导**：选择隔离配置时应考虑共享变量数（尽量减少）

### 关键发现

1. **移植成本分析**
   - **最小成本**：iperf (+15/-14，仅 4 个共享变量)
   - **中等成本**：sqlite (+199/-145，24 个共享变量)
   - **较高成本**：nginx (+470/-85，36 个共享变量) - 单体应用架构，隔离点多
   
2. **库 vs 应用对比**
   - 系统库改造相对简单（特别是调度器和时间管理）
   - 网络栈 (lwip) 改造最复杂：需要处理复杂的网络状态共享
   
3. **工程实现难度**
   - **红色警告区域**：nginx、lwip（高改造成本 + 高共享变量数 = 隔离设计承载大）
   - **绿色推荐区域**：iperf、uktime、uksched（低成本且共享变量少 = 易于隔离）

4. **可维护性指标**
   - 补丁规模相对较小（< 600 行新增），说明 FlexOS 改造具有**局部性**
   - 不需要全系统重写，验证了**增量迁移路径**的可行性

### 技术含义

- **自动门替换**：补丁中包含 `gate` 声明的自动转换（编译工具支持）
- **共享变量白名单**：检查源代码中的 `whitelist` 声明数量（表示显式指定的安全边界）
- **非 FlexOS 补丁注意**：表中某些库包含与 Unikraft 主分支不同步的通用补丁（见下文）

### 测量工作流

这些测量是手动的，但相当简单。对于每个仓库或子系统，与最后一个 Unikraft 提交执行 `git diff`，并计算有意义的 +/- 行数。对于共享变量，搜索 `whitelist` 并计算出现次数。

注意某些库（mm、lwip、vfscore）包含不是 FlexOS 一部分但在 FlexOS 从 Unikraft 分支时尚未合并到 Unikraft 主分支的补丁。我们不想在 diff 中计算这些。

以下是应用的外部非 FlexOS 补丁列表：
- lwip：将 `socket.c` 移动到胶水代码 **[[链接]](https://github.com/project-flexos/asplos22-ae/tree/main/experiments/tab-01_porting-effort/lwip-patches)**
- vfscore：CPIO 支持 **[[链接]](https://github.com/unikraft/eurosys21-artifacts/tree/master/support/patches-unikraft-eurosys21/cpio-series)**
- mm：页表支持 **[[链接]](https://github.com/project-flexos/asplos22-ae/blob/main/experiments/fig-09_iperf-throughput/docker-data/unikraft-pagetable.patch)**

注意 iperf 应用是为本论文开发的；你可以使用 [应用](https://github.com/project-flexos/app-iperf) 和 [库](https://github.com/project-flexos/lib-iperf) 的 [`unikraft-baseline`](https://github.com/project-flexos/lib-iperf/tree/unikraft-baseline) 分支作为基线。

类似的情况也影响了 sqlite；你可以使用 [此未修改的应用](https://github.com/project-flexos/asplos22-ae/blob/main/experiments/fig-10_sqlite-exec-time/docker-data/main.c) 作为基线。

为了简化操作，我们提供了一个简单的 Docker 容器，它克隆所有相关仓库到 `/root/flexos`。你可以使用 `make prepare` 构建它，并使用 `make run` 进入 bash。当前目录在 `/out` 中挂载，以便于与主机共享结果。