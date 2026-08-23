/*
 * Research console logic. No framework, no build step — DOM wiring plus
 * calls into window.WardlineApi. Chat history (including full answers) is
 * kept client-side in localStorage: the API's GET /v1/session/{id} only
 * echoes back audit metadata (retrieved chunk ids, latency, token cost),
 * not the rendered answer, so it's used for the "inspect" panel rather
 * than as the source of truth for the transcript.
 */
(function () {
  const HISTORY_KEY = "wardline-history";
  const MAX_HISTORY = 200;

  const els = {
    appShell: document.getElementById("appShell"),
    sidebarToggle: document.getElementById("sidebarToggle"),
    newChatBtn: document.getElementById("newChatBtn"),
    historySearch: document.getElementById("historySearch"),
    sessionHistory: document.getElementById("sessionHistory"),
    historyEmpty: document.getElementById("historyEmpty"),
    connStatusBtn: document.getElementById("connStatusBtn"),
    connDot: document.getElementById("connDot"),
    connLabel: document.getElementById("connLabel"),
    settingsBtn: document.getElementById("settingsBtn"),
    threadTitle: document.getElementById("threadTitle"),
    threadModeBadge: document.getElementById("threadModeBadge"),
    threadConfidenceBadge: document.getElementById("threadConfidenceBadge"),
    uploadBtn: document.getElementById("uploadBtn"),
    thread: document.getElementById("thread"),
    emptyState: document.getElementById("emptyState"),
    emptyStateSettingsLink: document.getElementById("emptyStateSettingsLink"),
    suggestions: document.getElementById("suggestions"),
    threadInner: document.getElementById("threadInner"),
    composerForm: document.getElementById("composerForm"),
    composerInput: document.getElementById("composerInput"),
    modeSegmented: document.getElementById("modeSegmented"),
    sendBtn: document.getElementById("sendBtn"),
    toastStack: document.getElementById("toastStack"),

    settingsModal: document.getElementById("settingsModal"),
    baseUrlInput: document.getElementById("baseUrlInput"),
    apiKeyInput: document.getElementById("apiKeyInput"),
    toggleKeyVisibility: document.getElementById("toggleKeyVisibility"),
    settingsStatus: document.getElementById("settingsStatus"),
    testConnBtn: document.getElementById("testConnBtn"),
    saveSettingsBtn: document.getElementById("saveSettingsBtn"),
    signInPrompt: document.getElementById("signInPrompt"),
    logoutBtn: document.getElementById("logoutBtn"),

    mfaIdle: document.getElementById("mfaIdle"),
    mfaEnrollBtn: document.getElementById("mfaEnrollBtn"),
    mfaDisableBtn: document.getElementById("mfaDisableBtn"),
    mfaEnrollPanel: document.getElementById("mfaEnrollPanel"),
    mfaSecretDisplay: document.getElementById("mfaSecretDisplay"),
    mfaConfirmCode: document.getElementById("mfaConfirmCode"),
    mfaConfirmBtn: document.getElementById("mfaConfirmBtn"),
    mfaRecoveryPanel: document.getElementById("mfaRecoveryPanel"),
    mfaRecoveryCodes: document.getElementById("mfaRecoveryCodes"),

    billingPlanLabel: document.getElementById("billingPlanLabel"),
    billingPortalBtn: document.getElementById("billingPortalBtn"),

    uploadModal: document.getElementById("uploadModal"),
    dropzone: document.getElementById("dropzone"),
    dropzoneLabel: document.getElementById("dropzoneLabel"),
    fileInput: document.getElementById("fileInput"),
    licenseInput: document.getElementById("licenseInput"),
    uploadStatus: document.getElementById("uploadStatus"),
    submitUploadBtn: document.getElementById("submitUploadBtn"),

    inspectModal: document.getElementById("inspectModal"),
    inspectBody: document.getElementById("inspectBody"),
  };

  let state = {
    mode: "auto",
    history: loadHistory(),
    activeSessionId: null,
    pendingFile: null,
  };

  // --- utilities ---------------------------------------------------------

  function loadHistory() {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
    } catch {
      return [];
    }
  }

  function saveHistory() {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(state.history.slice(0, MAX_HISTORY)));
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[c]);
  }

  function relativeTime(iso) {
    const diffMs = Date.now() - new Date(iso).getTime();
    const mins = Math.round(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
  }

  function toast(message, variant = "") {
    const el = document.createElement("div");
    el.className = `toast ${variant ? `toast--${variant}` : ""}`.trim();
    el.textContent = message;
    els.toastStack.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function openModal(modal) {
    modal.hidden = false;
    const focusable = modal.querySelector("input, button, textarea");
    if (focusable) focusable.focus();
  }

  function closeModal(modal) {
    modal.hidden = true;
  }

  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(document.getElementById(btn.dataset.closeModal)));
  });
  [els.settingsModal, els.uploadModal, els.inspectModal].forEach((modal) => {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal(modal);
    });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    [els.settingsModal, els.uploadModal, els.inspectModal].forEach((modal) => {
      if (!modal.hidden) closeModal(modal);
    });
  });

  // --- connection status ---------------------------------------------------

  async function refreshConnectionStatus() {
    const { baseUrl, apiKey } = WardlineApi.getConfig();
    els.signInPrompt.hidden = Boolean(apiKey);
    if (!apiKey) {
      els.connDot.className = "status-dot";
      els.connLabel.textContent = "Not connected";
      return;
    }
    try {
      await WardlineApi.health();
      els.connDot.className = "status-dot status-dot--ok";
      els.connLabel.textContent = new URL(baseUrl).host;
    } catch {
      els.connDot.className = "status-dot status-dot--bad";
      els.connLabel.textContent = "Unreachable";
    }
  }

  els.connStatusBtn.addEventListener("click", () => openSettings());
  els.settingsBtn.addEventListener("click", () => openSettings());
  els.emptyStateSettingsLink.addEventListener("click", (e) => {
    e.preventDefault();
    openSettings();
  });

  function resetMfaPanels() {
    els.mfaEnrollPanel.hidden = true;
    els.mfaRecoveryPanel.hidden = true;
    els.mfaConfirmCode.value = "";
  }

  async function refreshMfaState() {
    if (!WardlineApi.isConfigured()) {
      els.mfaEnrollBtn.hidden = false;
      els.mfaDisableBtn.hidden = true;
      return;
    }
    try {
      const me = await WardlineApi.me();
      els.mfaEnrollBtn.hidden = me.mfa_enabled;
      els.mfaDisableBtn.hidden = !me.mfa_enabled;
    } catch {
      // Not logged in via a session (e.g. an admin-minted CLI key, which
      // has no password/MFA to manage) -- leave the default "enroll" state,
      // it'll just fail informatively if actually clicked.
    }
  }

  async function refreshBillingLabel() {
    if (!WardlineApi.isConfigured()) {
      els.billingPlanLabel.textContent = "Sign in to see your plan.";
      return;
    }
    try {
      const sub = await WardlineApi.getSubscription();
      const statusNote = sub.status !== "active" ? ` (${sub.status})` : "";
      els.billingPlanLabel.textContent = `Current plan: ${sub.plan}${statusNote}`;
    } catch {
      els.billingPlanLabel.textContent = "Could not load billing status.";
    }
  }

  els.billingPortalBtn.addEventListener("click", async () => {
    try {
      const { portal_url: url } = await WardlineApi.billingPortal();
      window.location.href = url;
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  function openSettings() {
    const { baseUrl, apiKey } = WardlineApi.getConfig();
    els.baseUrlInput.value = baseUrl;
    els.apiKeyInput.value = apiKey;
    els.settingsStatus.hidden = true;
    resetMfaPanels();
    refreshMfaState();
    refreshBillingLabel();
    openModal(els.settingsModal);
  }

  els.logoutBtn.addEventListener("click", async () => {
    try {
      await WardlineApi.logout();
    } catch {
      // Revoking best-effort -- clearing the local key below is what
      // actually matters for "am I logged in" from this browser's view.
    }
    WardlineApi.setConfig({ apiKey: "" });
    toast("Logged out.", "success");
    closeModal(els.settingsModal);
    refreshConnectionStatus();
    window.location.href = "login.html";
  });

  els.mfaEnrollBtn.addEventListener("click", async () => {
    try {
      const { provisioning_uri: uri } = await WardlineApi.mfaEnroll();
      const secretMatch = uri.match(/secret=([^&]+)/);
      els.mfaSecretDisplay.textContent = secretMatch ? secretMatch[1] : uri;
      els.mfaEnrollPanel.hidden = false;
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  els.mfaConfirmBtn.addEventListener("click", async () => {
    const code = els.mfaConfirmCode.value.trim();
    if (!code) return;
    try {
      const { recovery_codes: codes } = await WardlineApi.mfaConfirm({ code });
      els.mfaEnrollPanel.hidden = true;
      els.mfaRecoveryPanel.hidden = false;
      els.mfaRecoveryCodes.innerHTML = codes.map((c) => `<span>${c}</span>`).join("");
      els.mfaEnrollBtn.hidden = true;
      els.mfaDisableBtn.hidden = false;
      toast("Two-factor authentication enabled.", "success");
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  els.mfaDisableBtn.addEventListener("click", async () => {
    const code = window.prompt("Enter a current 6-digit code (or a recovery code) to disable MFA:");
    if (!code) return;
    try {
      await WardlineApi.mfaDisable(
        /^\d{6}$/.test(code.trim()) ? { code: code.trim() } : { recoveryCode: code.trim() }
      );
      els.mfaEnrollBtn.hidden = false;
      els.mfaDisableBtn.hidden = true;
      resetMfaPanels();
      toast("Two-factor authentication disabled.", "success");
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  els.toggleKeyVisibility.addEventListener("click", () => {
    const isPw = els.apiKeyInput.type === "password";
    els.apiKeyInput.type = isPw ? "text" : "password";
    els.toggleKeyVisibility.textContent = isPw ? "Hide" : "Show";
  });

  els.saveSettingsBtn.addEventListener("click", () => {
    WardlineApi.setConfig({
      baseUrl: els.baseUrlInput.value.trim() || "http://localhost:8000",
      apiKey: els.apiKeyInput.value.trim(),
    });
    toast("Settings saved.", "success");
    closeModal(els.settingsModal);
    refreshConnectionStatus();
    updateComposerEnabled();
  });

  els.testConnBtn.addEventListener("click", async () => {
    WardlineApi.setConfig({
      baseUrl: els.baseUrlInput.value.trim() || "http://localhost:8000",
      apiKey: els.apiKeyInput.value.trim(),
    });
    els.settingsStatus.hidden = false;
    els.settingsStatus.className = "banner";
    els.settingsStatus.textContent = "Checking…";
    try {
      await WardlineApi.health();
      els.settingsStatus.className = "banner banner--accent";
      els.settingsStatus.textContent = "Reached the API — /healthz responded OK.";
    } catch (err) {
      els.settingsStatus.className = "banner banner--danger";
      els.settingsStatus.textContent = err.message;
    }
  });

  // --- sidebar / history --------------------------------------------------

  function renderHistory(filter = "") {
    const q = filter.trim().toLowerCase();
    const items = state.history.filter((h) => !q || h.question.toLowerCase().includes(q));
    els.sessionHistory.querySelectorAll(".session-item").forEach((n) => n.remove());
    els.historyEmpty.hidden = items.length > 0;
    items.forEach((h) => {
      const btn = document.createElement("button");
      btn.className = "session-item";
      btn.type = "button";
      btn.setAttribute("aria-current", String(h.sessionId === state.activeSessionId));
      btn.innerHTML = `
        <span class="session-item__title">${escapeHtml(h.question)}</span>
        <span class="session-item__meta">
          <span class="badge">${escapeHtml(h.mode)}</span>
          <span>${relativeTime(h.askedAt)}</span>
        </span>`;
      btn.addEventListener("click", () => loadHistoryEntry(h.sessionId));
      els.sessionHistory.appendChild(btn);
    });
  }

  els.historySearch.addEventListener("input", () => renderHistory(els.historySearch.value));

  function loadHistoryEntry(sessionId) {
    const entry = state.history.find((h) => h.sessionId === sessionId);
    if (!entry) return;
    state.activeSessionId = sessionId;
    resetThread({ keepHistorySelection: true });
    appendMessage("user", entry.question);
    renderAssistantMessage(entry);
    els.threadTitle.textContent = entry.question;
    setModeBadge(entry.mode);
    setConfidenceBadge(entry.response);
    renderHistory(els.historySearch.value);
  }

  els.newChatBtn.addEventListener("click", () => {
    state.activeSessionId = null;
    resetThread({});
    els.threadTitle.textContent = "New research";
    els.threadModeBadge.hidden = true;
    els.threadConfidenceBadge.hidden = true;
    renderHistory(els.historySearch.value);
    els.composerInput.focus();
  });

  function resetThread() {
    els.threadInner.innerHTML = "";
    els.threadInner.hidden = true;
    els.emptyState.hidden = false;
  }

  // --- mobile sidebar ------------------------------------------------------

  els.sidebarToggle.addEventListener("click", () => {
    const open = els.appShell.getAttribute("data-sidebar-open") === "true";
    els.appShell.setAttribute("data-sidebar-open", String(!open));
  });

  // --- mode segmented control ----------------------------------------------

  els.modeSegmented.addEventListener("click", (e) => {
    const btn = e.target.closest(".segmented__option");
    if (!btn) return;
    state.mode = btn.dataset.mode;
    els.modeSegmented.querySelectorAll(".segmented__option").forEach((opt) => {
      opt.setAttribute("aria-pressed", String(opt === btn));
    });
  });

  function setModeBadge(mode) {
    els.threadModeBadge.hidden = false;
    els.threadModeBadge.textContent = mode;
  }

  function setConfidenceBadge(response) {
    if (!response) {
      els.threadConfidenceBadge.hidden = true;
      return;
    }
    els.threadConfidenceBadge.hidden = false;
    const pct = Math.round(response.confidence * 100);
    els.threadConfidenceBadge.className =
      "badge " + (response.insufficient_evidence ? "badge--warning" : pct >= 70 ? "badge--success" : "badge");
    els.threadConfidenceBadge.textContent = response.insufficient_evidence
      ? "insufficient evidence"
      : `confidence ${pct}%`;
  }

  // --- composer --------------------------------------------------------

  function updateComposerEnabled() {
    const hasText = els.composerInput.value.trim().length > 0;
    els.sendBtn.disabled = !hasText;
  }

  els.composerInput.addEventListener("input", () => {
    els.composerInput.style.height = "auto";
    els.composerInput.style.height = `${Math.min(els.composerInput.scrollHeight, 220)}px`;
    updateComposerEnabled();
  });

  els.composerInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      els.composerForm.requestSubmit();
    }
  });

  els.suggestions.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    els.composerInput.value = chip.textContent;
    els.composerInput.dispatchEvent(new Event("input"));
    els.composerForm.requestSubmit();
  });

  els.composerForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = els.composerInput.value.trim();
    if (!question) return;
    if (!WardlineApi.isConfigured()) {
      toast("Add an API key in Settings first.", "danger");
      openSettings();
      return;
    }
    submitQuestion(question, state.mode);
    els.composerInput.value = "";
    els.composerInput.style.height = "auto";
    updateComposerEnabled();
  });

  // --- sending a question --------------------------------------------------

  async function submitQuestion(question, mode) {
    els.emptyState.hidden = true;
    els.threadInner.hidden = false;
    els.threadTitle.textContent = question;
    setModeBadge(mode);
    els.threadConfidenceBadge.hidden = true;

    appendMessage("user", question);
    const loadingNode = appendLoadingMessage();
    els.thread.scrollTop = els.thread.scrollHeight;

    try {
      const response = await WardlineApi.query({ question, mode, max_sources: 12 });
      loadingNode.remove();
      const entry = {
        sessionId: response.session_id,
        question,
        mode,
        askedAt: new Date().toISOString(),
        response,
        feedback: null,
      };
      state.history.unshift(entry);
      state.activeSessionId = entry.sessionId;
      saveHistory();
      renderHistory(els.historySearch.value);
      renderAssistantMessage(entry);
      setConfidenceBadge(response);
    } catch (err) {
      loadingNode.remove();
      appendErrorMessage(err instanceof WardlineApi.ApiError ? err.message : String(err));
      toast("The query failed — see the message in the thread.", "danger");
    }
    els.thread.scrollTop = els.thread.scrollHeight;
  }

  function appendMessage(role, text) {
    const wrap = document.createElement("div");
    wrap.className = `message message--${role}`;
    wrap.innerHTML = `
      <span class="avatar ${role === "user" ? "avatar--outline" : "avatar--accent"}" aria-hidden="true">
        ${role === "user" ? "you" : "wl"}
      </span>
      <div class="message__bubble"><div class="message__text">${escapeHtml(text)}</div></div>`;
    els.threadInner.appendChild(wrap);
    return wrap;
  }

  function appendLoadingMessage() {
    const wrap = document.createElement("div");
    wrap.className = "message message--assistant";
    wrap.innerHTML = `
      <span class="avatar avatar--accent" aria-hidden="true">wl</span>
      <div class="message__bubble">
        <div class="typing-dots"><span></span><span></span><span></span></div>
      </div>`;
    els.threadInner.appendChild(wrap);
    return wrap;
  }

  function appendErrorMessage(message) {
    const wrap = document.createElement("div");
    wrap.className = "message message--assistant";
    wrap.innerHTML = `
      <span class="avatar avatar--accent" aria-hidden="true">wl</span>
      <div class="message__bubble">
        <div class="banner banner--danger">${escapeHtml(message)}</div>
      </div>`;
    els.threadInner.appendChild(wrap);
  }

  function renderAssistantMessage(entry) {
    const { response } = entry;
    const wrap = document.createElement("div");
    wrap.className = "message message--assistant";

    const sourcesId = `sources-${response.session_id}`;
    const sourcesHtml = (response.sources || [])
      .map(
        (s, i) => `
        <div class="source-row">
          <span class="source-row__idx">[${i + 1}]</span>
          <div class="source-row__body">
            <span class="source-row__title">${escapeHtml(s.title || s.uri || s.id)}</span>
            <span class="source-row__meta">
              <span class="badge">${escapeHtml(s.kind)}</span>
              ${s.license ? `<span>${escapeHtml(s.license)}</span>` : ""}
              ${s.uri ? `<a href="${escapeHtml(s.uri)}" target="_blank" rel="noreferrer">${escapeHtml(s.uri)}</a>` : ""}
            </span>
          </div>
        </div>`
      )
      .join("");

    wrap.innerHTML = `
      <span class="avatar avatar--accent" aria-hidden="true">wl</span>
      <div class="message__bubble">
        ${
          response.insufficient_evidence
            ? `<div class="banner banner--warning" style="margin-bottom:0.75rem;">Insufficient evidence in the corpus to answer this fully — treat this as partial.</div>`
            : ""
        }
        <div class="message__text">${escapeHtml(response.answer)}</div>
        <div class="message__meta-row">
          <span class="badge ${response.confidence >= 0.7 ? "badge--success" : "badge--warning"}">
            confidence ${Math.round(response.confidence * 100)}%
          </span>
          <span class="badge">${response.latency_ms} ms</span>
          <button class="btn btn--sm btn--ghost" data-toggle-sources="${sourcesId}" type="button">
            Sources (${(response.sources || []).length})
          </button>
          <button class="btn btn--sm btn--ghost" data-inspect="${response.session_id}" type="button">
            Inspect session
          </button>
        </div>
        <div class="sources-panel" id="${sourcesId}" hidden>${sourcesHtml || '<p class="field__hint">No sources returned.</p>'}</div>
        <div class="message__actions" data-feedback-group="${response.session_id}">
          <button class="btn btn--icon btn--ghost btn--sm tooltip" data-feedback="1" data-tooltip="Good answer" aria-label="Thumbs up" aria-pressed="${entry.feedback === 1}" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M7 11v9H4v-9h3Zm0 0 4-8a2 2 0 0 1 3.6 1.4L13.5 9H18a2 2 0 0 1 2 2.4l-1.4 6A3 3 0 0 1 15.7 20H7" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
          </button>
          <button class="btn btn--icon btn--ghost btn--sm tooltip" data-feedback="-1" data-tooltip="Needs work" aria-label="Thumbs down" aria-pressed="${entry.feedback === -1}" type="button">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M17 13V4h3v9h-3Zm0 0-4 8a2 2 0 0 1-3.6-1.4L10.5 15H6a2 2 0 0 1-2-2.4l1.4-6A3 3 0 0 1 8.3 4H17" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
          </button>
        </div>
      </div>`;

    els.threadInner.appendChild(wrap);

    wrap.querySelector(`[data-toggle-sources]`).addEventListener("click", (e) => {
      const panel = wrap.querySelector(`#${sourcesId}`);
      panel.hidden = !panel.hidden;
      e.currentTarget.textContent = `${panel.hidden ? "Sources" : "Hide sources"} (${(response.sources || []).length})`;
    });

    wrap.querySelector(`[data-inspect]`).addEventListener("click", () => inspectSession(response.session_id));

    wrap.querySelectorAll("[data-feedback]").forEach((btn) => {
      btn.addEventListener("click", () => submitFeedback(entry, Number(btn.dataset.feedback), wrap));
    });
  }

  async function submitFeedback(entry, rating, wrap) {
    try {
      await WardlineApi.feedback({ sessionId: entry.sessionId, rating });
      entry.feedback = rating;
      const idx = state.history.findIndex((h) => h.sessionId === entry.sessionId);
      if (idx >= 0) {
        state.history[idx].feedback = rating;
        saveHistory();
      }
      wrap.querySelectorAll("[data-feedback]").forEach((b) => {
        b.setAttribute("aria-pressed", String(Number(b.dataset.feedback) === rating));
      });
      toast("Thanks — feedback recorded.", "success");
    } catch (err) {
      toast(err.message, "danger");
    }
  }

  async function inspectSession(sessionId) {
    openModal(els.inspectModal);
    els.inspectBody.textContent = "Loading…";
    try {
      const session = await WardlineApi.getSession(sessionId);
      els.inspectBody.textContent = JSON.stringify(session, null, 2);
    } catch (err) {
      els.inspectBody.textContent = `Could not load session ${sessionId}:\n${err.message}`;
    }
  }

  // --- upload modal --------------------------------------------------------

  els.uploadBtn.addEventListener("click", () => {
    els.uploadStatus.hidden = true;
    els.fileInput.value = "";
    els.licenseInput.value = "";
    els.dropzoneLabel.innerHTML = "Drag a file here, or <strong>click to browse</strong>";
    state.pendingFile = null;
    els.submitUploadBtn.disabled = true;
    openModal(els.uploadModal);
  });

  els.fileInput.addEventListener("change", () => {
    const file = els.fileInput.files[0];
    if (!file) return;
    state.pendingFile = file;
    els.dropzoneLabel.innerHTML = `Selected: <strong>${escapeHtml(file.name)}</strong> (${Math.round(file.size / 1024)} KB)`;
    els.submitUploadBtn.disabled = false;
  });

  ["dragover", "dragenter"].forEach((evt) =>
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.add("is-dragover");
    })
  );
  ["dragleave", "dragend", "drop"].forEach((evt) =>
    els.dropzone.addEventListener(evt, () => els.dropzone.classList.remove("is-dragover"))
  );
  els.dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    els.fileInput.files = e.dataTransfer.files;
    state.pendingFile = file;
    els.dropzoneLabel.innerHTML = `Selected: <strong>${escapeHtml(file.name)}</strong> (${Math.round(file.size / 1024)} KB)`;
    els.submitUploadBtn.disabled = false;
  });

  els.submitUploadBtn.addEventListener("click", async () => {
    if (!state.pendingFile) return;
    if (!WardlineApi.isConfigured()) {
      toast("Add an API key in Settings first.", "danger");
      return;
    }
    els.submitUploadBtn.disabled = true;
    els.uploadStatus.hidden = false;
    els.uploadStatus.className = "banner";
    els.uploadStatus.textContent = "Uploading…";
    try {
      const result = await WardlineApi.upload({
        file: state.pendingFile,
        license: els.licenseInput.value.trim(),
      });
      els.uploadStatus.className = "banner banner--accent";
      els.uploadStatus.textContent = `Queued for ingestion: ${JSON.stringify(result)}`;
      toast("Upload accepted.", "success");
    } catch (err) {
      els.uploadStatus.className = "banner banner--danger";
      els.uploadStatus.textContent = err.message;
    } finally {
      els.submitUploadBtn.disabled = false;
    }
  });

  // --- boot ------------------------------------------------------------

  renderHistory();
  updateComposerEnabled();
  refreshConnectionStatus();
  if (!WardlineApi.isConfigured()) {
    setTimeout(() => openSettings(), 400);
  }
})();
