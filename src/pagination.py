from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime

from fastapi import HTTPException, status

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def encode_cursor(updated_at: datetime, row_id: uuid.UUID) -> str:
    payload = {"t": updated_at.isoformat(), "i": str(row_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    # Re-pad before decoding because we strip padding in encode_cursor.
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["t"]), uuid.UUID(payload["i"])
    except (binascii.Error, ValueError, KeyError, json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid pagination cursor",
        )


def validate_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"limit must be between 1 and {MAX_LIMIT}",
        )
    return limit
