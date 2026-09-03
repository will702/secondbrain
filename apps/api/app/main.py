import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import ask, auth, documents, health, inbox, knowledge
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
    return app


app = create_app()
