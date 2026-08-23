/*
 * Shared light/dark toggle. Persists an explicit choice in localStorage;
 * absent a choice, tokens.css already falls back to prefers-color-scheme,
 * so this script only needs to act once the user overrides it.
 */
(function () {
  const STORAGE_KEY = "wardline-theme";
  const root = document.documentElement;

  function apply(theme) {
    if (theme === "light" || theme === "dark") {
      root.setAttribute("data-theme", theme);
    } else {
      root.removeAttribute("data-theme");
    }
    document
      .querySelectorAll("[data-theme-toggle]")
      .forEach((btn) => {
        const isDark =
          theme === "dark" ||
          (theme !== "light" &&
            window.matchMedia("(prefers-color-scheme: dark)").matches);
        btn.setAttribute("aria-pressed", String(isDark));
        btn.setAttribute(
          "data-tooltip",
          isDark ? "Switch to light" : "Switch to dark"
        );
      });
  }

  function current() {
    return localStorage.getItem(STORAGE_KEY);
  }

  function toggle() {
    const isDark =
      current() === "dark" ||
      (current() !== "light" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = isDark ? "light" : "dark";
    localStorage.setItem(STORAGE_KEY, next);
    apply(next);
  }

  apply(current());
  document.addEventListener("DOMContentLoaded", () => {
    apply(current());
    document
      .querySelectorAll("[data-theme-toggle]")
      .forEach((btn) => btn.addEventListener("click", toggle));
  });

  window.WardlineTheme = { toggle, apply, current };
})();
