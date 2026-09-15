from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Smart Comrade"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "dev-secret-key-change-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Database
    DATABASE_URL: str

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # Object Storage
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "smartcomrade"

    # SMTP
    SMTP_ENABLED: bool = False
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@smartcomrade.local"
    SMTP_FROM_NAME: str = "Smart Comrade"
    SMTP_USE_TLS: bool = True

	# ── Upload pipeline ─────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_PAGES_PER_FILE: int = 100
    ALLOWED_UPLOAD_EXTENSIONS: str = "pdf,png,jpg,jpeg,docx,doc,pptx,ppt"

	# ── Storage ─────────────────────────────────────────────────
    STORAGE_BACKEND: str = "local"          # "local" | "s3" | "both"
    S3_BUCKET_NAME: str | None = None
    S3_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None

	# ── OCR ─────────────────────────────────────────────────────
    OCR_PROVIDER: str = "auto"              # "auto" | "ai" | "tesseract"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o"
    TESSERACT_CMD: str | None = None        # e.g. "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

    # SMS
    SMS_ENABLED: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()