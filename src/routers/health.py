from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session

try:
    PROJECT_VERSION = _pkg_version("titan-tyr")
except PackageNotFoundError:
    PROJECT_VERSION = "0.0.0+unknown"

# No auth dependency on this router — orchestrators don't carry bearer tokens.
router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "degraded",
                "version": PROJECT_VERSION,
                "db": "unreachable",
            },
        )
    return {"status": "ok", "version": PROJECT_VERSION, "db": "reachable"}
