"""Scheduled calls that survive a restart (spec 8)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from zvonilka.calls import Notifier
from zvonilka.db import Database
from zvonilka.models import CallRequest, ScheduledCall
from zvonilka.tools import format_local

log = logging.getLogger(__name__)

# How late a call may still go out (bot restart, machine sleep).
TOLERANCE = timedelta(minutes=5)

RunCall = Callable[[int, CallRequest], Awaitable[object]]


class Scheduler:
    def __init__(
        self,
        db: Database,
        run_call: RunCall,
        notifier: Notifier,
        tz: ZoneInfo,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._db = db
        self._run_call = run_call
        self._notifier = notifier
        self._tz = tz
        self._now = now
        self._timers: dict[int, asyncio.Task] = {}

    def schedule(self, chat_id: int, req: CallRequest) -> int:
        assert req.when is not None
        call_id = self._db.add_scheduled(chat_id, req.when, req)
        self._arm(call_id, req.when)
        return call_id

    def pending(self, chat_id: int) -> list[ScheduledCall]:
        return self._db.scheduled_by_status("pending", chat_id)

    def cancel(self, call_id: int) -> bool:
        job = self._db.get_scheduled(call_id)
        if job is None or job.status != "pending":
            return False
        timer = self._timers.pop(call_id, None)
        if timer:
            timer.cancel()
        self._db.set_scheduled_status(call_id, "cancelled")
        return True

    async def restore(self) -> None:
        """On startup: re-arm future calls, mark overdue ones missed."""
        for job in self._db.scheduled_by_status("pending"):
            if self._now() - job.run_at <= TOLERANCE:
                self._arm(job.id, job.run_at)
            else:
                await self._missed(job)

    def _arm(self, call_id: int, run_at: datetime) -> None:
        task = asyncio.create_task(self._fire(call_id, run_at))
        self._timers[call_id] = task
        task.add_done_callback(lambda _: self._timers.pop(call_id, None))

    async def _fire(self, call_id: int, run_at: datetime) -> None:
        delay = (run_at - self._now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        job = self._db.get_scheduled(call_id)
        if job is None or job.status != "pending":
            return
        if self._now() - job.run_at > TOLERANCE:
            await self._missed(job)
            return
        # "started" before dialing, so a restart mid-call can't dial twice.
        self._db.set_scheduled_status(call_id, "started")
        req = job.request
        try:
            await self._notifier.send_text(job.chat_id, f"📞 Запланированный звонок: звоню в {req.business_name}")
            await self._run_call(job.chat_id, req)
            self._db.set_scheduled_status(call_id, "done")
        except Exception as e:
            log.exception("scheduled call %s failed", call_id)
            self._db.set_scheduled_status(call_id, "failed")
            await self._notifier.send_text(
                job.chat_id, f"❌ Не удалось выполнить запланированный звонок в {req.business_name}: {e}"
            )

    async def _missed(self, job: ScheduledCall) -> None:
        self._db.set_scheduled_status(job.id, "missed")
        await self._notifier.send_text(
            job.chat_id,
            f"⚠️ Пропущен запланированный звонок в {job.request.business_name} "
            f"(на {format_local(job.run_at, self._tz)}), бот был офлайн",
        )
