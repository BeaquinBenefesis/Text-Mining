// Renders every <canvas data-src> as a dual-axis timeline: raw article counts as
// bars, share of that year's corpus as a line. The line is the series to read --
// the corpus is 99% post-2010, so raw counts largely describe corpus coverage.
(function () {
  const COLOURS = { raw: "#c8d4e3", share: "#2f6f9f", context: "#d9b8a8" };

  async function fetchPoints(url) {
    const response = await fetch(url);
    if (!response.ok) return [];
    return (await response.json()).points || [];
  }

  async function draw(canvas) {
    const points = await fetchPoints(canvas.dataset.src);
    if (!points.length) {
      canvas.replaceWith(Object.assign(document.createElement("p"), {
        className: "empty", textContent: "No dated articles for this timeline.",
      }));
      return;
    }

    const datasets = [
      { type: "bar", label: "articles (raw)", data: points.map(p => p.n_articles),
        backgroundColor: COLOURS.raw, yAxisID: "y", order: 2 },
      { type: "line", label: "share of corpus", data: points.map(p => p.share),
        borderColor: COLOURS.share, backgroundColor: COLOURS.share,
        yAxisID: "yShare", tension: 0.25, pointRadius: 2, order: 1 },
    ];

    // On an association page, overlay the miRNA's overall attention curve so the
    // association can be read against it rather than in isolation.
    if (window.__contextTimeline) {
      const context = await fetchPoints(window.__contextTimeline);
      const byYear = new Map(context.map(p => [p.year, p.share]));
      datasets.push({
        type: "line", label: "miRNA overall (share)",
        data: points.map(p => byYear.get(p.year) ?? null),
        borderColor: COLOURS.context, borderDash: [4, 3], yAxisID: "yShare",
        tension: 0.25, pointRadius: 0, order: 0,
      });
    }

    const chart = new Chart(canvas, {
      data: { labels: points.map(p => p.year), datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { position: "left", title: { display: true, text: "articles" }, beginAtZero: true },
          yShare: { position: "right", title: { display: true, text: "share of corpus" },
                    beginAtZero: true, grid: { drawOnChartArea: false },
                    ticks: { callback: v => (v * 100).toFixed(2) + "%" } },
        },
        plugins: {
          tooltip: { callbacks: { label: item => item.dataset.yAxisID === "yShare"
              ? `${item.dataset.label}: ${(item.parsed.y * 100).toFixed(3)}%`
              : `${item.dataset.label}: ${item.parsed.y.toLocaleString()}` } },
        },
        onClick: (event, elements) => {
          const base = canvas.dataset.link;
          if (!base || !elements.length) return;
          window.location = base + points[elements[0].index].year;
        },
      },
    });
    if (canvas.dataset.link) canvas.style.cursor = "pointer";
    return chart;
  }

  document.querySelectorAll("canvas[data-src]").forEach(draw);
})();
