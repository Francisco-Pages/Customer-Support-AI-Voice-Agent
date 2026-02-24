from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_base_url: str = "https://your-domain.com"  # Used to construct Twilio webhook URLs
    debug: bool = False

    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str  # E.164 format, e.g. +15551234567

    # OpenAI
    openai_api_key: str

    # Deepgram
    deepgram_api_key: str

    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Pinecone
    pinecone_api_key: str
    pinecone_index_name: str

    # PostgreSQL
    database_url: str  # e.g. postgresql+asyncpg://user:password@host:5432/dbname

    # Redis
    redis_url: str  # e.g. redis://localhost:6379/0

    # Admin API
    admin_api_key: str


settings = Settings()
