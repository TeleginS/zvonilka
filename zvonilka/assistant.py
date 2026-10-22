"""The bot assistant: one tool loop over the Messages API (spec 5)."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from zvonilka.config import OwnerProfile
from zvonilka.db import Database
from zvonilka.llm import LLM
from zvonilka.tools import ToolInputError

log = logging.getLogger(__name__)

SESSION_TTL = timedelta(hours=2)
MAX_HISTORY = 40
MAX_STEPS = 8

# DeepSeek ignores `is_error`, so the meaning must be in the text (spec 5.3).
DECLINED = "The user declined this call. Do not call again unless the user asks."
NOT_ANSWERED = "The user did not confirm this call. Do not call again unless the user asks."

ConfirmFn = Callable[[str], Awaitable[bool | None]]  # True / False / None = no answer


@dataclass
class Tool:
    """A bot tool. `prepare` validates arguments before anything is shown to the user."""

    schema: dict
    run: Callable[[int, Any], Awaitable[str]]  # (chat_id, prepared args) -> result text
    prepare: Callable[[dict], Any] = lambda args: args
    confirm_text: Callable[[Any], str] | None = None  # set -> needs confirmation

    @property
    def name(self) -> str:
        return self.schema["name"]


def owner_section(owner: OwnerProfile, memory: str) -> str:
    names = f"{owner.name} {owner.surname}".strip()
    if owner.name_ru:
        names += f" (по-русски: {owner.name_ru} {owner.surname_ru}".rstrip() + ")"
    facts = memory.strip() or "(empty; the user can add facts with /memory)"
    return (
        "\nThe user you are talking to is the owner:\n"
        f"- name: {names}\n"
        f"- phone: {owner.phone} (when the user says 'call me', call this number)\n"
        f"- time zone: {owner.timezone.key}\n"
        "Facts about the owner from /memory:\n"
        f"{facts}\n"
        "Use this information; never ask the user for something that is already here.\n"
    )


def system_prompt(scenario_catalog: str | None, owner: OwnerProfile | None = None, memory: str = "") -> str:
    """Stable between requests so DeepSeek's prefix cache hits (spec 5.4): the
    owner section changes only after /memory, the current time goes into the
    user message."""
    base = (
        "You are the user's personal assistant in Telegram. Reply briefly, in Russian.\n\n"
        "Each user message starts with the current time and the owner's time zone in square "
        "brackets. Use them to turn relative times ('tomorrow at 10') into ISO date-times in "
        "that time zone.\n"
    )
    if owner is not None:
        base += owner_section(owner, memory)
    if scenario_catalog is None:
        return base + "\nPhone calls are not configured yet; say so if the user asks for a call.\n"
    return base + (
        "\nYou can phone businesses on the owner's behalf with place_call. The system shows the "
        "owner «Да / Нет» buttons for every call, so never ask 'should I call?' in text: call the "
        "tool once you have what you need. If a tool result says the user declined, don't call "
        "again unless asked. If a tool returns an error, fix the arguments or ask the user.\n\n"
        "Call scenarios:\n"
        f"{scenario_catalog}\n"
        "For every scenario except general, call get_scenario_guide first and follow it.\n"
    )


class Assistant:
    def __init__(
        self,
        llm: LLM,
        db: Database,
        tools: Sequence[Tool],
        *,
        system: str | Callable[[], str],
        tz: ZoneInfo,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._llm = llm
        self._db = db
        self._tools = {tool.name: tool for tool in tools}
        self._schemas = [tool.schema for tool in tools]
        # A callable is rebuilt per request, so /memory changes reach the next message.
        self._system = system if callable(system) else (lambda: system)
        self._tz = tz
        self._now = now
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def handle(self, chat_id: int, text: str, confirm: ConfirmFn) -> str:
        async with self._locks[chat_id]:
            messages = self._load(chat_id)
            messages.append({"role": "user", "content": self._stamp(text)})
            reply_text = ""
            system = self._system()
            try:
                for _ in range(MAX_STEPS):
                    reply = await self._llm.create(system=system, messages=messages, tools=self._schemas)
                    if reply.blocks:
                        messages.append({"role": "assistant", "content": reply.blocks})
                    reply_text = reply.text or reply_text
                    if not reply.tool_uses:
                        break
                    results = []
                    # The model may ask for several tools at once (spec 5.4).
                    for tool_use in reply.tool_uses:
                        content = await self._run_tool(chat_id, tool_use, confirm)
                        results.append({"type": "tool_result", "tool_use_id": tool_use["id"], "content": content})
                    messages.append({"role": "user", "content": results})
                    reply_text = ""
            finally:
                close_dangling_tool_uses(messages)
                self._db.save_session(chat_id, trim_history(messages), self._now())
            return reply_text or "Готово."

    async def _run_tool(self, chat_id: int, tool_use: dict, confirm: ConfirmFn) -> str:
        tool = self._tools.get(tool_use["name"])
        if tool is None:
            return f"Error: unknown tool {tool_use['name']!r}"
        try:
            prepared = tool.prepare(tool_use.get("input") or {})
        except ToolInputError as e:
            return f"Error: {e}"
        if tool.confirm_text is not None:
            answer = await confirm(tool.confirm_text(prepared))
            if answer is None:
                return NOT_ANSWERED
            if not answer:
                return DECLINED
        try:
            return await tool.run(chat_id, prepared)
        except Exception as e:
            log.exception("tool %s failed", tool.name)
            return f"Error: {tool.name} failed: {e}"

    def _load(self, chat_id: int) -> list[dict]:
        messages, updated_at = self._db.load_session(chat_id)
        if updated_at is None or self._now() - updated_at > SESSION_TTL:
            return []
        return messages

    def _stamp(self, text: str) -> str:
        local = self._now().astimezone(self._tz)
        return f"[{local:%Y-%m-%d %H:%M} ({local:%a}), {self._tz.key}]\n{text}"


def close_dangling_tool_uses(messages: list[dict]) -> None:
    """If the loop broke between a tool_use and its result, add the missing
    results; otherwise every later request in this session is rejected."""
    if not messages or messages[-1]["role"] != "assistant":
        return
    ids = [b["id"] for b in messages[-1]["content"] if b["type"] == "tool_use"]
    if ids:
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": i, "content": "Error: interrupted"} for i in ids],
        })


def _is_plain_user(message: dict) -> bool:
    return message["role"] == "user" and isinstance(message["content"], str)


def trim_history(messages: list[dict], limit: int = MAX_HISTORY) -> list[dict]:
    """Drop the oldest turns, cutting only at a plain user message so that
    tool_use / tool_result pairs stay together."""
    if len(messages) <= limit:
        return messages
    starts = [i for i, m in enumerate(messages) if _is_plain_user(m)]
    for i in starts:
        if len(messages) - i <= limit:
            return messages[i:]
    return messages[starts[-1]:] if starts else []
