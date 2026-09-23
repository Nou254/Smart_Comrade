from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ─────────────────────────────────────────────────────────────────
    # App
    # ─────────────────────────────────────────────────────────────────
    APP_NAME: str = "Smart Comrade"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "dev-secret-key-change-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ─────────────────────────────────────────────────────────────────
    # Cache (for pending registrations)
    # ─────────────────────────────────────────────────────────────────
    CACHE_BACKEND: str = "memory"    # memory | redis

    # ─────────────────────────────────────────────────────────────────
    # Database
    # ─────────────────────────────────────────────────────────────────
    DATABASE_URL: str

    # ─────────────────────────────────────────────────────────────────
    # Redis / Celery
    # ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # ─────────────────────────────────────────────────────────────────
    # Object Storage
    # ─────────────────────────────────────────────────────────────────
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "smartcomrade"

    # ─────────────────────────────────────────────────────────────────
    # Email providers
    # ─────────────────────────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────────────
    # SMS providers
    # ─────────────────────────────────────────────────────────────────
    SMS_PROVIDER: str = "console"         # console | africastalking | twilio | vonage
    AT_API_KEY: str | None = None
    AT_USERNAME: str | None = None
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_FROM_NUMBER: str | None = None
    VONAGE_API_KEY: str | None = None
    VONAGE_API_SECRET: str | None = None
    VONAGE_SENDER_ID: str | None = None

    # ─────────────────────────────────────────────────────────────────
    # Rate limiting
    # ─────────────────────────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_BACKEND: str = "memory"    # memory | redis
    TRUST_PROXY_HEADERS: bool = False

    # ─────────────────────────────────────────────────────────────────
    # CAPTCHA
    # ─────────────────────────────────────────────────────────────────
    CAPTCHA_PROVIDER: str = "none"        # none | hcaptcha | recaptcha | turnstile
    HCAPTCHA_SECRET_KEY: str | None = None
    RECAPTCHA_SECRET_KEY: str | None = None
    RECAPTCHA_MIN_SCORE: float = 0.5
    TURNSTILE_SECRET_KEY: str | None = None

    # ─────────────────────────────────────────────────────────────────
    # Upload pipeline
    # ─────────────────────────────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_PAGES_PER_FILE: int = 100
    ALLOWED_UPLOAD_EXTENSIONS: str = "pdf,png,jpg,jpeg,docx,doc,pptx,ppt"

    # ─────────────────────────────────────────────────────────────────
    # Storage
    # ─────────────────────────────────────────────────────────────────
    STORAGE_BACKEND: str = "local"          # "local" | "s3" | "both"
    S3_BUCKET_NAME: str | None = None
    S3_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None

    # ─────────────────────────────────────────────────────────────────
    # OCR / LLM extraction
    # ─────────────────────────────────────────────────────────────────
    OCR_PROVIDER: str = "auto"              # "auto" | "ai" | "groq" | "tesseract"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    TESSERACT_CMD: str | None = None        # e.g. "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

    # ─────────────────────────────────────────────────────────────────
    # AI assistance (Module 005) — OpenAI-compatible chat completions
    # ─────────────────────────────────────────────────────────────────
    # Every AI call in the platform goes through one HTTP client that
    # speaks the OpenAI /chat/completions protocol. Point AI_API_BASE at
    # Groq, OpenAI, or any compatible gateway.
    AI_ENABLED: bool = True
    AI_API_BASE: str = "https://api.groq.com/openai/v1"
    AI_API_KEY: str | None = None
    AI_MODEL_CHEAP: str = "llama-3.1-8b-instant"
    AI_MODEL_MID: str = "llama-3.3-70b-versatile"
    AI_MODEL_PREMIUM: str = "llama-3.3-70b-versatile"
    AI_TIMEOUT_SECONDS: float = 30.0
    AI_MAX_TOKENS: int = 1024
    # Minimum relevance confidence for a shared resource to auto-publish.
    AI_RESOURCE_MIN_CONFIDENCE: float = 0.6

    # ─────────────────────────────────────────────────────────────────
    # Payments — M-Pesa (Safaricom Daraja)
    # ─────────────────────────────────────────────────────────────────
    MPESA_CONSUMER_KEY: str | None = None
    MPESA_CONSUMER_SECRET: str | None = None
    MPESA_SHORTCODE: str | None = None
    MPESA_PASSKEY: str | None = None
    MPESA_ENVIRONMENT: str = "sandbox"          # sandbox | production
    MPESA_CALLBACK_URL: str = ""
    MPESA_TRANSACTION_TYPE: str = "CustomerPayBillOnline"
    # Refunds/reversals need an initiator and an RSA-encrypted credential.
    MPESA_INITIATOR_NAME: str | None = None
    MPESA_SECURITY_CREDENTIAL: str | None = None

    # ─────────────────────────────────────────────────────────────────
    # Payments — card / bank gateway
    # ─────────────────────────────────────────────────────────────────
    PAYMENT_GATEWAY_BASE_URL: str | None = None
    PAYMENT_GATEWAY_API_KEY: str | None = None
    # Shared secret used to HMAC-verify inbound provider webhooks.
    PAYMENT_WEBHOOK_SECRET: str = "dev_webhook_secret"

    # ─────────────────────────────────────────────────────────────────
    # Bootstrap admins
    # ─────────────────────────────────────────────────────────────────
    # Comma-separated list of emails. When a user with one of these
    # emails completes normal registration (verify-email), the system
    # automatically elevates them to Super Admin, provided they have
    # not been elevated before. Once elevated, the flag is sticky.
    BOOTSTRAP_ADMIN_EMAILS: str = ""

    @property
    def bootstrap_admin_email_list(self) -> list[str]:
        """Return the allowlist as a lowercase-stripped list."""
        if not self.BOOTSTRAP_ADMIN_EMAILS:
            return []
        return [
            e.strip().lower()
            for e in self.BOOTSTRAP_ADMIN_EMAILS.split(",")
            if e.strip()
        ]

    # ─────────────────────────────────────────────────────────────────
    # Legacy toggles (kept for backward compat)
    # ─────────────────────────────────────────────────────────────────
    SMS_ENABLED: bool = False

    # ────────────────────────────────────────────────────────────
    # Upload pipeline
    # ────────────────────────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_PAGES_PER_FILE: int = 100
    ALLOWED_UPLOAD_EXTENSIONS: str = "pdf,png,jpg,jpeg,docx,doc,pptx,ppt"

    # ────────────────────────────────────────────────────────────
    # Module 002 completion — approvals + verification
    # ────────────────────────────────────────────────────────────
    # Unit proposal escalation: every N minutes without a response
    # moves the proposal one level up the approval ladder.
    UNIT_PROPOSAL_ESCALATION_MINUTES: int = 120

    # Registration-number verification periods: default window in days
    # when a Super Admin initiates a period without specifying an end.
    REGISTRATION_VERIFICATION_DEFAULT_DAYS: int = 30


    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()