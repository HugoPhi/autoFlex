const {
  Alert,
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Container,
  CssBaseline,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  Link,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  ThemeProvider,
  Toolbar,
  IconButton,
  Tooltip,
  Typography,
  createTheme,
} = MaterialUI;

const HELP_MARKDOWN = `# AutoFlex Workflow Platform 使用手册

## 目录
1. 平台目标与适用场景
2. 页面结构总览
3. 快速开始（3 分钟）
4. Stage A：Code Porting 详细说明
5. Stage B：Config Search 详细说明
6. test bench 机制与扩展方式
7. Job 状态机与字段解释
8. 实时日志阅读指南
9. 产物说明（按文件逐项解释）
10. 重启网站与运行维护
11. 常见故障与排查
12. Nginx 论文 demo 推荐流程
13. 结果归档与复现实践

## 1. 平台目标与适用场景
本平台用于把 AutoFlex 的两阶段流程（Stage A 迁移、Stage B 配置搜索）转成可视化作业系统。
它特别适合以下场景：
- 首次上手：不熟悉脚本参数时可避免命令行记忆成本。
- 论文展示：可直接展示作业、日志和产物证据链。
- 故障定位：失败作业会保留 command / params / log 便于复盘。
- 协作复验：可将产物和日志下载给他人复核。

## 2. 页面结构总览
- 左侧：Stage A 提交、Stage B 提交、产物下载
- 右侧：Job Console、作业详情（含参数和命令）、实时日志
- 顶栏：刷新按钮、帮助按钮（当前文档）

## 3. 快速开始（3 分钟）
1. Stage A 上传原始源码 zip，点击“开始迁移”。
2. 在 Job Console 点 view，确认 status 从 queued -> running -> succeeded。
3. 在“产物下载”获取 Stage A 输出的 migrated_source.zip。
4. Stage B 上传 migrated_source.zip，选择 test bench，点击“开始搜索”。
5. 搜索完成后下载 report / csv / top_images 相关产物。

## 4. Stage A：Code Porting 详细说明
### 输入
- source_zip：原始源码压缩包（必须是 .zip）

### 执行行为
- 后端创建 job（kind=workflow_code_porting）
- 调用 run_code_porting_from_zip.py
- 产生迁移输出与迁移日志

### 你应该关注
- status：是否 succeeded
- return_code：是否 0
- command：调用了哪个脚本、用的是什么输入
- 产物：是否出现 migrated_source.zip 和报告

## 5. Stage B：Config Search 详细说明
### 输入
- source_zip：Stage A 输出的 migrated_source.zip
- test_bench：例如 fig06-nginx / fig06-redis
- 可调参数：baseline_threshold、num_compartments、host_cores、wayfinder_cores、test_iterations、top_k

### 执行行为
- 后端创建 job（kind=workflow_config_search）
- 调用 run_config_search_nginx_from_zip.py（当前脚本名历史遗留，但已支持 app 参数）
- 执行真实构建 + 真实测试 + 搜索，不是模拟结果

### 你应该关注
- 日志中的 build/test/search 阶段边界
- 是否出现 fallback 提示（若主链路失败）
- 产物是否包含 benchmark/performance/search_progress/top_images

## 6. test bench 机制与扩展方式
test bench 来源于配置文件目录：
- website/config/test_benches/nginx.json
- website/config/test_benches/redis.json
- website/config/test_benches/template.json（模板）

新增 benchmark 的推荐步骤：
1. 复制 template.json 为新文件。
2. 填写 id/name/app/defaults。
3. 刷新页面后自动出现在 test bench 下拉中。

## 7. Job 状态机与字段解释
### 状态
- queued：已入队，尚未启动
- running：正在执行
- succeeded：执行成功
- failed：执行失败

### 详情字段
- job_id：本次运行唯一编号
- kind：作业类型
- return_code：脚本返回码（0=成功）
- error：后端捕获异常（若有）
- command：真实执行命令（建议重点审查）
- params：本次参数快照（复现时关键）

## 8. 实时日志阅读指南
日志是增量流，且支持 ANSI 颜色。

建议顺序：
1. 先看第一条硬错误。
2. 再看该错误前 20~50 行上下文。
3. 最后回看 command 和 params 是否合理。

经验规则：
- 若提示 path / file not found，多半是输入包结构或路径参数问题。
- 若提示权限不足，多半是 sudo / 环境配置问题。
- 若 build 失败，先看 build_and_test.log 对应阶段首个报错。

## 9. 产物说明（按文件逐项解释）
以下以 Stage B nginx 常见输出为例。

### 核心数据
- benchmark_nginx.csv
  - 基准数据表，通常用于后续统计和画图。
- search_progress.csv
  - 搜索过程轨迹，记录候选演化和进度。
- performance_report.json
  - 机器可读结果摘要，适合程序化分析。
- performance_report.md
  - 人类可读报告，适合实验记录和论文附录。

### 构建与运行证据
- build_and_test.log
  - 最关键诊断日志，包含 build/test 细节。
- top_images/task-single/build.log
  - 单配置构建日志，定位镜像构建失败时很有用。
- top_images/task-single/config
  - 运行配置快照。
- top_images/task-single/kraft.yaml
  - 关键运行配置文件。

### 二进制与打包
- top_images/task-single/nginx_kvm-x86_64
  - 可执行镜像二进制。
- top_images/task-single/nginx_kvm-x86_64.dbg
  - 带调试符号版本。
- top_images.tar.gz
  - 打包归档，便于迁移或交付。

## 10. 重启网站与运行维护
### 本机重启（推荐）
\`\`\`bash
fuser -k 8080/tcp
cd /home/tibless/Desktop/auto_flex/website
/home/tibless/Desktop/auto_flex/.venv/bin/python app.py
\`\`\`

访问地址：
- http://127.0.0.1:8080/

### 重启后的行为
- 已完成作业会从 jobs 元数据恢复。
- 中断中的 running 作业会标记为 failed，避免僵尸状态。

## 11. 常见故障与排查
### 页面打开但作业不更新
1. 先点“刷新”。
2. 检查后端是否仍在 8080 端口监听。

### Stage A 成功但 Stage B 失败
1. 看 build_and_test.log 第一条硬错误。
2. 看 params 是否与 bench 默认值冲突。
3. 确认 migrated_source.zip 是否来自对应 Stage A。

### 看不到产物
1. 确认你当前选中的 job_id。
2. failed 作业可能仅有日志，产物不完整。

### 日志太长难以定位
1. 复制 log。
2. 搜索关键词：error, failed, traceback, permission, not found。

## 12. Nginx 论文 demo 推荐流程
1. 运行 Stage A，输入 nginx 源 zip。
2. 下载 Stage A 的 migrated_source.zip。
3. 运行 Stage B，选择 test_bench=fig06-nginx。
4. 等待 succeeded，下载：
   - benchmark_nginx.csv
   - performance_report.json
   - search_progress.csv
   - top_images.tar.gz
5. 将以上文件用于论文图和结果复查。

## 13. 结果归档与复现实践
建议每次实验保存如下最小集合：
1. 输入 zip
2. params 快照
3. command
4. 关键日志（至少 build_and_test.log）
5. 关键产物（report + csv + tar.gz）

做到以上五项后，后续复验、对比和答辩解释会稳定很多。
`;

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function inlineMarkdown(text) {
  let out = escapeHtml(text);
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return out;
}

function markdownToHtmlLite(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const html = [];
  let inCode = false;
  let inUl = false;
  let inOl = false;
  let codeBuf = [];

  const closeLists = () => {
    if (inUl) {
      html.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      html.push("</ol>");
      inOl = false;
    }
  };

  for (const raw of lines) {
    const line = raw || "";
    const trim = line.trim();

    if (trim.startsWith("```")) {
      if (!inCode) {
        closeLists();
        inCode = true;
        codeBuf = [];
      } else {
        html.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
        inCode = false;
        codeBuf = [];
      }
      continue;
    }

    if (inCode) {
      codeBuf.push(line);
      continue;
    }

    if (trim === "") {
      closeLists();
      continue;
    }

    const h = trim.match(/^(#{1,3})\s+(.+)$/);
    if (h) {
      closeLists();
      const lv = h[1].length;
      html.push(`<h${lv}>${inlineMarkdown(h[2])}</h${lv}>`);
      continue;
    }

    const ol = trim.match(/^\d+\.\s+(.+)$/);
    if (ol) {
      if (!inOl) {
        closeLists();
        html.push("<ol>");
        inOl = true;
      }
      html.push(`<li>${inlineMarkdown(ol[1])}</li>`);
      continue;
    }

    const ul = trim.match(/^[-*]\s+(.+)$/);
    if (ul) {
      if (!inUl) {
        closeLists();
        html.push("<ul>");
        inUl = true;
      }
      html.push(`<li>${inlineMarkdown(ul[1])}</li>`);
      continue;
    }

    closeLists();
    html.push(`<p>${inlineMarkdown(trim)}</p>`);
  }

  if (inCode) {
    html.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
  }
  closeLists();

  return html.join("\n");
}

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#0f766e" },
    secondary: { main: "#2563eb" },
    background: { default: "#f4f7fb", paper: "#ffffff" },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Google Sans Flex", Arial, Helvetica, sans-serif',
    h5: { fontWeight: 700 },
    h6: { fontWeight: 700 },
  },
});

function statusColor(status) {
  if (status === "succeeded") return "success";
  if (status === "failed") return "error";
  if (status === "running") return "info";
  return "warning";
}

function ansiFgColor(code) {
  const colors = {
    30: "#111827",
    31: "#ef4444",
    32: "#22c55e",
    33: "#eab308",
    34: "#60a5fa",
    35: "#d946ef",
    36: "#22d3ee",
    37: "#e5e7eb",
    90: "#6b7280",
    91: "#f87171",
    92: "#4ade80",
    93: "#facc15",
    94: "#93c5fd",
    95: "#f0abfc",
    96: "#67e8f9",
    97: "#f9fafb",
  };
  return colors[code] || null;
}

function ansiBgColor(code) {
  const colors = {
    40: "#111827",
    41: "#7f1d1d",
    42: "#14532d",
    43: "#713f12",
    44: "#1e3a8a",
    45: "#701a75",
    46: "#155e75",
    47: "#d1d5db",
    100: "#374151",
    101: "#b91c1c",
    102: "#166534",
    103: "#854d0e",
    104: "#1d4ed8",
    105: "#a21caf",
    106: "#0e7490",
    107: "#f3f4f6",
  };
  return colors[code] || null;
}

function parseAnsiLogToSpans(text) {
  const out = [];
  const pattern = /\x1b\[([0-9;]*)m/g;
  let cursor = 0;
  let match;
  let style = { color: "#d7e3ff", backgroundColor: "transparent", fontWeight: 400 };

  while ((match = pattern.exec(text)) !== null) {
    const chunk = text.slice(cursor, match.index);
    if (chunk) {
      out.push({ text: chunk, style: { ...style } });
    }

    const codes = (match[1] || "0")
      .split(";")
      .filter((x) => x !== "")
      .map((x) => Number.parseInt(x, 10))
      .filter((n) => !Number.isNaN(n));

    if (codes.length === 0) {
      codes.push(0);
    }

    for (const code of codes) {
      if (code === 0) {
        style = { color: "#d7e3ff", backgroundColor: "transparent", fontWeight: 400 };
        continue;
      }
      if (code === 1) {
        style = { ...style, fontWeight: 700 };
        continue;
      }
      if (code === 22) {
        style = { ...style, fontWeight: 400 };
        continue;
      }
      if (code === 39) {
        style = { ...style, color: "#d7e3ff" };
        continue;
      }
      if (code === 49) {
        style = { ...style, backgroundColor: "transparent" };
        continue;
      }

      const fg = ansiFgColor(code);
      if (fg) {
        style = { ...style, color: fg };
        continue;
      }
      const bg = ansiBgColor(code);
      if (bg) {
        style = { ...style, backgroundColor: bg };
      }
    }

    cursor = pattern.lastIndex;
  }

  if (cursor < text.length) {
    out.push({ text: text.slice(cursor), style: { ...style } });
  }

  return out;
}

function highlightShellCommand(commandText) {
  const text = commandText || "";
  const tokens = text.match(/"[^"]*"|'[^']*'|\S+/g) || [];
  return tokens.map((token, idx) => {
    let color = "#d7e3ff";
    if (idx === 0) {
      color = "#93c5fd";
    } else if (token.startsWith("--")) {
      color = "#f59e0b";
    } else if (token.startsWith("-")) {
      color = "#fbbf24";
    } else if (token.includes("=")) {
      color = "#67e8f9";
    } else if (token.startsWith("/") || token.startsWith(".")) {
      color = "#86efac";
    }
    const suffix = idx < tokens.length - 1 ? " " : "";
    return { text: token + suffix, style: { color } };
  });
}

function highlightJson(jsonText) {
  const text = jsonText || "";
  const regex = /("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"\s*:?)|(\btrue\b|\bfalse\b|\bnull\b)|(-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)/g;
  const out = [];
  let last = 0;
  let m;

  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) {
      out.push({ text: text.slice(last, m.index), style: { color: "#d7e3ff" } });
    }

    const token = m[0];
    let color = "#d7e3ff";
    if (m[1]) {
      color = token.endsWith(":") ? "#93c5fd" : "#86efac";
    } else if (m[2]) {
      color = "#fca5a5";
    } else if (m[3]) {
      color = "#fbbf24";
    }
    out.push({ text: token, style: { color } });
    last = regex.lastIndex;
  }

  if (last < text.length) {
    out.push({ text: text.slice(last), style: { color: "#d7e3ff" } });
  }
  return out;
}

async function fetchJSON(url, init) {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

function App() {
  const BASE_STAGE_B = {
    test_bench: "",
    baseline_metric: "REQ",
    baseline_threshold: "45000",
    num_compartments: "3",
    top_k: "3",
    host_cores: "3,4",
    wayfinder_cores: "1,2",
    test_iterations: "3",
    overlay_subdir: "",
  };

  const [jobs, setJobs] = React.useState([]);
  const [selectedIds, setSelectedIds] = React.useState([]);
  const [selectedJobId, setSelectedJobId] = React.useState("");
  const [selectedJob, setSelectedJob] = React.useState(null);
  const [artifacts, setArtifacts] = React.useState([]);
  const [logText, setLogText] = React.useState("");
  const [logOffset, setLogOffset] = React.useState(0);
  const [logComplete, setLogComplete] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState("");
  const logRef = React.useRef(null);

  const [stageAFile, setStageAFile] = React.useState(null);
  const [stageBFile, setStageBFile] = React.useState(null);
  const [testBenches, setTestBenches] = React.useState([]);
  const [stageB, setStageB] = React.useState(BASE_STAGE_B);
  const [helpOpen, setHelpOpen] = React.useState(false);

  const loadJobs = React.useCallback(async () => {
    const data = await fetchJSON("/api/jobs");
    setJobs(data.jobs || []);
  }, []);

  const loadTestBenches = React.useCallback(async () => {
    const data = await fetchJSON("/api/config/test-benches");
    const benches = data.test_benches || [];
    setTestBenches(benches);
    if (benches.length > 0) {
      setStageB((prev) => {
        if (prev.test_bench) return prev;
        const first = benches[0];
        return {
          ...BASE_STAGE_B,
          ...first.defaults,
          test_bench: first.id,
        };
      });
    }
  }, []);

  const loadJobDetail = React.useCallback(async () => {
    if (!selectedJobId) return;
    const data = await fetchJSON(`/api/jobs/${selectedJobId}`);
    setSelectedJob(data.job || null);
    setArtifacts(data.artifacts || []);
  }, [selectedJobId]);

  const streamLog = React.useCallback(async () => {
    if (!selectedJobId || logComplete) return;
    const data = await fetchJSON(`/api/jobs/${selectedJobId}/log-stream?offset=${logOffset}`);
    const chunk = data.chunk || "";
    if (chunk) {
      setLogText((prev) => prev + chunk);
      setLogOffset(data.offset || 0);
      requestAnimationFrame(() => {
        if (!logRef.current) return;
        const el = logRef.current;
        const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
        if (nearBottom) el.scrollTop = el.scrollHeight;
      });
    }
    setLogComplete(Boolean(data.complete));
  }, [selectedJobId, logOffset, logComplete]);

  React.useEffect(() => {
    loadJobs().catch((e) => setNotice(String(e)));
    loadTestBenches().catch((e) => setNotice(String(e)));
  }, [loadJobs, loadTestBenches]);

  React.useEffect(() => {
    if (!selectedJobId) return;
    if (!jobs.some((x) => x.id === selectedJobId)) {
      setSelectedJobId("");
      setSelectedJob(null);
      setArtifacts([]);
      setLogText("");
      setLogOffset(0);
      setLogComplete(false);
    }
  }, [jobs, selectedJobId]);

  React.useEffect(() => {
    const timer = setInterval(() => {
      loadJobs().catch(() => {});
      loadJobDetail().catch(() => {});
      streamLog().catch(() => {});
    }, 1500);
    return () => clearInterval(timer);
  }, [loadJobs, loadJobDetail, streamLog]);

  const pickJob = async (jobId) => {
    if (selectedJobId !== jobId) {
      setSelectedJobId(jobId);
      setLogText("");
      setLogOffset(0);
      setLogComplete(false);
    }
    await loadJobDetail();
  };

  const submitStageA = async () => {
    if (!stageAFile) {
      setNotice("请先选择 Stage A 源码 zip");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const form = new FormData();
      form.append("source_zip", stageAFile);
      await fetchJSON("/api/workflows/code-porting", { method: "POST", body: form });
      await loadJobs();
      setNotice("Stage A 已提交");
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  };

  const submitStageB = async () => {
    if (!stageBFile) {
      setNotice("请先选择 Stage B 迁移后源码 zip");
      return;
    }
    if (!stageB.test_bench) {
      setNotice("请先选择 test bench");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const form = new FormData();
      form.append("source_zip", stageBFile);
      Object.entries(stageB).forEach(([k, v]) => form.append(k, String(v)));
      await fetchJSON("/api/workflows/config-search", { method: "POST", body: form });
      await loadJobs();
      setNotice("Stage B 已提交");
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  };

  const textField = (key, label) => (
    <TextField
      size="small"
      fullWidth
      label={label}
      value={stageB[key]}
      onChange={(e) => setStageB((prev) => ({ ...prev, [key]: e.target.value }))}
    />
  );

  const currentBench = testBenches.find((x) => x.id === stageB.test_bench) || null;
  const helpHtml = React.useMemo(() => {
    const builtIn = markdownToHtmlLite(HELP_MARKDOWN);
    if (typeof window !== "undefined" && window.marked && typeof window.marked.parse === "function") {
      return window.marked.parse(HELP_MARKDOWN);
    }
    return builtIn;
  }, []);
  const ansiLogParts = React.useMemo(() => parseAnsiLogToSpans(logText || ""), [logText]);
  const commandText = selectedJob?.command || "-";
  const paramText = React.useMemo(() => JSON.stringify(selectedJob?.params || {}, null, 2), [selectedJob]);
  const commandParts = React.useMemo(() => highlightShellCommand(commandText), [commandText]);
  const paramParts = React.useMemo(() => highlightJson(paramText), [paramText]);

  const copyText = async (text, label) => {
    try {
      await navigator.clipboard.writeText(text || "");
      setNotice(`${label} 已复制`);
    } catch (e) {
      setNotice(`复制失败: ${String(e)}`);
    }
  };

  const applyBench = (benchId) => {
    const bench = testBenches.find((x) => x.id === benchId);
    if (!bench) {
      setStageB((prev) => ({ ...prev, test_bench: benchId }));
      return;
    }
    setStageB((prev) => ({
      ...prev,
      ...BASE_STAGE_B,
      ...bench.defaults,
      test_bench: bench.id,
    }));
  };

  const isAllSelected = jobs.length > 0 && selectedIds.length === jobs.length;
  const isIndeterminate = selectedIds.length > 0 && selectedIds.length < jobs.length;

  const toggleSelectAll = (checked) => {
    setSelectedIds(checked ? jobs.map((x) => x.id) : []);
  };

  const toggleJobSelected = (jobId, checked) => {
    setSelectedIds((prev) => {
      if (checked) {
        if (prev.includes(jobId)) return prev;
        return [...prev, jobId];
      }
      return prev.filter((x) => x !== jobId);
    });
  };

  const deleteOneJob = async (jobId) => {
    setBusy(true);
    setNotice("");
    try {
      await fetchJSON(`/api/jobs/${jobId}`, { method: "DELETE" });
      setSelectedIds((prev) => prev.filter((x) => x !== jobId));
      if (selectedJobId === jobId) {
        setSelectedJobId("");
        setSelectedJob(null);
        setArtifacts([]);
        setLogText("");
        setLogOffset(0);
        setLogComplete(false);
      }
      await loadJobs();
      setNotice(`已清除作业 ${jobId}`);
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  };

  const deleteSelectedJobs = async () => {
    if (selectedIds.length === 0) {
      setNotice("请先勾选要清除的作业");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const data = await fetchJSON("/api/jobs/delete-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: selectedIds }),
      });
      setSelectedIds([]);
      if (selectedJobId && data.deleted && data.deleted.includes(selectedJobId)) {
        setSelectedJobId("");
        setSelectedJob(null);
        setArtifacts([]);
        setLogText("");
        setLogOffset(0);
        setLogComplete(false);
      }
      await loadJobs();
      const summary = [
        `删除成功 ${data.deleted?.length || 0} 个`,
        `运行中跳过 ${data.skipped_active?.length || 0} 个`,
        `不存在 ${data.not_found?.length || 0} 个`,
      ].join("，");
      setNotice(summary);
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AppBar position="sticky" color="inherit" elevation={1}>
        <Toolbar>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="h6" color="primary.main">AutoFlex Workflow Platform</Typography>
            <Tooltip title="使用帮助">
              <IconButton
                size="small"
                onClick={() => setHelpOpen(true)}
                sx={{ border: "1px solid", borderColor: "primary.main", width: 26, height: 26 }}
              >
                <Typography sx={{ fontSize: 14, lineHeight: 1, color: "primary.main", fontWeight: 700 }}>?</Typography>
              </IconButton>
            </Tooltip>
          </Stack>
          <Box sx={{ flex: 1 }} />
          <Button onClick={() => { loadJobs(); loadJobDetail(); streamLog(); }}>
            刷新
          </Button>
        </Toolbar>
      </AppBar>

      <Container maxWidth={false} sx={{ py: 2 }}>
        {notice && (
          <Alert severity="info" sx={{ mb: 2 }} onClose={() => setNotice("")}>{notice}</Alert>
        )}

        <Grid container spacing={2}>
          <Grid item xs={12} md={4}>
            <Stack spacing={2}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>Stage A: Code Porting（代码迁移）</Typography>
                  <Stack spacing={1.5}>
                    <Button variant="outlined" component="label">
                      {stageAFile ? stageAFile.name : "选择 source_zip（源码压缩包）"}
                      <input hidden type="file" accept=".zip" onChange={(e) => setStageAFile(e.target.files?.[0] || null)} />
                    </Button>
                    <Button
                      variant="contained"
                      onClick={submitStageA}
                      disabled={busy}
                      startIcon={busy ? <CircularProgress size={16} color="inherit" /> : null}
                    >
                      开始迁移
                    </Button>
                  </Stack>
                </CardContent>
              </Card>

              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>Stage B: Config Search（配置搜索）</Typography>
                  <Stack spacing={1.2}>
                    <Button variant="outlined" component="label">
                      {stageBFile ? stageBFile.name : "选择 source_zip（迁移后源码包）"}
                      <input hidden type="file" accept=".zip" onChange={(e) => setStageBFile(e.target.files?.[0] || null)} />
                    </Button>

                    <FormControl size="small" fullWidth>
                      <InputLabel>test bench（测试基准）</InputLabel>
                      <Select
                        label="test bench（测试基准）"
                        value={stageB.test_bench}
                        onChange={(e) => applyBench(e.target.value)}
                      >
                        {testBenches.map((bench) => (
                          <MenuItem key={bench.id} value={bench.id}>{bench.name}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>

                    {currentBench && (
                      <Paper variant="outlined" sx={{ p: 1, bgcolor: "#f8fafc" }}>
                        <Typography variant="body2"><b>bench_id:</b> {currentBench.id}</Typography>
                        <Typography variant="body2"><b>target_app:</b> {currentBench.app}</Typography>
                        <Typography variant="body2" color="text.secondary">{currentBench.description || "-"}</Typography>
                      </Paper>
                    )}

                    <Grid container spacing={1}>
                      <Grid item xs={12} sm={6}>{textField("baseline_metric", "baseline_metric（基线指标）")}</Grid>
                      <Grid item xs={12} sm={6}>{textField("baseline_threshold", "baseline_threshold（基线阈值）")}</Grid>
                      <Grid item xs={12} sm={6}>{textField("num_compartments", "num_compartments（隔离域数量）")}</Grid>
                      <Grid item xs={12} sm={6}>{textField("top_k", "top_k（候选数量）")}</Grid>
                      <Grid item xs={12} sm={6}>{textField("host_cores", "host_cores（主机核绑定）")}</Grid>
                      <Grid item xs={12} sm={6}>{textField("wayfinder_cores", "wayfinder_cores（搜索核绑定）")}</Grid>
                      <Grid item xs={12} sm={6}>{textField("test_iterations", "test_iterations（测试轮次）")}</Grid>
                      <Grid item xs={12} sm={6}>{textField("overlay_subdir", "overlay_subdir（压缩包子目录）")}</Grid>
                    </Grid>

                    <Typography variant="body2" color="text.secondary">sudo 已固定启用，不再提供页面开关。</Typography>
                    <Button
                      variant="contained"
                      color="secondary"
                      onClick={submitStageB}
                      disabled={busy}
                      startIcon={busy ? <CircularProgress size={16} color="inherit" /> : null}
                    >
                      开始搜索
                    </Button>
                  </Stack>
                </CardContent>
              </Card>

              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>产物下载</Typography>
                  <List dense>
                    {artifacts.map((rel) => (
                      <ListItem key={rel} disablePadding sx={{ py: 0.3 }}>
                        <ListItemText
                          primary={
                            <Link href={`/api/jobs/${selectedJobId}/download?path=${encodeURIComponent(rel)}`} underline="hover">
                              {rel}
                            </Link>
                          }
                        />
                      </ListItem>
                    ))}
                    {artifacts.length === 0 && <Typography color="text.secondary">(none)</Typography>}
                  </List>
                </CardContent>
              </Card>
            </Stack>
          </Grid>

          <Grid item xs={12} md={8}>
            <Stack spacing={2}>
              <Card variant="outlined">
                <CardContent>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                    <Typography variant="h6" sx={{ flex: 1 }}>Job Console</Typography>
                    <Checkbox
                      checked={isAllSelected}
                      indeterminate={isIndeterminate}
                      onChange={(e) => toggleSelectAll(e.target.checked)}
                    />
                    <Typography variant="body2" color="text.secondary">全选</Typography>
                    <Button size="small" variant="outlined" onClick={deleteSelectedJobs} disabled={busy || selectedIds.length === 0}>批量清除</Button>
                  </Stack>
                  <Divider sx={{ my: 1.5 }} />
                  <Box sx={{ maxHeight: 280, overflow: "auto", pr: 0.5 }}>
                    <Stack spacing={1}>
                      {jobs.map((j) => (
                        <Paper key={j.id} variant="outlined" sx={{ p: 1.2 }}>
                          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                            <Checkbox
                              size="small"
                              checked={selectedIds.includes(j.id)}
                              onChange={(e) => toggleJobSelected(j.id, e.target.checked)}
                            />
                            <Typography fontFamily="JetBrains Mono" fontSize="0.86rem">{j.id}</Typography>
                            <Typography sx={{ flex: 1 }} color="text.secondary">{j.kind}</Typography>
                            <Chip size="small" color={statusColor(j.status)} label={j.status} />
                            <Button size="small" variant="outlined" onClick={() => pickJob(j.id)}>view</Button>
                            <Button
                              size="small"
                              color="error"
                              variant="outlined"
                              disabled={busy || j.status === "running" || j.status === "queued"}
                              onClick={() => deleteOneJob(j.id)}
                            >
                              清除
                            </Button>
                          </Stack>
                        </Paper>
                      ))}
                      {jobs.length === 0 && <Typography color="text.secondary">暂无作业</Typography>}
                    </Stack>
                  </Box>
                </CardContent>
              </Card>

              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>作业详情（含参数）</Typography>
                  {selectedJob ? (
                    <Paper variant="outlined" sx={{ p: 1.2, bgcolor: "#f8fafc" }}>
                      <Stack spacing={1.2}>
                        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                          <Typography variant="subtitle1" sx={{ flex: 1, fontWeight: 700 }}>Job Snapshot</Typography>
                          <Chip size="small" color={statusColor(selectedJob.status)} label={selectedJob.status} />
                        </Stack>

                        <Grid container spacing={1}>
                          <Grid item xs={12} sm={6}>
                            <Paper variant="outlined" sx={{ p: 1, bgcolor: "#ffffff" }}>
                              <Typography variant="caption" color="text.secondary">job_id</Typography>
                              <Typography sx={{ fontFamily: "JetBrains Mono", fontSize: "0.85rem" }}>{selectedJob.id}</Typography>
                            </Paper>
                          </Grid>
                          <Grid item xs={12} sm={6}>
                            <Paper variant="outlined" sx={{ p: 1, bgcolor: "#ffffff" }}>
                              <Typography variant="caption" color="text.secondary">kind</Typography>
                              <Typography sx={{ fontFamily: "JetBrains Mono", fontSize: "0.85rem" }}>{selectedJob.kind}</Typography>
                            </Paper>
                          </Grid>
                          <Grid item xs={12} sm={6}>
                            <Paper variant="outlined" sx={{ p: 1, bgcolor: "#ffffff" }}>
                              <Typography variant="caption" color="text.secondary">return_code</Typography>
                              <Typography sx={{ fontFamily: "JetBrains Mono", fontSize: "0.85rem" }}>{String(selectedJob.return_code)}</Typography>
                            </Paper>
                          </Grid>
                          <Grid item xs={12} sm={6}>
                            <Paper variant="outlined" sx={{ p: 1, bgcolor: "#ffffff" }}>
                              <Typography variant="caption" color="text.secondary">error</Typography>
                              <Typography sx={{ fontFamily: "JetBrains Mono", fontSize: "0.85rem", color: selectedJob.error ? "error.main" : "text.primary" }}>
                                {selectedJob.error || "-"}
                              </Typography>
                            </Paper>
                          </Grid>
                        </Grid>

                        <Paper variant="outlined" sx={{ p: 1, bgcolor: "#0b1220", color: "#d7e3ff" }}>
                          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.6 }}>
                            <Typography variant="caption" sx={{ color: "#9fb8ff", fontWeight: 700 }}>command</Typography>
                            <Box sx={{ flex: 1 }} />
                            <Button size="small" variant="outlined" onClick={() => copyText(commandText, "command")}>复制</Button>
                          </Stack>
                          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "JetBrains Mono" }}>
                            {commandParts.map((part, idx) => (
                              <span key={idx} style={part.style}>{part.text}</span>
                            ))}
                          </pre>
                        </Paper>

                        <Paper variant="outlined" sx={{ p: 1, bgcolor: "#0b1220", color: "#d7e3ff" }}>
                          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.6 }}>
                            <Typography variant="caption" sx={{ color: "#9fb8ff", fontWeight: 700 }}>params</Typography>
                            <Box sx={{ flex: 1 }} />
                            <Button size="small" variant="outlined" onClick={() => copyText(paramText, "params")}>复制</Button>
                          </Stack>
                          <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "JetBrains Mono" }}>
                            {paramParts.map((part, idx) => (
                              <span key={idx} style={part.style}>{part.text}</span>
                            ))}
                          </pre>
                        </Paper>
                      </Stack>
                    </Paper>
                  ) : (
                    <Typography color="text.secondary">请选择作业</Typography>
                  )}
                </CardContent>
              </Card>

              <Card variant="outlined">
                <CardContent>
                  <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                    <Typography variant="h6" sx={{ flex: 1 }}>实时日志</Typography>
                    <Button size="small" variant="outlined" onClick={() => copyText(logText || "", "log")}>复制</Button>
                  </Stack>
                  <Paper
                    ref={logRef}
                    variant="outlined"
                    sx={{ p: 1, bgcolor: "#0b1220", color: "#d7e3ff", height: 420, overflow: "auto" }}
                  >
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "JetBrains Mono" }}>
                      {logText
                        ? ansiLogParts.map((part, idx) => (
                            <span key={idx} style={part.style}>{part.text}</span>
                          ))
                        : "请选择作业"}
                    </pre>
                  </Paper>
                </CardContent>
              </Card>
            </Stack>
          </Grid>
        </Grid>
      </Container>

      <Dialog open={helpOpen} onClose={() => setHelpOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>使用帮助（Markdown）</DialogTitle>
        <DialogContent dividers>
          <Box
            sx={{
              "& h1, & h2, & h3": { mt: 1.2, mb: 1, fontWeight: 700 },
              "& h1": { fontSize: "1.4rem" },
              "& h2": { fontSize: "1.15rem" },
              "& h3": { fontSize: "1rem" },
              "& p": { mb: 1 },
              "& ul": { pl: 2.5, mb: 1 },
              "& li": { mb: 0.4 },
              "& code": { fontFamily: "JetBrains Mono", bgcolor: "#f1f5f9", px: 0.4, borderRadius: 0.5 },
              "& pre": {
                fontFamily: "JetBrains Mono",
                bgcolor: "#0b1220",
                color: "#d7e3ff",
                p: 1,
                borderRadius: 1,
                overflowX: "auto",
              },
            }}
            dangerouslySetInnerHTML={{ __html: helpHtml }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => copyText(HELP_MARKDOWN, "帮助文档 Markdown")}>复制 Markdown</Button>
          <Button variant="contained" onClick={() => setHelpOpen(false)}>关闭</Button>
        </DialogActions>
      </Dialog>
    </ThemeProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
