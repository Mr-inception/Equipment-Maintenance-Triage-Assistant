# Equipment Maintenance Triage Assistant

A web app where a user reports an equipment problem and gets AI-assisted triage that a technician must review. The AI suggests possible causes, follow-up questions, inspection steps, a priority and a draft work order. Every suggestion cites a manual section or report evidence. **The AI never approves work and never controls equipment.**

## What it does
- Report form: equipment type and identifier, issue description, recent operating events, optional sensor readings (blank value = missing reading, repeated sensor = conflicting readings).
- Deterministic threshold checks (plain code, no AI) with the limits from the manuals, unit conversion (F, K, psi, kPa, in/s), and explicit handling of missing, conflicting, implausible and unsupported-unit data. Bad data is never treated as healthy.
- Retrieval over a small manual knowledge base (pump, compressor, motor) using BM25 keyword search. Sections for exceeded thresholds and the lockout procedure are always included.
- AI triage through the Gemini API: possible causes (never presented as confirmed), targeted follow-up questions, inspection steps, a proposed priority and a draft work order.
- Citation validation: every cause and step must cite an ID that was actually provided (manual section, EVENT-n, SENSOR:name, ISSUE). Anything else is dropped and a warning is shown.
- Priority floor: the AI can raise the rule-based minimum priority but never lower it.
- Technician workflow: edit, approve or reject the draft work order; confirm a possible cause as a finding; add observations or confirmed findings. Approved and rejected orders are locked.
- Three kinds of findings kept separate: observations, possible causes (unconfirmed), confirmed findings. A database constraint allows only a technician to create a confirmed finding.
- Re-running triage does not stack drafts: an existing draft is left untouched and the new proposal is shown read-only.
- Persistent equipment issue and maintenance history with a full audit trail.
- Visible failures: retrieval failures and AI failures (missing key, bad key, timeout, rate limit, invalid reply) are stored as runs and shown in the UI.

## Tech stack
- Backend: Python, FastAPI, SQLAlchemy, SQLite, pytest
- Frontend: React (Vite)
- LLM: Gemini via its REST API (Anthropic is also supported behind a setting)
- Retrieval: pure-Python BM25 (no vector database)

## Run it locally
Requirements: Python 3.11+ (developed on 3.14), Node.js 20+.

Backend (Windows PowerShell):

    cd backend
    python -m venv .venv
    .venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    Copy-Item .env.example .env      # then put your key in .env
    python seed_demo.py              # optional demo reports
    uvicorn app.main:app --reload

macOS / Linux: use `source .venv/bin/activate` and `cp .env.example .env`.

Frontend (second terminal):

    cd frontend
    npm install
    npm run dev

Open http://localhost:5173. The dev server proxies `/api` to the backend on port 8000.

### Environment variables (backend/.env)
| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `gemini` (default) or `anthropic` |
| `GEMINI_API_KEY` | Gemini key (server side only) |
| `GEMINI_MODEL` | Gemini model name |
| `LLM_TIMEOUT_SECONDS` | Timeout for the AI call |
| `DATABASE_URL` | Default `sqlite:///./triage.db` |
| `CORS_ORIGINS` | Allowed frontend origins |
| `SEED_DEMO_ON_START` | `true` loads three demo reports on startup (useful on hosts that reset the database) |
| `VITE_API_URL` | Frontend build setting: the backend's origin when it is hosted on a different domain |

Without a key everything works except AI triage, which fails with a clear message.

## Tests

    cd backend
    python -m pytest -q

The suite covers the rules engine (thresholds, units, missing and conflicting data), retrieval, the data model constraints, the report and work order APIs, and the triage workflow. The AI workflow tests use a fake LLM, so they need no key or network.

## Project structure

    backend/app/       config, database, models, rules, retrieval, llm, triage, services, routers
    backend/tests/     pytest suite
    frontend/src/      React app (report form, report detail, work orders, equipment history)
    knowledge_base/    equipment manuals (markdown, one section per citable ID)

## Architecture

    Browser (React/Vite, Vercel)
        |  HTTPS, base URL from VITE_API_URL
        v
    FastAPI (Render)
        rules.py        deterministic threshold checks, unit conversion, missing/conflicting data
        retrieval.py    BM25 over knowledge_base/*.md, cited by section ID
        triage.py       retrieval -> prompt -> LLM -> JSON validation -> citation validation
                        -> priority floor -> persist (never approves anything)
        llm.py          Gemini REST client: timeout, retries on 429/5xx, mapped error messages
        workorders.py   edit / approve / reject (technician name required, drafts only)
        findings.py     technician-confirmed findings, duplicate detection
        SQLite (SQLAlchemy): equipment, issue_reports, sensor_readings, triage_runs,
                             findings, work_orders, history_events

Logging: Python logging to stdout (timestamp | level | component | message) for startup, retrieval, LLM calls (status, retries, timeouts, never keys) and triage results. Every user action is also stored as a `history_events` row, and every AI run as a `triage_runs` row with status, model and error message. Logs are plain text, not JSON.

## Scope
Completed: report form, deterministic checks, retrieval over manuals, AI triage with citations, priority floor, draft work orders with technician edit/approve/reject, separate observations / possible causes / confirmed findings, missing and conflicting sensor handling, visible AI and retrieval failures, equipment history with audit trail, 86 tests, deployment.

Intentionally excluded: user accounts and authentication, live IoT or equipment control, predictive models, inventory, technician dispatch, a vector database, an admin UI for thresholds, a persistent hosted database, JSON-structured logs, browser end-to-end tests.

## Reviewing the live demo
No login is needed. Enter any name in the Technician box, then use the three demo reports (pump, compressor, motor) or create your own. See AGENT_USAGE.md for how AI tools were used.
## Design decisions
- **Rules before AI.** Thresholds are deterministic code. The AI sees the results and cannot overrule them.
- **Evidence or it is dropped.** Citations are validated server side against the IDs supplied in the prompt.
- **Human in the loop by construction.** There is no code path from the AI step to approving a work order; approval is a separate endpoint that requires a named technician.
- **Failures are first-class.** A failed triage is stored as a run with a status and message, so history shows what happened.
- **Original AI draft preserved.** Edits are recorded as diffs in the audit trail.

## Limitations
- No authentication: the technician name is a free-text field, so the audit trail records claimed identity only.
- SQLite and a single process; fine for a demo, not for concurrent production use.
- Keyword (BM25) retrieval over a small set of illustrative manuals. The limits in them are example values, not manufacturer data.
- Thresholds live in code, not in an admin UI.
- No live IoT integration, predictive models, inventory or dispatch.

## AI tools used
Details, prompts and corrections are in [AGENT_USAGE.md](AGENT_USAGE.md).

- Claude (chat): planned the project and generated most of the code step by step; I ran, tested and reviewed each step.
- Cursor / Antigravity: used for refactors and for an automated API test and release audit; I reviewed the diffs.
- Gemini API: the runtime LLM that powers triage.
- What I verified myself: the test suite, the failure paths (no API key, provider overload), the safety rules (no AI approval, technician-only confirmation) and the full flow in the browser.

## Deployment
- Live app: https://equipment-maintenance-triage-assist-nine.vercel.app
- API health check: https://equipment-maintenance-triage-assistant-0y3x.onrender.com/api/health
- Frontend hosted on Vercel, backend on Render (free tier).

Notes for anyone trying the live demo:
- The free backend sleeps when idle, so the first request after a pause can take 30 to 60 seconds.
- The database is SQLite on an ephemeral disk, so data resets whenever the service restarts or redeploys. Three demo reports are re-created on startup (SEED_DEMO_ON_START=true).
- AI triage uses my Gemini quota and can be rate limited or temporarily unavailable. When that happens the app shows the failure instead of guessing.

## Quick demo walkthrough
1. Enter a name in the **Technician** box (top right).
2. Open **DEMO-PUMP-1**. The threshold checks show a conflicting bearing temperature, a vibration warning and a low suction pressure warning.
3. Click **Run AI triage**. Review the cited possible causes, follow-up questions, inspection steps and the proposed priority.
4. Click **Confirm as finding** on a cause, then **Edit** and **Approve** the draft work order.
5. Open **Equipment history** to see the audit trail.
6. Try **New report** with a blank sensor value (missing data) or the same sensor twice with different values (conflict).
