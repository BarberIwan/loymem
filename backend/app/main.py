from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps import csrf_guard
from app.api.routes import api
from app.services import DomainError

log = logging.getLogger("loymem")

app = FastAPI(
    title="Loymem",
    version="0.1.0",
    dependencies=[Depends(csrf_guard)],
    docs_url=None,
    redoc_url=None,
)
app.include_router(api)


@app.exception_handler(DomainError)
def domain_error(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse({"detail": exc.code}, status_code=exc.status)


@app.exception_handler(IntegrityError)
def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    log.warning("integrity error: %s", exc.orig)
    return JSONResponse({"detail": "already_exists"}, status_code=409)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
