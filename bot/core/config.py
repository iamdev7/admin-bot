from __future__ import annotations

from typing import List
import os
from pathlib import Path
from dotenv import load_dotenv

# Try to import from pydantic v2 first, then fall back to v1
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import field_validator
    PYDANTIC_V2 = True
except ImportError:
    from pydantic import BaseSettings, validator  # type: ignore
    PYDANTIC_V2 = False

# Load .env file explicitly
ENV_FILE_NAME = ".env"
env_path = Path(__file__).parent.parent.parent / ENV_FILE_NAME
load_dotenv(env_path, override=True)

if PYDANTIC_V2:
    class Settings(BaseSettings):
        BOT_TOKEN: str
        OWNER_IDS: List[int] = []
        DATABASE_URL: str = "sqlite+aiosqlite:///./data/bot.db"
        DEFAULT_LANG: str = "en"
        GEMINI_API_KEY: str = ""  # Optional, for AI Assistant feature

        @field_validator("OWNER_IDS", mode="before")
        @classmethod
        def parse_owner_ids(cls, v):  # type: ignore
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

        model_config = SettingsConfigDict(
            env_file=ENV_FILE_NAME,
            env_file_encoding="utf-8",
            extra="ignore",
        )
else:
    class Settings(BaseSettings):
        BOT_TOKEN: str
        OWNER_IDS: List[int] = []
        DATABASE_URL: str = "sqlite+aiosqlite:///./data/bot.db"
        DEFAULT_LANG: str = "en"
        GEMINI_API_KEY: str = ""  # Optional, for AI Assistant feature

        @validator("OWNER_IDS", pre=True)
        @classmethod
        def parse_owner_ids(cls, v):  # type: ignore
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
            env_file = ENV_FILE_NAME
            env_file_encoding = "utf-8"
            extra = "ignore"


# Force environment variables to be loaded
settings = Settings(
    BOT_TOKEN=os.getenv("BOT_TOKEN", ""),
    OWNER_IDS=os.getenv("OWNER_IDS", ""),
    DATABASE_URL=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/bot.db"),
    DEFAULT_LANG=os.getenv("DEFAULT_LANG", "en"),
    GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", "")
)
