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
  Typography,
  createTheme,
} = MaterialUI;

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#0f766e" },
    secondary: { main: "#2563eb" },
    background: { default: "#f4f7fb", paper: "#ffffff" },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Noto Sans SC", "Segoe UI", sans-serif',
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
  const ansiLogParts = React.useMemo(() => parseAnsiLogToSpans(logText || ""), [logText]);

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
          <Typography variant="h6" color="primary.main">AutoFlex Workflow Platform</Typography>
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
                      <Typography variant="body2"><b>job_id:</b> <span style={{ fontFamily: "JetBrains Mono" }}>{selectedJob.id}</span></Typography>
                      <Typography variant="body2"><b>kind:</b> {selectedJob.kind}</Typography>
                      <Typography variant="body2"><b>status:</b> {selectedJob.status}</Typography>
                      <Typography variant="body2"><b>return_code:</b> {String(selectedJob.return_code)}</Typography>
                      <Typography variant="body2" sx={{ wordBreak: "break-all" }}><b>command:</b> {selectedJob.command || "-"}</Typography>
                      <Typography variant="body2" color="error.main"><b>error:</b> {selectedJob.error || "-"}</Typography>
                      <Typography variant="subtitle2" sx={{ mt: 1 }}>params:</Typography>
                      <Paper variant="outlined" sx={{ p: 1, mt: 0.5, bgcolor: "#0b1220", color: "#d7e3ff" }}>
                        <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "JetBrains Mono" }}>{JSON.stringify(selectedJob.params || {}, null, 2)}</pre>
                      </Paper>
                    </Paper>
                  ) : (
                    <Typography color="text.secondary">请选择作业</Typography>
                  )}
                </CardContent>
              </Card>

              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>实时日志（可滚动 / 长驻）</Typography>
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
    </ThemeProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
