/*
 * Ops Console: eight admin/analyst-only panels, each a thin wrapper over an
 * existing (or, for jobs-list/log/graph, newly-added) admin API endpoint --
 * per internal planning's Ops Console phase. No section fabricates
 * data; every render call maps 1:1 to a WardlineApi method.
 */
(function () {
  const toastStack = document.getElementById("toastStack");
  function toast(message, variant = "") {
    const el = document.createElement("div");
    el.className = `toast ${variant ? `toast--${variant}` : ""}`.trim();
    el.textContent = message;
    toastStack.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // --- Connection settings modal -----------------------------------------

  const connModal = document.getElementById("settingsModal");
  const connLabel = document.getElementById("connLabel");
  const connDot = document.getElementById("connDot");

  function openModal() {
    document.getElementById("baseUrlInput").value = WardlineApi.getConfig().baseUrl;
    document.getElementById("apiKeyInput").value = WardlineApi.getConfig().apiKey;
    connModal.hidden = false;
  }
  function closeModal() {
    connModal.hidden = true;
  }
  document.getElementById("connStatusBtn").addEventListener("click", openModal);
  document.querySelectorAll("[data-close-modal]").forEach((btn) => btn.addEventListener("click", closeModal));

  document.getElementById("settingsSaveBtn").addEventListener("click", async () => {
    WardlineApi.setConfig({
      baseUrl: document.getElementById("baseUrlInput").value.trim(),
      apiKey: document.getElementById("apiKeyInput").value.trim(),
    });
    closeModal();
    await checkAccess();
  });

  // --- Access gate ---------------------------------------------------------

  const accessBanner = document.getElementById("accessBanner");
  let hasAccess = false;

  async function checkAccess() {
    if (!WardlineApi.isConfigured()) {
      hasAccess = false;
    } else {
      try {
        const me = await WardlineApi.me();
        hasAccess = me.role === "admin" || me.role === "analyst";
      } catch {
        hasAccess = false;
      }
    }
    accessBanner.hidden = hasAccess;
    connLabel.textContent = hasAccess ? "Connected" : "Not connected";
    connDot.className = `status-dot ${hasAccess ? "status-dot--ok" : "status-dot--bad"}`;
    document.querySelectorAll(".ops-nav__item").forEach((btn) => (btn.disabled = !hasAccess));
    if (hasAccess) loadPanel(activePanel);
  }

  // --- Nav / panel switching ------------------------------------------------

  let activePanel = "jobs";
  const loaders = {
    jobs: loadJobs,
    audit: loadAudit,
    "entity-review": loadEntityReview,
    engagements: loadEngagements,
    users: loadUsers,
    "kill-switch": loadKillSwitch,
    iceberg: loadIceberg,
    graph: () => {}, // search-driven, nothing to load on entry
  };

  function loadPanel(name) {
    if (!hasAccess) return;
    (loaders[name] || (() => {}))();
  }

  document.querySelectorAll(".ops-nav__item").forEach((btn) => {
    btn.addEventListener("click", () => {
      activePanel = btn.dataset.panel;
      document.querySelectorAll(".ops-nav__item").forEach((b) => b.classList.toggle("ops-nav__item--active", b === btn));
      document.querySelectorAll(".ops-panel").forEach((p) => (p.hidden = p.dataset.panel !== activePanel));
      stopLogPolling(); // leaving Jobs (or switching jobs) shouldn't keep polling in the background
      loadPanel(activePanel);
    });
  });
  document.querySelector('.ops-nav__item[data-panel="jobs"]').classList.add("ops-nav__item--active");
  document.getElementById("panel-jobs").hidden = false;

  // --- Jobs + live log -------------------------------------------------------

  let logPollTimer = null;
  let logLastId = 0;
  let logJobId = null;

  function stopLogPolling() {
    clearInterval(logPollTimer);
    logPollTimer = null;
  }

  async function loadJobs() {
    const status = document.getElementById("jobsStatusFilter").value;
    let jobs;
    try {
      jobs = await WardlineApi.listJobs({ status });
    } catch (err) {
      toast(err.message, "danger");
      return;
    }
    const table = document.getElementById("jobsTable");
    table.innerHTML = `
      <thead><tr><th>Connector</th><th>Status</th><th>Created</th><th>Finished</th><th></th></tr></thead>
      <tbody>${jobs
        .map(
          (j) => `
        <tr>
          <td>${esc(j.connector_name)}</td>
          <td>${esc(j.status)}</td>
          <td>${esc(j.created_at)}</td>
          <td>${esc(j.finished_at || "—")}</td>
          <td><button class="btn btn--secondary btn--sm" data-job-id="${esc(j.id)}" data-job-status="${esc(j.status)}">View log</button></td>
        </tr>`
        )
        .join("")}</tbody>`;
    table.querySelectorAll("[data-job-id]").forEach((btn) => {
      btn.addEventListener("click", () => openJobLog(btn.dataset.jobId, btn.dataset.jobStatus));
    });
  }
  document.getElementById("jobsRefreshBtn").addEventListener("click", loadJobs);
  document.getElementById("jobsStatusFilter").addEventListener("change", loadJobs);

  async function openJobLog(jobId, status) {
    stopLogPolling();
    logJobId = jobId;
    logLastId = 0;
    document.getElementById("jobLogCard").hidden = false;
    document.getElementById("jobLogTitle").textContent = `Live log — ${jobId}`;
    const output = document.getElementById("jobLogOutput");
    output.textContent = "";
    await fetchLogLines();
    if (status === "running" || status === "pending") {
      logPollTimer = setInterval(pollJobLog, 2000);
    }
  }
  document.getElementById("jobLogCloseBtn").addEventListener("click", () => {
    stopLogPolling();
    document.getElementById("jobLogCard").hidden = true;
  });

  async function fetchLogLines() {
    let lines;
    try {
      lines = await WardlineApi.getJobLog({ jobId: logJobId, afterId: logLastId });
    } catch {
      return;
    }
    if (lines.length === 0) return;
    const output = document.getElementById("jobLogOutput");
    for (const line of lines) {
      const span = document.createElement("span");
      span.className = line.level === "error" ? "ops-terminal__line--error" : "";
      span.textContent = `[${line.created_at}] ${line.message}\n`;
      output.appendChild(span);
      logLastId = line.id;
    }
    output.scrollTop = output.scrollHeight;
  }

  async function pollJobLog() {
    await fetchLogLines();
    try {
      const job = await WardlineApi.getJobStatus({ jobId: logJobId });
      if (job.status !== "running" && job.status !== "pending") stopLogPolling();
    } catch {
      stopLogPolling();
    }
  }

  // --- Audit -----------------------------------------------------------------

  async function loadAudit() {
    const user = document.getElementById("auditUserFilter").value.trim();
    let events;
    try {
      events = await WardlineApi.audit(user ? { user } : {});
    } catch (err) {
      toast(err.message, "danger");
      return;
    }
    document.getElementById("auditTable").innerHTML = `
      <thead><tr><th>Time</th><th>Type</th><th>User</th><th>Payload</th></tr></thead>
      <tbody>${events
        .map(
          (e) => `<tr><td>${esc(e.created_at)}</td><td>${esc(e.event_type)}</td><td>${esc(e.user_id)}</td><td>${esc(JSON.stringify(e.payload))}</td></tr>`
        )
        .join("")}</tbody>`;
  }
  document.getElementById("auditRefreshBtn").addEventListener("click", loadAudit);

  // --- Entity review -----------------------------------------------------------

  async function loadEntityReview() {
    let queue;
    try {
      queue = await WardlineApi.getEntityReviewQueue();
    } catch (err) {
      toast(err.message, "danger");
      return;
    }
    const table = document.getElementById("entityReviewTable");
    table.innerHTML = `
      <thead><tr><th>Entity A</th><th>Entity B</th><th>Score</th><th></th></tr></thead>
      <tbody>${queue
        .map(
          (r) => `
        <tr>
          <td>${esc(r.entity_a?.name)}</td>
          <td>${esc(r.entity_b?.name)}</td>
          <td>${esc(r.score)}</td>
          <td>
            <button class="btn btn--secondary btn--sm" data-review-id="${esc(r.id)}" data-decision="merged">Merge</button>
            <button class="btn btn--secondary btn--sm" data-review-id="${esc(r.id)}" data-decision="rejected">Reject</button>
          </td>
        </tr>`
        )
        .join("")}</tbody>`;
    table.querySelectorAll("[data-review-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await WardlineApi.decideEntityReview({ reviewId: btn.dataset.reviewId, decision: btn.dataset.decision });
          toast(`Marked ${btn.dataset.decision}`);
          loadEntityReview();
        } catch (err) {
          toast(err.message, "danger");
        }
      });
    });
  }
  document.getElementById("entityReviewRefreshBtn").addEventListener("click", loadEntityReview);

  // --- Engagements --------------------------------------------------------------

  async function loadEngagements() {
    let rows;
    try {
      rows = await WardlineApi.listEngagements();
    } catch (err) {
      toast(err.message, "danger");
      return;
    }
    const table = document.getElementById("engagementsTable");
    table.innerHTML = `
      <thead><tr><th>Target</th><th>Scope</th><th>Valid until</th><th>Active</th><th></th></tr></thead>
      <tbody>${rows
        .map(
          (e) => `
        <tr>
          <td>${esc(e.target)}</td>
          <td>${esc(e.scope_note)}</td>
          <td>${esc(e.valid_until)}</td>
          <td>${e.active ? "yes" : "no"}</td>
          <td>${e.active ? `<button class="btn btn--secondary btn--sm" data-engagement-id="${esc(e.id)}">Revoke</button>` : ""}</td>
        </tr>`
        )
        .join("")}</tbody>`;
    table.querySelectorAll("[data-engagement-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await WardlineApi.revokeEngagement({ engagementId: btn.dataset.engagementId });
          loadEngagements();
        } catch (err) {
          toast(err.message, "danger");
        }
      });
    });
  }

  document.getElementById("engagementForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await WardlineApi.createEngagement({
        target: document.getElementById("engTarget").value,
        scopeNote: document.getElementById("engScopeNote").value,
        evidenceRef: document.getElementById("engEvidenceRef").value,
        validFrom: new Date(document.getElementById("engValidFrom").value).toISOString(),
        validUntil: new Date(document.getElementById("engValidUntil").value).toISOString(),
      });
      event.target.reset();
      toast("Engagement created");
      loadEngagements();
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  // --- Users -----------------------------------------------------------------

  async function loadUsers() {
    let users;
    try {
      users = await WardlineApi.listUsers();
    } catch (err) {
      toast(err.message, "danger");
      return;
    }
    const table = document.getElementById("usersTable");
    table.innerHTML = `
      <thead><tr><th>Email</th><th>Role</th><th>Revoked</th><th></th></tr></thead>
      <tbody>${users
        .map(
          (u) => `
        <tr>
          <td>${esc(u.email)}</td>
          <td>${esc(u.role)}</td>
          <td>${u.revoked ? "yes" : "no"}</td>
          <td>${u.revoked ? "" : `<button class="btn btn--secondary btn--sm" data-user-id="${esc(u.id)}">Revoke</button>`}</td>
        </tr>`
        )
        .join("")}</tbody>`;
    table.querySelectorAll("[data-user-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await WardlineApi.revokeAdminUser({ userId: btn.dataset.userId });
          loadUsers();
        } catch (err) {
          toast(err.message, "danger");
        }
      });
    });
  }

  document.getElementById("userForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const mode = event.submitter?.dataset.mode || "create";
    const email = document.getElementById("userEmail").value;
    const role = document.getElementById("userRole").value;
    try {
      if (mode === "invite") {
        await WardlineApi.inviteAdminUser({ email, role });
        toast(`Invite sent to ${email}`);
      } else {
        const result = await WardlineApi.createUser({ email, role });
        toast(`Created — API key: ${result.api_key}`);
      }
      event.target.reset();
      loadUsers();
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  // --- Kill switch --------------------------------------------------------------

  async function loadKillSwitch() {
    try {
      const { enabled } = await WardlineApi.getKillSwitch();
      document.getElementById("killSwitchState").textContent = enabled ? "ENABLED (queries frozen)" : "disabled";
    } catch (err) {
      toast(err.message, "danger");
    }
  }
  document.getElementById("killSwitchToggleBtn").addEventListener("click", async () => {
    const current = document.getElementById("killSwitchState").textContent.startsWith("ENABLED");
    const next = !current;
    if (next && !confirm("This freezes /v1/query for every caller. Continue?")) return;
    try {
      await WardlineApi.setKillSwitch({ enabled: next });
      loadKillSwitch();
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  // --- Iceberg exports -----------------------------------------------------------

  async function loadIceberg() {
    let receipts;
    try {
      receipts = await WardlineApi.listExportReceipts();
    } catch (err) {
      toast(err.message, "danger");
      return;
    }
    document.getElementById("icebergTable").innerHTML = `
      <thead><tr><th>Snapshot</th><th>Rows</th><th>Range start</th><th>Range end</th><th>Created</th></tr></thead>
      <tbody>${receipts
        .map(
          (r) => `<tr><td>${esc(r.snapshot_id)}</td><td>${esc(r.row_count)}</td><td>${esc(r.time_range_start)}</td><td>${esc(r.time_range_end)}</td><td>${esc(r.created_at)}</td></tr>`
        )
        .join("")}</tbody>`;
  }
  document.getElementById("icebergExportBtn").addEventListener("click", async () => {
    try {
      await WardlineApi.triggerIcebergExport();
      toast("Export triggered");
      loadIceberg();
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  // --- Graph browser --------------------------------------------------------------

  document.getElementById("graphSearchForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("graphSearchName").value;
    const resultEl = document.getElementById("graphResult");
    let entity;
    try {
      entity = await WardlineApi.searchGraphEntity({ name });
    } catch (err) {
      resultEl.innerHTML = `<div class="banner banner--danger">${esc(err.message)}</div>`;
      return;
    }
    let edges = [];
    try {
      edges = await WardlineApi.traverseEntity({ entityId: entity.id, hops: 1 });
    } catch {
      // entity found but traversal failed -- still show the entity itself below
    }
    resultEl.innerHTML = `
      <div class="card card--pad" style="margin-bottom:1rem;">
        <strong>${esc(entity.canonical_name)}</strong> <span class="field__hint">${esc(entity.id)}</span>
      </div>
      <div class="ops-table-wrap"><table class="ops-table">
        <thead><tr><th>From</th><th>Relation</th><th>To</th><th>Confidence</th></tr></thead>
        <tbody>${edges
          .map(
            (e) => `<tr><td>${esc(e.from_name)}</td><td>${esc(e.type)}</td><td>${esc(e.to_name)}</td><td>${esc(e.confidence)}</td></tr>`
          )
          .join("")}</tbody>
      </table></div>`;
  });

  checkAccess();
})();
