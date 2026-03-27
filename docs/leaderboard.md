---
hide:
  - navigation
---

# Savings Leaderboard

See how the OpenJarvis community saves money, energy, and compute by running AI locally instead of using cloud providers.

!!! info "Win a Mac Mini!"
    Opt in to share your savings from the OpenJarvis browser app or desktop app for a chance to win a Mac Mini. Your data is fully anonymous — no email, no IP, no hardware info.

<div id="leaderboard-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:24px 0;">
  <div class="lb-stat-card">
    <div class="lb-stat-label">Community Members</div>
    <div class="lb-stat-value" id="stat-members">—</div>
  </div>
  <div class="lb-stat-card">
    <div class="lb-stat-label">Total Saved*</div>
    <div class="lb-stat-value" id="stat-dollars">—</div>
  </div>
  <div class="lb-stat-card">
    <div class="lb-stat-label">Total Requests</div>
    <div class="lb-stat-value" id="stat-requests">—</div>
  </div>
  <div class="lb-stat-card">
    <div class="lb-stat-label">Total Tokens</div>
    <div class="lb-stat-value" id="stat-tokens">—</div>
  </div>
</div>

<div id="leaderboard-table-wrapper">
  <table id="leaderboard-table" class="lb-table">
    <thead>
      <tr>
        <th style="width:50px">#</th>
        <th>Name</th>
        <th style="text-align:right">$ Saved*</th>
        <th style="text-align:right">Energy (Wh)</th>
        <th style="text-align:right">FLOPs</th>
        <th style="text-align:right">Requests</th>
        <th style="text-align:right">Tokens</th>
      </tr>
    </thead>
    <tbody id="leaderboard-body">
      <tr>
        <td colspan="7" style="text-align:center;padding:48px;opacity:0.5">
          Loading leaderboard...
        </td>
      </tr>
    </tbody>
  </table>
</div>

<div id="leaderboard-pagination" class="lb-pagination"></div>

<p style="font-size:12px;opacity:0.6;margin-top:12px">
*Dollar savings estimated vs. Claude Opus 4.6 API pricing ($5/1M input, $25/1M output tokens). Assumes local open-source models produce roughly the same number of tokens per request as cloud models.
</p>
