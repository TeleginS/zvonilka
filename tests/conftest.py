from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from zvonilka.config import LLMSettings, OwnerProfile, RetellSettings
from zvonilka.db import Database
from zvonilka.llm import LLMReply
from zvonilka.retell_api import CallSnapshot
from zvonilka.scenarios import Scenarios

TZ = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=TZ)


class FakeLLM:
    """Returns scripted replies and records every request."""

    def __init__(self, replies: list[LLMReply]):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.settings = LLMSettings("deepseek", "k", None, "deepseek-flash", "deepseek-flash", True)

    async def create(self, **kwargs) -> LLMReply:
        # Copy messages: the loop keeps appending to the same list.
        self.requests.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        return self.replies.pop(0)


def text(t: str) -> LLMReply:
    return LLMReply(blocks=[{"type": "text", "text": t}])


def tool_use(name: str, args: dict, id_: str = "t1", say: str = "") -> LLMReply:
    blocks = [{"type": "text", "text": say}] if say else []
    blocks.append({"type": "tool_use", "id": id_, "name": name, "input": args})
    return LLMReply(blocks=blocks, stop_reason="tool_use")


class FakeProvider:
    def __init__(self, snapshots: list[CallSnapshot] | None = None):
        self.snapshots = list(snapshots or [])
        self.started: list[dict] = []

    async def start_call(self, **kwargs) -> str:
        self.started.append(kwargs)
        return f"call-{len(self.started)}"

    async def get_call(self, call_id: str) -> CallSnapshot:
        return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]


class FakeNotifier:
    def __init__(self):
        self.texts: list[tuple[int, str]] = []
        self.recordings: list[tuple[int, str]] = []

    async def send_text(self, chat_id: int, text: str) -> None:
        self.texts.append((chat_id, text))

    async def send_recording(self, chat_id: int, url: str, caption: str) -> None:
        self.recordings.append((chat_id, url))


@pytest.fixture
def owner() -> OwnerProfile:
    return OwnerProfile(
        name="Sergei",
        surname="Telegin",
        name_ru="Сергей",
        surname_ru="Телегин",
        phone="+34600000000",
        timezone=TZ,
        gender="",
        calendar_ids=("primary",),
    )


@pytest.fixture
def retell_settings() -> RetellSettings:
    return RetellSettings(api_key="k", from_number="+15550000000", agent_ids={"es": "agent-es", "ru": "agent-ru"})


@pytest.fixture
def scenarios() -> Scenarios:
    return Scenarios.load()


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)
