from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    BASE_URL: str = "https://www.flikai.com/"

    # Outbound mail (RQ `send_invite_email`). Optional — omit both provider keys for log-only dev mode.
    MAIL_FROM_EMAIL: str | None = None
    MAIL_FROM_NAME: str = "Flik"
    SENDGRID_API_KEY: str | None = None
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True

    class Config:
        env_file = ".env"


settings = Settings()