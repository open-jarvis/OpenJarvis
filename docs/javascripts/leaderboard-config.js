// Public Supabase config for the savings leaderboard.
//
// This file is loaded *before* leaderboard.js and supplies the anon key it
// reads from `window.OPENJARVIS_SUPABASE_ANON_KEY`. The key is injected at
// docs-build time from the VITE_SUPABASE_ANON_KEY repo secret (see
// .github/workflows/docs.yml). It is intentionally empty here so that local
// `mkdocs build` and fork pull requests — which have no secret — render the
// graceful "Leaderboard not configured yet" message instead of failing.
//
// The anon key is public by design: Supabase Row-Level Security protects the
// data, so shipping it in the public docs bundle is expected.
window.OPENJARVIS_SUPABASE_ANON_KEY = "";
