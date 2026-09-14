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
    if (plan.id === "team") lines.push("Shared org-wide audit log", "Hosted or self-hosted");
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
            : `<a class="btn btn--secondary btn--block" href="#enterpriseInquiry" data-enterprise-inquiry>Talk to sales</a>`;
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

  // --- Enterprise "Talk to sales" inquiry -----------------------------
  // Delegated on document (not `grid`) so it covers both the dynamically
  // rendered plan-card CTA and the static footer link without separate
  // rebinding logic each render() call.
  const enterpriseForm = document.getElementById("enterpriseInquiry");
  const enterpriseStatus = document.getElementById("enterpriseStatus");
  const enterpriseSubmit = document.getElementById("enterpriseSubmit");

  function showEnterpriseForm() {
    enterpriseForm.hidden = false;
    enterpriseForm.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-enterprise-inquiry]");
    if (!trigger) return;
    event.preventDefault();
    showEnterpriseForm();
  });

  if (enterpriseSubmit) {
    enterpriseSubmit.addEventListener("click", async () => {
      const company = document.getElementById("enterpriseCompany").value.trim();
      const contactEmail = document.getElementById("enterpriseContactEmail").value.trim();
      const contactName = document.getElementById("enterpriseContactName").value.trim();
      const seatsRaw = document.getElementById("enterpriseSeats").value;
      const message = document.getElementById("enterpriseMessage").value.trim();

      enterpriseStatus.hidden = true;
      if (!company || !contactEmail) {
        enterpriseStatus.hidden = false;
        enterpriseStatus.className = "banner banner--danger";
        enterpriseStatus.textContent = "Company and work email are required.";
        return;
      }

      enterpriseSubmit.disabled = true;
      try {
        await WardlineApi.enterpriseInquiry({
          company,
          contactEmail,
          contactName,
          seatsEstimate: seatsRaw ? Number(seatsRaw) : null,
          message,
        });
        enterpriseStatus.hidden = false;
        enterpriseStatus.className = "banner banner--accent";
        enterpriseStatus.textContent = "Thanks -- we'll follow up at that email shortly.";
        [
          "enterpriseCompany",
          "enterpriseContactName",
          "enterpriseContactEmail",
          "enterpriseSeats",
          "enterpriseMessage",
        ].forEach((id) => (document.getElementById(id).value = ""));
      } catch (err) {
        enterpriseStatus.hidden = false;
        enterpriseStatus.className = "banner banner--danger";
        enterpriseStatus.textContent = err.message;
      } finally {
        enterpriseSubmit.disabled = false;
      }
    });
  }

  // Arriving from donate.html's footer link (no Enterprise CTA on that
  // page) with ?talk-to-sales=1 opens the form immediately instead of
  // requiring a second click once the plan grid has rendered.
  if (new URLSearchParams(window.location.search).get("talk-to-sales") === "1") {
    showEnterpriseForm();
  }

  render();
})();
