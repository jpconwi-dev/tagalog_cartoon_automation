from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.routes import public, router
from app.core.config import get_settings
from app.core.security import redact
from app.db.session import init_db

MAX_BODY_BYTES = 64 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # fails fast on unsafe config
    init_db()
    yield


app = FastAPI(title="Tagalog Cartoon Automation", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def limit_body(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request body too large"}, status_code=413)
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    return JSONResponse({"detail": redact(f"Internal error: {type(exc).__name__}")}, status_code=500)


app.include_router(public)
app.include_router(router)
