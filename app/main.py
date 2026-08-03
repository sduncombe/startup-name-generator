from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app import db as dbmod
from app.api.runs import router as runs_router
from app.config import ROOT, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("startup-name-generator")

STATIC_DIR = ROOT / "static"


class BasicRateLimitMiddleware(BaseHTTPMiddleware):
    """Very light in-process rate limit for local/internal use."""

    def __init__(self, app, max_per_minute: int = 120) -> None:
        super().__init__(app)
        self.max_per_minute = max_per_minute
        self._hits: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next):
        import time

        if request.url.path.startswith("/api/"):
            ip = request.client.host if request.client else "local"
            now = time.time()
            window = self._hits.setdefault(ip, [])
            self._hits[ip] = [t for t in window if now - t < 60]
            if len(self._hits[ip]) >= self.max_per_minute:
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
            self._hits[ip].append(now)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.db = await dbmod.connect()
    logger.info("SQLite ready at %s", settings.db_path)
    yield
    await app.state.db.close()


app = FastAPI(
    title="Startup Name Generator",
    description="Open-source pronounceable startup names, scoring, RDAP domains, and optional BYOK AI",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(BasicRateLimitMiddleware)

app.include_router(runs_router)


@app.get("/api/health")
async def health() -> dict[str, object]:
    from app.services.llm import llm_status

    settings = get_settings()
    status = llm_status()
    return {
        "status": "ok",
        "public_app_url": settings.public_app_url,
        "github_repo_url": settings.github_repo_url,
        **status,
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
