# 自动迁移后仍需人工修改说明（v11）

本文档说明：在自动迁移已经完成 gate 覆盖（`unresolved_calls=0`）后，哪些部分仍建议人工检查与修订。

## 1. 当前状态（基于 v11）

数据来源：
- `autoGen/eval_results/flexos_py_plus_v11/summary.json`
- `autoGen/eval_results/flexos_py_plus_v11/manual_effort_diff_stats.csv`

### 1.1 gate 覆盖状态
- `expected_calls = 81`
- `matched_calls = 81`
- `unresolved_calls = 0`

结论：从 gate 统计口径看，自动迁移已覆盖手工版本中的目标 gate 调用。

### 1.2 仍需人工工作（语义感知 diff 口径）

| app | total_manual_changed_lines | remaining_changed_lines | reduction_pct |
|---|---:|---:|---:|
| iperf | 43 | 0 | 100.00% |
| lwip | 55 | 38 | 30.91% |
| newlib | 304 | 115 | 62.17% |
| nginx | 635 | 287 | 54.80% |
| redis | 362 | 91 | 74.86% |

说明：`remaining_changed_lines` 表示“自动结果与 manual 之间，仍被判定为语义非等价”的剩余修改量估计。

## 2. 为什么 unresolved=0 仍需要人工修改

`unresolved_calls=0` 只保证 gate 调用覆盖，不保证以下内容完全一致：

1. 代码结构差异
- 例如 manual 采用 wrapper/宏封装，auto 采用直接 gate 插桩。

2. 类型与变量生命周期差异
- 临时变量定义位置、`volatile`、类型显式转换等可能与 manual 不同。

3. 宏/头文件路径下的风格约束
- 某些头文件中的宏替换策略对可读性和维护性影响较大。

4. 非 gate 语义的工程约束
- 注释、include 顺序、局部编码规范、编译警告规避写法等。

## 3. 建议人工检查清单

优先级建议：`nginx -> newlib -> redis -> lwip -> iperf`（按剩余量排序）

每个文件建议检查：
1. 是否存在与 manual 不同的 wrapper 组织方式。
2. 参数类型转换是否与 manual 对齐。
3. 宏中的函数替换是否保持可读与可维护。
4. 是否引入额外 include 或符号可见性变化。

## 4. 快速定位命令

在项目根目录执行：

```bash
# 查看各 app 仍需人工修改估计
cat autoGen/eval_results/flexos_py_plus_v11/manual_effort_diff_stats.csv

# 查看自动迁移总覆盖情况
cat autoGen/eval_results/flexos_py_plus_v11/summary.json

# 对某个 app 看 auto/manual 差异（示例：nginx）
diff -ruN \
  --exclude=cscope.out --exclude=cscope.files \
  autoGen/eval_results/flexos_py_plus_v11/projects/nginx/auto \
  autoGen/eval_results/flexos_py_plus_v11/projects/nginx/manual
```

## 5. 验收标准（建议）

1. 功能验收：`summary.json` 中 `unresolved_calls=0`。
2. 代码验收：关键 app（nginx/newlib/redis）完成人工 review 并记录特例。
3. 维护验收：新增特例规则后，同步更新规则文档与统计结果。
