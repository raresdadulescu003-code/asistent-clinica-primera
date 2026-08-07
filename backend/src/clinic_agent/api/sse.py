"""Contractul Server-Sent Events, într-un singur loc.

Widget-ul parsează exact formatul ăsta. Dacă se schimbă aici, se schimbă și
în `widget.js` — de aceea e un modul separat, nu șiruri împrăștiate prin rute.

    data: {"type": "token", "text": "..."}
    data: {"type": "done"}
    data: {"type": "error", "message": "..."}
"""

from __future__ import annotations

import json

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Fără asta, nginx-ul unui reverse proxy tamponează răspunsul și
    # streaming-ul dispare: textul apare tot deodată, la final.
    "X-Accel-Buffering": "no",
}


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def token_event(text: str) -> str:
    return _event({"type": "token", "text": text})


def done_event() -> str:
    return _event({"type": "done"})


def error_event(message: str) -> str:
    return _event({"type": "error", "message": message})
