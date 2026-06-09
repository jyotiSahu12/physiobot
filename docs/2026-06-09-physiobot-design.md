# PhysioBot — Design

**Date:** 2026-06-09
**Status:** Approved (Approach A — single standalone FastAPI app)

## Goal & scope

A single, fully open-source Python app that runs a WhatsApp chatbot for one
physiotherapy clinic. It must run today on a personal machine, with **no Engati
infrastructure** and no proprietary dependencies.

Capabilities:
1. Chat naturally with patients (local LLM via **Ollama**, model `qwen2.5`).
2. Capture patient info into a **Google Sheet** (name, phone, complaint, notes).
3. Book appointments — read the physio's **Google Calendar** for free slots,
   create an event, and log the booking to the Sheet.
4. Share the clinic's **contact number** when escalating or confirming.

Out of scope (YAGNI): payments, multi-clinic/multi-tenant, voice notes,
analytics dashboards, human-handover console.

## Architecture — one FastAPI process, clear internal modules

The logical stages of a production agent platform are kept as *modules*, not
separate services:

```
WhatsApp user
   │  (Meta WhatsApp Cloud API webhook)
   ▼
 webhook.py       verify + receive Meta messages, return 200 fast
   │
 orchestrator.py  load session, append turn, call agent, persist reply
   │
 agent.py         Ollama chat loop with tool-calling
   │  (model decides: reply, or call a tool, then loop)
   ▼
 tools/sheets.py     append patient / booking rows
 tools/calendar.py   list free slots, create event
   │
 outbound.py      send the reply text back to the Meta WhatsApp API
   │
 store.py         SQLite: sessions + message history
```

Each module exposes a small, mockable interface so it can be unit-tested in
isolation (e.g. `agent.respond(history, user_text) -> reply_text`).

## Data flow (one inbound message)

1. Patient messages the clinic WhatsApp number → Meta POSTs to `/webhook`.
2. `webhook` verifies the signature, extracts `(from_number, text)`, returns
   `200` immediately, and dispatches processing in the background.
3. `orchestrator` loads/creates the SQLite session, appends the user turn,
   calls `agent.respond()`.
4. `agent` sends system prompt + history + tool schemas to Ollama. The model
   either returns text (the reply) or a tool call; tool calls are executed in
   `tools/` and fed back to the model until it produces final text.
5. `orchestrator` persists the assistant turn.
6. `outbound` sends the reply to the Meta WhatsApp API.

## The agent & its tools

A bounded tool-calling loop (max N iterations) on top of Ollama's `/api/chat`.
Tools exposed to the model:

- `save_patient_info(name, phone, complaint, notes)` — append a row to the
  **Patients** sheet tab.
- `get_free_slots(date)` — read Calendar + working-hours config, return open
  slots for that day.
- `create_booking(name, phone, complaint, slot_datetime)` — create a Calendar
  event **and** append a row to the **Bookings** sheet tab; return confirmation.

The system prompt encodes the persona: a warm physiotherapy receptionist for
*[clinic name]* who collects patient details, books appointments, and shares the
clinic number when a human is needed. Clinic name, contact number, timezone,
working hours, and slot length all come from `config.yaml` — nothing hardcoded.

## Data & configuration

- **SQLite** (`physiobot.db`): `sessions(phone, state, updated_at)`,
  `messages(phone, role, content, ts)`. This is the entire "memory".
- **Google Sheet** (one spreadsheet, tabs `Patients`, `Bookings`) via `gspread`
  and a Google **service account** (JSON key, path from `.env`).
- **Google Calendar** via `google-api-python-client`, same service account
  (calendar shared with the service-account email).
- `config.yaml` (committed, no secrets): clinic name, contact number, timezone,
  working hours, slot length, Ollama model, sheet id, calendar id.
- `.env` (gitignored): `GOOGLE_APPLICATION_CREDENTIALS`, Meta token,
  phone-number id, webhook verify token, app secret.

## Tech stack (all open source / free)

FastAPI + Uvicorn · Ollama (`qwen2.5`) · `ollama` python client · `gspread` +
`google-auth` · `google-api-python-client` · SQLite (stdlib) · `httpx` (Meta
calls) · `PyYAML` + `python-dotenv` · `pytest` + `pytest-asyncio`. Dev tunnel
for the Meta webhook: `ngrok` / `cloudflared`.

## Error handling

- `/webhook` always returns `200` quickly (Meta retries otherwise); processing
  runs in the background and catches its own errors.
- Tool failures (Sheet/Calendar unavailable) → the agent apologizes and falls
  back to sharing the clinic contact number; the conversation never crashes.
- Ollama unreachable → friendly fallback message + log line.
- Every external call has a timeout; structured logging throughout.

## Testing

- Unit tests per module with externals mocked: webhook parsing, the agent
  tool-loop (faked Ollama responses), each tool (mocked gspread / Calendar),
  outbound payload shape.
- One end-to-end test: a fake inbound payload flows through to a mocked Meta
  send, asserting a Patients/Bookings row would be written.

## Project layout

```
physiobot/
  physiobot/
    app.py            FastAPI entry, wires modules
    config.py         load config.yaml + .env
    store.py          SQLite sessions + messages
    webhook.py        Meta verify + receive
    orchestrator.py   session + agent + persist + send
    agent.py          Ollama tool-calling loop
    outbound.py       send reply to Meta API
    tools/
      sheets.py       Patients/Bookings append
      calendar.py     free slots + create event
  scripts/verify_setup.py   one-shot connectivity check
  tests/
  config.yaml   .env.example   requirements.txt   README.md
```

## One-time setup (README)

Install Ollama + `ollama pull qwen2.5` · create Google service account, share
the Sheet & Calendar with its email · create a Meta WhatsApp app (free test
number), set the webhook to the ngrok URL · fill `.env` + `config.yaml` ·
`uvicorn physiobot.app:app`.
