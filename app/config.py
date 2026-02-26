from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_base_url: str = "https://your-domain.com"  # Public URL Twilio posts webhooks to
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
    livekit_url: str         # wss://your-livekit-server.com
    livekit_api_key: str
    livekit_api_secret: str

    # LiveKit SIP — used to build the <Dial><Sip> TwiML for inbound calls.
    # For LiveKit Cloud: find the SIP host on your project settings page
    #   (e.g. "xyz.sip.livekit.cloud")
    # For self-hosted: the hostname/IP of your LiveKit SIP server
    livekit_sip_host: str

    # SIP trunk credentials — must match the auth_username / auth_password
    # set when creating the LiveKit inbound trunk with `lk sip inbound create`
    sip_trunk_username: str
    sip_trunk_password: str

    # Pinecone
    pinecone_api_key: str
    pinecone_index_name: str       # HVAC knowledge-base index (1536-dim, cosine)
    pinecone_geo_index_name: str = "hvac-geo-directory"   # Geo-directory index (3-dim, dotproduct)

    # PostgreSQL (AWS RDS)
    database_url: str  # e.g. postgresql+asyncpg://user:password@host:5432/dbname

    # Redis (AWS ElastiCache)
    redis_url: str  # e.g. redis://localhost:6379/0

    # Admin API
    admin_api_key: str


settings = Settings()
