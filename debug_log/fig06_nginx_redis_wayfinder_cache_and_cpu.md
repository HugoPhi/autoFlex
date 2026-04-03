# Fig-06 Nginx/Redis 调试日志（详细版）

更新时间：2026-04-02
工作目录：`/home/tibless/Desktop/auto_flex/asplos22-ae/experiments/fig-06_nginx-redis-perm`

---

## 1. 问题背景
用户在 Fig-06 实验中执行：

```bash
cd /home/tibless/Desktop/auto_flex/asplos22-ae/experiments/fig-06_nginx-redis-perm
sudo -E make run
```

现象：实验无法正常跑通，且用户确认本机已有目标镜像，不希望触发远程 `pull`（避免版本偏移）。

---

## 2. 初始复现与第一阶段定位

### 2.1 现象 A：`make run` 行为异常
`make run` 跑到最后只打印了 wayfinder usage（没有真实执行 run 逻辑）。

关键现象：
- 命令末尾出现 wayfinder 帮助输出：
  - `Usage: wayfinder [command]`
  - `Available Commands: help, run, version`
- 表明被调用的是 `wayfinder`（裸命令），不是 `wayfinder run ...`

### 2.2 现象 B：单独执行 nginx 目标时报镜像加载失败
执行：

```bash
sudo -E make run-wayfinder-app-nginx
```

报错：
- `Could not start job: Could not pull image: Could not load image: unexpected EOF`

这说明失败点不在 make 层，而在 wayfinder 的镜像读取流程。

---

## 3. 本地镜像核验（排除“镜像不存在”）

核验命令（摘录）：

```bash
docker images --digests
docker image inspect ghcr.io/project-flexos/nginx:latest
docker image inspect ghcr.io/project-flexos/redis:latest
```

结论：
- 本地镜像存在且标签正确：
  - `ghcr.io/project-flexos/nginx:latest`
  - `ghcr.io/project-flexos/redis:latest`
- 因此问题并非 “镜像缺失”。

---

## 4. 深层根因（Wayfinder 缓存机制）

阅读 wayfinder 源码后确认：
- wayfinder 不直接使用本地 docker daemon 的镜像层。
- 它会将镜像处理为自己缓存目录下的 tar 包，再由 `crane.Load`/解包逻辑继续使用。
- 缓存路径位于：
  - `/tmp/fig-06_nginx-redis-perm/wayfinder-build-nginx/.cache/`
  - `/tmp/fig-06_nginx-redis-perm/wayfinder-build-redis/.cache/`

### 4.1 nginx 缓存损坏
检查发现 nginx 缓存 tar 异常：
- `tar: Unexpected EOF in archive`
- 文件内容不完整，导致 `Could not load image: unexpected EOF`。

### 4.2 redis 缓存同样损坏
redis 也存在同类损坏：
- 缓存包 `tar -tf` 报 `Unexpected EOF`。

---

## 5. 修复策略（严格使用本地镜像，不 pull）

采取的策略：
1. 保留损坏包备份（`.broken.bak`）。
2. 用本地已有镜像 `docker save` 重建 wayfinder 缓存 tar。
3. 因 wayfinder 对缓存命名可能按不同 digest 查找，额外创建“同内容别名文件”（按它实际查找的文件名复制一份）。

### 5.1 nginx 修复结果
- 镜像加载错误已消失。
- `run-wayfinder-app-nginx` 已进入实质编译阶段（大量 `kraft`/`gcc` 输出可见）。

### 5.2 redis 修复结果
- `unexpected EOF` 已消失。
- `run-wayfinder-app-redis` 成功进入构建流程。

---

## 6. CPU 抢占与并行调度处理

用户担心 nginx 与 redis 抢核。实际检查后确认：
- nginx 正在运行时，默认使用：
  - wayfinder 调度核：`1,2`
  - 任务核：`3,4`

为避免冲突，将 redis 显式迁移到高位核心：
- wayfinder 调度核：`15,16`
- 任务核：`17,18`

执行命令：

```bash
sudo -E make WAYFINDER_CORES=15,16 HOST_CORES=17,18 run-wayfinder-app-redis
```

核验结果：
- nginx 与 redis 的 wayfinder 进程同时运行。
- 核心集合无重叠，CPU 抢占冲突已规避。

---

## 7. 当前状态总结

1. 本次核心 bug 已确认并绕过：
- 根因是 wayfinder 的本地缓存 tar 损坏，不是 docker 本地镜像缺失。

2. nginx/redis 均已“打通到构建阶段”：
- 不再卡在 `Could not load image: unexpected EOF`。

3. CPU 并行策略已生效：
- nginx 与 redis 运行在不同核心集合，避免互相干扰。

---

## 8. 附：建议的后续运行方式

### 8.1 避免使用当前有歧义的总入口
建议优先运行按 app 拆分的目标：

```bash
sudo -E make run-wayfinder-app-nginx
sudo -E make WAYFINDER_CORES=15,16 HOST_CORES=17,18 run-wayfinder-app-redis
```

### 8.2 若再次出现同类 EOF
优先检查：

```bash
tar -tf /tmp/fig-06_nginx-redis-perm/wayfinder-build-<app>/.cache/*.tar.gz
```

若报 `Unexpected EOF`，即缓存损坏；可继续采用“本地镜像 `docker save` 重建缓存”的方式修复。

---

## 9. 备注

- 本次排障遵循了“尽量不远程 pull、优先复用本地镜像”的约束。
- 运行期间出现的一些 `Could not copy result`、`file exists` warning，多为首轮任务初始化时常见告警，不是此次阻塞主因。
