import logging
import logging.config

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import admin, linq, stream, telephony

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="HVAC Voice AI Customer Support Agent",
        description="Inbound and outbound voice AI agent powered by LiveKit, GPT-4o, and Twilio.",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,   # Disable Swagger in production
        redoc_url="/redoc" if settings.debug else None,
    )

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],   # Tighten in production
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------

    app.include_router(telephony.router)
    app.include_router(stream.router)
    app.include_router(admin.router)
    app.include_router(linq.router)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok"}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    # ------------------------------------------------------------------
    # Dashboard redirect
    # ------------------------------------------------------------------

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_redirect():
        return RedirectResponse(url="/dashboard/index.html")

    # ------------------------------------------------------------------
    # Static files (dashboard) — must come AFTER routes
    # ------------------------------------------------------------------

    app.mount(
        "/dashboard",
        StaticFiles(directory="app/static/dashboard", html=True),
        name="dashboard",
    )

    # ------------------------------------------------------------------
    # Startup / shutdown lifecycle
    # ------------------------------------------------------------------

    @app.on_event("startup")
    async def on_startup():
        logger.info("Starting HVAC Voice AI Agent | debug=%s", settings.debug)

        from sqlalchemy import text
        from app.dependencies import engine

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connection OK")
        except Exception as exc:
            logger.warning("Database unavailable at startup: %s", exc)

        try:
            from app.rag.retriever import _redis
            client = await _redis()
            await client.ping()
            logger.info("Redis connection OK")
        except Exception as exc:
            logger.warning("Redis unavailable at startup: %s", exc)

    @app.on_event("shutdown")
    async def on_shutdown():
        logger.info("Shutting down HVAC Voice AI Agent")
        from app.dependencies import engine
        await engine.dispose()

    return app


app = create_app()
