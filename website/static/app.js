const jobsTable = document.getElementById("jobs-table");
const jobMeta = document.getElementById("job-meta");
const jobLog = document.getElementById("job-log");
const artifactsBox = document.getElementById("job-artifacts");

const refreshBtn = document.getElementById("refresh-jobs");
const wfPortingZipInput = document.getElementById("wf-porting-zip");
const wfPortingSubmitBtn = document.getElementById("wf-porting-submit");

const wfSearchZipInput = document.getElementById("wf-search-zip");
const wfSearchAppInput = document.getElementById("wf-search-app");
const wfSearchBaselineMetricInput = document.getElementById("wf-search-baseline-metric");
const wfSearchBaselineThresholdInput = document.getElementById("wf-search-baseline-threshold");
const wfSearchNumCompInput = document.getElementById("wf-search-num-comp");
const wfSearchHostCoresInput = document.getElementById("wf-search-host-cores");
const wfSearchWayfinderCoresInput = document.getElementById("wf-search-wayfinder-cores");
const wfSearchTestIterationsInput = document.getElementById("wf-search-test-iterations");
const wfSearchTopKInput = document.getElementById("wf-search-top-k");
const wfSearchOverlaySubdirInput = document.getElementById("wf-search-overlay-subdir");
const wfSearchSubmitBtn = document.getElementById("wf-search-submit");

let selectedJobId = null;
let logOffset = 0;
let logComplete = false;

function statusTag(status) {
  return `<span class="status ${status}">${status}</span>`;
}

async function fetchJSON(url, init) {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

function resetLogView() {
  logOffset = 0;
  logComplete = false;
  jobLog.textContent = "";
}

async function loadJobs() {
  const data = await fetchJSON("/api/jobs");
  const rows = data.jobs
    .map((j) => {
      const created = new Date(j.created_at * 1000).toLocaleString();
      return `<tr>
        <td><button class="btn secondary view-btn" data-job-id="${j.id}">view</button></td>
        <td class="mono">${j.id}</td>
        <td>${j.kind}</td>
        <td>${statusTag(j.status)}</td>
        <td>${created}</td>
      </tr>`;
    })
    .join("");

  jobsTable.innerHTML = `<table><thead><tr><th>操作</th><th>job_id</th><th>kind</th><th>status</th><th>created</th></tr></thead><tbody>${rows}</tbody></table>`;

  document.querySelectorAll(".view-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const nextId = btn.getAttribute("data-job-id");
      if (selectedJobId !== nextId) {
        selectedJobId = nextId;
        resetLogView();
      }
      loadJobDetail().catch(console.error);
      streamJobLog().catch(console.error);
    });
  });
}

async function loadJobDetail() {
  if (!selectedJobId) {
    jobMeta.textContent = "请选择作业";
    artifactsBox.textContent = "";
    return;
  }

  const data = await fetchJSON(`/api/jobs/${selectedJobId}`);
  const j = data.job;

  const metaHtml = [
    `<div><strong>job_id:</strong> <span class="mono">${j.id}</span></div>`,
    `<div><strong>kind:</strong> ${j.kind}</div>`,
    `<div><strong>status:</strong> ${statusTag(j.status)}</div>`,
    `<div><strong>return_code:</strong> ${j.return_code ?? "-"}</div>`,
    `<div><strong>command:</strong> <span class="mono">${j.command || "-"}</span></div>`,
    `<div><strong>error:</strong> ${j.error || "-"}</div>`,
    `<div><strong>params:</strong></div>`,
    `<pre>${JSON.stringify(j.params || {}, null, 2)}</pre>`
  ].join("");
  jobMeta.innerHTML = metaHtml;

  const artifacts = (data.artifacts || [])
    .slice(0, 2000)
    .map((rel) => {
      const href = `/api/jobs/${selectedJobId}/download?path=${encodeURIComponent(rel)}`;
      return `<div><a href="${href}">${rel}</a></div>`;
    })
    .join("");
  artifactsBox.innerHTML = artifacts || "(none)";
}

async function streamJobLog() {
  if (!selectedJobId || logComplete) {
    return;
  }

  const data = await fetchJSON(`/api/jobs/${selectedJobId}/log-stream?offset=${logOffset}`);
  if (data.chunk) {
    const atBottom = jobLog.scrollTop + jobLog.clientHeight >= jobLog.scrollHeight - 16;
    jobLog.textContent += data.chunk;
    logOffset = data.offset;
    if (atBottom) {
      jobLog.scrollTop = jobLog.scrollHeight;
    }
  }
  logComplete = Boolean(data.complete);
}

async function submitWorkflowCodePorting() {
  const file = wfPortingZipInput.files && wfPortingZipInput.files[0];
  if (!file) {
    alert("请先上传源码 zip");
    return;
  }

  const form = new FormData();
  form.append("source_zip", file);
  await fetchJSON("/api/workflows/code-porting", { method: "POST", body: form });
  await loadJobs();
}

async function submitWorkflowConfigSearch() {
  const file = wfSearchZipInput.files && wfSearchZipInput.files[0];
  if (!file) {
    alert("请先上传迁移后的源码 zip");
    return;
  }

  const form = new FormData();
  form.append("source_zip", file);
  form.append("app", (wfSearchAppInput.value || "nginx").trim());
  form.append("baseline_metric", (wfSearchBaselineMetricInput.value || "REQ").trim());
  form.append("baseline_threshold", (wfSearchBaselineThresholdInput.value || "45000").trim());
  form.append("num_compartments", (wfSearchNumCompInput.value || "3").trim());
  form.append("host_cores", (wfSearchHostCoresInput.value || "3,4").trim());
  form.append("wayfinder_cores", (wfSearchWayfinderCoresInput.value || "1,2").trim());
  form.append("test_iterations", (wfSearchTestIterationsInput.value || "3").trim());
  form.append("top_k", (wfSearchTopKInput.value || "3").trim());
  form.append("overlay_subdir", (wfSearchOverlaySubdirInput.value || "").trim());

  await fetchJSON("/api/workflows/config-search", { method: "POST", body: form });
  await loadJobs();
}

wfPortingSubmitBtn.addEventListener("click", async () => {
  try {
    await submitWorkflowCodePorting();
  } catch (err) {
    alert(String(err));
  }
});

wfSearchSubmitBtn.addEventListener("click", async () => {
  try {
    await submitWorkflowConfigSearch();
  } catch (err) {
    alert(String(err));
  }
});

refreshBtn.addEventListener("click", async () => {
  try {
    await loadJobs();
    await loadJobDetail();
    await streamJobLog();
  } catch (err) {
    console.error(err);
  }
});

setInterval(async () => {
  try {
    await loadJobs();
    await loadJobDetail();
    await streamJobLog();
  } catch (err) {
    console.error(err);
  }
}, 1500);

loadJobs().catch(console.error);
