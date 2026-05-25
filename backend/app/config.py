from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Secrets only — normal config lives in database
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    gemini_api_key: str = ""
    # Model IDs from Google AI — set in Railway/local .env when Google deprecates a version
    gemini_model: str = "gemini-2.0-flash"
    gemini_model_deep: str = ""
    database_url: str = "sqlite:///./hive.db"
    railway_api_key: str = ""
    operator_secret: str = ""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    def resolve_database_url(self) -> str:
        """Resolve relative sqlite paths against backend root (cwd-independent)."""
        url = self.database_url
        if url.startswith("sqlite:///./"):
            db_path = BACKEND_ROOT / url.removeprefix("sqlite:///./")
            return f"sqlite:///{db_path.as_posix()}"
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            # sqlite:///relative/path.db — also anchor to backend root
            rel = url.removeprefix("sqlite:///")
            if rel and not Path(rel).is_absolute():
                db_path = BACKEND_ROOT / rel
                return f"sqlite:///{db_path.as_posix()}"
        return url

    @property
    def alpaca_configured(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    def gemini_model_for(self, mode: str = "quick") -> str:
        """Resolve model: env GEMINI_MODEL / GEMINI_MODEL_DEEP, then defaults."""
        if mode == "deep" and self.gemini_model_deep.strip():
            return self.gemini_model_deep.strip()
        return self.gemini_model.strip() or "gemini-3.5-flash"

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
