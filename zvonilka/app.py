"""Wiring: build the assistant and its tools from the config."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from zvonilka.assistant import Assistant, Tool, system_prompt
from zvonilka.availability import Availability, GoogleCalendar
from zvonilka.calls import CallService, Notifier
from zvonilka.config import Config
from zvonilka.db import Database
from zvonilka.llm import LLM
from zvonilka.models import CallRequest
from zvonilka.retell_api import CallProvider, RetellProvider
from zvonilka.scenarios import GENERAL, ScenarioError, Scenarios
from zvonilka.scheduler import Scheduler
from zvonilka.tools import (
    confirmation_text,
    format_local,
    parse_place_call,
    place_call_schema,
    scenario_guide_schema,
)

SCHEDULED_REPLY = "Звонок запланирован на {when}"
CALLING_REPLY = "Звоню, отчёт пришлю отдельно"


def make_call_tools(
    calls: CallService,
    scheduler: Scheduler,
    scenarios: Scenarios,
    tz: ZoneInfo,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[Tool]:
    languages = calls.languages

    def prepare(args: dict) -> CallRequest:
        return parse_place_call(args, languages=languages, scenarios=scenarios, tz=tz, now=now())

    async def place_call(chat_id: int, req: CallRequest) -> str:
        if req.when:
            scheduler.schedule(chat_id, req)
            return SCHEDULED_REPLY.format(when=format_local(req.when, tz))
        # Returns as soon as the call is dialed; the report comes separately (spec 6.1).
        await calls.start_in_background(chat_id, req)
        return CALLING_REPLY

    async def get_scenario_guide(chat_id: int, args: dict) -> str:
        try:
            return scenarios.guide(str(args.get("scenario", "")))
        except ScenarioError as e:
            return f"Error: {e}"

    tools = [
        Tool(
            schema=place_call_schema(languages, scenarios),
            run=place_call,
            prepare=prepare,
            confirm_text=lambda req: confirmation_text(req, tz),
        )
    ]
    if any(name != GENERAL for name in scenarios.names):
        tools.append(Tool(schema=scenario_guide_schema(scenarios), run=get_scenario_guide))
    return tools


@dataclass
class Components:
    db: Database
    llm: LLM
    assistant: Assistant
    scheduler: Scheduler | None


def build_components(
    config: Config,
    notifier: Notifier,
    *,
    provider: CallProvider | None = None,
    llm: LLM | None = None,
    db: Database | None = None,
) -> Components:
    tz = config.owner.timezone
    db = db or Database(config.db_path)
    llm = llm or LLM(config.llm)
    scenarios = Scenarios.load()

    tools: list[Tool] = []
    scheduler = None
    catalog = None
    if config.retell.enabled:
        calendar = GoogleCalendar(config.google, config.owner.calendar_ids) if config.google.enabled else None
        calls = CallService(
            provider or RetellProvider(config.retell.api_key),
            config.retell,
            config.owner,
            scenarios,
            memory=db.get_memory,
            availability=Availability(calendar, tz),
            notifier=notifier,
        )
        scheduler = Scheduler(db, calls.run, notifier, tz)
        tools = make_call_tools(calls, scheduler, scenarios, tz)
        catalog = scenarios.catalog()

    def system() -> str:
        return system_prompt(catalog, config.owner, db.get_memory())

    assistant = Assistant(llm, db, tools, system=system, tz=tz)
    return Components(db=db, llm=llm, assistant=assistant, scheduler=scheduler)
