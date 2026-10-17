/* Dashboard + read-only copilot for the onboarding prototype. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const sysName = (key) => (window.SYS_NAMES && window.SYS_NAMES[key]) || key;

function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `request failed (${res.status})`);
  }
  return res.json();
}

function tagClass(status) {
  if (["COMPLETED", "SUCCESS", "connected", "RESOLVED"].includes(status)) return "ok";
  if (["SKIPPED_IDEMPOTENT"].includes(status)) return "info";
  if (["PARTIALLY_COMPLETED", "NEEDS_REVIEW", "RETRY_PENDING", "OPEN", "OVERDUE", "FAILED_TEMPORARY"].includes(status)) return "warn";
  if (["FAILED", "FAILED_PERMANENT"].includes(status)) return "err";
  return "info";
}

/* -- tabs ---------------------------------------------------------------- */
function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  if (name.startsWith("sys-")) loadSystem(name.slice(4));
  else if (name === "exceptions") loadExceptions();
  else if (name === "audit") loadAudit();
  else if (name === "tasks") loadTasks();
  else if (name === "ledger") loadLedger();
}

/* -- overview ------------------------------------------------------------ */
async function loadSummary() {
  try {
    const s = await api("/api/summary");
    $("#card-open-exceptions").textContent = s.open_exceptions;
    $("#card-human-review").textContent = s.human_review_pending ? "yes" : "no";
    $("#card-overdue").textContent = s.overdue_tasks;
    $("#card-approaching").textContent = s.approaching_tasks;
    $("#card-failed").textContent = s.failed_operations;
    $("#card-skipped").textContent = s.skipped_operations;
    $("#exceptions-badge").textContent = s.open_exceptions;
  } catch (err) {
    console.error(err);
  }
}

function renderOutcomes(result) {
  const outcomes = result.outcomes || [];
  const rows = outcomes
    .map(
      (o) => `<tr>
        <td class="mono">${esc(sysName(o.target))}</td>
        <td>${esc(o.operation)}</td>
        <td><span class="tag ${tagClass(o.status)}">${esc(o.status)}</span></td>
        <td>${esc(o.attempts)}</td>
        <td class="audit-clamp">${esc(o.detail)}</td>
      </tr>`
    )
    .join("");
  const blocked = Object.entries(result.blocked || {})
    .map(([target, fields]) => `<li>${esc(sysName(target))}: ${esc(fields.join(", "))}</li>`)
    .join("");
  return `
    <h3>${esc(result.overall_status)} &mdash; ${esc(result.message)}</h3>
    <div class="row-sub">event ${esc(result.event_id)} &middot; employee ${esc(result.employee_id)} &middot;
      source ${esc(sysName(result.source))} &middot; changed: ${esc((result.changed_fields || []).join(", ") || "-")}</div>
    ${outcomes.length ? `<table class="record-table"><thead><tr><th>System</th><th>Operation</th><th>Status</th><th>Attempts</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>` : ""}
    ${blocked ? `<p class="row-sub">Blocked systems:</p><ul>${blocked}</ul>` : ""}
    ${result.exceptions && result.exceptions.length ? `<p class="row-sub">Exceptions raised: ${esc(result.exceptions.join(", "))}</p>` : ""}
  `;
}

async function runScenario(key, button) {
  const box = $("#scenario-result");
  button.disabled = true;
  box.classList.remove("hidden");
  box.innerHTML = `<p class="hint">Running "${esc(key)}"...</p>`;
  try {
    const result = await api(`/api/scenarios/${encodeURIComponent(key)}`, { method: "POST" });
    box.innerHTML = renderOutcomes(result);
  } catch (err) {
    box.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  } finally {
    button.disabled = false;
    loadSummary();
    loadSystems();
  }
}

/* -- systems (one tab per third-party app) ------------------------------- */
function updateBadge(key, count) {
  const el = document.getElementById(`badge-${key}`);
  if (el) el.textContent = count;
}

async function loadSystems() {
  try {
    const data = await api("/api/systems");
    data.systems.forEach((s) => {
      if (s.kind === "target" || s.kind === "source") updateBadge(s.key, s.record_count);
    });
    return data.systems;
  } catch (err) {
    console.error(err);
    return [];
  }
}

function kvCell(record, skip = ["employee_id", "event_id", "operation_key"]) {
  return Object.entries(record)
    .filter(([k]) => !skip.includes(k))
    .map(([k, v]) => `<span class="kv">${esc(k)}=${esc(v)}</span>`)
    .join(" ");
}

function renderSystem(sys) {
  if (sys.kind === "ai") {
    const actions = (sys.allowed_actions || []).map((a) => `<span class="tag info">${esc(a)}</span>`).join(" ");
    const rows = (sys.records || [])
      .map(
        (r) => `<tr>
          <td class="mono">${esc(r.exception_id)}</td>
          <td>${esc(r.employee_id)}</td>
          <td>${esc(r.exception_type)}</td>
          <td>${esc(r.field_name || "-")}</td>
          <td>${esc(r.recommended_action)}</td>
          <td>${r.ai_used ? "yes" : "no"}</td>
          <td class="audit-clamp">${esc(r.reason)}</td>
        </tr>`
      )
      .join("");
    return `
      <div class="row">
        <div class="row-top">
          <span class="row-title">Mode: ${esc(sys.mode)}</span>
          <span class="tag ${sys.enabled ? "ok" : "muted"}">${sys.enabled ? "OpenAI" : "deterministic fallback"}</span>
        </div>
        <div class="row-sub">model: ${esc(sys.model || "n/a")} &middot; advisory only (never changes records)</div>
        <div class="row-sub" style="margin-top:8px">Allowed recommendations: ${actions}</div>
      </div>
      ${rows ? `<table class="record-table"><thead><tr><th>Exception</th><th>Employee</th><th>Type</th><th>Field</th><th>Recommended</th><th>AI used</th><th>Reason</th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="hint">No exception classifications yet.</p>`}
    `;
  }

  if (sys.kind === "orchestrator") {
    return `<div class="row"><div class="row-sub">${esc(sys.note)}</div></div>`;
  }

  const records = sys.records || [];
  if (!records.length) {
    return `<p class="hint">No records in ${esc(sys.display_name)} yet. Run a scenario from the Overview tab.</p>`;
  }

  if (sys.kind === "source") {
    const rows = records
      .map(
        (r) => `<tr>
          <td class="mono">${esc(r.event_id)}</td>
          <td>${esc(r.employee_id)}</td>
          <td>${esc(r.event_type)}</td>
          <td>${esc((r.changed_fields || []).join(", ") || "-")}</td>
          <td>${esc(r.approved)}</td>
          <td class="mono">${esc(r.received_at || "")}</td>
        </tr>`
      )
      .join("");
    return `<table class="record-table"><thead><tr><th>Event</th><th>Employee</th><th>Type</th><th>Changed fields</th><th>Approved</th><th>Received</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  const rows = records
    .map(
      (r) => `<tr>
        <td class="mono">${esc(r.employee_id)}</td>
        <td class="mono">${esc(r.event_id || "-")}</td>
        <td class="audit-clamp">${kvCell(r)}</td>
      </tr>`
    )
    .join("");
  return `<table class="record-table"><thead><tr><th>Employee</th><th>Event</th><th>Stored data</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function loadSystem(key) {
  const body = $(`#sys-body-${key}`);
  if (!body) return;
  try {
    const sys = await api(`/api/systems/${encodeURIComponent(key)}`);
    const status = $(`#sys-status-${key}`);
    status.textContent = sys.connected ? "connected" : "not connected";
    status.className = "tag " + (sys.connected ? "ok" : "muted");
    $(`#sys-count-${key}`).textContent = `${sys.record_count} record${sys.record_count === 1 ? "" : "s"}`;
    if (sys.kind === "target" || sys.kind === "source") updateBadge(key, sys.record_count);
    body.innerHTML = renderSystem(sys);
  } catch (err) {
    body.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  }
}

/* -- exceptions ---------------------------------------------------------- */
async function loadExceptions() {
  const data = await api("/api/exceptions");
  const list = $("#exceptions-list");
  if (!data.exceptions.length) {
    list.innerHTML = `<p class="hint">No exceptions recorded.</p>`;
    return;
  }
  list.innerHTML = data.exceptions
    .map((e) => {
      const resolveBox = e.status === "OPEN"
        ? `<div class="row-actions">
             <input type="text" placeholder="Your name" id="by-${esc(e.exception_id)}" />
             <input type="text" placeholder="Resolution note" id="res-${esc(e.exception_id)}" />
             <button type="button" onclick="resolveException('${esc(e.exception_id)}')">Resolve</button>
           </div>`
        : `<div class="row-sub">resolved by ${esc(e.resolved_by)}: ${esc(e.resolution)}</div>`;
      return `<div class="row">
        <div class="row-top">
          <span class="row-title mono">${esc(e.exception_id)} &middot; ${esc(e.exception_type)}</span>
          <span class="tag ${tagClass(e.status)}">${esc(e.status)}</span>
        </div>
        <div class="row-sub">employee ${esc(e.employee_id)} &middot; event ${esc(e.event_id)} &middot;
          field ${esc(e.field_name || "-")} &middot; action ${esc(e.recommended_action || "-")} &middot;
          ai_used ${esc(e.ai_used)}</div>
        <div class="row-sub">${esc(e.reason)}</div>
        ${resolveBox}
      </div>`;
    })
    .join("");
}

async function resolveException(id) {
  const by = $(`#by-${id}`)?.value || "operator";
  const resolution = $(`#res-${id}`)?.value || "resolved via dashboard";
  await api(`/api/exceptions/${encodeURIComponent(id)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ by, resolution }),
  });
  await loadExceptions();
  loadSummary();
}

/* -- audit --------------------------------------------------------------- */
async function loadAudit() {
  const data = await api("/api/audit?limit=50");
  const list = $("#audit-list");
  if (!data.entries.length) {
    list.innerHTML = `<p class="hint">Audit trail is empty. Run a scenario first.</p>`;
    return;
  }
  const rows = data.entries
    .map((e) => {
      if (e.entry_type === "exception") {
        return `<tr>
          <td>${esc(e.processing_timestamp)}</td>
          <td><span class="tag info">exception</span></td>
          <td>${esc(e.exception_id)}</td>
          <td>${esc(e.action)} by ${esc(e.resolved_by || "-")}</td>
          <td class="audit-clamp">${esc(e.resolution || e.exception_type)}</td>
        </tr>`;
      }
      const changes = Object.entries(e.changes || {})
        .map(([k, v]) => `${k}: ${v.previous} -> ${v.new}`)
        .join("; ");
      return `<tr>
        <td>${esc(e.processing_timestamp)}</td>
        <td><span class="tag ${tagClass(e.overall_status)}">${esc(e.overall_status)}</span></td>
        <td>${esc(e.employee_id)} / ${esc(e.event_id)}</td>
        <td>${esc((e.changed_fields || []).join(", ") || "-")}</td>
        <td class="audit-clamp">${esc(changes || e.message)}</td>
      </tr>`;
    })
    .join("");
  list.innerHTML = `<table class="record-table"><thead><tr><th>When</th><th>Status</th><th>Employee / event</th><th>Changed</th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/* -- tasks --------------------------------------------------------------- */
async function loadTasks() {
  const data = await api("/api/tasks");
  const monitor = data.monitor || {};
  $("#monitor-summary").innerHTML = `
    <span class="tag warn">approaching ${esc(monitor.approaching ?? 0)}</span>
    <span class="tag err">overdue ${esc(monitor.overdue ?? 0)}</span>
    <span class="tag info">as of ${esc(monitor.as_of || "-")}</span>`;
  if (!data.tasks.length) {
    $("#tasks-list").innerHTML = `<p class="hint">No tasks tracked.</p>`;
    return;
  }
  const rows = data.tasks
    .map(
      (t) => `<tr>
        <td>${esc(t.name)}</td>
        <td class="mono">${esc(t.employee_id)}</td>
        <td>${esc(t.due_date)}</td>
        <td><span class="tag ${t.status === "COMPLETE" ? "ok" : "info"}">${esc(t.status)}</span></td>
        <td>${esc(t.owner)}</td>
      </tr>`
    )
    .join("");
  $("#tasks-list").innerHTML = `<table class="record-table"><thead><tr><th>Task</th><th>Employee</th><th>Due</th><th>Status</th><th>Owner</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function runMonitor() {
  const report = await api("/api/monitor/run", { method: "POST" });
  $("#monitor-summary").innerHTML += `<span class="tag ok">reminders sent ${esc(report.reminders_sent)}</span>`;
  loadTasks();
}

/* -- ledger -------------------------------------------------------------- */
async function loadLedger() {
  const data = await api("/api/ledger");
  const list = $("#ledger-list");
  if (!data.ledger.length) {
    list.innerHTML = `<p class="hint">Ledger is empty. Run a scenario first.</p>`;
    return;
  }
  const rows = data.ledger
    .map(
      (r) => `<tr>
        <td class="mono">${esc(r.employee_id)}</td>
        <td>${esc(sysName(r.target))}</td>
        <td>${esc(r.operation)}</td>
        <td><span class="tag ${tagClass(r.status)}">${esc(r.status)}</span></td>
        <td>${esc(r.attempts)}</td>
        <td class="audit-clamp">${esc(r.last_error || "")}</td>
      </tr>`
    )
    .join("");
  list.innerHTML = `<table class="record-table"><thead><tr><th>Employee</th><th>System</th><th>Operation</th><th>Status</th><th>Attempts</th><th>Last error</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/* -- chat ---------------------------------------------------------------- */
const chatHistory = [];

function appendChat(role, text, meta) {
  const log = $("#chat-log");
  if (!log) return;
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = `<div class="bubble">${esc(text)}${meta ? `<span class="meta">${esc(meta)}</span>` : ""}</div>`;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

async function sendChat(message) {
  appendChat("user", message);
  chatHistory.push({ role: "user", content: message });
  appendChat("assistant", "…");
  const pending = $("#chat-log").lastElementChild;
  try {
    const res = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, history: chatHistory.slice(0, -1) }),
    });
    pending.remove();
    const meta = `${res.ai_used ? "AI" : "fallback"} · intent: ${res.intent}${res.note ? " · " + res.note : ""}`;
    appendChat("assistant", res.reply, meta);
    chatHistory.push({ role: "assistant", content: res.reply });
  } catch (err) {
    pending.remove();
    appendChat("assistant", `Sorry, I couldn't answer: ${err.message}`);
  }
}

/* -- wiring -------------------------------------------------------------- */
async function resetDemo() {
  if (!window.confirm("Reset all demo state (ledger, exceptions, audit, tasks)?")) return;
  await api("/api/reset", { method: "POST" });
  $("#scenario-result").classList.add("hidden");
  refreshAll();
}

function refreshAll() {
  loadSummary();
  loadSystems();
  const active = $(".tab.active")?.dataset.tab;
  if (!active) return;
  if (active.startsWith("sys-")) loadSystem(active.slice(4));
  else if (active === "exceptions") loadExceptions();
  else if (active === "audit") loadAudit();
  else if (active === "tasks") loadTasks();
  else if (active === "ledger") loadLedger();
}

document.addEventListener("DOMContentLoaded", () => {
  $("#tabs").addEventListener("click", (ev) => {
    const tab = ev.target.closest(".tab");
    if (tab) switchTab(tab.dataset.tab);
  });
  $("#refresh-btn").addEventListener("click", refreshAll);
  $("#reset-btn").addEventListener("click", resetDemo);
  const monitorBtn = $("#run-monitor-btn");
  if (monitorBtn) monitorBtn.addEventListener("click", runMonitor);
  $$(".scenario").forEach((btn) =>
    btn.addEventListener("click", () => runScenario(btn.dataset.scenario, btn))
  );
  const chatForm = $("#chat-form");
  if (chatForm) {
    chatForm.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const input = $("#chat-input");
      const value = input.value.trim();
      if (!value) return;
      input.value = "";
      sendChat(value);
    });
  }
  refreshAll();
});

async function ingestEvent() {
  const event_id = $("#evt-event_id").value.trim();
  const source = $("#evt-source").value.trim() || "ashby";
  const employee_id = $("#evt-employee_id").value.trim();
  const event_type = $("#evt-event_type").value.trim() || "employee_updated";
  const changed_str = $("#evt-changed_fields").value.trim();
  const received_at = $("#evt-received_at").value.trim() || null;
  const name = $("#evt-name").value.trim();
  const start_date = $("#evt-start_date").value.trim();
  const location = $("#evt-location").value.trim();
  const address = $("#evt-address").value.trim();
  const dept = $("#evt-dept").value.trim();
  const job_title = $("#evt-job_title").value.trim();

  if (!event_id || !employee_id) {
    alert("event_id and employee_id required");
    return;
  }
  let changed = [];
  if (changed_str) {
    changed = changed_str.split(",").map((s) => s.trim()).filter((s) => s);
  }
  const employee = {};
  if (name) employee.name = name;
  if (start_date) employee.start_date = start_date;
  if (location) employee.location = location;
  if (location) employee.work_location = location;
  if (address) employee.address = address;
  if (dept) employee.department = dept;
  if (job_title) employee.job_title = job_title;

  const payload = {
    event_id,
    source,
    employee_id,
    event_type,
    changed_fields: changed,
    employee,
    approved: true,
  };
  if (received_at) payload.received_at = received_at;

  const box = $("#ingest-result");
  box.classList.remove("hidden");
  box.innerHTML = `<p class="hint">Ingesting...</p>`;
  try {
    const res = await api("/api/ingest/event", { method: "POST", body: payload });
    box.innerHTML = renderOutcomes(res);
    loadSummary();
    loadSystems();
    loadExceptions();
    loadAudit();
    loadLedger();
  } catch (err) {
    box.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  }
}

  const ingestBtn = $("#ingest-event-btn");
  if (ingestBtn) ingestBtn.addEventListener("click", ingestEvent);

async function feedDirect_workday() {
  const emp = $("#feed-workday-employee_id").value.trim();
  if (!emp) { alert("employee_id required"); return; }
  const eid = $("#feed-workday-event_id").value.trim() || null;
  const opk = $("#feed-workday-opkey").value.trim() || null;
  let data = {};
  const raw = $("#feed-workday-data").value.trim();
  if (raw) {
    try { data = JSON.parse(raw); } catch (e) { alert("Invalid JSON in data"); return; }
  }
  const box = $("#feed-workday-result");
  box.classList.remove("hidden");
  box.innerHTML = `<p class="hint">Writing...</p>`;
  try {
    const res = await api(`/api/portals/workday/write`, { method: "POST", body: { employee_id: emp, event_id: eid, operation_key: opk, data } });
    box.innerHTML = `<pre class="mono">${esc(JSON.stringify(res, null, 2))}</pre>`;
    loadSummary();
    loadSystems();
  } catch (err) {
    box.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  }
}

async function feedDirect_okta() {
  const emp = $("#feed-okta-employee_id").value.trim();
  if (!emp) { alert("employee_id required"); return; }
  const eid = $("#feed-okta-event_id").value.trim() || null;
  const opk = $("#feed-okta-opkey").value.trim() || null;
  let data = {};
  const raw = $("#feed-okta-data").value.trim();
  if (raw) {
    try { data = JSON.parse(raw); } catch (e) { alert("Invalid JSON in data"); return; }
  }
  const box = $("#feed-okta-result");
  box.classList.remove("hidden");
  box.innerHTML = `<p class="hint">Writing...</p>`;
  try {
    const res = await api(`/api/portals/okta/write`, { method: "POST", body: { employee_id: emp, event_id: eid, operation_key: opk, data } });
    box.innerHTML = `<pre class="mono">${esc(JSON.stringify(res, null, 2))}</pre>`;
    loadSummary();
    loadSystems();
  } catch (err) {
    box.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  }
}

async function feedDirect_google_workspace() {
  const emp = $("#feed-google_workspace-employee_id").value.trim();
  if (!emp) { alert("employee_id required"); return; }
  const eid = $("#feed-google_workspace-event_id").value.trim() || null;
  const opk = $("#feed-google_workspace-opkey").value.trim() || null;
  let data = {};
  const raw = $("#feed-google_workspace-data").value.trim();
  if (raw) {
    try { data = JSON.parse(raw); } catch (e) { alert("Invalid JSON in data"); return; }
  }
  const box = $("#feed-google_workspace-result");
  box.classList.remove("hidden");
  box.innerHTML = `<p class="hint">Writing...</p>`;
  try {
    const res = await api(`/api/portals/google_workspace/write`, { method: "POST", body: { employee_id: emp, event_id: eid, operation_key: opk, data } });
    box.innerHTML = `<pre class="mono">${esc(JSON.stringify(res, null, 2))}</pre>`;
    loadSummary();
    loadSystems();
  } catch (err) {
    box.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  }
}

async function feedDirect_slack() {
  const emp = $("#feed-slack-employee_id").value.trim();
  if (!emp) { alert("employee_id required"); return; }
  const eid = $("#feed-slack-event_id").value.trim() || null;
  const opk = $("#feed-slack-opkey").value.trim() || null;
  let data = {};
  const raw = $("#feed-slack-data").value.trim();
  if (raw) {
    try { data = JSON.parse(raw); } catch (e) { alert("Invalid JSON in data"); return; }
  }
  const box = $("#feed-slack-result");
  box.classList.remove("hidden");
  box.innerHTML = `<p class="hint">Writing...</p>`;
  try {
    const res = await api(`/api/portals/slack/write`, { method: "POST", body: { employee_id: emp, event_id: eid, operation_key: opk, data } });
    box.innerHTML = `<pre class="mono">${esc(JSON.stringify(res, null, 2))}</pre>`;
    loadSummary();
    loadSystems();
  } catch (err) {
    box.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  }
}

async function feedDirect_equipment() {
  const emp = $("#feed-equipment-employee_id").value.trim();
  if (!emp) { alert("employee_id required"); return; }
  const eid = $("#feed-equipment-event_id").value.trim() || null;
  const opk = $("#feed-equipment-opkey").value.trim() || null;
  let data = {};
  const raw = $("#feed-equipment-data").value.trim();
  if (raw) {
    try { data = JSON.parse(raw); } catch (e) { alert("Invalid JSON in data"); return; }
  }
  const box = $("#feed-equipment-result");
  box.classList.remove("hidden");
  box.innerHTML = `<p class="hint">Writing...</p>`;
  try {
    const res = await api(`/api/portals/equipment/write`, { method: "POST", body: { employee_id: emp, event_id: eid, operation_key: opk, data } });
    box.innerHTML = `<pre class="mono">${esc(JSON.stringify(res, null, 2))}</pre>`;
    loadSummary();
    loadSystems();
  } catch (err) {
    box.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  }
}

async function feedDirect_cohort_tracker() {
  const emp = $("#feed-cohort_tracker-employee_id").value.trim();
  if (!emp) { alert("employee_id required"); return; }
  const eid = $("#feed-cohort_tracker-event_id").value.trim() || null;
  const opk = $("#feed-cohort_tracker-opkey").value.trim() || null;
  let data = {};
  const raw = $("#feed-cohort_tracker-data").value.trim();
  if (raw) {
    try { data = JSON.parse(raw); } catch (e) { alert("Invalid JSON in data"); return; }
  }
  const box = $("#feed-cohort_tracker-result");
  box.classList.remove("hidden");
  box.innerHTML = `<p class="hint">Writing...</p>`;
  try {
    const res = await api(`/api/portals/cohort_tracker/write`, { method: "POST", body: { employee_id: emp, event_id: eid, operation_key: opk, data } });
    box.innerHTML = `<pre class="mono">${esc(JSON.stringify(res, null, 2))}</pre>`;
    loadSummary();
    loadSystems();
  } catch (err) {
    box.innerHTML = `<p class="tag err">${esc(err.message)}</p>`;
  }
}

  const fb_workday = $("#feed-workday-btn"); if (fb_workday) fb_workday.addEventListener("click", feedDirect_workday);
  const fb_okta = $("#feed-okta-btn"); if (fb_okta) fb_okta.addEventListener("click", feedDirect_okta);
  const fb_google_workspace = $("#feed-google_workspace-btn"); if (fb_google_workspace) fb_google_workspace.addEventListener("click", feedDirect_google_workspace);
  const fb_slack = $("#feed-slack-btn"); if (fb_slack) fb_slack.addEventListener("click", feedDirect_slack);
  const fb_equipment = $("#feed-equipment-btn"); if (fb_equipment) fb_equipment.addEventListener("click", feedDirect_equipment);
  const fb_cohort_tracker = $("#feed-cohort_tracker-btn"); if (fb_cohort_tracker) fb_cohort_tracker.addEventListener("click", feedDirect_cohort_tracker);