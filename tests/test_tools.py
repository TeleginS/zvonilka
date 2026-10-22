from datetime import date, datetime, timedelta

import pytest

from tests.conftest import NOW, TZ
from zvonilka.tools import ToolInputError, confirmation_text, parse_place_call

LANGS = ["es", "ru"]


def args(**overrides):
    base = {
        "business_name": "Can Solé",
        "to_number": "+34 932-21-50-12",
        "language": "es",
        "objective": "Book a table",
        "details": "Two people, tomorrow 21:00",
    }
    return base | overrides


def parse(scenarios, **overrides):
    return parse_place_call(args(**overrides), languages=LANGS, scenarios=scenarios, tz=TZ, now=NOW)


def test_valid_call_is_immediate_and_normalized(scenarios):
    req = parse(scenarios)
    assert req.to_number == "+34932215012"
    assert req.when is None and req.availability_from is None
    assert req.scenario == "general"


@pytest.mark.parametrize("when", [None, "", "now", "сейчас", "null"])
def test_absent_when_means_now(scenarios, when):
    assert parse(scenarios, when=when).when is None


def test_naive_when_is_in_owner_time_zone(scenarios):
    req = parse(scenarios, when="2026-10-23T18:00")
    assert req.when == datetime(2026, 10, 23, 18, 0, tzinfo=TZ)


def test_when_within_a_minute_is_immediate(scenarios):
    assert parse(scenarios, when=(NOW + timedelta(seconds=30)).isoformat()).when is None


def test_when_in_the_past_is_an_error(scenarios):
    with pytest.raises(ToolInputError, match="in the past"):
        parse(scenarios, when="2026-10-22T18:00")


def test_bad_inputs(scenarios):
    with pytest.raises(ToolInputError, match="E.164"):
        parse(scenarios, to_number="932215012")
    with pytest.raises(ToolInputError, match="no voice agent"):
        parse(scenarios, language="en")
    with pytest.raises(ToolInputError, match="ISO date-time"):
        parse(scenarios, when="tomorrow evening")
    with pytest.raises(ToolInputError, match="required"):
        parse(scenarios, objective="")


def test_double_zero_prefix(scenarios):
    assert parse(scenarios, to_number="0034932215012").to_number == "+34932215012"


def test_availability_from(scenarios):
    assert parse(scenarios, availability_from="2026-12-01").availability_from == date(2026, 12, 1)
    assert parse(scenarios, availability_from="").availability_from is None


def test_rental_requires_scenario_fields(scenarios):
    with pytest.raises(ToolInputError, match="listing, price, source"):
        parse(scenarios, scenario="rental_inquiry")
    req = parse(
        scenarios,
        scenario="rental_inquiry",
        scenario_fields={"listing": "ref 123", "price": "1400 €", "source": "Idealista", "extra": "x"},
    )
    assert req.scenario_fields == {"listing": "ref 123", "price": "1400 €", "source": "Idealista"}
    assert "listing: ref 123" in req.full_details()


def test_unknown_scenario(scenarios):
    with pytest.raises(ToolInputError, match="unknown scenario"):
        parse(scenarios, scenario="pizza")


def test_confirmation_text_shows_arguments(scenarios):
    text = confirmation_text(parse(scenarios, when="2026-10-23T18:00"), TZ)
    assert "place_call" in text
    assert "+34932215012" in text and "Язык: es" in text
    assert "Когда: 23.10 18:00" in text
