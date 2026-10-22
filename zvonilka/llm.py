"""The one LLM client for both providers (spec 5.4).

DeepSeek is reached through its Anthropic-compatible endpoint, so both providers
speak the Messages API and differ only in base URL, key, model, and thinking.
Provider-specific code must stay in this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from anthropic import AsyncAnthropic

from zvonilka.config import LLMSettings


@dataclass
class LLMReply:
    blocks: list[dict]  # only "text" and "tool_use" blocks, as plain dicts
    stop_reason: str | None = None

    @property
    def text(self) -> str:
        return "".join(b["text"] for b in self.blocks if b["type"] == "text").strip()

    @property
    def tool_uses(self) -> list[dict]:
        return [b for b in self.blocks if b["type"] == "tool_use"]


class LLM:
    def __init__(self, settings: LLMSettings, client: AsyncAnthropic | None = None):
        self.settings = settings
        self._client = client or AsyncAnthropic(
            api_key=settings.api_key, base_url=settings.base_url, max_retries=2, timeout=60
        )

    async def create(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: Sequence[dict] = (),
        model: str | None = None,
        max_tokens: int = 1024,
    ) -> LLMReply:
        kwargs: dict = {
            "model": model or self.settings.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = list(tools)
        if self.settings.disable_thinking:
            # DeepSeek thinks by default; call parsing doesn't need it (spec 5.4).
            kwargs["thinking"] = {"type": "disabled"}
        message = await self._client.messages.create(**kwargs)
        blocks = [b for b in (_block_to_dict(block) for block in message.content) if b]
        return LLMReply(blocks=blocks, stop_reason=message.stop_reason)


def _block_to_dict(block) -> dict | None:
    if block.type == "text":
        return {"type": "text", "text": block.text} if block.text else None
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input or {})}
    return None
