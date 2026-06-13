# PhysioBot — Architecture & Deployment Guide

**Status:** Live. Deployed at `https://physiobot-f70x.onrender.com`
**Repo:** `github.com/jyotiSahu12/physiobot` (private)
**Supersedes the high-level brief in** `2026-06-09-physiobot-design.md` **with the
as-built system and the full test → production path.**

---

## 1. What it is

A single open-source Python service that runs a WhatsApp chatbot for one
physiotherapy clinic. It:

1. Chats with patients in natural language (LLM).
2. Captures patient leads into a **Google Sheet**.
3. Books appointments — reads free slots from **Google Calendar**, creates the
   event, logs the booking to the Sheet.
4. Shares the clinic's contact number when a human is needed.

**Design principle:** the logical stages of a production agent platform are kept
as *internal modules* of one process — not separate services. No message bus, no
external state stores beyond SQLite + Google. Runs on a laptop (Ollama) or a free
cloud host (Groq) with no code changes.

---

## 2. Architecture

```
                          WhatsApp user
                               │
                               │  Meta WhatsApp Cloud API
                               ▼
        ┌──────────────────────────────────────────────────────┐
        │  PhysioBot  (one FastAPI process — physiobot/app.py)   │
        │                                                        │
        │  webhook.py    GET  /webhook  → verify subscription    │
        │                POST /webhook  → verify sig, parse,     │
        │                                 return 200 FAST,       │
        │                                 dispatch to background │
        │                     │                                  │
        │                     ▼                                  │
        │  orchestrator.py   load session → append user turn →   │
        │                    agent.respond() → persist reply →   │
        │                    outbound.send_text()                │
        │                     │                                  │
        │                     ▼                                  │
        │  agent.py          bounded tool-calling loop           │
        │                     │         ▲                        │
        │                     ▼         │ canonical messages     │
        │  llm.py            provider.chat(messages, tools)      │
        │                     ├── OllamaProvider  (local)        │
        │                     └── GroqProvider    (cloud)        │
        │                     │                                  │
        │                     ▼  tool calls                      │
        │  tools/sheets.py    save_patient_info / append_booking │
        │  tools/calendar.py  get_free_slots / create_event      │
        │                     │                                  │
        │  store.py          SQLite: sessions + messages         │
        │  config.py         config.yaml + env vars              │
        │  google_auth.py    service-account creds (file or env) │
        └──────────────────────────────────────────────────────┘
                     │                          │
                     ▼                          ▼
            Google Sheets API           Google Calendar API
         (Patients / Bookings tabs)      (free slots, events)
```

### Module responsibilities

| File | Responsibility | Key interface |
|------|----------------|---------------|
| `app.py` | FastAPI wiring, routes, build marker | `GET/POST /webhook`, `/healthz`, `/simulate` |
| `webhook.py` | Pure Meta helpers (no FastAPI) | `verify_subscription`, `verify_signature`, `parse_incoming` |
| `orchestrator.py` | One-message pipeline | `handle_message(phone, text) -> reply` |
| `agent.py` | Tool-calling loop, system prompt, tool dispatch | `Agent.respond(history) -> str` |
| `llm.py` | Provider abstraction + canonical msg conversion | `get_provider(config)`, `provider.chat(messages, tools)` |
| `tools/sheets.py` | Patients/Bookings tabs (idempotent) | `save_patient_info`, `append_booking`, `booking_exists` |
| `tools/calendar.py` | Free slots + event creation | `get_free_slots(date)`, `create_event(...)` |
| `outbound.py` | Send reply to Meta Graph API | `Outbound.send_text(to, text)` |
| `store.py` | SQLite conversation memory | `touch_session`, `add_message`, `history` |
| `config.py` | Load `config.yaml` + env, dataclasses | `get_config()` |
| `google_auth.py` | Creds from key file (local) or JSON env (cloud) | `load_credentials(scopes)` |

---

## 3. Request flow (one inbound message)

```
Patient ──"Hi, knee pain"──▶ Meta ──POST /webhook──▶ webhook.py
  1. verify_signature(body, X-Hub-Signature-256, app_secret)   [skipped if no secret]
  2. parse_incoming(payload) → [(phone, text)]
  3. return 200 immediately;  background.add_task(orchestrator.handle_message)

orchestrator.handle_message(phone, text):
  4. store.touch_session(phone); store.add_message(phone,"user",text)
  5. reply = agent.respond(store.history(phone))         ← may call tools
  6. store.add_message(phone,"assistant",reply)
  7. outbound.send_text(phone, reply) → POST graph.facebook.com/.../messages

agent.respond(history):
  loop up to max_tool_iterations:
    assistant = provider.chat([system]+history, TOOL_SCHEMAS)
    if no tool_calls: return text
    for each call: result = run_tool(name, args); append tool result
  (the model decides: reply directly, or call save_patient_info /
   get_free_slots / create_booking, see the result, then continue)
```

**Why return 200 before processing:** Meta retries webhooks that don't get a fast
200, which would double-process messages. Processing runs in a FastAPI
`BackgroundTask` after the response is sent.

---

## 4. The agent, tools, and LLM abstraction

### Tools exposed to the model (`agent.py: TOOL_SCHEMAS`)

| Tool | Args | Effect |
|------|------|--------|
| `save_patient_info` | name, phone, complaint, notes? | Append/update a row in **Patients** |
| `get_free_slots` | date (YYYY-MM-DD) | Free start times = working hours − busy events − past |
| `create_booking` | name, phone, complaint, slot_datetime | Create Calendar event + append **Bookings** row |

The system prompt (built per-request in `build_system_prompt`) injects: clinic
name, today's date/timezone, open/closed weekdays, working hours, slot length,
contact number, and behavioral rules (collect-then-save once, never invent slots,
never reveal it's an AI).

### Provider abstraction (`llm.py`)

The agent speaks one **canonical message shape**; each provider translates to/from
its wire format:

```
canonical: {"role","content", "tool_calls":[{"id","name","arguments(dict)"}],
            "tool_call_id","name"}
```

- **OllamaProvider** (local dev): no tool-call ids; arguments are dicts.
- **GroqProvider** (cloud): requires `id` + `tool_call_id` linkage and
  JSON-string arguments. Also **retries + salvages** Llama-3.3's occasional
  malformed `<function=...>` output (HTTP 400 `tool_use_failed`) so a bad
  generation never crashes a turn.

Selected by `LLM_PROVIDER` env (`ollama` | `groq`) — same agent code either way.

### Reliability guards (learned from live testing)

| Risk | Guard | Where |
|------|-------|-------|
| Model re-calls `save_patient_info` every turn → duplicate leads | Upsert by phone; reject empty phone | `sheets.save_patient_info` |
| Model re-calls `create_booking` → duplicate calendar events | Skip if phone+slot already booked | `agent._run_tool` + `sheets.booking_exists` |
| Groq returns malformed tool call (400) | Retry then salvage from `failed_generation` | `GroqProvider.chat` |
| Model wraps a string arg in a dict | `_normalize_args` flattens | `agent._run_tool` |
| Tool/LLM exception mid-chat | Caught → friendly fallback + contact number; webhook still 200 | `agent`, `orchestrator` |

---

## 5. Data model

**SQLite** (`physiobot.db`, ephemeral on cloud — conversation context only):
- `sessions(phone PK, state, updated_at)`
- `messages(id, phone, role, content, ts)` — last 20 turns fed to the model.

**Google Sheet** (durable record of leads/bookings):
- `Patients`: Timestamp, Name, Phone, Complaint, Notes
- `Bookings`: Timestamp, Name, Phone, Complaint, Slot, EventId

**Google Calendar**: one event per booking; free-slot logic = configured working
hours minus existing events minus past times, respecting `closed_weekdays`.

> Bookings/patients live in Google (durable). SQLite is only short-term
> conversation memory; losing it on redeploy is acceptable.

---

## 6. Configuration & secrets

`config.yaml` (committed, **no secrets**): clinic name/number/timezone, working
hours + closed days + slot length, LLM provider/models, Google sheet & calendar
ids.

Secrets via environment (`.env` locally, dashboard env vars on cloud):

| Var | Purpose | Local | Cloud |
|-----|---------|-------|-------|
| `LLM_PROVIDER` | ollama / groq | `ollama` | `groq` |
| `GROQ_API_KEY` | Groq auth | — | required |
| `GOOGLE_APPLICATION_CREDENTIALS` | key file path | required | — |
| `GOOGLE_CREDENTIALS_JSON` | full key JSON | — | required |
| `WHATSAPP_TOKEN` | send messages | optional | required |
| `WHATSAPP_PHONE_NUMBER_ID` | sender id | optional | required |
| `WHATSAPP_VERIFY_TOKEN` | webhook handshake | `physiobot-verify` | `physiobot-verify` |
| `WHATSAPP_APP_SECRET` | verify inbound sig | optional | recommended |

`.gitignore` excludes `.env`, `*.json`, `*.db`. Confirmed no secrets are tracked.

---

## 7. Wiring it to TEST

### 7a. Local, no WhatsApp (fastest inner loop)
```bash
cd physiobot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5                       # local brain
# .env: GOOGLE_APPLICATION_CREDENTIALS=<key path>, LLM_PROVIDER=ollama
python scripts/verify_setup.py            # checks Ollama + Sheet + Calendar
uvicorn physiobot.app:app --reload
# in another terminal:
python scripts/chat.py                    # REPL conversation with the bot
# or one-shot:
curl -s localhost:8000/simulate -H 'content-type: application/json' \
  -d '{"text":"Hi, I have knee pain, can I book Friday?"}'
```
`pytest -q` runs 34 offline tests (Ollama + Google mocked).

### 7b. On WhatsApp with a Meta TEST number (staging)
The deployed Render service already does this. To connect Meta:

1. **developers.facebook.com** → your app → **WhatsApp → Configuration → Webhook → Edit**
   - Callback URL: `https://physiobot-f70x.onrender.com/webhook`
   - Verify token: `physiobot-verify`
   - **Verify and save** (Meta GETs the URL; handshake passes).
2. **Webhook fields → Manage → toggle `messages` ON** (required, easy to miss).
3. **WhatsApp → API Setup → "To" → Manage phone number list** → add your own
   number (verify via the code Meta sends on WhatsApp).
4. Message the test number (`+1 555-655-2188`) from your phone → bot replies,
   writes to the Sheet, books to the Calendar.
5. Watch Render → **Logs** for `POST /webhook` lines.

**Test-number limits:** only approved recipients can chat; the temporary token
expires ~24h.

---

## 8. Wiring it for PRODUCTION

Moving from the sandbox test number to a real clinic line involves Meta business
setup, a durable token, and a few hardening steps. None require code changes
beyond `config.yaml`.

### 8a. Meta / WhatsApp Business (the big one)
1. **Meta Business Manager** → create/verify the **Business** (business
   verification: legal name, address, docs — can take days).
2. **Add a real phone number** to the WhatsApp Business Account (WABA). It must
   not already be on a personal/Business WhatsApp app; you'll verify it by
   SMS/call. This becomes the clinic's bot number.
3. **Display name & messaging profile** review by Meta.
4. **Permanent access token** — do NOT use the 24h token in production:
   - Business Manager → **System Users** → create a system user (Admin).
   - Assign the app + WABA assets to it.
   - **Generate token** with scopes `whatsapp_business_messaging` +
     `whatsapp_business_management`. This token does not expire.
   - Put it in `WHATSAPP_TOKEN` on Render.
5. **Set `WHATSAPP_APP_SECRET`** (App settings → Basic) on Render so inbound
   webhooks are signature-verified (`webhook.verify_signature`).
6. **Messaging rules:** outside a 24-hour customer-service window you can only
   send pre-approved **message templates**. The bot's free-form replies work
   only within 24h of the user's last message. (Today PhysioBot only replies
   reactively, so it's compliant; any future "reminders/follow-ups" need
   approved templates + a small outbound addition.)

### 8b. Hosting hardening
| Concern | Action |
|---------|--------|
| Free tier sleeps (50s cold start) | Upgrade Render to a paid always-on instance (~$7/mo), or add an external uptime ping |
| Auto-deploy | Render → Settings → Build & Deploy → **Auto-Deploy: On Commit** |
| Secrets | Keep all in Render env vars; rotate the keys that were shared in chat |
| Build marker | `/healthz` returns `build` + `provider` — check after each deploy |
| Conversation memory across restarts | If needed, move SQLite to a Render Disk (persistent volume) or swap to Postgres |
| Observability | Render Logs; consider structured logging + an error alert (Sentry free) |
| Google quota | Sheets/Calendar API quotas are ample for one clinic; batch if volume grows |

### 8c. Real-clinic config
Edit `config.yaml`: real `clinic.name`, `clinic.contact_number`, `timezone`,
actual `hours` (open/close, `slot_minutes`, `closed_weekdays`), and the
production Sheet/Calendar ids. Commit + push → Render auto-deploys.

### 8d. Pre-launch checklist
- [ ] Business verified; real number added & display name approved
- [ ] Permanent System User token in `WHATSAPP_TOKEN`
- [ ] `WHATSAPP_APP_SECRET` set; signature verification active
- [ ] `config.yaml` has real clinic details + hours
- [ ] Sheet shared with service account (Editor); Calendar shared (make changes)
- [ ] `GROQ_API_KEY` rotated; old chat-exposed keys/tokens revoked
- [ ] Render on always-on plan; auto-deploy on
- [ ] `/healthz` shows expected `build`; webhook subscribed to `messages`
- [ ] End-to-end: real phone → message → reply + Sheet row + Calendar event

---

## 9. Environments at a glance

| | Local dev | Staging (now) | Production |
|---|-----------|---------------|------------|
| LLM | Ollama `qwen2.5` | Groq `llama-3.3-70b` | Groq `llama-3.3-70b` |
| Host | laptop `uvicorn` | Render free | Render paid (always-on) |
| WhatsApp | none (`/simulate`) | Meta test number | Real clinic number (verified) |
| Token | n/a | temporary (~24h) | permanent System User token |
| Google creds | key file | JSON env var | JSON env var |
| Inbound sig check | off | off/optional | on (`WHATSAPP_APP_SECRET`) |

---

## 10. Known limitations / future work

- **No message templates** → cannot initiate conversations outside the 24h
  window (reminders/follow-ups) without adding template support.
- **SQLite memory is ephemeral** on free hosting (fine; Google is the record).
- **Single clinic / single number** by design (no multi-tenant).
- **No human-handover console** — escalation = sharing the contact number.
- **Cold starts** on free tier; upgrade for always-on.
- Calendar free/busy uses simple event overlap (no multi-resource/room logic).
