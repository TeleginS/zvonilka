"""The voice provider behind a "start call / get status" interface (spec 14)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from retell import AsyncRetell


@dataclass(frozen=True)
class CallSnapshot:
    call_status: str  # registered / ongoing / ended / error / not_connected
    disconnection_reason: str | None = None
    duration_ms: int | None = None
    in_voicemail: bool | None = None
    call_successful: bool | None = None
    summary_en: str | None = None
    custom: dict = field(default_factory=dict)  # custom post-call analysis: summary_ru, facts_ru
    recording_url: str | None = None
    analysis_ready: bool = False


class CallProvider(Protocol):
    async def start_call(
        self, *, from_number: str, to_number: str, agent_id: str, variables: dict[str, str], metadata: dict
    ) -> str: ...

    async def get_call(self, call_id: str) -> CallSnapshot: ...


class RetellProvider:
    def __init__(self, api_key: str, client: AsyncRetell | None = None):
        self._client = client or AsyncRetell(api_key=api_key)

    async def start_call(
        self, *, from_number: str, to_number: str, agent_id: str, variables: dict[str, str], metadata: dict
    ) -> str:
        call = await self._client.call.create_phone_call(
            from_number=from_number,
            to_number=to_number,
            override_agent_id=agent_id,
            retell_llm_dynamic_variables=variables,
            metadata=metadata,
        )
        return call.call_id

    async def get_call(self, call_id: str) -> CallSnapshot:
        return snapshot_from_retell(await self._client.call.retrieve(call_id))


def snapshot_from_retell(call) -> CallSnapshot:
    analysis = getattr(call, "call_analysis", None)
    custom = dict(getattr(analysis, "custom_analysis_data", None) or {}) if analysis else {}
    ready = analysis is not None and bool(
        custom or getattr(analysis, "call_summary", None) or getattr(analysis, "call_successful", None) is not None
    )
    return CallSnapshot(
        call_status=call.call_status,
        disconnection_reason=getattr(call, "disconnection_reason", None),
        duration_ms=getattr(call, "duration_ms", None),
        in_voicemail=getattr(analysis, "in_voicemail", None) if analysis else None,
        call_successful=getattr(analysis, "call_successful", None) if analysis else None,
        summary_en=getattr(analysis, "call_summary", None) if analysis else None,
        custom=custom,
        recording_url=getattr(call, "recording_url", None),
        analysis_ready=ready,
    )
