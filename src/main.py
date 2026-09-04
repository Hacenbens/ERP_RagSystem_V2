"""
FastAPI application entry point.

Run with:
    uvicorn src.main:app --reload

Middleware order (outermost first at request time):
    LoggingMiddleware → AuthMiddleware → RateLimitMiddleware
    → RBACMiddleware → PIIMaskingMiddleware → route handler

Starlette applies add_middleware() in reverse, so the calls below read
bottom-up: the last one added is the first one to see a request.

All five middlewares documented in src/middleware/__init__.py are mounted.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv

# .env must be loaded before any src.* import. Several modules read
# os.environ at import time — jwt_handler computes its token expiry,
# celery_app resolves its broker URL — so importing them first would bake in
# defaults and silently ignore the operator's configuration. This is the one
# place that ordering matters, hence the E402 suppressions below.
load_dotenv()

from fastapi import FastAPI  # noqa: E402

from src.infrastructure.di.factory import build_container  # noqa: E402
from src.middleware.AuthMiddleware import AuthMiddleware  # noqa: E402
from src.middleware.LoggingMiddleware import LoggingMiddleware  # noqa: E402
from src.middleware.PIIMaskingMiddleware import PIIMaskingMiddleware  # noqa: E402
from src.middleware.RateLimitMiddleware import RateLimitMiddleware  # noqa: E402
from src.middleware.RBACMiddleware import RBACMiddleware  # noqa: E402
from src.observability.structured_logger import get_logger  # noqa: E402
from src.routes.admin import router as admin_router  # noqa: E402
from src.routes.auth import router as auth_router  # noqa: E402
from src.routes.data import router as data_router  # noqa: E402
from src.routes.query import router as query_router  # noqa: E402

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build and validate the DI container once, before serving traffic.

    build_container() calls DIContainer.validate(), so an unbound required
    port fails startup here rather than surfacing as a 500 on first request.
    """
    app.state.container = build_container()
    logger.info("app.startup", message="DI container ready")
    yield
    logger.info("app.shutdown")


app = FastAPI(
    title="ERP Agentic RAG",
    version="0.9.0",
    lifespan=lifespan,
)

# Added in reverse: LoggingMiddleware ends up outermost, PIIMasking innermost.
# RateLimit sits inside Auth so it can key on the authenticated user_id that
# AuthMiddleware puts on request.state; outside it, every caller would share
# the anonymous bucket.
app.add_middleware(PIIMaskingMiddleware)
app.add_middleware(RBACMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(LoggingMiddleware)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(query_router)
app.include_router(data_router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness probe. Public — see src/middleware/public_paths.py."""
    return {"status": "ok"}


__all__ = ["app"]
