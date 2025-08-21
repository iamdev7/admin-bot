from __future__ import annotations

from datetime import datetime, timedelta

from telegram.ext import Application, ContextTypes

from ...infra import db
from ...infra.repos import JobsRepo


async def cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    # Placeholder for expiring warns/mutes cleanup
    pass


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
        # Execute
        if j.kind == "announce":
            text = j.payload.get("text") or ""
            try:
                await context.bot.send_message(j.group_id, text)
            except Exception:
                pass
        elif j.kind == "rotate_pin":
            text = j.payload.get("text") or ""
            unpin_prev = bool(j.payload.get("unpin_previous", True))
            last_pinned = j.payload.get("last_pinned")
            mid = None
            try:
                m = await context.bot.send_message(j.group_id, text)
                mid = m.message_id
                await context.bot.pin_chat_message(j.group_id, message_id=mid, disable_notification=True)
                if unpin_prev and last_pinned:
                    try:
                        await context.bot.unpin_chat_message(j.group_id, message_id=last_pinned)
                    except Exception:
                        pass
            except Exception:
                pass
            if mid:
                j.payload["last_pinned"] = mid
                async with db.SessionLocal() as s:  # type: ignore
                    await JobsRepo(s).update_payload(j.id, j.payload)
                    await s.commit()
        elif j.kind == "timed_unmute":
            uid = j.payload.get("user_id")
            if uid:
                try:
                    from telegram import ChatPermissions

                    await context.bot.restrict_chat_member(
                        j.group_id, uid, permissions=ChatPermissions(can_send_messages=True)
                    )
                except Exception:
                    pass
        elif j.kind == "timed_unban":
            uid = j.payload.get("user_id")
            if uid:
                try:
                    await context.bot.unban_chat_member(j.group_id, uid, only_if_banned=True)
                except Exception:
                    pass
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
