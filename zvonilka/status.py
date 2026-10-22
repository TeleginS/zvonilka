"""Reduce Retell's three status fields to one status (spec 6.3)."""

from __future__ import annotations

from zvonilka.retell_api import CallSnapshot

ACTIVE = frozenset({"registered", "ongoing"})
NO_ANSWER_REASONS = frozenset({"dial_busy", "dial_failed", "dial_no_answer"})

# Retell sometimes marks a 3-second unanswered call successful and invents a summary.
TOO_SHORT_MS = 10_000


def normalize(call: CallSnapshot) -> str:
    if call.call_status == "error":
        return "failed"
    if call.call_status == "not_connected":
        return "no_answer"
    if call.call_status != "ended":
        return "in_progress"

    reason = call.disconnection_reason
    if call.in_voicemail or reason == "voicemail_reached":
        status = "voicemail"
    elif reason in NO_ANSWER_REASONS:
        status = "no_answer"
    elif reason == "max_duration_reached":
        status = "timeout"
    elif call.call_successful:
        status = "success"
    else:
        status = "completed"

    if status in ("success", "completed") and (call.duration_ms or 0) < TOO_SHORT_MS:
        return "too_short"
    return status
