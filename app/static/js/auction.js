// Live auction page: countdown, real-time bids over Socket.IO, and bid submission.
// All server-supplied text is written with textContent, never innerHTML.
(function () {
  const root = document.getElementById("auction-live");
  if (!root) return;

  const auctionId = root.dataset.auctionId;
  const me = root.dataset.userId ? parseInt(root.dataset.userId, 10) : null;
  const currency = root.dataset.currency;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content;

  let status = root.dataset.status;
  let startMs = Date.parse(root.dataset.start);
  let endMs = Date.parse(root.dataset.end);
  let skew = Date.parse(root.dataset.now) - Date.now(); // server clock minus this browser's clock
  let leadingId = root.dataset.leadingId ? parseInt(root.dataset.leadingId, 10) : null;
  let syncing = false;

  const $ = (id) => document.getElementById(id);
  const money = (v) => currency + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pad = (n) => String(n).padStart(2, "0");
  // Times are shown in the site zone (fixed offset, from <meta name="app-tz">); the countdown itself works on absolute UTC instants.
  const tzMeta = document.querySelector('meta[name="app-tz"]');
  const tzName = tzMeta ? tzMeta.content : "UTC";
  const tzOffset = tzMeta ? parseInt(tzMeta.dataset.offset, 10) || 0 : 0;
  const fmtTime = (iso) => new Date(Date.parse(iso) + tzOffset * 60000).toUTCString().slice(5, 22) + " " + tzName;

  function notice(text, kind) {
    const el = $("notice");
    el.className = "alert alert-" + kind;
    el.textContent = text;
  }

  // ---- badge / form visibility ------------------------------------------
  function renderStatus() {
    const badge = $("status-badge");
    const map = { active: ["Live", "chip-live"], scheduled: ["Upcoming", "chip-upcoming"], closed: ["Ended", "chip-muted"] };
    const [label, cls] = map[status] || ["", "chip-muted"];
    badge.textContent = label;
    badge.className = "chip " + cls;
    const form = $("bid-form");
    if (form) form.classList.toggle("d-none", status !== "active");
    $("end-label").textContent = status === "closed" ? "Ended" : "Ends";
  }

  // ---- countdown: Days : Hours : Minutes : Seconds -----------------------
  function tick() {
    const label = $("countdown-label");
    const el = $("countdown");
    if (status === "closed") {
      label.textContent = "";
      el.textContent = "Ended";
      return;
    }
    const target = status === "scheduled" ? startMs : endMs;
    label.textContent = status === "scheduled" ? "Starts in" : "Time remaining";
    let secs = Math.floor((target - (Date.now() + skew)) / 1000);
    if (secs <= 0) {
      el.textContent = "00 : 00 : 00 : 00";
      syncState(); // ask the server what happened at zero (it closes or starts the auction)
      return;
    }
    const d = Math.floor(secs / 86400);
    const h = Math.floor((secs % 86400) / 3600);
    const m = Math.floor((secs % 3600) / 60);
    el.textContent = [pad(d), pad(h), pad(m), pad(secs % 60)].join(" : ");
  }

  // ---- applying server state --------------------------------------------
  function applyState(s, announceExtension) {
    skew = Date.parse(s.server_now) - Date.now();
    const newEnd = Date.parse(s.end_time);
    if (announceExtension && newEnd > endMs && status === "active") {
      notice("Last-minute bid! The auction was extended by 2 minutes.", "warning");
    }
    startMs = Date.parse(s.start_time);
    endMs = newEnd;
    status = s.status;
    leadingId = s.leading_bidder_id;
    $("current-bid").textContent = money(s.current_bid);
    $("bid-count").textContent = s.bid_count;
    $("bid-label").textContent = s.bid_count ? "Current highest bid" : "Starting price";
    $("end-time").textContent = fmtTime(s.end_time);
    const minEl = $("min-bid");
    if (minEl) minEl.textContent = money(s.min_next_bid);
    const amt = $("amount");
    if (amt) amt.placeholder = s.min_next_bid;
    const stepEl = $("bid-step");
    if (stepEl && s.bid_step) stepEl.textContent = money(s.bid_step);
    const reserve = $("reserve-chip");
    if (reserve) {
      reserve.textContent = s.reserve_met ? "Reserve met" : "Reserve not met";
      reserve.className = "chip " + (s.reserve_met ? "chip-verified" : "chip-muted");
    }
    const buyNow = $("buy-now-form");
    if (buyNow && !s.buy_now_price) buyNow.remove(); // gone with the first bid, for good
    renderStatus();
    tick();
  }

  function syncState() {
    if (syncing) return;
    syncing = true;
    fetch(`/auctions/${auctionId}/state`, { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((s) => {
        const wasClosed = status === "closed";
        applyState(s, false);
        if (s.status === "closed" && !wasClosed) showClosed(s); // the state also carries the masked winner
      })
      .catch(() => {})
      .finally(() => setTimeout(() => (syncing = false), 1500)); // avoid hammering at zero
  }

  function showClosed(info) {
    status = "closed";
    renderStatus();
    tick();
    const box = $("winner-box");
    if (info && info.winner_mask) {
      box.textContent = `Won by ${info.winner_mask} for ${money(info.winning_amount)}.`;
      box.classList.remove("d-none");
    }
    notice("This auction has ended.", "secondary");
    if (me && leadingId === me) notice("Congratulations, you won! Check your won auctions to pay.", "success");
  }

  // ---- bid history row ---------------------------------------------------
  function addBidRow(b) {
    const rows = $("bid-rows");
    const tr = document.createElement("tr");
    const who = document.createElement("td");
    if (me && b.bidder_id === me) {
      const strong = document.createElement("strong");
      strong.textContent = "You";
      who.appendChild(strong);
    } else {
      who.textContent = b.bidder_mask;
    }
    const amt = document.createElement("td");
    amt.textContent = money(b.amount);
    const when = document.createElement("td");
    when.textContent = fmtTime(b.bid_time);
    tr.append(who, amt, when);
    rows.insertBefore(tr, rows.firstChild);
    while (rows.children.length > 20) rows.removeChild(rows.lastChild);
    $("bid-table").classList.remove("d-none");
    $("no-bids").classList.add("d-none");
  }

  // ---- Socket.IO ---------------------------------------------------------
  const indicator = $("live-indicator");
  function setLive(on) {
    indicator.textContent = on ? "updating live" : "reconnecting…";
    indicator.className = "live-indicator" + (on ? " is-on" : "");
  }

  if (typeof io === "function") {
    const socket = window.mintlotSocket || io({ transports: ["websocket"] }); // signed-in pages share one connection
    const onConnect = () => {
      setLive(true);
      socket.emit("join", { auction_id: parseInt(auctionId, 10) });
      syncState(); // catch anything missed while disconnected
    };
    socket.on("connect", onConnect);
    if (socket.connected) onConnect(); // the shared socket may already be connected
    socket.on("disconnect", () => setLive(false));
    socket.on("bid_update", (b) => {
      const wasLeading = me && leadingId === me;
      applyState(b, true);
      (b.new_bids || [b]).forEach(addBidRow); // a bid, then any automatic bids it set off
      if (wasLeading && b.bidder_id !== me) notice("You have been outbid.", "warning");
    });
    socket.on("auction_closed", (info) => showClosed(info));
  } else {
    indicator.textContent = "offline";
  }

  // ---- placing a bid -----------------------------------------------------
  const form = $("bid-form");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const err = $("bid-error");
      const btn = $("bid-btn");
      err.textContent = "";
      btn.disabled = true;
      fetch(form.action, {
        method: "POST",
        headers: { "X-CSRFToken": csrf, Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ amount: $("amount").value, max_amount: ($("max_amount") || {}).value || "" }),
      })
        .then((r) => {
          if (r.redirected) { window.location = r.url; return null; } // session expired: sent to log in
          return r.json().catch(() => ({ ok: false, error: "Something went wrong. Please try again." }));
        })
        .then((data) => {
          if (!data) return;
          if (data.ok) {
            $("amount").value = "";
            if ($("max_amount")) $("max_amount").value = "";
            if (data.my_max && $("my-max")) {
              $("my-max").textContent = money(data.my_max);
              $("my-max-line").classList.remove("d-none");
            }
            if (data.leading_bidder_id !== me) notice("Another bidder's automatic bid beat yours at once. You can bid again.", "warning");
            if (!window.io) applyState(data, true); // no socket: update from the response instead
          } else {
            err.textContent = data.error;
            syncState();
          }
        })
        .catch(() => (err.textContent = "Network error. Please try again."))
        .finally(() => (btn.disabled = false));
    });
  }

  renderStatus();
  tick();
  setInterval(tick, 1000);
})();
