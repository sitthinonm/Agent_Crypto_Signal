from pydantic import BaseModel
from dotenv import load_dotenv
import os


load_dotenv()


class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "dev")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    default_interval: str = os.getenv("DEFAULT_INTERVAL", "15m")
    default_limit: int = int(os.getenv("DEFAULT_LIMIT", "300"))
    binance_fapi_base_url: str = os.getenv("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com")


settings = Settings()
