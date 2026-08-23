/*
 * Pricing page: fetches the real plan list from GET /v1/billing/plans (no
 * dollar amount or limit here is hard-coded in the page — it all comes
 * from common/plans.py on the server, the one place those numbers live)
 * and wires "Subscribe" into POST /v1/billing/checkout.
 */
(function () {
  const grid = document.getElementById("planGrid");
  const status = document.getElementById("pricingStatus");
  const toastStack = document.getElementById("toastStack");

  function toast(message, variant = "") {
    const el = document.createElement("div");
    el.className = `toast ${variant ? `toast--${variant}` : ""}`.trim();
    el.textContent = message;
    toastStack.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function formatPrice(plan) {
    if (plan.monthly_price_usd === null) return "Contact us";
    if (plan.monthly_price_usd === 0) return "Free";
    return `$${plan.monthly_price_usd}<span>/mo${plan.per_seat ? " per seat" : ""}</span>`;
  }

  function featureLines(plan) {
    const lines = [
      `${plan.modes.includes("research") ? "Fast, Auto & Research" : "Fast & Auto"} query modes`,
      `Up to ${plan.max_sources_cap} sources per answer`,
    ];
    if (plan.id === "team") lines.push("Shared org-wide audit log");
    if (plan.id === "enterprise") lines.push("Dedicated instance or self-host, SSO, SLA");
    return lines;
  }

  async function render() {
    let plans;
    try {
      plans = await WardlineApi.listPlans();
    } catch (err) {
      grid.innerHTML = `<div class="banner banner--danger">${err.message}</div>`;
      return;
    }

    let currentPlan = null;
    if (WardlineApi.isConfigured()) {
      try {
        currentPlan = (await WardlineApi.getSubscription()).plan;
      } catch {
        // Not logged in via a session, or the call otherwise failed --
        // just render without a "current plan" highlight.
      }
    }

    grid.innerHTML = plans
      .map((plan) => {
        const isCurrent = plan.id === currentPlan;
        const featured = plan.id === "pro";
        let action;
        if (isCurrent) {
          action = `<button class="btn btn--secondary btn--block" disabled>Current plan</button>`;
        } else if (!plan.self_serve_checkout) {
          action = plan.id === "free"
            ? `<a class="btn btn--secondary btn--block" href="login.html">Get started</a>`
            : `<a class="btn btn--secondary btn--block" href="mailto:sales@wardline.example">Talk to sales</a>`;
        } else {
          action = `<button class="btn btn--primary btn--block" data-plan="${plan.id}">Subscribe</button>`;
        }
        return `
          <article class="card card--interactive plan-card ${featured ? "plan-card--featured" : ""}">
            <div>
              <span class="badge ${featured ? "badge--accent" : ""}">${plan.label}</span>
              <div class="plan-card__price">${formatPrice(plan)}</div>
            </div>
            <ul class="plan-card__features">
              ${featureLines(plan).map((l) => `<li>· ${l}</li>`).join("")}
            </ul>
            ${action}
          </article>`;
      })
      .join("");

    grid.querySelectorAll("[data-plan]").forEach((btn) => {
      btn.addEventListener("click", () => subscribe(btn.dataset.plan));
    });
  }

  async function subscribe(planId) {
    if (!WardlineApi.isConfigured()) {
      toast("Sign in first, then come back to subscribe.", "danger");
      window.location.href = "login.html";
      return;
    }
    try {
      const { checkout_url: url } = await WardlineApi.checkout({ planId });
      window.location.href = url;
    } catch (err) {
      status.hidden = false;
      status.className = "banner banner--danger";
      status.textContent = err.message;
    }
  }

  render();
})();
