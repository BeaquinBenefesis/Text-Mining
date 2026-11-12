// Search suggestions for every search box: a list under the input, filled from
// /api/suggest while typing. Picking one opens its page; Enter without a pick
// still submits the normal search.
(function () {
  const DELAY = 150, MIN_CHARS = 2;

  document.querySelectorAll("form.search input[name=q]").forEach(input => {
    const form = input.form, list = document.createElement("ul");
    list.className = "suggest";
    list.hidden = true;
    form.appendChild(list);
    let timer, controller, active = -1;

    const items = () => [...list.children];
    const close = () => { list.hidden = true; active = -1; };
    const highlight = i => {
      items().forEach((li, j) => li.classList.toggle("active", j === i));
      active = i;
    };

    function show(suggestions) {
      list.replaceChildren(...suggestions.map(s => {
        const li = document.createElement("li"), a = document.createElement("a"), meta = document.createElement("span");
        a.href = s.url;
        a.textContent = s.name;
        meta.className = "meta";
        meta.textContent = s.matched ? `${s.meta} · “${s.matched}”` : s.meta;
        a.appendChild(meta);
        li.appendChild(a);
        return li;
      }));
      active = -1;
      list.hidden = !suggestions.length;
      list.style.left = input.offsetLeft + "px";
      list.style.top = input.offsetTop + input.offsetHeight + 4 + "px";
      list.style.width = input.offsetWidth + "px";
    }

    input.addEventListener("input", () => {
      clearTimeout(timer);
      if (controller) controller.abort();
      const query = input.value.trim();
      if (query.length < MIN_CHARS) { close(); return; }
      timer = setTimeout(() => {
        controller = new AbortController();
        fetch("/api/suggest?q=" + encodeURIComponent(query), { signal: controller.signal })
          .then(r => r.json()).then(show).catch(() => {});
      }, DELAY);
    });

    input.addEventListener("keydown", e => {
      if (list.hidden) return;
      const n = items().length;
      if (e.key === "ArrowDown") { e.preventDefault(); highlight((active + 1) % n); }
      else if (e.key === "ArrowUp") { e.preventDefault(); highlight((active - 1 + n) % n); }
      else if (e.key === "Escape") close();
      else if (e.key === "Enter" && active >= 0) {
        e.preventDefault();
        window.location = items()[active].firstChild.href;
      }
    });
    // mousedown fires before blur, so a click on a suggestion is not lost to closing the list
    list.addEventListener("mousedown", e => e.preventDefault());
    input.addEventListener("blur", close);
  });
})();
