from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────
    APP_NAME: str = "Smart Comrade"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "dev-secret-key-change-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ── Cache (for pending registrations) ────────────────────
    CACHE_BACKEND: str = "memory"    # memory | redis

    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str

    # ── Redis / Celery ────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # ── Object Storage ────────────────────────────────────────
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "smartcomrade"

    # ── Email providers ───────────────────────────────────────
    EMAIL_PROVIDER: str = "console"       # console | smtp | sendgrid | mailgun | ses
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "noreply@smartcomrade.com"
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SENDGRID_API_KEY: str | None = None
    MAILGUN_API_KEY: str | None = None
    MAILGUN_DOMAIN: str | None = None

    # ── SMS providers ─────────────────────────────────────────
    SMS_PROVIDER: str = "console"         # console | africastalking | twilio | vonage
    AT_API_KEY: str | None = None
    AT_USERNAME: str | None = None
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_FROM_NUMBER: str | None = None
    VONAGE_API_KEY: str | None = None
    VONAGE_API_SECRET: str | None = None
    VONAGE_SENDER_ID: str | None = None

    # ── Rate limiting ─────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_BACKEND: str = "memory"    # memory | redis
    TRUST_PROXY_HEADERS: bool = False

    # ── CAPTCHA ───────────────────────────────────────────────
    CAPTCHA_PROVIDER: str = "none"        # none | hcaptcha | recaptcha | turnstile
    HCAPTCHA_SECRET_KEY: str | None = None
    RECAPTCHA_SECRET_KEY: str | None = None
    RECAPTCHA_MIN_SCORE: float = 0.5
    TURNSTILE_SECRET_KEY: str | None = None

    # ── Upload pipeline ───────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_PAGES_PER_FILE: int = 100
    ALLOWED_UPLOAD_EXTENSIONS: str = "pdf,png,jpg,jpeg,docx,doc,pptx,ppt"

    # ── Storage ───────────────────────────────────────────────
    STORAGE_BACKEND: str = "local"          # "local" | "s3" | "both"
    S3_BUCKET_NAME: str | None = None
    S3_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None

    # ── OCR / LLM extraction ──────────────────────────────────
    OCR_PROVIDER: str = "auto"              # "auto" | "ai" | "groq" | "tesseract"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    TESSERACT_CMD: str | None = None        # e.g. "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

    # ── Legacy toggles (kept for backward compat) ─────────────
    SMS_ENABLED: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()