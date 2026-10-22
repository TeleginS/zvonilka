import pytest

from tests.conftest import FakeLLM, text
from zvonilka import robot
from zvonilka.config import Config, ConfigError, LLMSettings, RetellSettings
from zvonilka.memory import MemoryMergeError, clean_facts, merge_memory
from zvonilka.scenarios import parse_scenario

# Memory (spec 7.2)


async def test_merge_memory_uses_memory_model():
    llm = FakeLLM([text("- Аллергия на орехи\n2. Полис 12345")])
    assert await merge_memory(llm, "Аллергия на орехи", "номер полиса 12345") == "Аллергия на орехи\nПолис 12345"
    assert llm.requests[0]["model"] == "deepseek-flash"


@pytest.mark.parametrize("bad", ["", "   \n", "```\nfacts\n```", "x" * 400])
def test_clean_facts_rejects_non_lists(bad):
    with pytest.raises(MemoryMergeError):
        clean_facts(bad)


# Config (spec 9)

BASE_ENV = {
    "TELEGRAM_BOT_TOKEN": "t",
    "ALLOWED_CHAT_IDS": "1, 2",
    "TIMEZONE": "Europe/Madrid",
    "OWNER_NAME": "Sergei",
    "OWNER_PHONE": "+34600000000",
    "DEEPSEEK_API_KEY": "dk",
}


def test_config_defaults_to_deepseek():
    config = Config.from_env(BASE_ENV)
    assert config.allowed_chat_ids == {1, 2}
    assert config.llm.provider == "deepseek"
    assert config.llm.base_url == "https://api.deepseek.com/anthropic"
    assert config.llm.model == "deepseek-flash" and config.llm.disable_thinking
    assert not config.retell.enabled
    assert config.owner.calendar_ids == ("primary",)


def test_missing_provider_key_is_a_clear_error():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        LLMSettings.from_env(BASE_ENV | {"LLM_PROVIDER": "anthropic"})
    with pytest.raises(ConfigError, match="TIMEZONE"):
        Config.from_env(BASE_ENV | {"TIMEZONE": "Barcelona"})


def test_overrides_and_retell_enabled():
    env = BASE_ENV | {
        "LLM_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "ak",
        "LLM_MODEL": "m",
        "RETELL_API_KEY": "rk",
        "RETELL_FROM_NUMBER": "+1555",
        "RETELL_AGENT_ID_ES": "a",
    }
    config = Config.from_env(env)
    assert config.llm.model == "m" and not config.llm.disable_thinking
    assert config.retell.enabled and config.retell.agent_ids == {"es": "a"}
    assert not RetellSettings.from_env({"RETELL_API_KEY": "rk"}).enabled


# Robot settings (spec 4)


def test_agent_settings_follow_the_spec():
    params = robot.agent_params("es", "llm-1")
    assert params["end_call_after_silence_ms"] == params["max_call_duration_ms"] == 7_200_000
    assert params["reminder_trigger_ms"] == 30_000 and params["reminder_max_count"] == 1
    assert params["voice_id"] == "retell-Andrea" and "voice_model" not in params
    assert params["ambient_sound_volume"] == 1.5
    assert [f["name"] for f in params["post_call_analysis_data"]] == ["summary_ru", "facts_ru"]
    assert robot.agent_params("ru", "llm-2")["voice_model"] == "eleven_multilingual_v2"
    assert robot.agent_params("ru", "llm-2")["stt_mode"] == "accurate"


def test_prompt_has_the_rules_and_variables():
    prompt = robot.prompt("ru", "f")
    for variable in ["caller_name", "business_name", "objective", "details", "caller_full_name",
                     "caller_phone", "about_me", "availability", "playbook"]:
        assert "{{" + variable + "}}" in prompt
    assert "Speak only Russian." in prompt and "feminine" in prompt
    assert "AI assistant" in prompt and "SILENTLY" in prompt and "press_digit" in prompt
    tools = [t["type"] for t in robot.llm_params("es")["general_tools"]]
    assert tools == ["end_call", "press_digit"]
    assert robot.llm_params("es")["model_config"]["primary"]["tier"] == "fast"


# Scenarios (spec 4.7, 5.5)


def test_scenario_file_and_guide(scenarios):
    rental = scenarios.get("rental_inquiry")
    assert set(rental.required_fields) == {"listing", "price", "source"}
    assert "señal" in rental.playbook and "## Playbook" not in rental.intake
    guide = scenarios.guide("rental_inquiry")
    assert "design tree" in guide  # the grilling skill itself
    assert "these rules take priority" in guide
    assert "- listing:" in guide
    assert "general" in scenarios.catalog()


def test_parse_scenario_without_frontmatter_fails():
    from zvonilka.scenarios import ScenarioError

    with pytest.raises(ScenarioError):
        parse_scenario("x", "## Intake\nhi")
