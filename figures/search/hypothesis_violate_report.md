# Hypothesis Violation Report (Nginx + Redis)

- epsilon_mode: absolute
- epsilon: 0.0
- total_series: 3

## Per-Series Summary

| App | Method | Edges | Violations | Missing | Max Gap | Mean Gap |
|---|---:|---:|---:|---:|---:|---:|
| nginx | REQ | 288 | 33 | 0 | 1243.140 | 310.039 |
| redis | GET | 288 | 29 | 0 | 13728.686 | 3993.014 |
| redis | SET | 288 | 25 | 0 | 8960.742 | 2771.363 |

## Top Violations Across All Series

- [redis/GET] C45 -> C41: gap=13728.686, need_abs_eps=13728.686, need_rel_eps=0.070168
- [redis/GET] C39 -> C37: gap=10685.800, need_abs_eps=10685.800, need_rel_eps=0.050353
- [redis/GET] C20 -> C18: gap=9339.574, need_abs_eps=9339.574, need_rel_eps=0.034850
- [redis/GET] C96 -> C91: gap=9170.888, need_abs_eps=9170.888, need_rel_eps=0.078706
- [redis/SET] C70 -> C69: gap=8960.742, need_abs_eps=8960.742, need_rel_eps=0.068987
- [redis/GET] C96 -> C92: gap=8950.054, need_abs_eps=8950.054, need_rel_eps=0.076811
- [redis/SET] C43 -> C52: gap=7072.378, need_abs_eps=7072.378, need_rel_eps=0.045426
- [redis/GET] C79 -> C73: gap=6565.000, need_abs_eps=6565.000, need_rel_eps=0.046124
- [redis/GET] C55 -> C49: gap=5875.586, need_abs_eps=5875.586, need_rel_eps=0.032204
- [redis/GET] C55 -> C51: gap=5522.122, need_abs_eps=5522.122, need_rel_eps=0.030267
- [redis/GET] C45 -> C42: gap=5430.252, need_abs_eps=5430.252, need_rel_eps=0.027754
- [redis/GET] C96 -> C94: gap=5185.272, need_abs_eps=5185.272, need_rel_eps=0.044501
- [redis/SET] C80 -> C77: gap=4756.488, need_abs_eps=4756.488, need_rel_eps=0.038596
- [redis/GET] C80 -> C74: gap=4655.266, need_abs_eps=4655.266, need_rel_eps=0.032935
- [redis/SET] C80 -> C74: gap=4629.516, need_abs_eps=4629.516, need_rel_eps=0.037566
- [redis/GET] C61 -> C58: gap=4304.816, need_abs_eps=4304.816, need_rel_eps=0.024740
- [redis/SET] C88 -> C93: gap=4083.728, need_abs_eps=4083.728, need_rel_eps=0.040458
- [redis/SET] C94 -> C93: gap=4034.034, need_abs_eps=4034.034, need_rel_eps=0.039946
- [redis/SET] C78 -> C77: gap=3917.860, need_abs_eps=3917.860, need_rel_eps=0.031576
- [redis/SET] C70 -> C66: gap=3875.868, need_abs_eps=3875.868, need_rel_eps=0.029840
