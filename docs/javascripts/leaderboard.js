(function () {
  "use strict";

  var SUPABASE_URL =
    window.OPENJARVIS_SUPABASE_URL || "https://mtbtgpwzrbostweaanpr.supabase.co";
  var SUPABASE_ANON_KEY = window.OPENJARVIS_SUPABASE_ANON_KEY || "";

  var PAGE_SIZE = 50;
  var allRows = [];
  var currentPage = 0;

  // Outlier detection — hide entries with values that are physically
  // implausible relative to their token count.  Thresholds are ~1000x
  // above legitimate per-token values to avoid false positives.
  // Outlier bounds. Set well above realistic upper limits but tight
  // enough to drop the pre-fix bimodal Group B (1-5 Wh/token, ~3e16
  // FLOPs/token) — see the leaderboard PR for the full diagnosis.
  // Realistic per-token rates on a consumer GPU + 10–30B local model:
  // ~0.001 Wh/token, ~1e10–1e11 FLOPs/token. We allow 500× and 10,000×
  // headroom respectively for inefficient hardware / larger models.
  var MAX_ENERGY_WH_PER_TOKEN = 0.5;        // legit ≈ 0.001 Wh/tok
  var MAX_FLOPS_PER_TOKEN = 1e15;           // legit ≈ 1e11 /tok
  var MAX_DOLLAR_PER_TOKEN = 25.0 / 1e6;   // hard ceiling: $25/1M output

  function isOutlier(row) {
    var tokens = Number(row.total_tokens) || 0;
    if (tokens <= 0) return false;
    var energy = Number(row.energy_wh_saved) || 0;
    var flops = Number(row.flops_saved) || 0;
    var dollars = Number(row.dollar_savings) || 0;
    return (
      energy / tokens > MAX_ENERGY_WH_PER_TOKEN ||
      flops / tokens > MAX_FLOPS_PER_TOKEN ||
      dollars / tokens > MAX_DOLLAR_PER_TOKEN
    );
  }

  // Distinguish "user actually has zero work done" from "user's energy /
  // FLOPs telemetry never landed". The latter happens when the server
  // submits with valid dollar savings + token counts but the per-record
  // energy stamp was missing (pre-fix builds, GPU energy meter
  // unavailable, etc.). Without this check those rows show as "0.00 Wh"
  // and skew the rankings + headline totals.
  //
  // Threshold: 1000 tokens is well above any single chat-turn — if a
  // user has that many tokens recorded but no measured energy, the
  // telemetry is incomplete, not legitimately zero.
  var MIN_TOKENS_FOR_TELEMETRY = 1000;

  function isMissingTelemetry(row) {
    var tokens = Number(row.total_tokens) || 0;
    var energy = Number(row.energy_wh_saved) || 0;
    var flops = Number(row.flops_saved) || 0;
    return tokens > MIN_TOKENS_FOR_TELEMETRY && energy === 0 && flops === 0;
  }

  function escapeHtml(s) {
    var el = document.createElement("span");
    el.textContent = s;
    return el.innerHTML;
  }

  function fmtLarge(n) {
    if (n >= 1e12) return (n / 1e12).toFixed(1) + "T";
    if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toLocaleString();
  }

  function totalPages() {
    return Math.max(1, Math.ceil(allRows.length / PAGE_SIZE));
  }

  function renderPage() {
    var tbody = document.getElementById("leaderboard-body");
    if (!tbody) return;

    var start = currentPage * PAGE_SIZE;
    var end = Math.min(start + PAGE_SIZE, allRows.length);
    var pageRows = allRows.slice(start, end);

    var html = "";
    for (var j = 0; j < pageRows.length; j++) {
      var rank = start + j + 1;
      var rankClass = rank <= 3 ? " lb-rank-" + rank : "";
      var medal =
        rank === 1 ? "\uD83E\uDD47" : rank === 2 ? "\uD83E\uDD48" : rank === 3 ? "\uD83E\uDD49" : "";
      var row = pageRows[j];
      // Render "—" for energy / FLOPs columns when telemetry didn't
      // land (vs the user genuinely having 0). The dollar / request /
      // token columns are unaffected because those measurements landed
      // even when energy didn't.
      var missing = isMissingTelemetry(row);
      var energyCell = missing
        ? '<td class="lb-number lb-missing" title="Energy telemetry missing for this entry">—</td>'
        : '<td class="lb-number">' + Number(row.energy_wh_saved || 0).toFixed(2) + "</td>";
      var flopsCell = missing
        ? '<td class="lb-number lb-missing" title="FLOPs telemetry missing for this entry">—</td>'
        : '<td class="lb-number">' + fmtLarge(Number(row.flops_saved || 0)) + "</td>";
      html +=
        "<tr>" +
        '<td><span class="lb-rank' + rankClass + '">' + (medal || rank) + "</span></td>" +
        '<td class="lb-name">' + escapeHtml(row.display_name) + "</td>" +
        '<td class="lb-number">$' + Number(row.dollar_savings || 0).toFixed(4) + "</td>" +
        energyCell +
        flopsCell +
        '<td class="lb-number">' + Number(row.total_calls || 0).toLocaleString() + "</td>" +
        '<td class="lb-number">' + Number(row.total_tokens || 0).toLocaleString() + "</td>" +
        "</tr>";
    }
    tbody.innerHTML = html;

    renderPagination();
  }

  function renderPagination() {
    var container = document.getElementById("leaderboard-pagination");
    if (!container) return;

    var pages = totalPages();
    if (pages <= 1) {
      container.innerHTML = "";
      return;
    }

    var prevDisabled = currentPage === 0;
    var nextDisabled = currentPage >= pages - 1;

    container.innerHTML =
      '<button class="lb-page-btn"' + (prevDisabled ? " disabled" : "") + ' id="lb-prev">' +
      "\u2190 Prev</button>" +
      '<span class="lb-page-info">Page ' + (currentPage + 1) + " of " + pages + "</span>" +
      '<button class="lb-page-btn"' + (nextDisabled ? " disabled" : "") + ' id="lb-next">' +
      "Next \u2192</button>";

    var prevBtn = document.getElementById("lb-prev");
    var nextBtn = document.getElementById("lb-next");
    if (prevBtn) prevBtn.onclick = function () { if (currentPage > 0) { currentPage--; renderPage(); } };
    if (nextBtn) nextBtn.onclick = function () { if (currentPage < pages - 1) { currentPage++; renderPage(); } };
  }

  function loadLeaderboard() {
    var tbody = document.getElementById("leaderboard-body");
    if (!tbody) return;

    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
      tbody.innerHTML =
        '<tr><td colspan="7" style="text-align:center;padding:48px;opacity:0.5">' +
        "Leaderboard not configured yet.</td></tr>";
      return;
    }

    fetch(
      // `methodology_version=gte.1` filter excludes rows that the
      // leaderboard-correctness migration quarantined (version 0). Rows
      // written by current and future clients carry version >= 1, so this
      // is forward-compatible — pre-fix corrupt rows hide at the query
      // level (fewer bytes over the wire than client-side outlier
      // filtering), and downstream client-side checks remain as a
      // belt-and-suspenders second line of defence.
      SUPABASE_URL +
        "/rest/v1/savings_entries?select=display_name,dollar_savings,energy_wh_saved,flops_saved,total_calls,total_tokens&methodology_version=gte.1&order=dollar_savings.desc&limit=1000",
      {
        headers: {
          apikey: SUPABASE_ANON_KEY,
          Authorization: "Bearer " + SUPABASE_ANON_KEY,
        },
      }
    )
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (rows) {
        if (!rows.length) {
          tbody.innerHTML =
            '<tr><td colspan="7" style="text-align:center;padding:48px;opacity:0.5">' +
            "No entries yet. Be the first to opt in!</td></tr>";
          return;
        }

        allRows = rows.filter(function (r) { return !isOutlier(r); });
        currentPage = 0;

        var totalMembers = allRows.length;
        var totalDollars = 0;
        var totalRequests = 0;
        var totalTokens = 0;
        for (var i = 0; i < allRows.length; i++) {
          totalDollars += Number(allRows[i].dollar_savings || 0);
          totalRequests += Number(allRows[i].total_calls || 0);
          totalTokens += Number(allRows[i].total_tokens || 0);
        }

        var elMembers = document.getElementById("stat-members");
        var elDollars = document.getElementById("stat-dollars");
        var elRequests = document.getElementById("stat-requests");
        var elTokens = document.getElementById("stat-tokens");

        if (elMembers) elMembers.textContent = totalMembers.toLocaleString();
        if (elDollars) elDollars.textContent = "$" + totalDollars.toFixed(2);
        if (elRequests) elRequests.textContent = totalRequests.toLocaleString();
        if (elTokens) elTokens.textContent = fmtLarge(totalTokens);

        renderPage();
      })
      .catch(function (err) {
        tbody.innerHTML =
          '<tr><td colspan="7" style="text-align:center;padding:48px;color:var(--md-accent-fg-color)">' +
          "Failed to load leaderboard: " +
          escapeHtml(String(err)) +
          "</td></tr>";
      });
  }

  if (document.getElementById("leaderboard-body")) {
    loadLeaderboard();
    setInterval(loadLeaderboard, 60000);
  }
})();
