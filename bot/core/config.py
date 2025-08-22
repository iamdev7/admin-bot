from __future__ import annotations

from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file explicitly
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path, override=True)

class Settings(BaseSettings):
    BOT_TOKEN: str
    OWNER_IDS: List[int] = []
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/bot.db"
    DEFAULT_LANG: str = "en"

    @field_validator("OWNER_IDS", mode="before")
    @classmethod
    def parse_owner_ids(cls, v):  # type: ignore[override]
        # Force read from environment if not provided
        if v in (None, "", []):
            v = os.getenv("OWNER_IDS", "")
        if not v:
            return []
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            result = [int(x.strip()) for x in v.split(",") if x.strip()]
            return result
        return []

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Force environment variables to be loaded
settings = Settings(
    BOT_TOKEN=os.getenv("BOT_TOKEN", ""),
    OWNER_IDS=os.getenv("OWNER_IDS", ""),
    DATABASE_URL=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/bot.db"),
    DEFAULT_LANG=os.getenv("DEFAULT_LANG", "en")
)

