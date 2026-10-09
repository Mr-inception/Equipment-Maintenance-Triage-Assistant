# Agent usage

## Tools used
- **Claude (chat)**: main assistant. Chose the architecture and build order, and generated nearly all of the initial code in small steps. I ran every step myself and reported the real output (test results, errors, screenshots) before moving on.
- **Cursor (agent mode)**: made citation matching tolerant of formatting variants, and changed how re-running triage behaves (no duplicate drafts, old suggestions superseded).
- **Antigravity (agent)**: (1) automated API-level QA of the work order flow, (2) a coding task for duplicate confirmed causes and cleaning internal tags out of AI text, (3) a read-only release audit (secrets scan, clean clone, safety checks, deployment readiness).
- **Gemini API**: the runtime LLM used by the deployed app.

## Representative prompts (paraphrased)
1. **Claude, building**: "Build this one step at a time. After each step I will run it and paste the output; do not move on until it works." (Rules engine, retrieval, models, API, AI workflow, frontend.)
2. **Cursor, re-run handling**: "Make citation matching tolerant of variants like 'SENSOR: bearing_temp', 'event 1' and 'issue description', but keep rejecting unknown IDs. Re-running triage must not create a second draft or stack current causes. Never change an existing draft. No schema changes. Keep all tests passing and report the counts."
3. **Antigravity, QA**: "Test only, do not modify files. Edit the work order below the rule floor, re-run triage, confirm the edit survived, approve it, confirm editing and re-approving return 409, re-run and confirm a new draft appears, then check the audit trail. Report a table with evidence."
4. **Antigravity, fix**: "Do not offer Confirm on a cause that duplicates one already confirmed (409 from the API). Add a pure helper that strips ISSUE and SENSOR tags from AI text but keeps manual section IDs. Add tests."
5. **Antigravity, audit**: "Audit only. Scan tracked files and git history for secrets, clean-clone and test, verify the safety invariants, check requirement coverage and README accuracy, and assess deployment readiness. Report PASS/FAIL with evidence."

## What I delegated
- Claude: scaffolding, rules, retrieval, models, API, triage workflow, React UI, Gemini client, tests, README, deployment steps.
- Cursor: the citation and re-run refactor.
- Antigravity: the API-level QA, the duplicate-cause and tag-cleanup change, and the release audit.
- Me: running everything, reading the diffs, choosing tradeoffs, the browser checks, and the deployment.

## Agent mistakes, corrections and things not used
- **Dependency pins**: Claude pinned old versions (pydantic 2.9.2) with no prebuilt wheels for my Python 3.14, so pip tried to compile Rust. I loosened the pins.
- **Byte-order marks**: PowerShell 5.1 `Set-Content -Encoding utf8` added a BOM that broke Vite (`package.json`). I switched to BOM-free writes and added a BOM check; the audit later found four more BOM files (manuals and .gitignore), which I fixed.
- **Glued requirements line**: `Add-Content` appended to a file without a trailing newline and corrupted a requirement. I rewrote the file.
- **Citation validator too strict**: it dropped valid evidence because the issue description was not a citable ID. I added `ISSUE` as an allowed source.
- **Internal tags leaking into AI text**: the model wrote things like "(ISSUE, SENSOR:bearing_temp)" in prose. Fixed with a sanitiser, a prompt rule and tests.
- **Re-runs created duplicates**: the first design stacked drafts and causes. It was redesigned so existing drafts are never touched, and a later bug let a confirmed cause be confirmed twice, which was fixed with duplicate detection and a 409.
- **Agent patch applied twice**: a duplicated line in `ui.jsx` was cleaned up by hand.
- **QA agent over-reported**: it marked a step PASS while its own notes showed a duplicate cause. I treated the note as a defect and fixed it.
- **Browser automation unavailable**: Antigravity's browser tool failed (Playwright driver download returned 404), so its checks were API-only. I did the visual checks myself.
- **Provider overload**: Gemini returned 503 "high demand" and the app showed a hard failure. I added automatic retries (2 s, then 5 s) for 429 and 5xx; failures are still shown if they persist.
- **Stale server process**: after editing `.env` the old server kept running and reported the key as missing until I fully restarted it.
- **Initial provider assumption**: the first LLM client targeted Anthropic. I switched to Gemini because that was the key I had. A "demo mode" fallback was proposed in case I had no key; I did not need it.
- **Cursor limit**: I hit the usage limit mid-way and finished that part by hand from scripts.

## How I verified the output
- **86 automated tests**: rules (thresholds, units, missing and conflicting data), retrieval, database constraints, report and work order APIs, the triage workflow using a fake LLM, and LLM error handling including retries.
- **Failure paths for real**: ran triage with no API key and saw the stored failure and UI banner; saw a real Gemini 503 handled.
- **Safety checks by search and test**: no code path sets a work order to approved or rejected outside the technician endpoints; the database refuses an AI-origin confirmed finding; approved orders return 409 on edit.
- **API-level QA**: edit survives a re-run, approval locks the order, a new draft appears afterwards, and the audit trail records each action.
- **Manual browser checks**: confirm a cause, edit, approve, equipment history, and a new report with conflicting and missing sensor values.
- **Release checks**: clean-clone install, tests and build; a secrets scan of tracked files and git history (none found); then checks on the live deployment.
- **Not done**: browser end-to-end automation, load testing, authentication.