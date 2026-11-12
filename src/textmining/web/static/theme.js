// The theme follows the system setting until the toggle stores a choice. timeline.js
// redraws its charts on the "themechange" event, since canvas colours are not CSS.
(function () {
  const root = document.documentElement, toggle = document.getElementById("theme-toggle");
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  const current = () => root.dataset.theme || (system.matches ? "dark" : "light");
  const label = () => { toggle.textContent = current() === "dark" ? "Light mode" : "Dark mode"; };
  const changed = () => { label(); document.dispatchEvent(new Event("themechange")); };

  toggle.addEventListener("click", () => {
    root.dataset.theme = current() === "dark" ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
    changed();
  });
  system.addEventListener("change", changed);
  label();
  toggle.hidden = false;
})();
