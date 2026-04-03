# 搜索实验思路与 Baseline 实现说明

这份文档只讲两件事：
1. 实验为什么这样设计。
2. baseline 在当前代码里到底怎么实现。

对应代码入口：
- `evaluate_search_baselines_multi.py`
- `dag_poset_search.py`
- `dag_poset_search_cli.py`
- `run_debug_generate.sh`

## 1. 实验目标

目标不是只看“有没有找到可行解”，而是同时比较：
- 查询成本：要测多少个配置点才能结束。
- 命中速度：多快能碰到最优前沿（result frontier）中的任一点。

在本项目里，配置空间被建模为 DAG 偏序图：
- 节点：一个配置。
- 边 `u -> v`：`v` 比 `u` 更强隔离（更“向下”）。
- 语义单调性：若某点不可行，其所有后代也不可行；若某点可行，其祖先都可行。

基于这个单调性，搜索每查询一个点，就能批量剪枝一组点。

## 2. 实验协议（公平对比）

当前默认流程在 `run_debug_generate.sh` 中：
- 数据集：`nginx:REQ`、`redis:GET`、`redis:SET`。
- 每个数据集多个阈值（默认各 5 个）。
- 多随机种子（默认 10 个）。
- 方法集：`exhaustive` + `balanced`(ours) + `random` baseline。

说明：
- `first` 与 `worst` 策略在代码中仍可选，但当前主流程默认不纳入图表对比。
- `exhaustive` 是参考上界/下界基线（查询最多，但答案定义最直接）。

## 3. 评估指标定义

评估脚本：`evaluate_search_baselines_multi.py`

### 3.1 查询比例

- `query_count`：该方法在一次试验中的查询次数。
- `query_ratio = query_count / |V|`，其中 `|V|` 是节点总数（本实验通常是 96）。

解释：越小越好，表示单位搜索任务所需查询更少。

### 3.2 首次命中最优前沿

- 先用穷举得到最优前沿 `F*`（`reduce_to_minimal_frontier`）。
- 对于某方法的搜索轨迹，找到第一个被查询且属于 `F*` 的 step：
  - 记为 `first_result_query`。
- 归一化为 `first_result_query_ratio = first_result_query / |V|`。

解释：越小越好，表示越快碰到“真正结果集合”中的点。

### 3.3 穷举法在该指标下的取值

实现里对 `exhaustive` 使用期望位置：
- `first_result_query = |V| / |F*|`

这是“随机扫描全部点时首次命中前沿点”的平均位置，用于和搜索法在同一尺度上比较。

## 4. 基线算法怎么实现

核心类：`DagPosetSearch`（文件 `dag_poset_search.py`）。

预处理：
- `desc_bits[i]`：节点 `i` 的后代闭包（含自身）位集。
- `anc_bits[i]`：节点 `i` 的祖先闭包（含自身）位集。

搜索状态：
- `candidate`：当前候选集位掩码。
- 每轮选择一个候选 `c` 查询 `g(c)` 与阈值比较。

统一剪枝规则（所有策略都一样）：
- 若 `g(c) >= threshold`（可行）：
  - 记录 `c` 到结果集中。
  - 从候选集中删除 `anc_bits[c]`（祖先都不可能是更优前沿点）。
- 否则（不可行）：
  - 从候选集中删除 `desc_bits[c]`（后代更强隔离，只会更不可行）。

差异只在“下一步选哪个点查询”。

### 4.1 `exhaustive`（穷举基线）

位置：`evaluate_search_baselines_multi.py` 中直接计算，不走 `run_single_source_search`。

做法：
1. 全量扫描所有节点判定可行集合。
2. 用 `reduce_to_minimal_frontier(...)` 保留最优前沿。
3. 记 `query_count = |V|`，`query_ratio = 1.0`。

作用：提供“完全信息”参考，不依赖任何搜索策略。

### 4.2 `random`（随机候选基线）

函数：`_find_random_candidate(candidate_mask, rng)`。

做法：
1. 从当前 `candidate` 中均匀随机挑一个点。
2. 执行统一剪枝规则。
3. 重复直到 `candidate` 为空。

作用：对比“没有结构化决策”时，偏序剪枝本身能带来多少收益。

### 4.3 `balanced`（我们的策略）

当前实现并不是固定中位点，而是“期望剪枝最大化”：

函数：`_find_expected_prune(candidate_mask, p_feasible)`。

对任一候选点 `i`：
- `a_i = |anc(i) ∩ candidate|`
- `d_i = |desc(i) ∩ candidate|`
- 估计可行概率 `p`（由历史观测平滑估计）：
  - `p = (observed_feasible + 1) / (observed_count + 2)`
- 期望剪枝量：
  - `E_i = p * a_i + (1 - p) * d_i`

每轮选 `E_i` 最大的点查询；若并列，优先 `|a_i - d_i|` 更小（更平衡），再按节点名稳定打破并列。

作用：把“剪枝规模”显式作为优化目标，减少查询次数，并通常更快触达前沿。

### 4.4 代码里仍保留但默认不参评的方法

- `first`：总是选当前候选集中按节点序第一个点（`_find_first_candidate`）。
- `worst`：故意选最差分裂点（`_find_worst_split`），用于压力测试，不建议当作正式 baseline。

## 5. 单次搜索伪代码（适用于 random/balanced/first/worst）

```text
candidate <- all nodes
results <- empty
while candidate is not empty:
    c <- pick_candidate(candidate, strategy)
    if g(c) >= threshold:      # feasible
        add c to results
        candidate <- candidate \ anc(c)
    else:                      # infeasible
        candidate <- candidate \ desc(c)

final_answers <- remove dominated nodes from results
```

其中 `final_answers` 与穷举前沿比较，得到 `exact/subset/...` 一致性标签。

## 6. 为什么这个 baseline 组合是合理的

- `exhaustive`：给出参考真值与成本上限。
- `random`：给出“无策略选择点”的自然下界对照。
- `balanced`：验证利用 DAG 结构和在线统计做决策是否显著更优。

这三者组合能回答一个清晰问题：
- 我们的方法到底是“比乱选好多少”，以及“离完全穷举的答案质量有多近”。

## 7. 复现实验（当前默认命令）

在 `search` 目录运行：

```bash
bash run_debug_generate.sh
```

核心输出：
- `../figures/search/dag_search_multi_detail.csv`
- `../figures/search/dag_search_multi_agg.csv`
- `../figures/search/svg/search_baseline_query_ratio_by_threshold.svg`
- `../figures/search/svg/search_baseline_first_result_by_threshold.svg`

如果只想重跑 baseline 评估，可单独运行：

```bash
python3 evaluate_search_baselines_multi.py \
  --out-detail ../figures/search/dag_search_multi_detail.csv \
  --out-agg ../figures/search/dag_search_multi_agg.csv
```