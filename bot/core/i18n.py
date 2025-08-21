from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict
from importlib import resources

from telegram import Update


log = logging.getLogger(__name__)


class I18N:
    _messages: Dict[str, Dict[str, str]] = {}
    _group_lang: Dict[int, str] = {}

    @classmethod
    def load_locales(cls) -> None:
        # Load packaged locale files
        for lang in ("en", "ar"):
            try:
                with resources.open_text("bot.locales", f"{lang}.json", encoding="utf-8") as fh:
                    data = json.load(fh)
                cls._messages[lang] = data
            except Exception as e:  # pragma: no cover
                log.warning("Failed to load locale %s: %s", lang, e)

    @staticmethod
    def pick_lang(update: Update, fallback: str = "en") -> str:
        # Try per-user language code first
        lc = (update.effective_user and update.effective_user.language_code) or None
        # Group override takes precedence in group chats
        chat = update.effective_chat
        if chat and chat.type in {"group", "supergroup"}:
            gl = I18N._group_lang.get(chat.id)
            if gl in I18N._messages:
                return gl  # group override
        if lc:
            lc = lc.split("-")[0]
            if lc in I18N._messages:
                return lc
        return fallback if fallback in I18N._messages else "en"

    @classmethod
    def set_group_lang(cls, group_id: int, code: str) -> None:
        if code in cls._messages:
            cls._group_lang[group_id] = code

    @classmethod
    def get_group_lang(cls, group_id: int) -> str | None:
        return cls._group_lang.get(group_id)


def t(lang: str, key: str, **kwargs: Any) -> str:
    msg = I18N._messages.get(lang, {}).get(key)
    if msg is None:
        # fallback to English
        msg = I18N._messages.get("en", {}).get(key, key)
    try:
        return msg.format(**kwargs)
    except Exception:
        return msg
