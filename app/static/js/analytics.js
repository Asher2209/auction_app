// Admin analytics. Colour, marks and interaction follow the dataviz method:
//  - single-series charts use ONE colour (slot 1); nominal categories are never value-ramped
//  - multi-series charts use categorical slots in a FIXED order (an entity keeps its colour)
//  - one axis per chart, thin marks, 4px rounded data ends, 2px surface gaps between stacked fills
//  - a legend is always present for 2+ series and carries the values; every chart has a table view
// All server-supplied text (names, titles) is written with textContent: nothing is interpreted as HTML.
(function () {
  const root = document.getElementById("analytics");
  if (!root || typeof Chart === "undefined") return;

  const css = (n) => getComputedStyle(root).getPropertyValue(n).trim();
  const SLOTS = ["--viz-s1", "--viz-s2", "--viz-s3", "--viz-s4"];
  const slot = (i) => css(SLOTS[i]);
  const cur = root.dataset.currency || "";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
  const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });
  const money = (v) => cur + inr2.format(v);
  const trunc = (s, n = 24) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;

  const charts = {};
  const cardOf = (id) => {
    const el = root.querySelector(`[data-chart="${id}"]`);
    return { el, canvas: el.querySelector("canvas"), plot: el.querySelector(".viz-plot"), legend: el.querySelector(".viz-legend"),
             empty: el.querySelector(".viz-empty"), table: el.querySelector(".viz-table"), toggle: el.querySelector(".viz-toggle") };
  };

  function setTable(c, headers, rows) {
    const t = document.createElement("table");
    t.className = "table table-sm table-borderless";
    const head = t.createTHead().insertRow();
    headers.forEach((h, i) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = h; if (i) th.className = "text-end"; head.appendChild(th); });
    const body = t.createTBody();
    rows.forEach((r) => { const tr = body.insertRow(); r.forEach((v, i) => { const td = tr.insertCell(); td.textContent = v; if (i) td.className = "text-end"; }); });
    c.table.replaceChildren(t);
  }

  function setLegend(c, items) { // items: [{color, label, value}]
    c.legend.replaceChildren(...items.map((it) => {
      const li = document.createElement("li");
      const sw = document.createElement("span"); sw.className = "viz-swatch"; sw.style.background = it.color;
      const name = document.createElement("span"); name.textContent = it.label;
      li.append(sw, name);
      if (it.value !== undefined) { const b = document.createElement("b"); b.textContent = it.value; li.appendChild(b); }
      return li;
    }));
  }

  function present(c, hasData) {
    c.plot.hidden = !hasData; c.legend.hidden = !hasData; c.empty.hidden = hasData; c.toggle.hidden = !hasData;
    if (!hasData) c.table.hidden = true;
  }

  function draw(id, c, config) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(c.canvas, config);
  }

  const baseOptions = (extra = {}) => ({
    responsive: true, maintainAspectRatio: false, animation: reduceMotion ? false : { duration: 250 },
    plugins: { legend: { display: false }, tooltip: { padding: 10, boxPadding: 4 } }, ...extra,
  });
  const gridY = () => ({ grid: { color: css("--viz-grid"), drawTicks: false }, border: { display: false }, ticks: { color: css("--viz-muted"), padding: 6 } });
  const noGrid = () => ({ grid: { display: false }, border: { color: css("--viz-axis") }, ticks: { color: css("--viz-muted") } });
  const hit = { mode: "index", intersect: false }; // wide hover target: the whole column band
  const rounded = { borderRadius: 4, borderSkipped: "start", maxBarThickness: 22 };

  // ---- column charts over months -------------------------------------------------------------
  function revenue(d) {
    const c = cardOf("revenue");
    present(c, !d.empty.revenue);
    if (d.empty.revenue) return;
    const sum = (a) => a.reduce((x, y) => x + y, 0);
    const sim = sum(d.revenue.simulated), cry = sum(d.revenue.crypto);
    setLegend(c, [{ color: slot(0), label: "Card, UPI and wallet (simulated)", value: money(sim) }, { color: slot(1), label: "Cryptocurrency", value: money(cry) }]);
    const gap = { borderWidth: 2, borderColor: css("--viz-surface"), maxBarThickness: 36 };
    draw("revenue", c, { type: "bar", data: { labels: d.labels, datasets: [
      { label: "Simulated payments", data: d.revenue.simulated, backgroundColor: slot(0), ...gap },
      { label: "Cryptocurrency", data: d.revenue.crypto, backgroundColor: slot(1), ...gap }] },
      options: baseOptions({ interaction: hit, scales: { x: { ...noGrid(), stacked: true }, y: { ...gridY(), stacked: true, beginAtZero: true,
        ticks: { color: css("--viz-muted"), padding: 6, callback: (v) => cur + compact.format(v) } } },
        plugins: { legend: { display: false }, tooltip: { padding: 10, callbacks: { label: (i) => ` ${i.dataset.label}: ${money(i.parsed.y)}`,
          footer: (items) => "Total: " + money(items.reduce((a, i) => a + i.parsed.y, 0)) } } } }) });
    setTable(c, ["Month", "Simulated", "Cryptocurrency", "Total"],
      d.labels.map((l, i) => [l, money(d.revenue.simulated[i]), money(d.revenue.crypto[i]), money(d.revenue.simulated[i] + d.revenue.crypto[i])]));
  }

  function columnSingle(id, labels, data, name, fmt, empty, tick) {
    const c = cardOf(id);
    present(c, !empty);
    if (empty) return;
    draw(id, c, { type: "bar", data: { labels, datasets: [{ label: name, data, backgroundColor: slot(0), ...rounded }] },
      options: baseOptions({ interaction: hit, scales: { x: noGrid(), y: { ...gridY(), beginAtZero: true, ticks: { color: css("--viz-muted"), padding: 6, ...tick } } },
        plugins: { legend: { display: false }, tooltip: { padding: 10, callbacks: { label: (i) => ` ${name}: ${fmt(i.parsed.y)}` } } } }) });
    setTable(c, ["Month", name], labels.map((l, i) => [l, fmt(data[i])]));
  }

  // ---- one-bar part-to-whole (states, payment methods) -------------------------------------------
  function parts(id, items) {
    const c = cardOf(id);
    const total = items.reduce((a, i) => a + i.value, 0);
    present(c, total > 0);
    if (!total) return;
    setLegend(c, items.map((it, i) => ({ color: slot(i), label: it.label, value: `${it.value} (${Math.round((100 * it.value) / total)}%)` })));
    draw(id, c, { type: "bar", data: { labels: [""], datasets: items.map((it, i) => ({ label: it.label, data: [it.value], backgroundColor: slot(i),
      borderWidth: 2, borderColor: css("--viz-surface"), borderRadius: 3, maxBarThickness: 44 })) },
      options: baseOptions({ indexAxis: "y", interaction: { mode: "nearest", intersect: true }, layout: { padding: 0 },
        scales: { x: { stacked: true, display: false, max: total }, y: { stacked: true, display: false } },
        plugins: { legend: { display: false }, tooltip: { padding: 10, callbacks: { title: () => "", label: (i) => ` ${i.dataset.label}: ${i.parsed.x} (${Math.round((100 * i.parsed.x) / total)}%)` } } } }) });
    setTable(c, ["Group", "Count", "Share"], items.map((it) => [it.label, it.value, Math.round((100 * it.value) / total) + "%"]));
  }

  // ---- ranked horizontal bars ------------------------------------------------------------------------
  function ranked(id, rows, name, fmt, extraHeaders = [], extraCells = () => []) {
    const c = cardOf(id);
    present(c, rows.length > 0);
    if (!rows.length) return;
    draw(id, c, { type: "bar", data: { labels: rows.map((r) => trunc(r.label)), datasets: [{ label: name, data: rows.map((r) => r.value), backgroundColor: slot(0), ...rounded }] },
      options: baseOptions({ indexAxis: "y", interaction: { mode: "nearest", axis: "y", intersect: false },
        scales: { x: { ...gridY(), beginAtZero: true, ticks: { color: css("--viz-muted"), padding: 6, precision: 0, callback: (v) => (fmt === money ? cur + compact.format(v) : v) } },
                  y: { grid: { display: false }, border: { color: css("--viz-axis") }, ticks: { color: css("--viz-ink-2") } } },
        plugins: { legend: { display: false }, tooltip: { padding: 10, callbacks: { title: (i) => rows[i[0].dataIndex].label, label: (i) => ` ${name}: ${fmt(i.parsed.x)}` } } } }) });
    setTable(c, ["Name", name, ...extraHeaders], rows.map((r) => [r.label, fmt(r.value), ...extraCells(r)]));
  }

  function tiles(d) {
    const set = (id, text) => { document.getElementById("tile-" + id).textContent = text; };
    set("revenue", money(d.kpis.revenue)); set("paid_sales", d.kpis.paid_sales); set("average_sale", money(d.kpis.average_sale));
    set("crypto_confirmed", d.crypto.confirmed + (d.crypto.pending ? ` (+${d.crypto.pending} pending)` : "") + (d.crypto.failed ? `, ${d.crypto.failed} failed` : ""));
    set("eth_total", d.crypto.eth_total ? d.crypto.eth_total.toLocaleString(undefined, { maximumFractionDigits: 6 }) + " ETH" : "0 ETH");
    set("crypto_rate", d.crypto.success_rate === null ? "–" : d.crypto.success_rate + "%");
  }

  function render(d) {
    tiles(d);
    revenue(d);
    columnSingle("auctions", d.labels, d.auctions_per_month, "Auctions", (v) => String(v), d.empty.auctions, { precision: 0 });
    parts("status", d.status);
    ranked("categories", d.categories, "Bids", (v) => String(v), ["Auctions"], (r) => [r.auctions]);
    parts("methods", d.methods);
    ranked("products", d.top_products, "Sale value", money, ["Seller"], (r) => [r.seller]);
    ranked("sellers", d.top_sellers, "Paid sales", money, ["Sales"], (r) => [r.sales]);
    ranked("buyers", d.active_buyers, "Bids", (v) => String(v), ["Auctions bid on"], (r) => [r.auctions]);
    columnSingle("eth", d.labels, d.eth_per_month, "ETH received", (v) => v.toLocaleString(undefined, { maximumFractionDigits: 6 }) + " ETH",
      !d.eth_per_month.some(Boolean), { callback: (v) => v });
  }

  // ---- table view toggles ------------------------------------------------------------------------------------
  root.querySelectorAll(".viz-card").forEach((card) => {
    const btn = card.querySelector(".viz-toggle"), table = card.querySelector(".viz-table");
    btn.addEventListener("click", () => {
      const open = table.hidden;
      table.hidden = !open;
      btn.setAttribute("aria-pressed", String(open));
      btn.textContent = open ? "Hide table" : "View as table";
    });
  });

  // ---- loading and the one filter ---------------------------------------------------------------------------------
  const note = document.getElementById("load-note");
  const select = document.getElementById("months");
  function load() {
    root.classList.add("loading"); // hold the previous render, dimmed: no skeleton flash
    note.textContent = "";
    fetch(`${root.dataset.url}?months=${encodeURIComponent(select.value)}`, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => { render(d); const u = new URL(location.href); u.searchParams.set("months", d.months); history.replaceState(null, "", u); })
      .catch(() => { note.textContent = "Could not load the analytics data. Please refresh."; })
      .finally(() => root.classList.remove("loading"));
  }
  select.addEventListener("change", load);
  load();
})();
