# PhysioBot Design Principles & Robustness Playbook

This document captures the *invariants* and hard-won nuances that keep PhysioBot
robust — especially around the things we don't control: the Meta WhatsApp Cloud
API, the LLM, and Google Calendar/Sheets. Read this before changing the dialogue
flow, the templates, or any external integration. The recurring theme: **treat
every external dependency as hostile — it will reject, hallucinate, time out, or
change schema, and the bot must degrade gracefully, never go silent.**

---

## 1. The core architecture is deterministic on purpose

The LLM is a *stateless, single-turn text→JSON translator*, nothing more. All
memory, all decisions, and all booking logic live in the deterministic state
machine (`state_machine.py`) backed by SQLite.

- **Never** let the LLM drive an irreversible action (booking, DB wipe, handoff).
  It can only *propose* slots/intent; the state machine decides.
- The bot must behave identically regardless of which LLM is behind it (Ollama,
  Groq, or a future one). If a change makes correctness depend on model quality,
  it's wrong — push that logic into the state machine.
- Anything the LLM returns is *untrusted input*. Validate, gate, and scope it.

## 2. External API limits are hard rejections, not warnings — clamp centrally

Meta rejects an entire send (HTTP 400) if any field exceeds its limit. Because
the send happens *after* the state machine has advanced and saved the session,
a rejected message makes the bot **go silent mid-conversation** — the worst
possible failure mode, invisible to the patient.

**Rule: never hand-truncate fields at the call site.** All Meta limits are
enforced in ONE place — `enforce_meta_interactive_limits()` in `templates.py` —
which every interactive payload flows through. Builders express *intent* (which
rows/buttons, in what order); the enforcer guarantees *validity*. This is what
`test_templates.py::test_every_interactive_template_produces_a_valid_payload`
locks in.

### Meta WhatsApp interactive-message limits (the ones that have bitten us)
| Field | Limit |
| :--- | :--- |
| Body text | 1024 chars |
| Header text | 60 chars |
| Quick-reply button title | 20 chars |
| Quick-reply buttons | 3 per message |
| List "open" button label | 20 chars |
| **List rows — total across ALL sections** | **10** (not per-section) |
| List sections | 10 |
| Section title | 24 chars |
| **List row title** | **24 chars** (error 131009) |
| List row description | 72 chars |
| `cta_url` display text | 20 chars |
| Empty section | rejected — drop sections with 0 rows |

Two distinct 400s we hit, both now structurally impossible:
- `131009 "Row title is too long. Max length is 24"` (long branch names).
- `"Total row count exceed max allowed count: 10"` (13-row pain-area list, 11-row 0–10 pain scale).

### Other Meta constraints to keep in mind
- **24-hour customer-service window:** outside it you can only send *pre-approved
  template messages*, not free-form text. The bot only ever *replies* to inbound
  messages, so it stays inside the window — but any future proactive/reminder
  message must use an approved template.
- **Native interactive replies (button/list) need no template approval** and
  work immediately in-window. Prefer them over free text (also grandma-friendly).
- **Interactive replies carry an unambiguous `id`** — always route on the `id`,
  never re-parse the visible title through the NLU (see §4).

## 3. Don't make the patient read like they're talking to a machine

- No format-teaching prompts ("e.g. 2026-06-25, or say next Monday"). Ask like a
  receptionist: "When would you like to come in?" — and accept natural answers
  ("today evening", "tomorrow morning").
- Scheduling should *act like a person scanning the diary*: parse the day + rough
  time-of-day, show matching slots, and if that window is full, say so and roll
  forward to the next real availability ("Today evening is fully booked — here's
  the next availability: …") rather than silently showing unrelated times.
- Humanize all patient-facing dates/times (`formatting.py`): store ISO
  internally for Calendar/Sheets, show "Monday, June 22, 2026 at 1:00 PM".
- Confirmations should be self-sufficient: include address + contact so the
  patient isn't left asking "where?" / "what number?".
- Pre-fill from WhatsApp (sender number always; profile name for one-tap confirm).
- Keep choices small and tappable; a 0–10 scale becomes Mild/Moderate/Severe.

## 4. Slot-filling discipline (how we avoid "assumed" values)

- **Interactive `id` bypasses NLU entirely.** `_current_expected_slot()` maps a
  button/list reply to exactly the slot being asked, so "1-3 days" can never be
  misread as a pain score or a date.
- **Gate NLU slot merges by conversation phase.** `preferred_date`/`preferred_time`
  are only accepted once `status == AWAITING_SLOT_SELECTION` — otherwise a chatty
  LLM "helpfully" invents a date during intake and the bot books a day nobody asked for.
- **`phone_number` is never NLU-writable** — it's always the WhatsApp sender id.
- The regex fallback must cover the same slots the LLM does (e.g. natural-date
  AND time-of-day parsing — `parse_natural_date`/`parse_time_of_day`) so behaviour
  doesn't degrade when the LLM is down. A bare time-of-day ("evening") defaults to
  today rather than re-asking the day.
- **Slot availability search is forward-looking** (`_find_next_availability`): it
  prefers the requested day + time-of-day window, rolls day-by-day if it's full,
  then falls back to the first day with any slots, capped at 14 days. It books
  against the date actually shown, not the one originally requested.

## 5. Safety vs. helpfulness (red flags)

- Red flags are scoped to the **most recent message only** — both the LLM prompt
  and the regex fallback. Don't let a past "chest pain" keep firing the urgent
  alert when the patient has moved on to "lower back pain".
- A red-flag handoff is **not a permanent dead end**: once the urgent symptom
  isn't restated, resume intake for what the clinic *can* treat, with a one-time
  reminder that the urgent symptom needs separate medical attention.
- **Never** substring-match the message to "verify" a red flag — the LLM
  normalizes "my chest hurts" → "chest pain", so substring-matching would discard
  real red flags. False negatives on safety are unacceptable; prefer over-alerting.
- Only say what the clinic has confirmed. Pricing/hours/exact address are marked
  `needs_confirmation` in the metadata — answer with the clinic-approved canned
  copy, never improvise a number.

## 6. State & persistence must self-heal and never silently die

- `Store`/`StateMachine` re-run `CREATE TABLE IF NOT EXISTS` on every connection,
  so deleting/replacing `physiobot.db` under a live process self-heals instead of
  crashing with "no such table".
- `orchestrator.handle_message` wraps the *entire* turn (incl. initial DB writes)
  in try/except, because it runs in a FastAPI `BackgroundTask` whose exceptions
  are otherwise swallowed — a failure must still send a fallback, never silence.
- Destructive session resets require an *explicit* signal (an actual
  "book_appointment" intent + a booking-shaped keyword), so a misclassified
  "thank you" can't wipe a confirmed appointment.

## 7. Idempotency & integration failures (Google)

- **Webhook dedup:** Meta retries a notification until it gets a 200, so the same
  inbound message can arrive several times. `Store.mark_processed(message_id)`
  atomically claims each Meta message id (via `INSERT OR IGNORE`); a duplicate
  delivery is dropped before any work, so it can't double-reply or double-book.
  `/simulate` passes no id and is never deduped.
- `save_patient_info` upserts by phone; `booking_exists` guards against duplicate
  calendar events — models/retries may re-call these.
- Every Sheets/Calendar call is wrapped; failures fall back to a clean template
  (`no_slots_available`, `booking_failed`, `generic_fallback`), never a raw error.
- Only the **primary (HSR) branch** has a live calendar/sheet. Any other branch
  routes to a human handoff rather than the bot faking availability it can't see.
  Booking rows carry a `BranchId` so a returning patient's branch can be recalled.

## 8. Schema drift is inevitable — hide it behind a facade

- All `clinic_metadata.json` access goes through `ClinicKB` (`clinic_kb.py`). When
  the clinic ships a new schema version, only this file changes — not five call
  sites that would otherwise silently degrade to empty `.get()` chains.
- `metadata.py` logs a loud warning if an expected top-level key is missing, so
  drift surfaces at load time instead of as mysteriously empty answers.

## 9. When you add or change something, ask:
1. What happens if the LLM returns garbage / nothing here?
2. What happens if this field is empty, too long, or contains an unexpected value
   from the clinic metadata?
3. Does this exceed any Meta limit? (If it's a new interactive payload, it must
   flow through `enforce_meta_interactive_limits` and the smoke test.)
4. Does this make an irreversible decision based on untrusted input?
5. If the external call fails, does the patient still get a coherent reply?
6. Does the copy read like a human wrote it?
