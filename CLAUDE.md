# CLAUDE.md — Clinical Data-Quality Reviewer / Ask Your Dataset Agent

## What this is
Project 2 of a 3-project CV portfolio (clinical-study-team-tools theme). A chat app where
users ask natural-language questions about a clinical trial dataset and get answers backed
by real SQL queries (never guessed from memory), plus a data-quality scan that flags likely
issues in plain language.

## Stack
- Backend: FastAPI + Claude API tool-use agent loop
- Database: Supabase (free Postgres) — connection string in `.env` as `DATABASE_URL`, never committed
- Frontend: React + Vite + Tailwind — chat interface (message list + input box)
- Deploy target: frontend on Vercel, backend on Render (both free tier)
- AI: Claude API (Anthropic) — the only allowed cost

## Data source
CDISC Pilot Submission Package (study CDISCPILOT01), from
https://github.com/cdisc-org/sdtm-adam-pilot-project — same source as Project 1.
Domains used: DM, AE, VS, LB (as `.xpt` SAS Transport files — requires pandas + pyreadstat
to read, same as Project 1's conversion step).

## Database schema (Postgres / Supabase)
- `subjects` (from DM, one row per subject): usubjid (PK), siteid, age, age_unit, sex, race,
  ethnic, arm, country
- `adverse_events` (from AE): ae_id (PK), usubjid (FK), aeseq, aeterm, aedecod, aebodsys,
  aesev, aesev_rank (derived int 1/2/3), aeser (raw flag, unreliable per Project 1 finding),
  is_serious_derived (bool, computed server-side from AESDTH/AESLIFE/AESHOSP/AESDISAB/
  AESCONG/AESMIE = 'Y'), aerel, aeout, start_date, end_date (real DATE columns)
- `vital_signs` (from VS): vs_id (PK), usubjid (FK), vstestcd, vstest, result_value (numeric,
  from VSSTRESN), result_unit, visit, visit_date
- `labs` (from LB): lb_id (PK), usubjid (FK), lbtestcd, lbtest, lbcat, result_value (numeric),
  result_unit, normal_range_indicator (from LBNRIND — reliable, unlike AESER), visit,
  visit_date
- Index on usubjid on all three child tables.

## Core design rule
Claude must never answer a factual question from memory/training data. Every number in a
response has to come from a tool call that runs real SQL against Supabase. This is the
central thing this project demonstrates.

## Conventions
- `.env` holds `DATABASE_URL` and `ANTHROPIC_API_KEY` — never commit, already in .gitignore
- Supabase free tier pauses after ~1 week of inactivity — needs a dashboard visit to resume;
  document this candidly in the README, same pattern as Project 1's Render cold-start note
- No auth/rate-limiting planned for the demo endpoints (acceptable for an unlisted portfolio
  demo, same stance as Project 1)



## Environment variables (two DB roles, different purposes)
- `DATABASE_URL` — connects as the `postgres` owner role. Full DDL rights. Used ONLY by
  `scripts/load_data.py` (the one-time data loader). Never used by the running app.
- `AGENT_DATABASE_URL` — connects as `app_readonly`, a role granted SELECT-only on
  subjects/adverse_events/vital_signs/labs. This is what the agent's SQL tools use.
  Verified working: SELECT succeeds, DELETE/INSERT/UPDATE fail with
  "permission denied" at the database level (not just app-level validation).

## Status
Data loaded into Supabase and verified queryable (306 subjects / 1,191 AE / 29,643 VS /
59,580 LB rows, all matching source). Read-only role created and confirmed to block writes.
Next: build and test the three SQL-backed tools (run_sql_query, get_summary_stats,
run_quality_checks) before wiring into the agent loop.