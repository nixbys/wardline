/*
 * Logic for the standalone auth pages (login.html, verify-email.html,
 * reset-password.html, accept-invite.html). One shared file, guarded by
 * checking which elements exist — these pages are simple enough that a
 * separate bundle per page would just be four near-identical files.
 */
(function () {
  const toastStack = document.getElementById("toastStack");

  function toast(message, variant = "") {
    if (!toastStack) return;
    const el = document.createElement("div");
    el.className = `toast ${variant ? `toast--${variant}` : ""}`.trim();
    el.textContent = message;
    toastStack.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function goToConsole() {
    window.location.href = "app.html";
  }

  function tokenFromUrl() {
    return new URLSearchParams(window.location.search).get("token");
  }

  // --- login.html --------------------------------------------------------

  const tabLogin = document.getElementById("tabLogin");
  const tabSignup = document.getElementById("tabSignup");
  const loginForm = document.getElementById("loginForm");
  const signupForm = document.getElementById("signupForm");

  if (tabLogin && tabSignup) {
    tabLogin.addEventListener("click", () => {
      tabLogin.setAttribute("aria-pressed", "true");
      tabSignup.setAttribute("aria-pressed", "false");
      loginForm.hidden = false;
      signupForm.hidden = true;
    });
    tabSignup.addEventListener("click", () => {
      tabLogin.setAttribute("aria-pressed", "false");
      tabSignup.setAttribute("aria-pressed", "true");
      loginForm.hidden = true;
      signupForm.hidden = false;
    });
  }

  if (loginForm) {
    const mfaField = document.getElementById("mfaField");
    const errorBanner = document.getElementById("loginError");

    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      errorBanner.hidden = true;
      const email = document.getElementById("loginEmail").value.trim();
      const password = document.getElementById("loginPassword").value;
      const mfaCode = document.getElementById("loginMfaCode").value.trim();

      try {
        const result = await WardlineApi.login({
          email,
          password,
          mfaCode: mfaCode || undefined,
          recoveryCode: mfaField.hidden ? undefined : mfaCode || undefined,
        });
        WardlineApi.setConfig({ apiKey: result.api_key });
        toast("Welcome back.", "success");
        goToConsole();
      } catch (err) {
        if (err.message === "mfa_required") {
          mfaField.hidden = false;
          errorBanner.hidden = false;
          errorBanner.className = "banner banner--accent";
          errorBanner.textContent = "Enter the 6-digit code from your authenticator app (or a recovery code).";
        } else {
          errorBanner.hidden = false;
          errorBanner.className = "banner banner--danger";
          errorBanner.textContent = err.message;
        }
      }
    });
  }

  if (signupForm) {
    const errorBanner = document.getElementById("signupError");
    const successBanner = document.getElementById("signupSuccess");

    signupForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      errorBanner.hidden = true;
      successBanner.hidden = true;
      const email = document.getElementById("signupEmail").value.trim();
      const password = document.getElementById("signupPassword").value;

      try {
        const result = await WardlineApi.signup({ email, password });
        successBanner.hidden = false;
        successBanner.textContent = result.message;
        signupForm.reset();
      } catch (err) {
        errorBanner.hidden = false;
        errorBanner.textContent = err.message;
      }
    });
  }

  // --- verify-email.html ---------------------------------------------

  const verifyStatus = document.getElementById("verifyStatus");
  if (verifyStatus) {
    const token = tokenFromUrl();
    if (!token) {
      verifyStatus.className = "banner banner--danger";
      verifyStatus.textContent = "No verification token in the link — check you copied the whole URL.";
    } else {
      WardlineApi.verifyEmail({ token })
        .then((result) => {
          verifyStatus.className = "banner banner--accent";
          verifyStatus.textContent = `${result.email} is verified. You can log in now.`;
        })
        .catch((err) => {
          verifyStatus.className = "banner banner--danger";
          verifyStatus.textContent = err.message;
        });
    }
  }

  // --- reset-password.html ------------------------------------------

  const requestResetForm = document.getElementById("requestResetForm");
  const setNewPasswordForm = document.getElementById("setNewPasswordForm");

  if (requestResetForm && setNewPasswordForm) {
    const token = tokenFromUrl();
    if (token) {
      requestResetForm.hidden = true;
      setNewPasswordForm.hidden = false;
    } else {
      requestResetForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = document.getElementById("resetEmail").value.trim();
        const status = document.getElementById("requestResetStatus");
        try {
          const result = await WardlineApi.forgotPassword({ email });
          status.hidden = false;
          status.textContent = result.message;
        } catch (err) {
          toast(err.message, "danger");
        }
      });

      setNewPasswordForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorBanner = document.getElementById("setPasswordError");
        errorBanner.hidden = true;
        const newPassword = document.getElementById("newPassword").value;
        try {
          await WardlineApi.resetPassword({ token, newPassword });
          toast("Password updated — log in with it now.", "success");
          window.location.href = "login.html";
        } catch (err) {
          errorBanner.hidden = false;
          errorBanner.textContent = err.message;
        }
      });
    }
  }

  // --- accept-invite.html -----------------------------------------

  const acceptInviteForm = document.getElementById("acceptInviteForm");
  if (acceptInviteForm) {
    const token = tokenFromUrl();
    acceptInviteForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errorBanner = document.getElementById("acceptInviteError");
      errorBanner.hidden = true;
      if (!token) {
        errorBanner.hidden = false;
        errorBanner.textContent = "No invite token in the link — check you copied the whole URL.";
        return;
      }
      const password = document.getElementById("invitePassword").value;
      try {
        const result = await WardlineApi.acceptInvite({ token, password });
        WardlineApi.setConfig({ apiKey: result.api_key });
        toast("Account set up — welcome to Wardline.", "success");
        goToConsole();
      } catch (err) {
        errorBanner.hidden = false;
        errorBanner.textContent = err.message;
      }
    });
  }
})();
