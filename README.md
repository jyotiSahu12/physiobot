# PhysioBot

A self-contained, open-source WhatsApp chatbot for a physiotherapy clinic. It
chats with patients using a **local LLM (Ollama)**, captures patient details to
a **Google Sheet**, and books appointments on **Google Calendar** — and shares
the clinic's contact number when a human is needed.

No external platform, no cloud LLM, no paid services. One FastAPI process.

See `docs/2026-06-09-physiobot-design.md` for the full design.

## How it works

```
WhatsApp ─▶ /webhook ─▶ orchestrator ─▶ agent (Ollama + tools) ─▶ outbound ─▶ WhatsApp
                              │                  │
                           SQLite           Google Sheets + Calendar
```

## Quick start (local, no WhatsApp yet)

1. **Install deps** (a virtualenv is created for you):
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Ollama** — install from https://ollama.com, then:
   ```bash
   ollama pull qwen2.5
   ```
3. **Google** — you already have a service account. Put its JSON key path in
   `.env` (`GOOGLE_APPLICATION_CREDENTIALS`), and in `config.yaml` set:
   - `google.sheet_id` — from the Sheet URL `.../spreadsheets/d/<ID>/edit`
   - `google.calendar_id` — usually the calendar owner's email, or the ID under
     Calendar settings → "Integrate calendar"
   Share **both** the Sheet (Editor) and the Calendar ("Make changes to events")
   with the service-account email.
4. **Edit `config.yaml`** — clinic name, contact number, working hours.
5. **Verify everything is wired:**
   ```bash
   python scripts/verify_setup.py
   ```
6. **Run and chat with the agent directly** (no WhatsApp needed):
   ```bash
   uvicorn physiobot.app:app --reload
   curl -s localhost:8000/simulate -H 'content-type: application/json' \
     -d '{"text":"Hi, I have knee pain and want to book a visit"}'
   ```

## Going live on WhatsApp (Meta Cloud API)

1. Create a Meta app → add **WhatsApp** → get a test number, **temporary token**,
   and **phone number id**. Put them in `.env` (`WHATSAPP_TOKEN`,
   `WHATSAPP_PHONE_NUMBER_ID`).
2. Expose your local server:
   ```bash
   ngrok http 8000
   ```
3. In the Meta dashboard, set the **Webhook callback URL** to
   `https://<ngrok>/webhook` and the **Verify token** to the value of
   `WHATSAPP_VERIFY_TOKEN` in `.env`. Subscribe to the `messages` field.
4. Set `WHATSAPP_APP_SECRET` in `.env` to enable signature verification.
5. Message the test number from your phone — the bot replies.

## Tests

```bash
source .venv/bin/activate
pytest -q
```

Tests mock Ollama and Google, so they run offline.

## Layout

| Path | Responsibility |
|------|----------------|
| `physiobot/webhook.py` | Meta verify + parse inbound payloads |
| `physiobot/orchestrator.py` | session → agent → persist → send |
| `physiobot/agent.py` | Ollama tool-calling loop |
| `physiobot/tools/sheets.py` | append Patients / Bookings rows |
| `physiobot/tools/calendar.py` | free slots + create event |
| `physiobot/outbound.py` | send reply to Meta API |
| `physiobot/store.py` | SQLite sessions + history |
| `physiobot/config.py` | load `config.yaml` + `.env` |
```
