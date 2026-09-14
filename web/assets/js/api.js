/*
 * Thin client for the wardline API (see src/wardline/api/routers/*.py).
 * Everything here maps 1:1 to a real endpoint — this UI never fabricates
 * data. Config (base URL + bearer API key, minted by
 * `wardline.cli create-admin-user`, see README) lives in localStorage only;
 * nothing is sent anywhere but the configured base URL.
 */
(function () {
  const CONFIG_KEY = "wardline-api-config";

  function getConfig() {
    try {
      const raw = localStorage.getItem(CONFIG_KEY);
      if (!raw) return { baseUrl: "http://localhost:8000", apiKey: "" };
      const parsed = JSON.parse(raw);
      return {
        baseUrl: parsed.baseUrl || "http://localhost:8000",
        apiKey: parsed.apiKey || "",
      };
    } catch {
      return { baseUrl: "http://localhost:8000", apiKey: "" };
    }
  }

  function setConfig(next) {
    const current = getConfig();
    localStorage.setItem(
      CONFIG_KEY,
      JSON.stringify({ ...current, ...next })
    );
  }

  function isConfigured() {
    const { apiKey } = getConfig();
    return Boolean(apiKey && apiKey.trim());
  }

  class ApiError extends Error {
    constructor(message, status, detail) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
    }
  }

  async function request(path, { method = "GET", body, isForm = false } = {}) {
    const { baseUrl, apiKey } = getConfig();
    if (!baseUrl) throw new ApiError("No API base URL configured.", 0);

    const headers = {};
    if (apiKey) headers["Authorization"] = `Bearer ${apiKey}`;
    if (body && !isForm) headers["Content-Type"] = "application/json";

    let response;
    try {
      response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
        method,
        headers,
        body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
      });
    } catch (networkErr) {
      throw new ApiError(
        `Could not reach ${baseUrl} — is the API running and CORS-enabled for this origin?`,
        0,
        String(networkErr)
      );
    }

    if (response.status === 204) return null;

    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }

    if (!response.ok) {
      const detail =
        (data && typeof data === "object" && (data.detail || data.message)) ||
        (typeof data === "string" ? data : response.statusText);
      throw new ApiError(
        typeof detail === "string" ? detail : JSON.stringify(detail),
        response.status,
        data
      );
    }

    return data;
  }

  const WardlineApi = {
    getConfig,
    setConfig,
    isConfigured,
    ApiError,

    health() {
      return request("/healthz");
    },

    /** GET /v1/auth/me — the caller's own account, from the token in use */
    me() {
      return request("/v1/auth/me");
    },

    /** POST /v1/auth/signup — body: { email, password } */
    signup({ email, password }) {
      return request("/v1/auth/signup", { method: "POST", body: { email, password } });
    },

    /** POST /v1/auth/login — body: { email, password, mfa_code?, recovery_code? }.
     *  A failure with detail === "mfa_required" means the password was
     *  right and the caller should re-submit with mfa_code or recovery_code. */
    login({ email, password, mfaCode, recoveryCode }) {
      return request("/v1/auth/login", {
        method: "POST",
        body: { email, password, mfa_code: mfaCode || null, recovery_code: recoveryCode || null },
      });
    },

    /** POST /v1/auth/logout — revokes only the session key in use. */
    logout() {
      return request("/v1/auth/logout", { method: "POST" });
    },

    /** POST /v1/auth/verify-email — body: { token } */
    verifyEmail({ token }) {
      return request("/v1/auth/verify-email", { method: "POST", body: { token } });
    },

    /** POST /v1/auth/password/forgot — body: { email } */
    forgotPassword({ email }) {
      return request("/v1/auth/password/forgot", { method: "POST", body: { email } });
    },

    /** POST /v1/auth/password/reset — body: { token, new_password } */
    resetPassword({ token, newPassword }) {
      return request("/v1/auth/password/reset", {
        method: "POST",
        body: { token, new_password: newPassword },
      });
    },

    /** POST /v1/auth/mfa/enroll — authenticated; returns { provisioning_uri } */
    mfaEnroll() {
      return request("/v1/auth/mfa/enroll", { method: "POST" });
    },

    /** POST /v1/auth/mfa/confirm — body: { code }; returns { recovery_codes } */
    mfaConfirm({ code }) {
      return request("/v1/auth/mfa/confirm", { method: "POST", body: { code } });
    },

    /** POST /v1/auth/mfa/disable — body: { code?, recovery_code? } */
    mfaDisable({ code, recoveryCode }) {
      return request("/v1/auth/mfa/disable", {
        method: "POST",
        body: { code: code || null, recovery_code: recoveryCode || null },
      });
    },

    /** POST /v1/auth/accept-invite — body: { token, password } */
    acceptInvite({ token, password }) {
      return request("/v1/auth/accept-invite", { method: "POST", body: { token, password } });
    },

    /** GET /v1/billing/plans — public, no auth required */
    listPlans() {
      return request("/v1/billing/plans");
    },

    /** GET /v1/billing/subscription — the caller's current plan/status */
    getSubscription() {
      return request("/v1/billing/subscription");
    },

    /** POST /v1/billing/checkout — body: { plan_id }; returns { checkout_url } */
    checkout({ planId }) {
      return request("/v1/billing/checkout", { method: "POST", body: { plan_id: planId } });
    },

    /** POST /v1/billing/portal — returns { portal_url } (manage/cancel a subscription) */
    billingPortal() {
      return request("/v1/billing/portal", { method: "POST" });
    },

    /** POST /v1/billing/donate — public, no account needed; body: { amount_usd, message? };
     *  returns { checkout_url } */
    donate({ amountUsd, message }) {
      return request("/v1/billing/donate", {
        method: "POST",
        body: { amount_usd: amountUsd, message: message || null },
      });
    },

    /** POST /v1/query — body: { question, mode, filters, max_sources } */
    query({ question, mode = "auto", filters = {}, max_sources = 12 }) {
      return request("/v1/query", {
        method: "POST",
        body: { question, mode, filters, max_sources },
      });
    },

    /** GET /v1/session/{id} */
    getSession(sessionId) {
      return request(`/v1/session/${encodeURIComponent(sessionId)}`);
    },

    /** POST /v1/feedback — body: { session_id, rating, comment } */
    feedback({ sessionId, rating, comment }) {
      return request("/v1/feedback", {
        method: "POST",
        body: { session_id: sessionId, rating, comment: comment || null },
      });
    },

    /** POST /v1/documents/upload — multipart file (+ optional license) */
    upload({ file, license }) {
      const form = new FormData();
      form.append("file", file);
      if (license) form.append("license", license);
      return request("/v1/documents/upload", {
        method: "POST",
        body: form,
        isForm: true,
      });
    },

    /** GET /v1/audit — append-only audit log, admin/analyst only */
    audit(params = {}) {
      const qs = new URLSearchParams(params).toString();
      return request(`/v1/audit${qs ? `?${qs}` : ""}`);
    },

    /** GET /v1/audit/coverage-gaps — admin/analyst only; mode-level insufficient_evidence rates */
    getCoverageGaps() {
      return request("/v1/audit/coverage-gaps");
    },

    /** GET /v1/orgs/me — the caller's org, or null if they don't have one */
    getMyOrg() {
      return request("/v1/orgs/me");
    },

    /** POST /v1/orgs — body: { name }; caller becomes the owner */
    createOrg({ name }) {
      return request("/v1/orgs", { method: "POST", body: { name } });
    },

    /** GET /v1/orgs/members — owner-only */
    getOrgMembers() {
      return request("/v1/orgs/members");
    },

    /** POST /v1/orgs/invite — owner-only; body: { email, role } */
    inviteToOrg({ email, role }) {
      return request("/v1/orgs/invite", { method: "POST", body: { email, role } });
    },

    // --- Ops Console (web/ops.html) -- admin/analyst only ---------------

    /** GET /v1/admin/connectors/jobs?status=&connector_name=&limit= */
    listJobs({ status, connectorName, limit = 50 } = {}) {
      const qs = new URLSearchParams();
      if (status) qs.set("status", status);
      if (connectorName) qs.set("connector_name", connectorName);
      qs.set("limit", limit);
      return request(`/v1/admin/connectors/jobs?${qs}`);
    },

    /** GET /v1/admin/connectors/jobs/{id} */
    getJobStatus({ jobId }) {
      return request(`/v1/admin/connectors/jobs/${encodeURIComponent(jobId)}`);
    },

    /** GET /v1/admin/connectors/jobs/{id}/log?after_id= -- cursor-based polling */
    getJobLog({ jobId, afterId = 0 }) {
      return request(`/v1/admin/connectors/jobs/${encodeURIComponent(jobId)}/log?after_id=${afterId}`);
    },

    /** GET /v1/admin/entity-review/queue */
    getEntityReviewQueue() {
      return request("/v1/admin/entity-review/queue");
    },

    /** POST /v1/admin/entity-review/{id}/decision — body: { decision: "merged" | "rejected" } */
    decideEntityReview({ reviewId, decision }) {
      return request(`/v1/admin/entity-review/${encodeURIComponent(reviewId)}/decision`, {
        method: "POST",
        body: { decision },
      });
    },

    /** GET /v1/admin/engagements */
    listEngagements() {
      return request("/v1/admin/engagements");
    },

    /** POST /v1/admin/engagements — admin-only */
    createEngagement({ target, scopeNote, evidenceRef, validFrom, validUntil }) {
      return request("/v1/admin/engagements", {
        method: "POST",
        body: {
          target,
          scope_note: scopeNote,
          evidence_ref: evidenceRef,
          valid_from: validFrom,
          valid_until: validUntil,
        },
      });
    },

    /** POST /v1/admin/engagements/{id}/revoke — admin-only */
    revokeEngagement({ engagementId }) {
      return request(`/v1/admin/engagements/${encodeURIComponent(engagementId)}/revoke`, { method: "POST" });
    },

    /** GET /v1/admin/users — admin-only */
    listUsers() {
      return request("/v1/admin/users");
    },

    /** POST /v1/admin/users — admin-only; mints a usable API key immediately */
    createUser({ email, role }) {
      return request("/v1/admin/users", { method: "POST", body: { email, role } });
    },

    /** POST /v1/admin/users/invite — admin-only; emails an accept-invite link */
    inviteAdminUser({ email, role }) {
      return request("/v1/admin/users/invite", { method: "POST", body: { email, role } });
    },

    /** POST /v1/admin/users/{id}/revoke — admin-only */
    revokeAdminUser({ userId }) {
      return request(`/v1/admin/users/${encodeURIComponent(userId)}/revoke`, { method: "POST" });
    },

    /** GET /v1/admin/kill-switch */
    getKillSwitch() {
      return request("/v1/admin/kill-switch");
    },

    /** POST /v1/admin/kill-switch — admin-only; body: { enabled } */
    setKillSwitch({ enabled }) {
      return request("/v1/admin/kill-switch", { method: "POST", body: { enabled } });
    },

    /** POST /v1/admin/iceberg/export-audit-events — admin-only, on-demand export */
    triggerIcebergExport() {
      return request("/v1/admin/iceberg/export-audit-events", { method: "POST" });
    },

    /** GET /v1/admin/iceberg/export-receipts — admin-only */
    listExportReceipts() {
      return request("/v1/admin/iceberg/export-receipts");
    },

    /** GET /v1/admin/graph/entities/search?name= */
    searchGraphEntity({ name }) {
      return request(`/v1/admin/graph/entities/search?name=${encodeURIComponent(name)}`);
    },

    /** GET /v1/admin/graph/entities/{id}/traverse?hops= */
    traverseEntity({ entityId, hops = 1 }) {
      return request(`/v1/admin/graph/entities/${encodeURIComponent(entityId)}/traverse?hops=${hops}`);
    },
  };

  window.WardlineApi = WardlineApi;
})();
