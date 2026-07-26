const THEME_STORAGE_KEY = "ppe_theme";

function systemPrefersDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveTheme(pref) {
  if (pref === "auto") return systemPrefersDark() ? "dark" : "light";
  return pref === "light" ? "light" : "dark";
}

function applyTheme(pref) {
  const resolved = resolveTheme(pref);
  document.documentElement.setAttribute("data-theme", resolved);
  const label = document.getElementById("themeToggleLabel");
  if (label) label.textContent = resolved === "dark" ? "Dark mode" : "Light mode";
}

function getThemePref() {
  return localStorage.getItem(THEME_STORAGE_KEY) || "dark";
}

function setThemePref(pref) {
  localStorage.setItem(THEME_STORAGE_KEY, pref);
  applyTheme(pref);
  const select = document.getElementById("settingTheme");
  if (select) select.value = pref;
}

applyTheme(getThemePref());

document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("themeToggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const current = resolveTheme(getThemePref());
      setThemePref(current === "dark" ? "light" : "dark");
    });
  }

  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (getThemePref() === "auto") applyTheme("auto");
    });
  }
});
