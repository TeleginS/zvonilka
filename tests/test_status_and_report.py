import pytest

from zvonilka.report import format_report
from zvonilka.retell_api import CallSnapshot
from zvonilka.status import normalize


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (CallSnapshot("error"), "failed"),
        (CallSnapshot("not_connected"), "no_answer"),
        (CallSnapshot("ongoing"), "in_progress"),
        (CallSnapshot("registered"), "in_progress"),
        (CallSnapshot("ended", duration_ms=60_000, in_voicemail=True, call_successful=True), "voicemail"),
        (CallSnapshot("ended", "voicemail_reached", duration_ms=60_000), "voicemail"),
        (CallSnapshot("ended", "dial_busy", duration_ms=0), "no_answer"),
        (CallSnapshot("ended", "dial_failed"), "no_answer"),
        (CallSnapshot("ended", "dial_no_answer"), "no_answer"),
        (CallSnapshot("ended", "max_duration_reached", duration_ms=7_200_000), "timeout"),
        (CallSnapshot("ended", "agent_hangup", duration_ms=60_000, call_successful=True), "success"),
        (CallSnapshot("ended", "user_hangup", duration_ms=60_000, call_successful=False), "completed"),
        # Under 10 s, "successful" and "completed" can't be trusted.
        (CallSnapshot("ended", "user_hangup", duration_ms=3_000, call_successful=True), "too_short"),
        (CallSnapshot("ended", "user_hangup", duration_ms=9_999), "too_short"),
        (CallSnapshot("ended", "user_hangup", duration_ms=10_000), "completed"),
    ],
)
def test_normalize(snapshot, expected):
    assert normalize(snapshot) == expected


def test_report_uses_russian_summary_and_facts():
    call = CallSnapshot(
        "ended",
        duration_ms=125_400,
        summary_en="Booked a table.",
        custom={"summary_ru": "Столик забронирован на 21:00.", "facts_ru": "- Столик на двоих\nНа имя Сергей\n"},
    )
    report = format_report("success", "Can Solé", call)
    assert report.startswith("✅ Готово\nCan Solé")
    assert "Столик забронирован на 21:00." in report
    assert "Booked a table." not in report
    assert "• Столик на двоих\n• На имя Сергей" in report
    assert "Длительность: 125 с" in report


def test_report_falls_back_to_english_summary_and_skips_empty_facts():
    call = CallSnapshot("ended", duration_ms=30_000, summary_en="No tables left.", custom={"facts_ru": "  "})
    report = format_report("completed", "Can Solé", call)
    assert "No tables left." in report
    assert "•" not in report
