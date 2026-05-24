from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Secrets only — normal config lives in database
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    gemini_api_key: str = ""
    database_url: str = "sqlite:///./hive.db"
    railway_api_key: str = ""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    @property
    def alpaca_configured(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
