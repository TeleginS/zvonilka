"""Tool definitions for the bot LLM and validation of their arguments (spec 5.2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from zvonilka.models import CallRequest
from zvonilka.scenarios import GENERAL, Scenarios


class ToolInputError(Exception):
    """Invalid tool arguments; the message goes back to the model as the tool result."""


LANGUAGE_NAMES = {"es": "Spanish (Spain)", "en": "English", "ru": "Russian"}

# Tuned wording: without "ONLY" / "DO NOT pass" the model scheduled calls "for
# now" and passed availability_from for every booking (spec 5.2).
WHEN_DESCRIPTION = (
    "ISO 8601 date-time in the owner's time zone. ONLY if the user explicitly named a future "
    "time ('at 18:00', 'tomorrow at 10', 'in an hour'). If the user said 'now' or named no time, "
    "DO NOT pass this field at all: the call goes out immediately."
)
AVAILABILITY_FROM_DESCRIPTION = (
    "ISO 8601 date: start of the period in which the booking is needed. ONLY if the booking is "
    "explicitly not for the near term ('book something in October' -> the 1st of October). "
    "Otherwise DO NOT pass this field."
)


def place_call_schema(languages: Sequence[str], scenarios: Scenarios) -> dict:
    scenario_lines = "; ".join(f"`{s}`: {scenarios.get(s).description}" for s in scenarios.names)
    return {
        "name": "place_call",
        "description": (
            "Phone a business (or a person) on the owner's behalf, now or at a given time. "
            "The voice robot only knows what you put in objective and details, so write them so "
            "a stranger could act on them. The system asks the owner to confirm every call with "
            "buttons; never ask for confirmation in text. For every scenario except `general`, "
            "call get_scenario_guide first and follow it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "business_name": {"type": "string", "description": "Name of the business or person."},
                "to_number": {"type": "string", "description": "Phone number in E.164 format, e.g. +34931234567."},
                "language": {
                    "type": "string",
                    "enum": list(languages),
                    "description": "Language of the conversation: "
                    + ", ".join(f"{lang} = {LANGUAGE_NAMES.get(lang, lang)}" for lang in languages),
                },
                "objective": {"type": "string", "description": "The goal of the call."},
                "details": {
                    "type": "string",
                    "description": "Details: date, time, number of people, name, what to ask.",
                },
                "when": {"type": "string", "description": WHEN_DESCRIPTION},
                "availability_from": {"type": "string", "description": AVAILABILITY_FROM_DESCRIPTION},
                "scenario": {
                    "type": "string",
                    "enum": scenarios.names,
                    "description": f"Call scenario: {scenario_lines}. Default `general`.",
                },
                "scenario_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Values of the scenario's required fields, as listed by "
                    "get_scenario_guide. Leave out for `general`.",
                },
            },
            "required": ["business_name", "to_number", "language", "objective", "details"],
        },
    }


def scenario_guide_schema(scenarios: Scenarios) -> dict:
    return {
        "name": "get_scenario_guide",
        "description": (
            "Load the instructions for a call scenario: what to ask the user before calling and "
            "which fields place_call needs. Call it before place_call for every scenario except "
            "`general`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scenario": {"type": "string", "enum": [s for s in scenarios.names if s != GENERAL]},
            },
            "required": ["scenario"],
        },
    }


_PHONE_JUNK = re.compile(r"[\s\-().]")
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
_NOT_PASSED = {"", "now", "none", "null", "immediately", "asap", "сейчас", "ahora"}

# A `when` this far in the past is a mistake to ask about, not "call now".
PAST_TOLERANCE = timedelta(minutes=5)
# Spec 5.2: schedule only if more than a minute ahead.
SCHEDULE_THRESHOLD = timedelta(minutes=1)


def _text(args: dict, key: str, *, required: bool = False) -> str:
    value = args.get(key)
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise ToolInputError(f"`{key}` is required")
    return value


def _absent(value) -> bool:
    return value is None or str(value).strip().lower() in _NOT_PASSED


def normalize_phone(raw: str) -> str:
    number = _PHONE_JUNK.sub("", raw)
    if number.startswith("00"):
        number = "+" + number[2:]
    if not _E164.match(number):
        raise ToolInputError(f"`to_number` {raw!r} is not an E.164 number like +34931234567")
    return number


def parse_when(raw, *, tz: ZoneInfo, now: datetime) -> datetime | None:
    """None means "call now". A naive time is in the owner's time zone (spec 8)."""
    if _absent(raw):
        return None
    try:
        when = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        raise ToolInputError(f"`when` {raw!r} is not an ISO date-time; leave it out to call now") from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=tz)
    if when < now - PAST_TOLERANCE:
        raise ToolInputError(
            f"`when` {when.isoformat()} is in the past; check the date with the user or leave it out to call now"
        )
    return when if when - now > SCHEDULE_THRESHOLD else None


def parse_availability_from(raw) -> date | None:
    if _absent(raw):
        return None
    text = str(raw).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise ToolInputError(f"`availability_from` {raw!r} is not an ISO date") from None


def parse_place_call(
    args: dict,
    *,
    languages: Sequence[str],
    scenarios: Scenarios,
    tz: ZoneInfo,
    now: datetime,
) -> CallRequest:
    language = _text(args, "language", required=True).lower()
    if language not in languages:
        raise ToolInputError(
            f"no voice agent for language {language!r}; available: {', '.join(languages)}"
        )
    scenario_name = _text(args, "scenario") or GENERAL
    try:
        scenario = scenarios.get(scenario_name)
    except Exception as e:
        raise ToolInputError(str(e)) from None

    raw_fields = args.get("scenario_fields") or {}
    if not isinstance(raw_fields, dict):
        raise ToolInputError("`scenario_fields` must be an object")
    fields = {str(k): str(v).strip() for k, v in raw_fields.items() if v is not None and str(v).strip()}
    missing = [key for key in scenario.required_fields if not fields.get(key)]
    if missing:
        raise ToolInputError(
            f"scenario {scenario.name} needs scenario_fields: {', '.join(missing)}. "
            "Ask the user for them before calling (see get_scenario_guide)."
        )

    return CallRequest(
        business_name=_text(args, "business_name", required=True),
        to_number=normalize_phone(_text(args, "to_number", required=True)),
        language=language,
        objective=_text(args, "objective", required=True),
        details=_text(args, "details"),
        scenario=scenario.name,
        scenario_fields={key: fields[key] for key in scenario.required_fields} if scenario.required_fields else {},
        when=parse_when(args.get("when"), tz=tz, now=now),
        availability_from=parse_availability_from(args.get("availability_from")),
    )


def confirmation_text(req: CallRequest, tz: ZoneInfo) -> str:
    """What the owner sees next to the «Да / Нет» buttons (spec 5.3)."""
    lines = [
        "📞 Подтверди звонок (place_call)",
        f"Куда: {req.business_name}, {req.to_number}",
        f"Язык: {req.language}",
        f"Цель: {req.objective}",
    ]
    if req.details:
        lines.append(f"Детали: {req.details}")
    if req.scenario != GENERAL:
        lines.append(f"Сценарий: {req.scenario}")
        lines += [f"  {key}: {value}" for key, value in req.scenario_fields.items()]
    lines.append(f"Когда: {format_local(req.when, tz)}" if req.when else "Когда: сейчас")
    if req.availability_from:
        lines.append(f"Свободные окна с: {req.availability_from.isoformat()}")
    return "\n".join(lines)


def format_local(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%d.%m %H:%M")
