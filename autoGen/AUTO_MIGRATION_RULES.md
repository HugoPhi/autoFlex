# Auto Migration Rules (FlexOS)

本文件记录 `autoGen/flexos_porthelper_py.py` 中当前生效的自动迁移规则、设计意图，以及规则级统计口径。

## 1. 规则总览

### 1.1 映射规则（函数 -> lib）
- 来源 1: cscope 唯一定义推断（优先）
- 来源 2: fallback 显式映射（补全常见系统调用）
- 关键点:
  - socket/lwip 家族映射到 `liblwip`
  - 时间相关映射到 `libuktime`
  - vfscore 相关映射到 `libvfscore`
  - 下划线别名 `_write/_fstat` 会归一化到 gate 中的 `write/fstat`

### 1.2 Coccinelle 基础替换规则
- 赋值调用:
  - `var = foo(args);` -> `flexos_gate_r(libX, var, foo, args);`
- 纯调用:
  - `foo(args);` -> `flexos_gate(libX, foo, args);`

### 1.3 语句级后处理重写规则
用于补齐 spatch 难覆盖的代码形态（尤其是多行 if/return、带类型转换调用）。

- if + 赋值调用:
  - `if ((ret = foo(...)) op rhs)`
  - 改写为先 gate 再 `if (ret op rhs)`
- if + 直接调用:
  - `if (foo(...) op rhs)`
  - 改写为临时变量接收 gate 返回值后判断
- return 调用:
  - `return foo(...);`
  - 改写为临时变量接收 gate 返回值再 return
- 赋值调用（带 cast）:
  - `ret = (type) foo(...);`
  - 改写为 `flexos_gate_r(...)`
- 纯调用语句:
  - `foo(...);`
  - 改写为 `flexos_gate(...)`

## 2. 规则级统计（当前 v11）

统计输入:
- `autoGen/eval_results/flexos_py_plus_v11/projects/*/{manual,auto}`

统计脚本:
- `autoGen/compute_rule_match_stats.py`

统计输出:
- `autoGen/eval_results/flexos_py_plus_v11/rule_match_stats.csv`

口径说明:
- `expected`: manual 中该 `(lib,function)` 出现次数
- `produced`: auto 中该 `(lib,function)` 出现次数
- `matched`: `min(expected, produced)`
- `unresolved`: `expected - matched`

当前摘要:
- 全局: `expected=80, matched=80, unresolved=0`
- 重点规则（按 matched 降序）:

| lib | function | expected | produced | matched | unresolved |
|---|---:|---:|---:|---:|---:|
| liblwip | setsockopt | 25 | 58 | 25 | 0 |
| liblwip | getaddrinfo | 7 | 7 | 7 | 0 |
| liblwip | getsockopt | 7 | 19 | 7 | 0 |
| liblwip | recv | 6 | 8 | 6 | 0 |
| liblwip | socket | 6 | 7 | 6 | 0 |
| libc | printf | 5 | 32 | 5 | 0 |
| libuktime | gettimeofday | 5 | 9 | 5 | 0 |
| liblwip | bind | 4 | 6 | 4 | 0 |
| liblwip | accept | 3 | 4 | 3 | 0 |
| liblwip | listen | 3 | 4 | 3 | 0 |

完整规则统计见 CSV。

## 3. 维护与同步要求

后续如果新增/修改规则，必须同步更新本文件，建议流程:

1. 运行全量评测（示例）
```bash
/home/tibless/Desktop/auto_flex/.venv/bin/python autoGen/evaluate_flexos_porthelper_py.py \
  --dataset-root autoGen/dataset \
  --out-dir autoGen/eval_results/flexos_py_plus_vXX
```

2. 生成规则级统计
```bash
/home/tibless/Desktop/auto_flex/.venv/bin/python autoGen/compute_rule_match_stats.py \
  --eval-dir autoGen/eval_results/flexos_py_plus_vXX
```

3. 在本文件更新:
- 新规则说明
- 口径是否变化
- 规则级统计摘要表
- 对比上一版本的 delta

## 4. 关于“是否还需要漏洞检测程序”

结论: **仍然建议保留漏洞检测程序，但它不再是“和 manual 对齐”的主评测指标。**

原因:
- 当前 `manual` 作为 oracle 时，`expected/matched/unresolved` 用于衡量“是否复现人工迁移答案”。
- 这并不等价于“安全性已充分覆盖”。manual 也可能有遗漏、风格偏差或场景特定假设。
- 漏洞检测程序的作用应转为:
  - 发现 manual 与自动迁移都未覆盖的风险模式
  - 发现新增规则引入的潜在副作用（误改、漏改、危险调用）
  - 提供额外安全信号，而非替代 oracle 对齐指标

建议实践:
- 对齐评测主线: `expected/matched/unresolved`
- 安全评估辅线: 静态检查/风险扫描报告（单独输出，不混入主指标）
