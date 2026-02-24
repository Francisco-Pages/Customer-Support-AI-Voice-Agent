import logging
import logging.config

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, stream, telephony

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

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Startup / shutdown lifecycle
    # ------------------------------------------------------------------

    @app.on_event("startup")
    async def on_startup():
        logger.info("Starting HVAC Voice AI Agent | debug=%s", settings.debug)
        # TODO: Verify DB connection
        # TODO: Verify Redis connection
        # TODO: Verify Pinecone index exists

    @app.on_event("shutdown")
    async def on_shutdown():
        logger.info("Shutting down HVAC Voice AI Agent")
        # TODO: Gracefully close active LiveKit sessions

    return app


app = create_app()
