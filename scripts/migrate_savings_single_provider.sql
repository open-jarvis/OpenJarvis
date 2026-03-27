-- Migration: Recompute dollar_savings to use only Claude Opus 4.6 pricing
-- -----------------------------------------------------------------------
-- Previously the frontend summed hypothetical costs across all 3 cloud
-- providers (GPT-5.3 + Claude Opus 4.6 + Gemini 3.1 Pro).  This
-- migration recalculates dollar_savings using Claude Opus 4.6 only.
--
-- Derivation
-- ----------
-- Let P = prompt_tokens, C = completion_tokens, T = total_tokens = P + C.
--
--   old = (P/1M)*(2+5+2) + (C/1M)*(10+25+12) = (P/1M)*9 + (C/1M)*47
--   new = (P/1M)*5 + (C/1M)*25
--
-- Solving the system {T = P + C, old = 9P/1M + 47C/1M} for P and C and
-- substituting into the "new" formula gives:
--
--   new = T / 3_800_000 + 10 * old / 19
--
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor).
-- -----------------------------------------------------------------------

BEGIN;

-- Preview the changes first (uncomment the SELECT, comment the UPDATE)
-- SELECT
--   display_name,
--   dollar_savings AS old_savings,
--   total_tokens / 3800000.0 + 10.0 * dollar_savings / 19.0 AS new_savings
-- FROM savings_entries
-- WHERE dollar_savings > 0
-- ORDER BY dollar_savings DESC;

UPDATE savings_entries
SET dollar_savings = total_tokens / 3800000.0 + 10.0 * dollar_savings / 19.0
WHERE dollar_savings > 0;

COMMIT;
