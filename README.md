# Clinical Data-Quality Reviewer

A chat agent that answers natural-language questions about a clinical trial dataset
(CDISCPILOT01) by running real SQL against Postgres — never by recalling numbers from
model memory — and runs a fixed battery of data-quality checks that flag likely issues
in plain language. Every figure in an answer traces back to a tool call made in that
conversation, and the UI shows the actual SQL that produced it.

**Live app:** https://clinical-data-quality-agent.vercel.app
**API:** https://clinical-data-quality-agent.onrender.com
**Repo:** https://github.com/Sergei1607/clinical-data-quality-agent

(The API is on Render's free tier — the first request after ~15 minutes idle takes
20–30 seconds to wake up. Known free-tier tradeoff, not a bug.)

## What it does

Ask it something like *"which subjects had a severe adverse event with a fatal
outcome?"* and it writes the SQL, runs it against the database as a read-only user,
and answers from the rows that came back — showing you the query it ran. Ask it to
*"run the data-quality scan"* and it executes a fixed set of checks (orphaned records,
impossible date ranges, missing required fields, implausible vital/lab values, and
seriousness-flag disagreements) and explains what it found, with clinical significance
called out where it matters.

The point of the project is the guardrail: the model is structurally prevented from
answering factual questions from training data. It has three tools and nothing else to
go on.

## Tech stack

- **Frontend:** React + Vite + TypeScript + Tailwind CSS, deployed on Vercel
- **Backend:** FastAPI (Python), deployed on Render
- **Database:** Supabase (free-tier Postgres)
- **AI:** Claude API (`claude-sonnet-5`) with a tool-use agent loop — the backend runs
  the call → execute tools → call loop until the model stops asking for tools, then
  returns the turn

## Data source

[CDISC SDTM/ADaM Pilot Project](https://github.com/cdisc-org/sdtm-adam-pilot-project)
(public) — study CDISCPILOT01, a synthetic Alzheimer's trial. Domains used: DM
(demographics), AE (adverse events), VS (vital signs), LB (labs). Standardized,
publicly published synthetic data — not real patient information. Same source as
Project 1 in this portfolio series.

Loaded totals: **306 subjects · 1,191 adverse events · 29,643 vital-sign measurements
· 59,580 lab results.**

## Database design

This is the part of the project worth reading closely.

### Four tables, mirroring the SDTM domains — with derived columns alongside the raw strings

| Table | From | Notable columns |
|---|---|---|
| `subjects` | DM | `usubjid` (PK), `siteid`, `age`, `sex`, `race`, `ethnic`, `arm`, `country` |
| `adverse_events` | AE | `aeterm`, `aedecod`, `aebodsys`, `aesev`, **`aesev_rank`**, `aeser`, **`is_serious_derived`**, `aerel`, `aeout`, **`start_date`**, **`end_date`** |
| `vital_signs` | VS | `vstestcd`, `vstest`, `result_value` (numeric), `result_unit`, `visit`, **`visit_date`** |
| `labs` | LB | `lbtestcd`, `lbtest`, `lbcat`, `result_value` (numeric), `result_unit`, `normal_range_indicator`, `visit`, **`visit_date`** |

The bold columns are derived at load time and stored next to the raw SDTM values, not
instead of them:

- **`aesev_rank`** — `MILD`/`MODERATE`/`SEVERE` mapped to `1`/`2`/`3`, so severity can be
  compared and ordered in SQL instead of string-matched.
- **`is_serious_derived`** — a real boolean, computed server-side as *true if any of
  `AESDTH`, `AESLIFE`, `AESHOSP`, `AESDISAB`, `AESCONG`, `AESMIE` equals `'Y'`* — i.e.
  the actual regulatory seriousness criteria, not the sponsor's summary flag.
- **`start_date` / `end_date` / `visit_date`** — real `DATE` columns cast from the SDTM
  `--DTC` ISO-8601 strings, so date arithmetic (`end_date < start_date`, durations,
  ranges) works.

Project 1 dumped the equivalent data into SQLite as strings and did the derivation in
Python at request time. Here the data actually calls for a database — the agent writes
arbitrary SQL, so anything it might want to filter, order, or aggregate on has to be a
proper typed column, not a string it has to `CAST` or `LIKE` its way around. The raw
strings stay so nothing is lost and the transform is auditable.

### Two database roles

| Role | Grants | Used by |
|---|---|---|
| `postgres` (owner) | full DDL | `scripts/load_data.py` only — the one-time loader |
| `app_readonly` | `SELECT` on the four tables, nothing else | the running app |

The owner connection string (`DATABASE_URL`) is **not present in the deployed
environment at all** — Render only gets `AGENT_DATABASE_URL`, which points at
`app_readonly`. The loader runs from a laptop.

This was verified end-to-end, not just assumed. Connected as `app_readonly`:

```sql
DELETE FROM subjects WHERE usubjid = 'x';
-- ERROR: permission denied for table subjects
```

`SELECT` works; `INSERT` / `UPDATE` / `DELETE` all fail at the database.

### Layered defense

The SQL tool (`run_sql_query`) also validates queries before they reach Postgres: the
statement must start with `SELECT` (after stripping comments), and a semicolon anywhere
but the very end is rejected to block statement stacking. This is deliberately *not* the
only line of defense — it's a fast, clear rejection for obviously-wrong input, sitting on
top of the database-level `SELECT`-only grant. A bug in the string check doesn't mean a
write gets through; the role still can't write. A bug in the grant doesn't mean the agent
can stack `; DROP TABLE`; the validator still rejects it.

### The core rule

The agent must never answer a factual question from memory or estimation — every number
in a response has to come from a tool call it actually made in that conversation. The
system prompt states this explicitly, and the frontend renders each `tool_use` with the
real SQL (or which fixed check ran) and its result, as visible proof. If you don't
believe an answer, the query that produced it is right there above it.

## Notable finding: the seriousness-flag discrepancy

Running `run_quality_checks` surfaces this on demand:

**33 of the 1,191 adverse-event records have `aeser = 'N'` (raw sponsor flag: not
serious) while the derived criteria say the event *is* serious** — meaning at least one
of death, life-threatening, hospitalization, disability, congenital anomaly, or medically
important applies. Three of those 33 are **fatal events** (`aeout = 'FATAL'`), including
a sudden death and a completed suicide.

This is the same discrepancy Project 1 found by hand while building the narrative
generator. The difference is that it's now a reproducible query result rather than a
one-time manual observation — anyone can ask the agent "run the quality scan" and get
the current count and examples back, backed by SQL.

## Known limitations

Stated plainly, same as Project 1:

- **Render cold start.** Free tier spins down after ~15 minutes idle; the next request
  takes ~20–30 seconds while it wakes.
- **Supabase pause.** The free-tier database pauses after ~1 week of no activity and
  needs a visit to the Supabase dashboard to resume. If the live app returns database
  errors, this is why.
- **Conversation history is stateless and unbounded.** The frontend owns the full
  history and resends all of it to `/chat` every turn — no trimming, no summarization.
  Fine for a demo where conversations are short; a real deployment would blow through the
  context window (and the token budget) on a long thread.
- **The semicolon check is a naive string check.** It would false-positive on a
  legitimate query containing `;` inside a string literal (e.g. `WHERE note = 'a;b'`).
  Acceptable because the real enforcement is the read-only database role, not this check
  — but it's a string check, not a SQL parser.
- **No auth or rate limiting on `/chat`.** Acceptable for an unlisted portfolio demo on
  a free tier; not for anything real.

## What I'd improve next

Pulled from the actual rough edges hit while building this:

- **History management for long conversations** — trim or summarize older turns instead
  of resending everything. This is the clearest gap between "demo" and "usable."
- **Lab-specific plausible-range checks** — `run_quality_checks` currently only flags
  *negative* lab values, because `LBTESTCD` spans dozens of assay types with wildly
  different valid ranges and I wasn't willing to hardcode ranges I wasn't confident in.
  Vital signs already get proper per-test bounds (systolic BP, temperature in °C, etc.);
  labs deserve the same, done carefully.
- **Broader DB-error handling** — the agent already turns a database *outage* into a
  clean `tool_result` the model can relay ("the database may be paused…"). Auth failures
  and query timeouts currently surface differently; they probably deserve the same
  graceful treatment so the agent degrades predictably however the database misbehaves.

## Running locally

### Backend

```
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# to run the app:            pip install -r requirements.txt
# to also load data:         pip install -r requirements-dev.txt

# create .env from .env.example and fill in:
#   DATABASE_URL         (postgres owner role — for the loader)
#   AGENT_DATABASE_URL   (app_readonly role — for the app)
#   ANTHROPIC_API_KEY
#   FRONTEND_ORIGINS     (optional; defaults to http://localhost:5173)

# one-time: create the schema and load the CDISC data
python -m scripts.load_data

# run the API
python -m uvicorn app.main:app --reload --port 8000
```

`scripts/load_data.py` downloads the four `.xpt` files from the CDISC pilot repo (or
reads them from `backend/data/` if already present), transforms them, and wipes-and-
reloads the four tables — safe to re-run.

### Frontend

```
cd frontend
npm install
# create .env from .env.example:  VITE_API_URL=http://localhost:8000
npm run dev
```

Then open http://localhost:5173.
