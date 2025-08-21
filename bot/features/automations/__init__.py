from __future__ import annotations

from telegram.ext import Application

from .handlers import register_jobs


def register(app: Application) -> None:
    register_jobs(app)

