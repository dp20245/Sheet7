from __future__ import annotations

import hashlib


def event_id(*parts: object) -> str:
    text = "|".join("" if part is None else str(part).strip().lower() for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

