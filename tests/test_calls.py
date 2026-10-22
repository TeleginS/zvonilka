import pytest

from tests.conftest import FakeNotifier, FakeProvider
from zvonilka.calls import CallService
from zvonilka.models import CallRequest
from zvonilka.retell_api import CallSnapshot

REQ = CallRequest("Can Solé", "+34932215012", "es", "Book a table", "Two people")


def service(provider, retell_settings, owner, scenarios, notifier, *, availability="", ceiling=60.0, attempts=3):
    async def availability_fn(start):
        return availability

    ticks = iter(range(10_000))
    return CallService(
        provider,
        retell_settings,
        owner,
        scenarios,
        memory=lambda: "Аллергия на орехи",
        availability=availability_fn,
        notifier=notifier,
        poll_interval=0,
        wait_ceiling=ceiling,
        analysis_attempts=attempts,
        clock=lambda: next(ticks),
    )


async def test_variables_for_spanish_and_russian(retell_settings, owner, scenarios):
    calls = service(FakeProvider(), retell_settings, owner, scenarios, FakeNotifier(), availability="2026-10-24 (Sat): 10:00–21:00")
    es = await calls.variables(REQ)
    assert es["caller_name"] == "Sergei" and es["caller_full_name"] == "Sergei Telegin"
    assert es["about_me"] == "Аллергия на орехи"
    assert es["availability"].startswith("2026-10-24")
    assert es["playbook"] == ""
    ru = await calls.variables(CallRequest("Иван", "+34612345678", "ru", "Спросить про книгу", ""))
    assert ru["caller_name"] == "Сергей" and ru["caller_full_name"] == "Сергей Телегин"


async def test_rental_playbook_and_fields_reach_the_robot(retell_settings, owner, scenarios):
    req = CallRequest(
        "Agencia", "+34600000000", "es", "Ask about the flat", "Long-term only",
        scenario="rental_inquiry", scenario_fields={"listing": "ref 1", "price": "1400 €", "source": "Idealista"},
    )
    variables = await service(FakeProvider(), retell_settings, owner, scenarios, FakeNotifier()).variables(req)
    assert "señal" in variables["playbook"]
    assert "listing: ref 1" in variables["details"]


async def test_full_lifecycle_waits_for_analysis_and_sends_report(retell_settings, owner, scenarios):
    provider = FakeProvider([
        CallSnapshot("registered"),
        CallSnapshot("ongoing"),
        CallSnapshot("ended", "agent_hangup", duration_ms=95_000),  # analysis not ready yet
        CallSnapshot(
            "ended", "agent_hangup", duration_ms=95_000, call_successful=True,
            custom={"summary_ru": "Столик забронирован."}, recording_url="https://x/rec.wav", analysis_ready=True,
        ),
    ])
    notifier = FakeNotifier()
    calls = service(provider, retell_settings, owner, scenarios, notifier)
    status = await calls.run(7, REQ)
    assert status == "success"
    assert provider.started[0]["agent_id"] == "agent-es"
    assert provider.started[0]["metadata"] == {"language": "es", "scenario": "general"}
    assert "Столик забронирован." in notifier.texts[0][1]
    assert notifier.recordings == [(7, "https://x/rec.wav")]


async def test_unanswered_call_doesnt_wait_for_analysis(retell_settings, owner, scenarios):
    provider = FakeProvider([CallSnapshot("not_connected")])
    notifier = FakeNotifier()
    assert await service(provider, retell_settings, owner, scenarios, notifier).run(1, REQ) == "no_answer"
    assert notifier.texts[0][1].startswith("📵")


async def test_timeout_when_call_never_ends(retell_settings, owner, scenarios):
    provider = FakeProvider([CallSnapshot("ongoing")])
    notifier = FakeNotifier()
    assert await service(provider, retell_settings, owner, scenarios, notifier, ceiling=5).run(1, REQ) == "timeout"
    assert notifier.texts[0][1].startswith("⏱")


async def test_polling_errors_are_retried(retell_settings, owner, scenarios):
    class Flaky(FakeProvider):
        failed = False

        async def get_call(self, call_id):
            if not self.failed:
                self.failed = True
                raise RuntimeError("network")
            return CallSnapshot("ended", "user_hangup", duration_ms=2_000, analysis_ready=True)

    notifier = FakeNotifier()
    assert await service(Flaky(), retell_settings, owner, scenarios, notifier).run(1, REQ) == "too_short"


@pytest.mark.parametrize("missing", ["en"])
async def test_agent_ids_by_language(retell_settings, owner, scenarios, missing):
    calls = service(FakeProvider(), retell_settings, owner, scenarios, FakeNotifier())
    assert missing not in calls.languages
