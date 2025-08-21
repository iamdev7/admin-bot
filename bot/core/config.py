from __future__ import annotations

from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )
    
    BOT_TOKEN: str
    OWNER_IDS: List[int] = []
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/bot.db"
    DEFAULT_LANG: str = "en"

    @field_validator("OWNER_IDS", mode="before")
    @classmethod
    def parse_owner_ids(cls, v):  # type: ignore[override]
        if v in (None, "", []):
            return []
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []


settings = Settings()
