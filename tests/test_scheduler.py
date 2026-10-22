import asyncio
from datetime import UTC, datetime, timedelta

from tests.conftest import TZ, FakeNotifier
from zvonilka.models import CallRequest
from zvonilka.scheduler import Scheduler


def req(when):
    return CallRequest("Can Solé", "+34932215012", "es", "Book", "", when=when)


def make(db, run_call=None, now=None):
    ran = []

    async def default_run(chat_id, request):
        ran.append((chat_id, request.business_name))

    notifier = FakeNotifier()
    scheduler = Scheduler(db, run_call or default_run, notifier, TZ, now=now or (lambda: datetime.now(UTC)))
    return scheduler, ran, notifier


async def test_scheduled_call_runs_on_time_and_is_marked_done(db):
    scheduler, ran, notifier = make(db)
    call_id = scheduler.schedule(5, req(datetime.now(UTC) + timedelta(milliseconds=50)))
    assert [job.id for job in scheduler.pending(5)] == [call_id]
    await asyncio.sleep(0.2)
    assert ran == [(5, "Can Solé")]
    assert db.get_scheduled(call_id).status == "done"
    assert scheduler.pending(5) == []


async def test_cancel(db):
    scheduler, ran, _ = make(db)
    call_id = scheduler.schedule(5, req(datetime.now(UTC) + timedelta(milliseconds=50)))
    assert scheduler.cancel(call_id)
    await asyncio.sleep(0.15)
    assert ran == [] and db.get_scheduled(call_id).status == "cancelled"
    assert not scheduler.cancel(call_id)


async def test_restore_rearms_future_and_marks_overdue_missed(db):
    now = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
    future_id = db.add_scheduled(1, now + timedelta(hours=1), req(now + timedelta(hours=1)))
    overdue_id = db.add_scheduled(1, now - timedelta(hours=1), req(now - timedelta(hours=1)))
    scheduler, ran, notifier = make(db, now=lambda: now)
    await scheduler.restore()
    assert db.get_scheduled(overdue_id).status == "missed"
    assert "⚠️ Пропущен запланированный звонок в Can Solé (на 23.10 11:00), бот был офлайн" == notifier.texts[0][1]
    assert db.get_scheduled(future_id).status == "pending"
    assert scheduler.cancel(future_id)


async def test_restore_runs_slightly_late_call(db):
    now = datetime.now(UTC)
    call_id = db.add_scheduled(1, now - timedelta(minutes=2), req(now - timedelta(minutes=2)))
    scheduler, ran, _ = make(db)
    await scheduler.restore()
    await asyncio.sleep(0.05)
    assert ran and db.get_scheduled(call_id).status == "done"


async def test_failed_call_is_reported(db):
    async def boom(chat_id, request):
        raise RuntimeError("retell down")

    scheduler, _, notifier = make(db, run_call=boom)
    call_id = scheduler.schedule(3, req(datetime.now(UTC) + timedelta(milliseconds=20)))
    await asyncio.sleep(0.15)
    assert db.get_scheduled(call_id).status == "failed"
    assert "Не удалось выполнить запланированный звонок" in notifier.texts[-1][1]
