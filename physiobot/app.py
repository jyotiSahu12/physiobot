"""FastAPI entry point — wires the webhook to the orchestrator.

Run:  uvicorn physiobot.app:app --reload
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, BackgroundTasks, Request, Response
from pydantic import BaseModel

from .config import get_config
from .orchestrator import Orchestrator
from . import webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("physiobot.app")

app = FastAPI(title="PhysioBot")
config = get_config()
orchestrator = Orchestrator(config)

# Bump on each meaningful deploy so /healthz tells us exactly what's live.
BUILD = "2026-06-21-clinic-kb-v3-migration"


@app.get("/healthz")
def healthz():
    return {"status": "ok", "build": BUILD,
            "provider": config.llm.provider,
            "meta_configured": config.meta.configured}


@app.get("/webhook")
def verify(request: Request):
    """Meta subscription handshake."""
    params = request.query_params
    if webhook.verify_subscription(
        params.get("hub.mode", ""),
        params.get("hub.verify_token", ""),
        config.meta.verify_token,
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    """Receive inbound WhatsApp messages. Returns 200 immediately (Meta retries
    otherwise) and processes each message in the background."""
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not webhook.verify_signature(body, sig, config.meta.app_secret):
        return Response(status_code=403)

    payload = await request.json()
    for event in webhook.parse_incoming(payload):
        background.add_task(
            orchestrator.handle_message,
            event["phone"],
            event["text"],
            interactive_id=event["interactive_id"],
            profile_name=event["profile_name"],
        )
    return {"status": "received"}


# --- local testing without Meta -------------------------------------------
class SimulateIn(BaseModel):
    phone: str = "test-user"
    text: str


@app.post("/simulate")
def simulate(msg: SimulateIn):
    """Send a message to the bot directly (no WhatsApp). Returns the reply so
    you can chat with the agent from curl / a browser while developing."""
    reply = orchestrator.handle_message(msg.phone, msg.text)
    return {"reply": reply}
