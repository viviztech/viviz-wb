from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.database import init_db
from app.services.auth import ensure_admin_exists
from app.database import AsyncSessionLocal
from app.routers import webhook, auth, dashboard, conversations, contacts, broadcasts, templates, api
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/app.log")],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Viviz WhatsApp Business API...")
    await init_db()
    async with AsyncSessionLocal() as db:
        await ensure_admin_exists(db)
    logger.info("Database initialized. Admin user ensured.")
    yield
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Viviz WhatsApp Business",
    description="Official Meta WhatsApp Business API Platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
)

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=86400)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(webhook.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(conversations.router)
app.include_router(contacts.router)
app.include_router(broadcasts.router)
app.include_router(templates.router)
app.include_router(api.router)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates
    t = Jinja2Templates(directory="app/templates")
    return t.TemplateResponse("dashboard/404.html", {"request": request}, status_code=404)
