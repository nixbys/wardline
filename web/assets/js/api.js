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
  };

  window.WardlineApi = WardlineApi;
})();
