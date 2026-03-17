(function () {
  "use strict";

  var SUPABASE_URL = "https://mtbtgpwzrbostweaanpr.supabase.co";
  var SUPABASE_ANON_KEY =
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im10YnRncHd6cmJvc3R3ZWFhbnByIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMxODk0OTQsImV4cCI6MjA4ODc2NTQ5NH0._xMlqCfljtXpwPj54H-ghxfLFO-jiq4W2WhpU8vVL1c";

  var PAGE_SIZE = 50;
  var allRows = [];
  var currentPage = 0;

  // No-KV-cache formula: FLOPs = params_b * 1e9 * N * (N+1)
  var DEFAULT_PARAMS_B = 137;
  var ENERGY_WH_PER_FLOP = 0.4 / (1000 * 3e12);

  function recomputeFlopsNoKvCache(totalTokens) {
    var n = Number(totalTokens) || 0;
    if (n <= 0) return 0;
    return DEFAULT_PARAMS_B * 1e9 * n * (n + 1);
  }

  function recomputeEnergyNoKvCache(flops) {
    return flops * ENERGY_WH_PER_FLOP;
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
      html +=
        "<tr>" +
        '<td><span class="lb-rank' + rankClass + '">' + (medal || rank) + "</span></td>" +
        '<td class="lb-name">' + escapeHtml(row.display_name) + "</td>" +
        '<td class="lb-number">$' + Number(row.dollar_savings || 0).toFixed(4) + "</td>" +
        '<td class="lb-number">' + Number(row.energy_wh_saved || 0).toFixed(2) + "</td>" +
        '<td class="lb-number">' + fmtLarge(Number(row.flops_saved || 0)) + "</td>" +
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
      SUPABASE_URL +
        "/rest/v1/savings_entries?select=display_name,dollar_savings,energy_wh_saved,flops_saved,total_calls,total_tokens&order=dollar_savings.desc&limit=1000",
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

        allRows = rows;
        currentPage = 0;

        var totalMembers = rows.length;
        var totalDollars = 0;
        var totalRequests = 0;
        var totalTokens = 0;
        for (var i = 0; i < rows.length; i++) {
          totalDollars += Number(rows[i].dollar_savings || 0);
          totalRequests += Number(rows[i].total_calls || 0);
          totalTokens += Number(rows[i].total_tokens || 0);
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
