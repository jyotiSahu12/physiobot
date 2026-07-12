# PhysioBot — Current State & Start-Here Handoff

**Read this first when picking the project back up.** It's the single source of
"where things stand right now" and points to the deeper docs. Last refreshed
2026-07-12.

---

## 1. What PhysioBot is (in one paragraph)

A deterministic, state-machine-driven **WhatsApp chatbot for Balance Plus
Physiotherapy Clinic** (HSR Layout, Sector 7, Bengaluru). It guides a patient
through intake (name → consent → complaint → pain details → service mode →
branch), screens for red-flag symptoms, recommends a service, then checks Google
Calendar and books an appointment (writing the lead/booking to Google Sheets and
creating a Calendar event). The LLM is used **only** as a single-turn NLU
translator (text → JSON); all decisions/memory/booking logic live in
deterministic code so the bot behaves identically regardless of which LLM
backend is live. Design bias: grandma-friendly (tappable buttons/lists, minimal
typing) and robust (never hallucinate, never go silent).

## 2. Repo / git state

- **Working branch:** `feature/template-transition` (this is where all recent work lives; PRs go to `main`).
- **Remote:** `origin` = https://github.com/jyotiSahu12/physiobot.git — branch is pushed and up to date.
- Latest work committed: metadata v3.0.0 migration, human-like booking flow,
  branch selection, safety hardening, Python 3.12.3 migration, robustness
  layer. If `git status` is clean, everything below is already committed.

## 3. Runtime — Python 3.12.3 (local AND prod)

- Pinned in `.python-version` (`3.12.3`) and `render.yaml` (`PYTHON_VERSION: 3.12.3`).
- Local venv is `.venv` built on pyenv's 3.12.3. Recreate with:
  `pyenv install -s 3.12.3 && rm -rf .venv && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install pyflakes`
- ⚠️ **Gotcha (bit us once):** the app can't hot-swap its interpreter. If the
  venv/Python version changes while a `uvicorn --reload` process is live, that
  process hangs (serves `HTTP 000`). SQLite schema self-heals, but the
  **interpreter does not** — a manual restart is required after any venv change.

## 4. How to run / verify

```bash
source .venv/bin/activate
python -m pytest -q          # expect: 134 passed
python -m pyflakes physiobot/ tests/   # expect: clean
uvicorn physiobot.app:app --reload     # dev server on :8000
curl -s localhost:8000/healthz         # shows build tag + provider + meta_configured
curl -s localhost:8000/simulate -H 'content-type: application/json' -d '{"text":"Hi, I have knee pain"}'
```

- `/simulate` runs the exact same pipeline as the WhatsApp webhook but with no
  Meta/WhatsApp involved — the primary way to test flows locally.
- Tests fully mock Sheets/Calendar/LLM/Meta; no real external calls.

## 5. Architecture & file map

Pipeline: **webhook → orchestrator → parser (NLU) → state_machine → templates → outbound**.

| File | Role |
| :--- | :--- |
| `physiobot/app.py` | FastAPI: `/webhook` (verify + receive), `/simulate`, `/healthz`. `BUILD` tag bumped per deploy. |
| `physiobot/webhook.py` | Signature verify + parse inbound events (extracts `text`, `interactive_id`, `profile_name`, `message_id`). |
| `physiobot/orchestrator.py` | Ties one turn together; dedupes by `message_id`; wraps the whole turn in try/except so failures still send a fallback. |
| `physiobot/parser.py` | NLU: LLM prompt → strict JSON, with a regex fallback gated by `detect_expected_slot`. Natural date + time-of-day parsing. |
| `physiobot/llm.py` | Thin provider abstraction (`OllamaProvider` / `GroqProvider`), `chat(messages) -> {content}`. No tool-calling. |
| `physiobot/state_machine.py` | The deterministic dialogue manager. Slot filling, branch logic, forward-looking slot search, booking. Longest/most important file. |
| `physiobot/clinic_kb.py` | `ClinicKB` — the ONLY interpreter of `clinic_metadata.json`'s schema (name, phone, address, maps_url, red flags, canned copy, service match, branches). |
| `physiobot/metadata.py` | Raw JSON loader + schema-drift warning. |
| `physiobot/formatting.py` | Humanize dates/times for patient-facing copy (ISO stays internal). |
| `physiobot/templates.py` | WhatsApp message registry + `META_LIMITS` + `enforce_meta_interactive_limits` (the single Meta-limit choke point). |
| `physiobot/outbound.py` | Meta Graph API sender (text / template / interactive). Graph version from config. |
| `physiobot/store.py` | SQLite: sessions, message history, `processed_messages` (dedup). Self-heals schema on every connect. |
| `physiobot/tools/calendar.py` | Google Calendar v3: `get_free_slots(date)` (excludes past/closed), `create_event`. |
| `physiobot/tools/sheets.py` | Google Sheets (gspread): patients + bookings (bookings carry `BranchId`), `last_branch_for_phone`. |
| `physiobot/config.py` | Loads `config.yaml` + env; frozen dataclasses. Secrets only from env. |

## 6. Current feature set (end-to-end behaviour)

- **Intake order:** phone (always from WhatsApp sender) → name (one-tap confirm
  of WhatsApp profile name, else ask) → consent → complaint (→ service hint) →
  pain area/duration/score → service mode → **branch** → date/time → booking.
- **Branch selection (never assumed):** patient explicitly picks a branch;
  returning patients get a one-tap "same as last time?" (from `BranchId` in the
  Bookings sheet). Only the **HSR (primary) branch** has a live calendar; any
  other branch → `non_hsr_branch_handoff` (human confirms) rather than faking
  availability.
- **Natural scheduling:** asks "When would you like to come in?" and accepts
  "today evening" / "tomorrow morning". Resolves a day + time-of-day window,
  then **searches forward like a receptionist** (`_find_next_availability`): if
  the requested window is full it says so and shows the next real availability
  ("Today evening is fully booked — here's the next availability: …"). Books
  against the date actually shown.
- **Pain scale:** Mild/Moderate/Severe buckets (stored as 3/6/9), not a 0–10 list.
- **Red-flag safety:** scoped to the latest message only (no re-firing from
  history). A red-flag handoff is not a dead end — once the urgent symptom isn't
  restated the bot resumes helping with what the clinic can treat, with a
  one-time reminder to seek separate care. Never substring-match to "verify" a
  red flag (LLM normalizes wording; that would drop real flags).
- **FAQs answered inline** from clinic-approved canned copy (price/hours/services/
  home-visit/online/therapist), never improvised. `ask_location` returns a
  tappable Google Maps link (built from the public address, no Maps API/GCP
  billing) + folds in contact details. `ask_contact` handled too.
- **Booking confirmation** includes date/time (humanized), address, phone, and a
  tappable "View on Map" button (`booking_confirmed_map`). A post-booking "hi"/
  "thank you" reaffirms the appointment instead of wiping it; only an explicit
  new-booking request resets intake.
- **Handoff intents:** cancel / insurance / payment / medical-report → human.

## 7. Robustness invariants already in place (don't regress these)

- **One Meta-limit choke point:** every interactive payload flows through
  `enforce_meta_interactive_limits`; never hand-truncate at call sites. Guard
  test builds every template with adversarial data.
- **Webhook idempotency:** duplicate Meta deliveries dropped via
  `Store.mark_processed(message_id)` (Meta retries until it gets a 200).
- **Never go silent:** the whole orchestrator turn is wrapped; DB schema
  self-heals on every connection.
- **Slot discipline:** interactive `id` bypasses NLU; `preferred_date/time/
  time_of_day` only merge in `AWAITING_SLOT_SELECTION`; `phone_number` never
  NLU-writable.
- **Schema drift:** all metadata access via `ClinicKB` only.
- **Configurable Graph API version** via `META_GRAPH_API_VERSION` (default v21.0).

Full rationale for each: **`docs/design-principles.md`** (the robustness playbook + §9 pre-change checklist).

## 8. Doc map (what lives where)

- **`docs/current-state.md`** ← you are here (start point / current status).
- **`docs/design-principles.md`** — robustness playbook, Meta limit table, the
  "before you change anything" checklist, all the hard-won nuances.
- **`docs/project-summary.md`** — architecture overview + numbered Key Learnings
  (#1–#11), each tied to a real bug and its fix.
- **`docs/tech-stack.md`** — versioned inventory of every dependency/service +
  "please send me latest docs for…" checklist.
- **`docs/production-whatsapp-setup.md`** — (user-authored) step-by-step for
  moving from the Meta sandbox test number to a permanent production number.
- `docs/local-testing.md`, `docs/2026-06-*.md` — earlier design/testing notes.

## 9. Known open items / intentionally deferred

Deferred to the productionization phase (user said correctness + design matter
most now; production later):
- No dependency lockfile (`requirements.txt` uses `==` pins; no hash-lock). A
  `requirements-dev.txt` for pyflakes/pytest is the first easy step.
- Render free tier sleeps / ephemeral disk — fine while SQLite is transient and
  durable records live in Sheets/Calendar; revisit before real launch.
- FastAPI `BackgroundTasks` has no durable retry queue — acceptable at current
  volume (turn is wrapped, failures send fallback).
- `config.yaml` still has placeholder clinic name/number (`Dr. Sahu's...`) —
  the real customer-facing identity comes from `clinic_metadata.json` via
  `ClinicKB`, so this is mostly moot, but worth aligning before launch.

## 10. Testing caveat (avoid re-introducing time-bombs)

Some parser tests exercise natural-date resolution against the **real system
clock** (`parse_message` uses `datetime.now`). Never hard-code an expected date
like `"2026-06-23"` — compute it (see `_next_occurrence_iso` / `_today_iso` in
`tests/test_parser.py`), or the test breaks once "today" passes that date. The
pure-function `parse_natural_date` tests pass a fixed `today`, so they're safe.

## 11. How the user works (so you match their workflow)

- Tests the live bot on real WhatsApp and reports issues with **screenshots**;
  fixes should target the root cause, not just the reported symptom, and land
  with a regression test.
- Wants the bot to **feel like a real human** and to **degrade gracefully**
  against external-API limits. Keep `pytest -q` + `pyflakes` green.
- Will provide latest official docs for dependencies on request (see
  `tech-stack.md` §9) to keep things current.
- Commits: only when asked; branch off `main`; co-author trailer required (see
  the repo's git-commit convention). `.env` and `*.db` are gitignored — never commit them.
