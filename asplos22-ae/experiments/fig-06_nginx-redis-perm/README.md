# NGINX 和 Redis 在不同隔离分割方案下的性能

<img src="./fig-06_nginx-redis-perm-redis.svg" />
<img src="./fig-06_nginx-redis-perm-nginx.svg" />

| 预计准备时间 | 预计运行时间 |
| ----------- | ----------- |
| 4-10 小时    | 2-3 小时     |

## 概述

Redis（上方）和 Nginx（下方）在不同配置下的性能表现。左侧显示了各个组件。每个组件的软件加固可以启用 [●] 或禁用 [○]。白色/蓝色/红色表示组件所在的隔离间隔。隔离通过 MPK 和 DSS 实现。

本实验使用了通用操作系统性能评估平台 [Wayfinder](https://github.com/lancs-net/wayfinder)。Wayfinder 是全自动化的，确保了结果的准确性和可重复性。它用于生成论文图 6 中所示的库隔离分割的所有排列组合。

## 论文式解说与图例说明

### 图表结构
- **左侧**：显示所有 FlexOS 库组件（libc、OpenSSL、libpthread 等）
- **中间**：各组件的隔离/加固配置的所有排列组合（96 种配置）
- **右侧**：性能指标柱状图

### 视觉编码图例
- **[●] 符号**：该库已启用软件加固（代码检查、边界检查等）
- **[○] 符号**：该库未加固（基线性能）
- **白色区域**：库所在的主保护隔离间隔
- **蓝色区域**：库所在的 MPK（内存保护密钥）隔离间隔
- **红色区域**：库所在的 DSS（非常细粒度的隔离）隔离间隔
- **混合颜色**：组件在不同隔离机制间的分布

### Y 轴（性能）
- **单位**：吞吐量（操作/秒）或延迟（毫秒），取决于应用
- **向上**：性能更好
- **向下**：隔离开销更大

### 主要发现通道
1. **无隔离基线**：最左侧的柱子（全 ○），代表最佳性能
2. **最小隔离成本**：寻找与无隔离基线最接近的配置
3. **隔离与性能权衡**：观察不同隔离级别（MPK vs DSS）的性能差异
4. **加固成本**（[●] vs [○]）：通常显示 5-15% 的性能开销

## Makefile 命令总结

| 命令                                 | 说明                                                                          |
| ----------------------------------- | ---------------------------------------------------------------------------- |
| `make prepare-wayfinder-app-nginx`  | 为 NGINX 生成 Wayfinder 任务文件。                                              |
| `make prepare-wayfinder-app-redis`  | 为 Redis 生成 Wayfinder 任务文件。                                              |
| `make prepare-templates`            | 为 NGINX 和 Redis 创建所有任务文件。                                            |
| `make prepare`                      | 运行所有准备步骤，包括为 Wayfinder 生成任务文件和安装实验所需的额外工具。       |
| `make run-wayfinder-app-nginx`      | 生成 NGINX 的所有排列组合。                                                    |
| `make run-wayfinder-app-redis`      | 生成 Redis 的所有排列组合。                                                    |
| `make run-wayfinder`                | 运行 NGINX 和 Redis 的 Wayfinder 排列组合构建。                                |
| `make test-app-nginx`               | 对所有 NGINX 排列组合运行 [测试脚本](./apps/nginx/test.sh)。                   |
| `make test-app-redis`               | 对所有 Redis 排列组合运行 [测试脚本](./apps/redis/test.sh)。                   |
| `make run`                          | 运行 NGINX 和 Redis 的两个测试。                                              |
| `make plot-app-nginx`               | 仅绘制 NGINX 图表。                                                            |
| `make plot-app-redis`               | 仅绘制 Redis 图表。                                                            |
| `make plot`                         | 绘制两个图表。                                                                |

## 运行和自定义

本图表的目标已映射为 FlexOS 项目在 ASPLOS'22 论文再现（AE）仓库的全局 `Makefile` 系统的一部分。在高层次上，你可以运行：

```bash
make prepare-fig-06
make run-fig-06
make plot-fig-06
```

然后实验就会运行。但更常见的情况是，你可能需要根据自己的需求调整实验。

> 为了获得更好的整体实验执行时间（即使实验耗时更少），请调整 `Makefile` 中的 `HOST_CORES` 变量。提供更多的核心会导致更多 Unikraft 排列组合构建的并行进行。

有许多内部目标可以独立于高级 `Makefile` ASPLOS'22 AE 仓库运行。要开始，请克隆此仓库并进入此目录：

```bash
git clone https://github.com/project-flexos/asplos-ae.git
cd asplos-ae/experiments/fig-06_nginx-redis-perm
```

要构建的应用程序是"可变的"（注意：添加新应用程序需要为其创建构建环境。有关示例，请参阅仓库的 `support/` 文件夹）。这意味着我们可以单独针对它们。例如，要为 NGINX 运行排列组合，可以运行：

```
make prepare-wayfinder-app-nginx
make run-wayfinder-app-nginx
```

Redis 的操作方式相同：

```
make prepare-wayfinder-app-redis
make run-wayfinder-app-redis
```

隔离间隔的数量是全局变量，可以通过 `NUM_COMPARTMENTS=n` 变量设置。在默认情况下和论文中，设置为 `3` 以展示良好的排列组合范围和多样性，同时保持可理解性。例如，如果你只想构建 2 个隔离间隔，可以尝试：

```
NUM_COMPARTMENTS=2 make prepare-wayfinder-app-nginx
```

此步骤用于为 [Wayfinder](https://github.com/lancs-net/wayfinder) 生成任务文件。创建此任务文件后，可以将其传递给 Wayfinder 以接管并运行 NGINX 和 Redis 的 96 个唯一镜像构建。

 > **注意！** Wayfinder 将报告 144 个排列组合。差异（48 个镜像）是预期的，因为这些是无效的排列组合。

要启动应用程序的 Wayfinder，例如运行：

```
NUM_COMPARTMENTS=2 make run-wayfinder-app-nginx
```

构建后，是时候测试每个镜像了。你可以通过以下方式针对特定应用程序进行操作：

```
NUM_COMPARTMENTS=2 make test-app-nginx
```

最后，绘制特定应用程序：

```
NUM_COMPARTMENTS=2 make plot-app-nginx
```

## 故障排除

- **问题**：我的图表中缺少一些条形？

  **解决方案**：可能并非所有排列组合都已构建，因此无法对这些单个排列组合进行实验。确保 Wayfinder 正确构建所有排列组合。你可以使用以下方式检查构建的镜像数量：

  ```bash
  tree /tmp/fig-06_nginx-redis-perm/wayfinder-build-$APP/ | grep dbg | wc | awk '{ print $1 }'
  ```

  对于本实验的 `nginx` 和 `redis` 都应返回 `96`。如果数字少于此值，可能是 Wayfinder 提供的核心不足或无效。此实验的 `Makefile` 中的 `HOST_CORES` 变量必须调整为主机机器上可用的核心集，这些核心可用于运行单个排列组合构建。根据你的机器进行调整。Wayfinder 的推荐值大约是 2 的幂次方且大于 4。
