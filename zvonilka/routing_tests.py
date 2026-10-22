"""Routing tests against the real LLM API (spec 5.4).

Sends sample user messages through the real tool loop and checks which tool
call comes out. Nothing is dialed: place_call is intercepted before it runs.
Run after changing the provider, the model, or the tool descriptions:

    uv run zvonilka-routing-tests
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

from zvonilka.assistant import Assistant, Tool, system_prompt
from zvonilka.config import LLMSettings, OwnerProfile
from zvonilka.db import Database
from zvonilka.llm import LLM
from zvonilka.models import CallRequest
from zvonilka.scenarios import Scenarios
from zvonilka.tools import normalize_phone, parse_place_call, place_call_schema, scenario_guide_schema

LANGUAGES = ["es", "en", "ru"]
OWNER_PHONE = [""]  # filled from the config in run_all(), normalized to E.164


@dataclass
class Outcome:
    calls: list[CallRequest]
    guides: list[str]
    reply: str


Check = Callable[[Outcome, datetime], str | None]  # None = pass, text = why it failed


def one_call(check: Callable[[CallRequest, datetime], str | None] | None = None) -> Check:
    def run(out: Outcome, now: datetime) -> str | None:
        if len(out.calls) != 1:
            return f"expected one place_call, got {len(out.calls)}; reply: {out.reply[:120]!r}"
        return check(out.calls[0], now) if check else None

    return run


def no_call(out: Outcome, now: datetime) -> str | None:
    return f"expected no place_call, got {out.calls[0]}" if out.calls else None


def immediate(req: CallRequest, now: datetime) -> str | None:
    if req.when:
        return f"expected an immediate call, got when={req.when}"
    if req.availability_from:
        return f"expected no availability_from, got {req.availability_from}"
    return None


def scheduled_at(hour: int, days: int = 0) -> Callable[[CallRequest, datetime], str | None]:
    def check(req: CallRequest, now: datetime) -> str | None:
        if not req.when:
            return "expected `when`, got an immediate call"
        local = req.when.astimezone(now.tzinfo)
        expected_day = (now + timedelta(days=days)).date()
        if local.hour != hour or local.date() != expected_day:
            return f"expected {expected_day} {hour}:00, got {local:%Y-%m-%d %H:%M}"
        return None

    return check


def in_language(lang: str) -> Callable[[CallRequest, datetime], str | None]:
    return lambda req, now: None if req.language == lang else f"expected language {lang}, got {req.language}"


def rental(out: Outcome, now: datetime) -> str | None:
    if "rental_inquiry" not in out.guides:
        return f"expected get_scenario_guide(rental_inquiry), got {out.guides}"
    if any(c.scenario != "rental_inquiry" for c in out.calls):
        return "a place_call went out with a scenario other than rental_inquiry"
    return None


def rental_asks(out: Outcome, now: datetime) -> str | None:
    if out.calls:
        return "expected questions, not a call: the listing reference and address are missing"
    return None if "?" in out.reply else f"expected a question to the user, got {out.reply[:120]!r}"


CASES: list[tuple[str, Check]] = [
    ("позвони в ресторан Can Solé +34 932 21 50 12, забронируй столик на двоих на завтра в 21:00", one_call(immediate)),
    ("позвони сейчас в клинику Dexeus +34 932 27 47 00, узнай, работают ли они в субботу", one_call(immediate)),
    ("позвони прямо сейчас в пиццерию +34 931 11 22 33 и спроси, до скольки доставка", one_call(immediate)),
    ("забронируй столик в Disfrutar на 4 человек на субботу в 20:30, номер +34 933 48 68 96", one_call(immediate)),
    ("позвони мне на +34 611 223 344 и скажи привет", one_call(immediate)),
    ("позвони мне и напомни про встречу", one_call(lambda r, n: None if r.to_number == OWNER_PHONE[0] else f"expected the owner's phone, got {r.to_number}")),
    ("как меня зовут?", no_call),
    ("позвони в 18:00 в парикмахерскую +34 934 56 78 90, запиши меня на стрижку на пятницу", one_call(scheduled_at(18))),
    ("завтра в 10 утра позвони в автошколу +34 935 55 44 33 и спроси цену практических занятий", one_call(scheduled_at(10, days=1))),
    ("запиши меня к стоматологу на декабрь, клиника +34 932 00 11 22", one_call(lambda r, n: None if r.availability_from and r.availability_from.month == 12 else f"expected availability_from in December, got {r.availability_from}")),
    ("call the hotel +44 20 7946 0000 and ask whether they have a double room for November 3", one_call(in_language("en"))),
    ("позвони Ивану +34 612 345 678 по-русски и спроси, когда он вернёт книгу", one_call(in_language("ru"))),
    ("позвони агенту по квартире на Idealista, реф. 34567890, Carrer de Mallorca 250, 1400 € в месяц, +34 600 000 000", rental),
    ("позвони риелтору +34 600 111 222 по поводу квартиры", rental_asks),
    ("привет, как дела?", no_call),
    ("напомни мне купить молоко", no_call),
    ("сколько будет 17 умножить на 23?", no_call),
    ("какие у тебя есть команды?", no_call),
]


async def run_case(llm: LLM, scenarios: Scenarios, owner: OwnerProfile, text: str, now: datetime) -> Outcome:
    calls: list[CallRequest] = []
    guides: list[str] = []

    async def capture_call(chat_id: int, req: CallRequest) -> str:
        calls.append(req)
        return "Звоню, отчёт пришлю отдельно"

    async def guide(chat_id: int, args: dict) -> str:
        guides.append(str(args.get("scenario")))
        return scenarios.guide(str(args.get("scenario")))

    async def approve(text: str) -> bool:
        return True

    tools = [
        Tool(
            schema=place_call_schema(LANGUAGES, scenarios),
            run=capture_call,
            prepare=lambda args: parse_place_call(args, languages=LANGUAGES, scenarios=scenarios, tz=owner.timezone, now=now),
            confirm_text=lambda req: "",
        ),
        Tool(schema=scenario_guide_schema(scenarios), run=guide),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(f"{tmp}/routing.db")
        system = system_prompt(scenarios.catalog(), owner)
        assistant = Assistant(llm, db, tools, system=system, tz=owner.timezone, now=lambda: now)
        reply = await assistant.handle(1, text, approve)
        db.close()
    return Outcome(calls=calls, guides=guides, reply=reply)


async def run_all() -> int:
    load_dotenv()
    settings = LLMSettings.from_env(os.environ)
    owner = OwnerProfile.from_env(os.environ)
    OWNER_PHONE[0] = normalize_phone(owner.phone)
    llm = LLM(settings)
    scenarios = Scenarios.load()
    now = datetime.now(UTC).astimezone(owner.timezone).replace(hour=12, minute=0, second=0, microsecond=0)
    print(f"provider={settings.provider} model={settings.model}, simulated now {now:%Y-%m-%d %H:%M %Z}\n")

    failures = 0
    for text, check in CASES:
        try:
            outcome = await run_case(llm, scenarios, owner, text, now)
            problem = check(outcome, now)
        except Exception as e:
            problem = f"{type(e).__name__}: {e}"
        failures += problem is not None
        print(f"{'PASS' if problem is None else 'FAIL'}  {text}")
        if problem:
            print(f"      {problem}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


def main() -> int:
    return asyncio.run(run_all())


if __name__ == "__main__":
    sys.exit(main())
