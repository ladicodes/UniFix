from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import ServicesDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: Literal["ok"]


class ReadyOut(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]


@router.get("/health", summary="Liveness: the process is running")
async def health() -> HealthOut:
    return HealthOut(status="ok")


@router.get(
    "/ready",
    summary="Readiness: dependencies are reachable",
    response_model=ReadyOut,
    responses={503: {"model": ReadyOut, "description": "A dependency is unavailable"}},
)
async def ready(services: ServicesDep) -> Response:
    try:
        async with services.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:  # any connection failure means "not ready"; details go to the log
        logger.exception("Readiness check failed")
        body = ReadyOut(status="not_ready", database="unavailable")
        return JSONResponse(status_code=503, content=body.model_dump())
    return JSONResponse(status_code=200, content=ReadyOut(status="ready", database="ok").model_dump())
