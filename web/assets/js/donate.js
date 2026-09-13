/*
 * Support Wardline: POST /v1/billing/donate is public (no account needed),
 * so this never checks WardlineApi.isConfigured() the way pricing.js's
 * subscribe button does -- only the base URL needs to be reachable.
 */
(function () {
  const amountGrid = document.getElementById("amountGrid");
  const customAmount = document.getElementById("customAmount");
  const messageInput = document.getElementById("donateMessage");
  const submitButton = document.getElementById("donateSubmit");
  const status = document.getElementById("donateStatus");

  let selectedAmount = null;

  amountGrid.querySelectorAll("[data-amount]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedAmount = Number(button.dataset.amount);
      customAmount.value = "";
      amountGrid
        .querySelectorAll("[data-amount]")
        .forEach((b) => b.classList.toggle("btn--primary", b === button));
      amountGrid
        .querySelectorAll("[data-amount]")
        .forEach((b) => b.classList.toggle("btn--secondary", b !== button));
    });
  });

  customAmount.addEventListener("input", () => {
    selectedAmount = null;
    amountGrid.querySelectorAll("[data-amount]").forEach((b) => {
      b.classList.remove("btn--primary");
      b.classList.add("btn--secondary");
    });
  });

  submitButton.addEventListener("click", async () => {
    const amount = selectedAmount || Number(customAmount.value);
    status.hidden = true;
    if (!amount || amount <= 0) {
      status.hidden = false;
      status.className = "banner banner--danger";
      status.textContent = "Pick an amount or enter your own.";
      return;
    }

    submitButton.disabled = true;
    try {
      const { checkout_url: url } = await WardlineApi.donate({
        amountUsd: amount,
        message: messageInput.value.trim(),
      });
      window.location.href = url;
    } catch (err) {
      status.hidden = false;
      status.className = "banner banner--danger";
      status.textContent = err.message;
      submitButton.disabled = false;
    }
  });
})();
