from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./louf_ai.db"
    frontend_origins: str = "http://localhost:5173"
    cookie_secure: bool = False
    session_ttl_hours: int = 168
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout_seconds: float = 180
    storage_dir: str = "./storage"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_runtime_settings(self) -> "Settings":
        if self.session_ttl_hours < 1:
            raise ValueError("SESSION_TTL_HOURS must be at least 1.")
        if self.app_env.lower() == "production" and (
            self.secret_key == "development-only-change-me" or len(self.secret_key) < 32
        ):
            raise ValueError("Production requires a SECRET_KEY of at least 32 characters.")
        if self.app_env.lower() == "production" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true in production.")
        return self


settings = Settings()
