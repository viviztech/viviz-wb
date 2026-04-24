from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.services.auth import ensure_admin_exists
from app.routers import webhook, auth, dashboard, conversations, contacts, broadcasts, templates, api, quick_replies, analytics, auto_replies, optin
import app.models  # ensure all models imported for init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.logging_config import configure_logging, RequestIDMiddleware
import logging

configure_logging()
logger = logging.getLogger(__name__)

# Rate limiter — uses Redis backend when available, falls back to memory
try:
    import redis as redis_lib
    _redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
    _redis_client.ping()
    from slowapi.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"],
                      storage_uri=settings.redis_url)
    logger.info("Rate limiter using Redis backend")
except Exception:
    limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
    logger.info("Rate limiter using in-memory backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Viviz WhatsApp Business API...")
    await init_db()
    async with AsyncSessionLocal() as db:
        await ensure_admin_exists(db)
    logger.info("Database initialized. Admin user ensured.")
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Viviz WhatsApp Business",
    description="Official Meta WhatsApp Business API Platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=86400,
    https_only=not settings.debug,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",")],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(webhook.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(conversations.router)
app.include_router(contacts.router)
app.include_router(broadcasts.router)
app.include_router(templates.router)
app.include_router(api.router)
app.include_router(quick_replies.router)
app.include_router(analytics.router)
app.include_router(auto_replies.router)
app.include_router(optin.router)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    t = Jinja2Templates(directory="app/templates")
    return t.TemplateResponse("dashboard/404.html", {"request": request}, status_code=404)
