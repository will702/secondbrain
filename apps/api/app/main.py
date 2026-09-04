import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import ai, ask, auth, briefing, calendar, documents, health, inbox, knowledge
from app.core.config import get_settings
from app.core.logging import configure_logging, new_request_id

configure_logging()
logger = logging.getLogger("secondbrain.api")
settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or new_request_id()
        start = time.perf_counter()
        response: JSONResponse = await call_next(request)
        response.headers["x-request-id"] = request_id
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
            extra={"request_id": request_id},
        )
        return response

    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router)
    app.include_router(inbox.router)
    app.include_router(documents.router)
    app.include_router(knowledge.router)
    app.include_router(ask.router)
    app.include_router(calendar.router)
    app.include_router(briefing.router)
    app.include_router(ai.router)

    # Packaged app: serve the static web export at "/" (registered last, so
    # API routes win; every page has its own HTML file in the export).
    if settings.web_dist_dir is not None:
        dist = settings.web_dist_dir
        if dist.is_dir():
            app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
        else:  # pragma: no cover - packaging misconfiguration
            logger.warning("web_dist_dir %s does not exist; serving API only", dist)
    return app


app = create_app()
