import asyncio

from tests.conftest import FakeLLM, FakeNotifier, FakeProvider, text, tool_use
from zvonilka.app import CALLING_REPLY, build_components
from zvonilka.config import Config
from zvonilka.retell_api import CallSnapshot

ENV = {
    "TELEGRAM_BOT_TOKEN": "123:abc",
    "ALLOWED_CHAT_IDS": "42",
    "TIMEZONE": "Europe/Madrid",
    "OWNER_NAME": "Sergei",
    "OWNER_PHONE": "+34600000000",
    "DEEPSEEK_API_KEY": "dk",
    "RETELL_API_KEY": "rk",
    "RETELL_FROM_NUMBER": "+15550000000",
    "RETELL_AGENT_ID_ES": "agent-es",
}

CALL_ARGS = {
    "business_name": "Can Solé",
    "to_number": "+34932215012",
    "language": "es",
    "objective": "Book a table for two",
    "details": "Tomorrow 21:00, name Sergei",
}


def config(tmp_path, **extra):
    return Config.from_env(ENV | {"DB_PATH": str(tmp_path / "z.db")} | extra)


async def test_message_to_report(tmp_path):
    provider = FakeProvider([
        CallSnapshot("ended", "agent_hangup", duration_ms=80_000, call_successful=True,
                     custom={"summary_ru": "Забронировали."}, analysis_ready=True),
    ])
    notifier = FakeNotifier()
    llm = FakeLLM([tool_use("place_call", CALL_ARGS), text("Звоню, отчёт пришлю отдельно.")])
    components = build_components(config(tmp_path), notifier, provider=provider, llm=llm)

    async def confirm(text):
        assert "Can Solé" in text
        return True

    reply = await components.assistant.handle(42, "позвони в Can Solé", confirm)
    assert reply == "Звоню, отчёт пришлю отдельно."
    assert llm.requests[1]["messages"][-1]["content"][0]["content"] == CALLING_REPLY
    for _ in range(20):
        if notifier.texts:
            break
        await asyncio.sleep(0.01)
    assert notifier.texts[0][1].startswith("✅ Готово")
    variables = provider.started[0]["variables"]
    assert variables["availability"] == ""  # no Google settings
    assert provider.started[0]["to_number"] == "+34932215012"


async def test_future_call_is_scheduled_not_dialed(tmp_path):
    provider = FakeProvider([CallSnapshot("ongoing")])
    llm = FakeLLM([tool_use("place_call", CALL_ARGS | {"when": "2099-01-01T18:00"}), text("Запланировал.")])
    components = build_components(config(tmp_path), FakeNotifier(), provider=provider, llm=llm)

    async def confirm(text):
        return True

    await components.assistant.handle(42, "позвони потом", confirm)
    assert provider.started == []
    assert llm.requests[1]["messages"][-1]["content"][0]["content"] == "Звонок запланирован на 01.01 18:00"
    assert len(components.scheduler.pending(42)) == 1


def test_without_retell_there_are_no_call_tools(tmp_path):
    env = {k: v for k, v in ENV.items() if not k.startswith("RETELL")}
    components = build_components(Config.from_env(env | {"DB_PATH": str(tmp_path / "z.db")}), FakeNotifier(), llm=FakeLLM([]))
    assert components.scheduler is None
    assert components.assistant._schemas == []


async def test_telegram_sends_retry_only_on_connection_errors():
    import pytest
    from telegram.error import BadRequest, NetworkError

    from zvonilka.bot import with_retries

    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise NetworkError("httpx.ConnectError")
        return "sent"

    assert await with_retries(flaky, delay=0) == "sent" and len(calls) == 3

    async def bad():
        calls.append(1)
        raise BadRequest("chat not found")

    calls.clear()
    with pytest.raises(BadRequest):
        await with_retries(bad, delay=0)
    assert len(calls) == 1


def test_telegram_application_builds(tmp_path):
    from zvonilka.bot import build_application, split_message

    app = build_application(config(tmp_path))
    assert app.bot_data["scheduler"] is not None
    assert split_message("a\n" * 3000, limit=4000)[0].endswith("a")
