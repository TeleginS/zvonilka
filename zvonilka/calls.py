"""Call lifecycle: start, poll, wait for analysis, report (spec 6)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Protocol

from zvonilka.config import OwnerProfile, RetellSettings
from zvonilka.models import CallRequest
from zvonilka.report import format_report
from zvonilka.retell_api import CallProvider, CallSnapshot
from zvonilka.scenarios import Scenarios
from zvonilka.status import ACTIVE, normalize

log = logging.getLogger(__name__)

POLL_INTERVAL = 5.0
# Slightly above Retell's 2-hour maximum call duration.
WAIT_CEILING = 2 * 3600 + 300
ANALYSIS_ATTEMPTS = 12


class Notifier(Protocol):
    async def send_text(self, chat_id: int, text: str) -> None: ...

    async def send_recording(self, chat_id: int, url: str, caption: str) -> None: ...


class CallService:
    def __init__(
        self,
        provider: CallProvider,
        retell: RetellSettings,
        owner: OwnerProfile,
        scenarios: Scenarios,
        memory: Callable[[], str],
        availability: Callable[[date | None], Awaitable[str]],
        notifier: Notifier,
        *,
        poll_interval: float = POLL_INTERVAL,
        wait_ceiling: float = WAIT_CEILING,
        analysis_attempts: int = ANALYSIS_ATTEMPTS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._provider = provider
        self._retell = retell
        self._owner = owner
        self._scenarios = scenarios
        self._memory = memory
        self._availability = availability
        self._notifier = notifier
        self._poll_interval = poll_interval
        self._wait_ceiling = wait_ceiling
        self._analysis_attempts = analysis_attempts
        self._clock = clock
        self._watchers: set[asyncio.Task] = set()

    @property
    def languages(self) -> list[str]:
        return list(self._retell.agent_ids)

    async def variables(self, req: CallRequest) -> dict[str, str]:
        """Dynamic variables for the robot's prompt (spec 4.5)."""
        return {
            "business_name": req.business_name,
            "objective": req.objective,
            "details": req.full_details(),
            "caller_name": self._owner.caller_name(req.language),
            "caller_full_name": self._owner.caller_full_name(req.language),
            "caller_phone": self._owner.phone,
            "about_me": self._memory(),
            "availability": await self._availability(req.availability_from),
            "playbook": self._scenarios.get(req.scenario).playbook,
        }

    async def start(self, req: CallRequest) -> str:
        return await self._provider.start_call(
            from_number=self._retell.from_number,
            to_number=req.to_number,
            agent_id=self._retell.agent_ids[req.language],
            variables=await self.variables(req),
            metadata={"language": req.language, "scenario": req.scenario},
        )

    async def start_in_background(self, chat_id: int, req: CallRequest) -> str:
        """Start the call and return right away; a background task reports (spec 6.1)."""
        call_id = await self.start(req)
        task = asyncio.create_task(self._watch_safely(chat_id, call_id, req.business_name))
        self._watchers.add(task)
        task.add_done_callback(self._watchers.discard)
        return call_id

    async def run(self, chat_id: int, req: CallRequest) -> str:
        """Start and watch to the end; used by scheduled calls (spec 8)."""
        call_id = await self.start(req)
        return await self.watch(chat_id, call_id, req.business_name)

    async def _watch_safely(self, chat_id: int, call_id: str, business_name: str) -> None:
        try:
            await self.watch(chat_id, call_id, business_name)
        except Exception as e:
            log.exception("watching call %s failed", call_id)
            await self._notifier.send_text(chat_id, f"⚠️ Потерял звонок в {business_name} ({call_id}): {e}")

    async def watch(self, chat_id: int, call_id: str, business_name: str) -> str:
        call, timed_out = await self._poll_until_done(call_id)
        if not timed_out and call.call_status == "ended" and (call.duration_ms or 0) > 0:
            call = await self._wait_for_analysis(call_id, call)
        status = "timeout" if timed_out else normalize(call)
        await self._notifier.send_text(chat_id, format_report(status, business_name, call))
        if call.recording_url:
            await self._notifier.send_recording(chat_id, call.recording_url, f"Запись: {business_name}")
        return status

    async def _poll_until_done(self, call_id: str) -> tuple[CallSnapshot, bool]:
        deadline = self._clock() + self._wait_ceiling
        call = CallSnapshot(call_status="registered")
        while True:
            try:
                call = await self._provider.get_call(call_id)
            except Exception:
                log.warning("polling call %s failed, retrying", call_id, exc_info=True)
            if call.call_status not in ACTIVE:
                return call, False
            if self._clock() >= deadline:
                return call, True
            await asyncio.sleep(self._poll_interval)

    async def _wait_for_analysis(self, call_id: str, call: CallSnapshot) -> CallSnapshot:
        # Retell computes the summary and success flag a few seconds after the end.
        for _ in range(self._analysis_attempts):
            if call.analysis_ready:
                break
            await asyncio.sleep(self._poll_interval)
            try:
                call = await self._provider.get_call(call_id)
            except Exception:
                log.warning("fetching analysis for %s failed", call_id, exc_info=True)
        return call
