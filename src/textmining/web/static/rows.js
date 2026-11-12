// Association rows (tr[data-href]) open their association; links inside a row keep their own target.
(function () {
  function row(event) {
    if (event.target.closest("a")) return null;
    return event.target.closest("tr[data-href]");
  }
  function open(event) {
    const tr = row(event);
    if (!tr) return;
    const newTab = event.button === 1 || event.ctrlKey || event.metaKey;
    if (newTab) window.open(tr.dataset.href, "_blank", "noopener");
    else if (event.button === 0 && String(window.getSelection()) === "") window.location.href = tr.dataset.href;
  }
  document.addEventListener("click", open);
  document.addEventListener("auxclick", open);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.matches("tr[data-href]")) window.location.href = event.target.dataset.href;
  });
})();
