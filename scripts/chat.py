"""Interactive terminal chat with the running bot — a REPL over /simulate.

Start the server first (in another terminal):
    uvicorn physiobot.app:app --reload

Then chat here:
    python scripts/chat.py
Type your messages and press Enter. Ctrl-C or 'quit' to exit. Every line is
sent as the same patient (phone 'cli-user') so the conversation has memory.
"""
from __future__ import annotations

import sys

import httpx

URL = "http://localhost:8000/simulate"
PHONE = "cli-user"


def main():
    print("PhysioBot chat — type a message (Ctrl-C or 'quit' to exit)\n")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            return 0
        try:
            resp = httpx.post(URL, json={"phone": PHONE, "text": text}, timeout=120)
            resp.raise_for_status()
            print(f"bot> {resp.json()['reply']}\n")
        except httpx.HTTPError as e:
            print(f"[error talking to server: {e}]\n"
                  f"Is the server running? uvicorn physiobot.app:app --reload",
                  file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
