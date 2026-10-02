"""Where PNGs are written, and how they reach a chat as a photo.

Hermes delivers a local file to Telegram, Slack, Discord and the other
gateways (LINE when LINE_PUBLIC_URL is set) when the assistant's final message
contains ``MEDIA:/absolute/path``.
The gateway adds that line by itself only for its own image and speech tools,
so a chart would be lost whenever the model forgets the line. The optional
``transform_llm_output`` hook below closes that gap: at the end of a turn it
appends the MEDIA line for charts this session rendered that the reply does
not already include. It never touches replies on terminals, where MEDIA lines
are printed as text.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple

# Surfaces that print MEDIA: lines literally instead of attaching the file, and the
# raw-text gateways (API server, webhooks) whose replies go back to a program as text.
NO_ATTACHMENT_PLATFORMS = frozenset({"", "cli", "tui", "acp", "sms", "local",
                                     "api_server", "webhook", "msgraph_webhook"})
PENDING_TTL_SECONDS = 30 * 60
MAX_ATTACH_PER_TURN = 4

_pending: Dict[str, List[Tuple[float, str]]] = {}
_lock = threading.Lock()


def output_dir() -> str:
    """Hermes' image cache (always allowed for delivery), else a temp folder."""
    try:
        from hermes_constants import get_hermes_dir
        path = str(get_hermes_dir("cache/images", "image_cache"))
    except Exception:  # running outside Hermes (tests, scripts)
        home = os.environ.get("HERMES_HOME")
        path = (os.path.join(home, "cache", "images") if home
                else os.path.join(tempfile.gettempdir(), "hermes-charts"))
    os.makedirs(path, exist_ok=True)
    return path


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def png_path(title: str, filename: str = "") -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha1(f"{title}{time.time_ns()}".encode()).hexdigest()[:8]
    base = _SAFE.sub("-", os.path.basename(filename or "")).strip("-.")
    if base.lower().endswith(".png"):
        base = base[:-4]
    name = f"{base[:60]}-{digest}.png" if base else f"chart-{stamp}-{digest}.png"
    return os.path.join(output_dir(), name)


def media_line(path: str) -> str:
    return f"MEDIA:{path}"


def remember(session_id: Optional[str], path: str) -> None:
    if not session_id:
        return
    now = time.time()
    with _lock:
        items = [(t, p) for t, p in _pending.get(session_id, []) if now - t < PENDING_TTL_SECONDS]
        items.append((now, path))
        _pending[session_id] = items[-MAX_ATTACH_PER_TURN:]


def take(session_id: str) -> List[str]:
    now = time.time()
    with _lock:
        items = _pending.pop(session_id, [])
    return [p for t, p in items if now - t < PENDING_TTL_SECONDS and os.path.isfile(p)]


def append_missing_media(response_text: str, session_id: str = "", platform: str = "") -> Optional[str]:
    """Return the reply with MEDIA lines added for unsent charts, or None to leave it alone."""
    paths = take(session_id) if session_id else []
    if not paths or (platform or "").lower() in NO_ATTACHMENT_PLATFORMS:
        return None
    text = response_text or ""
    missing = [p for p in paths if p not in text]
    if not missing or len(missing) < len(paths) and "MEDIA:" in text:
        # The model attached at least one of this turn's charts itself: it chose what to send.
        return None
    return text.rstrip() + "\n\n" + "\n".join(media_line(p) for p in missing)
