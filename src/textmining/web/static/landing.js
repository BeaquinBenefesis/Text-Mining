// Fills the landing page from /api/stats: the statistics scan every association, so
// the page does not wait for them.
(async function () {
  const response = await fetch("/api/stats");
  if (!response.ok) return;
  const stats = await response.json();
  const fmt = n => n.toLocaleString("en-US");
  const set = (id, n) => { document.getElementById(id).textContent = fmt(n); };

  set("stat-mirnas", stats.n_mirnas);
  set("stat-terms", stats.n_terms);
  set("stat-associations", stats.n_associations);
  set("stat-articles", stats.n_articles);
  set("no-relation", stats.n_no_label);
  set("early-articles", stats.n_early);
  set("undated-articles", stats.n_undated);

  const name = type => type[0] + type.slice(1).toLowerCase().replace(/_/g, " ");
  const maxType = Math.max(...stats.types.map(t => t.direct + t.propagated));
  document.getElementById("type-bars").innerHTML = stats.types.map(t => `
    <li><div class="head"><span>${name(t.type)}</span><b>${fmt(t.direct + t.propagated)}</b></div>
      <div class="bar"><span class="direct" style="width:${100 * t.direct / maxType}%" title="Direct: ${fmt(t.direct)}"></span>${
        t.propagated ? `<span class="propagated" style="width:${100 * t.propagated / maxType}%" title="Propagated: ${fmt(t.propagated)}"></span>` : ""}</div>
      <div class="note">${fmt(t.direct)} direct &middot; ${t.propagated ? fmt(t.propagated) + " propagated" : "no propagation"}</div></li>`).join("");

  const maxLabel = Math.max(...stats.labels.map(l => l.n));
  document.getElementById("label-bars").innerHTML = stats.labels.map(l => `
    <li><div class="head"><span>${l.label.replace(/_/g, " ")}</span><b>${fmt(l.n)}</b></div>
      <div class="bar"><span class="relation rel-${l.label}" style="width:${100 * l.n / maxLabel}%"></span></div></li>`).join("");
})();
