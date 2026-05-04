"""Shared project-resolution helper (#44).

Both the parts router and the contracts router accept an optional
project slug on POST/PUT and on the list filter. This module
centralises the slug-to-id lookup so the same not-found error shape
appears in both places.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Project


async def resolve_project_slug(
    session: AsyncSession, slug: str | None
) -> uuid.UUID | None:
    """Resolve a project slug to a project id.

    Returns None when the slug is None (i.e. caller wants to clear or
    didn't tag the row). Raises 422 when the slug refers to a project
    that doesn't exist — same shape and status as other slug-resolution
    failures in this codebase.
    """
    if slug is None:
        return None
    proj = (
        await session.execute(select(Project).where(Project.name == slug))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Project {slug!r} does not exist",
        )
    return proj.id
