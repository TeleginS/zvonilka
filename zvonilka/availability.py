"""The owner's free slots from Google Calendar (spec 7.1)."""

from __future__ import annotations

import logging
import time as monotonic_time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from zvonilka.config import GoogleSettings

log = logging.getLogger(__name__)

WORK_START = time(9, 0)
WORK_END = time(21, 0)
MIN_SLOT = timedelta(minutes=30)
DAYS = 14

Interval = tuple[datetime, datetime]


def _subtract(free: list[Interval], busy: Interval) -> list[Interval]:
    b0, b1 = busy
    result = []
    for f0, f1 in free:
        if b1 <= f0 or b0 >= f1:
            result.append((f0, f1))
            continue
        if b0 > f0:
            result.append((f0, b0))
        if b1 < f1:
            result.append((b1, f1))
    return result


def _ceil_quarter(moment: datetime) -> datetime:
    base = moment.replace(second=0, microsecond=0)
    if base < moment:
        base += timedelta(minutes=1)
    return base + timedelta(minutes=-base.minute % 15)


def free_slots(
    busy: Sequence[Interval], *, start_day: date, tz: ZoneInfo, now: datetime, days: int = DAYS
) -> list[tuple[date, list[Interval]]]:
    """Working window 09:00–21:00 minus busy time, slots of 30+ minutes,
    today's elapsed time counted as busy. Fully busy days are left out."""
    result = []
    local_now = now.astimezone(tz)
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        start = datetime.combine(day, WORK_START, tzinfo=tz)
        end = datetime.combine(day, WORK_END, tzinfo=tz)
        if local_now > start:
            start = _ceil_quarter(local_now)
        if start >= end:
            continue
        free = [(start, end)]
        for interval in busy:
            free = _subtract(free, interval)
        free = [(a, b) for a, b in free if b - a >= MIN_SLOT]
        if free:
            result.append((day, free))
    return result


def format_slots(slots: list[tuple[date, list[Interval]]], tz: ZoneInfo) -> str:
    lines = []
    for day, intervals in slots:
        spans = ", ".join(f"{a.astimezone(tz):%H:%M}–{b.astimezone(tz):%H:%M}" for a, b in intervals)
        lines.append(f"{day.isoformat()} ({day:%a}): {spans}")
    return "\n".join(lines)


class GoogleCalendar:
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"

    def __init__(self, settings: GoogleSettings, calendar_ids: Sequence[str], http: httpx.AsyncClient | None = None):
        self._settings = settings
        self._calendar_ids = list(calendar_ids)
        self._http = http or httpx.AsyncClient(timeout=15)
        self._token: str | None = None
        self._token_expires = 0.0

    async def _access_token(self) -> str:
        if self._token and monotonic_time.monotonic() < self._token_expires:
            return self._token
        response = await self._http.post(
            self.TOKEN_URL,
            data={
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "refresh_token": self._settings.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        self._token_expires = monotonic_time.monotonic() + int(data.get("expires_in", 3600)) - 60
        return self._token

    async def busy(self, time_min: datetime, time_max: datetime) -> list[Interval]:
        token = await self._access_token()
        response = await self._http.post(
            self.FREEBUSY_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "timeMin": time_min.astimezone(UTC).isoformat(),
                "timeMax": time_max.astimezone(UTC).isoformat(),
                "items": [{"id": calendar_id} for calendar_id in self._calendar_ids],
            },
        )
        response.raise_for_status()
        intervals = []
        for calendar_id, info in response.json().get("calendars", {}).items():
            if info.get("errors"):
                raise RuntimeError(f"calendar {calendar_id}: {info['errors']}")
            for slot in info.get("busy", []):
                intervals.append((_parse(slot["start"]), _parse(slot["end"])))
        return intervals


def _parse(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


class Availability:
    """Free slots as text for {{availability}}. Any calendar problem gives an
    empty string, never "the whole day is free", and never breaks the call."""

    def __init__(
        self,
        calendar: GoogleCalendar | None,
        tz: ZoneInfo,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._calendar = calendar
        self._tz = tz
        self._now = now

    async def __call__(self, availability_from: date | None = None) -> str:
        if self._calendar is None:
            return ""
        now = self._now()
        today = now.astimezone(self._tz).date()
        start_day = max(today, availability_from) if availability_from else today
        try:
            time_min = datetime.combine(start_day, time(0), tzinfo=self._tz)
            busy = await self._calendar.busy(time_min, time_min + timedelta(days=DAYS))
            return format_slots(free_slots(busy, start_day=start_day, tz=self._tz, now=now), self._tz)
        except Exception:
            log.warning("calendar unavailable, passing empty availability", exc_info=True)
            return ""
