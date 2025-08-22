from __future__ import annotations

from datetime import datetime, timedelta

from telegram.ext import Application, ContextTypes
import logging

from ...infra import db
from ...infra.repos import JobsRepo

log = logging.getLogger(__name__)

async def cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    # Placeholder: could purge old audit/logs; for now just a heartbeat log
    log.debug("automation.cleanup_job tick")


def job_name(job_id: int) -> str:
    return f"job:{job_id}"


async def run_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data if context.job else None
    if not data:
        return
    job_id = data.get("job_id")
    if job_id is None:
        return
    async with db.SessionLocal() as s:  # type: ignore
        repo = JobsRepo(s)
        j = await repo.get(job_id)
        if not j:
            return
        # Skip if paused
        if isinstance(j.payload, dict) and j.payload.get("paused"):
            # For repeating jobs, advance run_at to the next tick for UI purposes
            if j.interval_sec:
                next_run = datetime.utcnow() + timedelta(seconds=j.interval_sec)
                await repo.update_next_run(job_id, next_run)
                await s.commit()
            log.info("automation.run_job paused id=%s kind=%s group=%s", j.id, j.kind, j.group_id)
            return
        # Execute
        log.info("automation.run_job executing id=%s kind=%s group=%s", j.id, j.kind, j.group_id)
        if j.kind == "announce":
            text = (j.payload or {}).get("text") or ""
            cp = (j.payload or {}).get("copy") or None
            album = (j.payload or {}).get("album_media") or None
            success = False
            try:
                if album and isinstance(album, list):
                    from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio
                    media = []
                    for i, it in enumerate(album):
                        t = it.get("type")
                        fid = it.get("file_id")
                        cap = it.get("caption") if i == 0 else None
                        if t == "photo":
                            media.append(InputMediaPhoto(media=fid, caption=cap))
                        elif t == "video":
                            media.append(InputMediaVideo(media=fid, caption=cap))
                        elif t == "document":
                            media.append(InputMediaDocument(media=fid, caption=cap))
                        elif t == "audio":
                            media.append(InputMediaAudio(media=fid, caption=cap))
                    if media:
                        await context.bot.send_media_group(j.group_id, media=media)
                        success = True
                elif cp and isinstance(cp, dict) and cp.get("chat_id") and cp.get("message_id"):
                    await context.bot.copy_message(chat_id=j.group_id, from_chat_id=cp["chat_id"], message_id=cp["message_id"])  # type: ignore[arg-type]
                    success = True
                else:
                    await context.bot.send_message(j.group_id, text)
                    success = True
            except Exception as e:
                log.exception("automation.announce failed id=%s: %s", j.id, e)
            # Notify scheduler once (if requested)
            if success and isinstance(j.payload, dict) and j.payload.get("notify"):
                n = j.payload.get("notify")
                try:
                    await context.bot.send_message(n.get("chat_id"), "✅ Announcement sent.")
                except Exception as e:
                    log.exception("automation.announce notify failed id=%s: %s", j.id, e)
                # Clear notify after first run
                try:
                    j.payload.pop("notify", None)
                    await repo.update_payload(j.id, j.payload)
                    await s.commit()
                except Exception as e:
                    log.exception("automation.announce notify cleanup failed id=%s: %s", j.id, e)
        elif j.kind == "rotate_pin":
            text = (j.payload or {}).get("text") or ""
            cp = (j.payload or {}).get("copy") or None
            unpin_prev = bool(j.payload.get("unpin_previous", True))
            last_pinned = j.payload.get("last_pinned")
            mid = None
            try:
                if cp and isinstance(cp, dict) and cp.get("chat_id") and cp.get("message_id"):
                    res = await context.bot.copy_message(chat_id=j.group_id, from_chat_id=cp["chat_id"], message_id=cp["message_id"])  # type: ignore[arg-type]
                    # PTB returns MessageId or Message; handle both
                    mid = getattr(res, "message_id", None)
                    if mid is None and isinstance(res, dict):
                        mid = res.get("message_id")
                else:
                    m = await context.bot.send_message(j.group_id, text)
                    mid = m.message_id
                await context.bot.pin_chat_message(j.group_id, message_id=mid, disable_notification=True)
                if unpin_prev and last_pinned:
                    try:
                        await context.bot.unpin_chat_message(j.group_id, message_id=last_pinned)
                    except Exception as e:
                        log.exception("automation.rotate_pin unpin failed id=%s: %s", j.id, e)
            except Exception as e:
                log.exception("automation.rotate_pin failed id=%s: %s", j.id, e)
            if mid:
                j.payload["last_pinned"] = mid
                async with db.SessionLocal() as s:  # type: ignore
                    await JobsRepo(s).update_payload(j.id, j.payload)
                    await s.commit()
        elif j.kind == "timed_unmute":
            uid = j.payload.get("user_id")
            if uid:
                try:
                    from ...core.utils import group_default_permissions
                    perms = await group_default_permissions(context, j.group_id)
                    await context.bot.restrict_chat_member(j.group_id, uid, permissions=perms)
                except Exception as e:
                    log.exception("automation.timed_unmute failed id=%s: %s", j.id, e)
        elif j.kind == "timed_unban":
            uid = j.payload.get("user_id")
            if uid:
                try:
                    await context.bot.unban_chat_member(j.group_id, uid, only_if_banned=True)
                except Exception as e:
                    log.exception("automation.timed_unban failed id=%s: %s", j.id, e)
        # Reschedule or delete
        if j.interval_sec:
            next_run = datetime.utcnow() + timedelta(seconds=j.interval_sec)
            await repo.update_next_run(job_id, next_run)
            await s.commit()
        else:
            await repo.delete(job_id)
            await s.commit()
            # Also cancel this job in queue
            jobs = context.job_queue.get_jobs_by_name(job_name(job_id))
            for jb in jobs:
                jb.schedule_removal()


def register_jobs(app: Application) -> None:
    # Run cleanup hourly
    app.job_queue.run_repeating(cleanup_job, interval=3600, first=10)


async def load_jobs(app: Application) -> None:
    # Schedule DB jobs at startup
    async with db.SessionLocal() as s:  # type: ignore
        from sqlalchemy import select
        from ...infra.models import Job

        rows = (await s.execute(select(Job))).scalars().all()
    now = datetime.utcnow()
    for j in rows:
        delay = max(0, int((j.run_at - now).total_seconds()))
        if j.interval_sec:
            app.job_queue.run_repeating(
                run_job, interval=j.interval_sec, first=delay or 1, name=job_name(j.id), data={"job_id": j.id}
            )
        else:
            app.job_queue.run_once(run_job, when=delay or 1, name=job_name(j.id), data={"job_id": j.id})
