from datetime import date, datetime

from tests.conftest import NOW, TZ
from zvonilka.availability import Availability, format_slots, free_slots


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def test_free_slots_subtract_busy_and_skip_short_gaps_and_full_days():
    busy = [
        (at(24, 12, 30), at(24, 15, 0)),
        (at(24, 15, 20), at(24, 16, 0)),  # leaves a 20-minute gap: dropped
        (at(25, 8, 0), at(25, 22, 0)),  # whole day busy: skipped
    ]
    slots = free_slots(busy, start_day=date(2026, 10, 24), tz=TZ, now=NOW, days=3)
    text = format_slots(slots, TZ)
    assert text == "2026-10-24 (Sat): 09:00–12:30, 16:00–21:00\n2026-10-26 (Mon): 09:00–21:00"


def test_today_elapsed_time_is_busy():
    now = datetime(2026, 10, 23, 14, 7, tzinfo=TZ)
    slots = free_slots([], start_day=date(2026, 10, 23), tz=TZ, now=now, days=1)
    assert format_slots(slots, TZ) == "2026-10-23 (Fri): 14:15–21:00"


def test_late_evening_has_no_slots_today():
    now = datetime(2026, 10, 23, 20, 45, tzinfo=TZ)
    assert free_slots([], start_day=date(2026, 10, 23), tz=TZ, now=now, days=1) == []


async def test_calendar_errors_give_empty_string():
    class Broken:
        async def busy(self, a, b):
            raise RuntimeError("token expired")

    assert await Availability(Broken(), TZ, now=lambda: NOW)() == ""
    assert await Availability(None, TZ, now=lambda: NOW)() == ""


async def test_availability_from_moves_the_window():
    seen = []

    class Calendar:
        async def busy(self, a, b):
            seen.append(a)
            return []

    text = await Availability(Calendar(), TZ, now=lambda: NOW)(date(2026, 12, 1))
    assert seen[0].date() == date(2026, 12, 1)
    assert text.startswith("2026-12-01 (Tue): 09:00–21:00")
