# PhysioBot — Technology Stack & Versions

A complete inventory of every technology, package, external API, and service this
project depends on, with the exact version in use. The purpose of this doc is to
make it easy to share **the latest official documentation** for each item so we
can keep the project current, robust, and idiomatic.

> How to use this doc: pick a row, grab its **Docs** link (or a newer one), and
> share it. The **Version in use** column is what's actually pinned/running today
> (as of 2026-06-21); the **Notes** call out where we're behind or where a
> version detail matters.

---

## 1. Language & Runtime

| Technology | Version in use | Where pinned | Docs | Notes |
| :--- | :--- | :--- | :--- | :--- |
| Python (local + cloud) | **3.12.3** | `.python-version` + `render.yaml` (`PYTHON_VERSION`) | https://docs.python.org/3.12/ | Aligned across local dev and prod — one runtime everywhere. Local selected via pyenv (`.python-version`). |

> ✅ **Runtime is now unified at 3.12.3** (local and cloud). Recreate the local
> venv with `pyenv install 3.12.3 && python -m venv .venv` if it predates this.
> `from __future__ import annotations` is kept in modules for hint hygiene but is
> no longer load-bearing for the runtime.

## 2. Web Framework & Server

| Technology | Version in use | Docs | Notes |
| :--- | :--- | :--- | :--- |
| FastAPI | **0.115.6** | https://fastapi.tiangolo.com/ | Webhook + `/simulate` + `/healthz`. Uses `BackgroundTasks` (whose exceptions are swallowed — see design-principles §6). |
| Starlette | **0.41.3** | https://www.starlette.io/ | FastAPI's underlying ASGI toolkit (transitive). |
| Uvicorn | **0.34.0** | https://www.uvicorn.org/ | ASGI server; `uvicorn physiobot.app:app`. `[standard]` extra installed. |
| Pydantic | **2.13.4** (core 2.46.4) | https://docs.pydantic.dev/latest/ | Only `SimulateIn` request model today; config uses plain dataclasses, not pydantic-settings. |
| HTTPX | **0.27.2** | https://www.python-httpx.org/ | Outbound calls to the Meta Graph API (`httpx.post`). |

## 3. LLM Providers (NLU layer)

| Technology | Version / Model | Docs | Notes |
| :--- | :--- | :--- | :--- |
| Ollama (Python client) | pkg **0.4.5** | https://github.com/ollama/ollama/blob/main/docs/api.md | Local dev provider. |
| Ollama model | **qwen2.5** | https://ollama.com/library/qwen2.5 | Default local model (`config.yaml`). |
| Groq (Python SDK) | **0.13.1** | https://console.groq.com/docs/quickstart | Cloud provider (Render sets `LLM_PROVIDER=groq`). Key from https://console.groq.com/keys |
| Groq model | **llama-3.3-70b-versatile** | https://console.groq.com/docs/models | Cloud NLU model. Worth checking the models page for newer/cheaper options. |

> The LLM is a stateless single-turn JSON translator; the bot must behave
> identically across providers (see design-principles §1). When checking docs,
> the relevant surface is just the chat-completions / chat endpoint.

## 4. Google APIs (Calendar + Sheets)

| Technology | Version in use | Docs | Notes |
| :--- | :--- | :--- | :--- |
| Google Calendar API | **v3** (via client lib) | https://developers.google.com/calendar/api/v3/reference | `build("calendar", "v3", ...)`; scope `.../auth/calendar`. One calendar (HSR branch) only. |
| Google Sheets API (gspread) | gspread **6.1.4** | https://docs.gspread.org/en/latest/ | Patients + Bookings tabs; scope `.../auth/spreadsheets`. |
| google-api-python-client | **2.156.0** | https://github.com/googleapis/google-api-python-client | Calendar client. |
| google-auth | **2.37.0** | https://google-auth.readthedocs.io/ | Service-account auth (`Credentials.from_service_account_*`). |
| google-auth-oauthlib | **1.3.1** | https://google-auth-oauthlib.readthedocs.io/ | Transitive. |
| google-api-core | **2.30.3** | https://googleapis.dev/python/google-api-core/latest/ | Emits the Python-3.9-unsupported `FutureWarning` we see in test runs. |

> Auth is a **service account** (not OAuth user flow): the target Sheet and
> Calendar must be shared with the service-account email as Editor.

## 5. Meta WhatsApp Cloud API

| Item | Version / Value | Docs | Notes |
| :--- | :--- | :--- | :--- |
| Graph API version | **v21.0** | https://developers.facebook.com/docs/whatsapp/cloud-api | Hardcoded in `outbound.py` (`GRAPH_URL`). Meta deprecates versions ~2 yrs; check for the current default version. |
| Cloud API — send messages | — | https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages | Text, template, and interactive (button/list/cta_url) sends. |
| Interactive messages reference | — | https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates | Source of the hard limits enforced in `templates.py` (`META_LIMITS`). |
| Message templates | — | https://developers.facebook.com/docs/whatsapp/message-templates | Needed for sends **outside** the 24-hour window. |
| Webhooks | — | https://developers.facebook.com/docs/graph-api/webhooks | Inbound `messages` field; `X-Hub-Signature-256` verification. |

> 🔑 **Most valuable docs to keep current:** the interactive-message limits and
> the latest stable Graph API version. The hard limits (row title 24, 10 rows
> total, etc.) are the constraints that have caused silent failures — if Meta
> changes them, update `META_LIMITS` in `physiobot/templates.py`.

## 6. Local Dev Tunnel (Meta webhook)

| Tool | Version | Docs | Notes |
| :--- | :--- | :--- | :--- |
| ngrok | not pinned (CLI) | https://ngrok.com/docs | `ngrok http 8000` to expose the local webhook to Meta during dev. |
| cloudflared (alt) | not pinned (CLI) | https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/ | Mentioned as an alternative tunnel in the design doc. |

> Tunnels are **dev-only**. Production uses Render's public URL (no tunnel).

## 7. Hosting / Deployment

| Service | Plan / Config | Docs | Notes |
| :--- | :--- | :--- | :--- |
| Render | **free web service** | https://render.com/docs/blueprint-spec | Defined in `render.yaml` (Blueprint). Free tier **sleeps after ~15 min idle** (~50s cold start; Meta retries). SQLite on **ephemeral disk** — resets on redeploy. |
| GitHub repo | — | https://github.com/jyotiSahu12/physiobot | Source + Render deploy source. |

> Durable data (bookings/patients) lives in Google Sheets/Calendar precisely
> because Render's disk is ephemeral. SQLite holds only transient session state.

## 8. Config, Storage & Tooling

| Technology | Version in use | Docs | Notes |
| :--- | :--- | :--- | :--- |
| SQLite | stdlib `sqlite3` (Python 3.12) | https://docs.python.org/3/library/sqlite3.html | Session + message history + `processed_messages` (webhook dedup); schema self-heals on every connection. |
| PyYAML | **6.0.2** | https://pyyaml.org/wiki/PyYAMLDocumentation | Loads `config.yaml` via `yaml.safe_load`. |
| python-dotenv | **1.0.1** | https://saurabh-kumar.com/python-dotenv/ | Loads `.env` (secrets). |
| pytest | **8.3.4** | https://docs.pytest.org/ | 132 tests. |
| pytest-asyncio | **0.25.0** | https://pytest-asyncio.readthedocs.io/ | Installed; current tests are sync. |
| pyflakes | (dev, not pinned in requirements) | https://github.com/PyCQA/pyflakes | Unused-import/lint gate run alongside pytest. |

---

## 9. Quick "please send me latest docs for…" checklist

If you can share current docs for these, it has the highest leverage for keeping
the project robust and up to date:

1. **Meta WhatsApp Cloud API** — current stable Graph API version (now
   configurable via `META_GRAPH_API_VERSION`, default `v21.0`) + the
   interactive-message limits page (enforced via `META_LIMITS`).
2. **Groq models** — newest recommended chat model (we use `llama-3.3-70b-versatile`).
3. **Render free-tier** — any changes to sleep behaviour / persistent disk options.
4. **Google Calendar API v3 + gspread** — current auth + rate-limit guidance.
5. **FastAPI / Uvicorn** — latest stable, esp. anything on `BackgroundTasks`
   error handling and graceful shutdown.

## 10. Version-hygiene status

Resolved in this pass:
- ✅ **Python runtime unified at 3.12.3** (local `.python-version` + cloud `render.yaml`).
- ✅ **Graph API version is now configurable** (`META_GRAPH_API_VERSION`, default `v21.0`).
- ✅ **Dead `max_tool_iterations` config removed** (leftover from the removed tool-calling agent).
- ✅ **Webhook idempotency added** — duplicate Meta deliveries are dropped via `processed_messages`.
- ✅ **google-api-core Python-3.9 warning gone** with the 3.12 move.

Still open (intentionally deferred — productionization phase):
- **No dependency lockfile** — `requirements.txt` uses `==` pins but no hash-locked
  file (`pip-tools`/`uv`). Add `requirements-dev.txt` for pyflakes/pytest first.
- **Render free tier** sleeps/has ephemeral disk — fine while SQLite is transient
  and durable records live in Sheets/Calendar; revisit before a real launch.
- **BackgroundTasks** has no durable retry queue — acceptable at current volume;
  the whole turn is already wrapped so failures send a fallback, never silence.
