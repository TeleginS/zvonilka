"""The voice robot in Retell: prompt, tools, and agent settings, in code (spec 4).

`setup_agents` creates the agents from this module and `sync_agents` applies it
to existing ones. Change things here, then run sync.
"""

from __future__ import annotations

from dataclasses import dataclass

LANGUAGE_NAMES = {"es": "Spanish (Spain)", "en": "English", "ru": "Russian"}

# Conversation LLM inside Retell (billed by Retell). "fast" is the priority
# queue that cut latency from 2.3 to 1.7 s for es and en (spec 4.4).
RETELL_MODEL = "claude-5.5-sonnet"

TWO_HOURS_MS = 2 * 60 * 60 * 1000


@dataclass(frozen=True)
class Voice:
    language_code: str
    voice_id: str
    voice_model: str | None
    speed: float
    stt_mode: str
    ambient_volume: float
    llm_tier: str


# Tuned on test calls; a voice can only be chosen by listening (spec 4.4).
VOICES = {
    "es": Voice("es-ES", "retell-Andrea", None, 0.9, "fast", 1.5, "fast"),
    "en": Voice("en-US", "11labs-Lily", "eleven_v3", 1.0, "fast", 0.3, "fast"),
    "ru": Voice("ru-RU", "11labs-Lily", "eleven_multilingual_v2", 1.1, "accurate", 0.3, "standard"),
}

PROMPT = """\
## Who you are
You are {{caller_name}}'s assistant, calling on their behalf. Introduce yourself: "Hello, I'm \
{{caller_name}}'s assistant" (in the language of the call). If asked whether you are a human, \
honestly say you are an AI assistant.
Speak only __LANGUAGE__.__GENDER_NOTE__

## The call
You are calling {{business_name}}. Objective: {{objective}}. Details: {{details}}
Make the booking in the name of {{caller_full_name}}; if asked for a contact phone, give {{caller_phone}}.

## About the owner
{{about_me}}
Answer questions about the owner ONLY from this data. If you don't know something (date of \
birth, policy number, address), don't make it up; say you'll check and get back to them.

## The owner's free slots
{{availability}}
Propose and confirm only times from these slots. If they offer another time or the list is \
empty, agree tentatively and say you'll check the schedule and call back if it doesn't work.

## Rules
- When on hold (music, "all lines are busy", an answering system asking you to wait), stay on \
the line SILENTLY for as long as needed. NEVER hang up while waiting.
- If a phone menu asks you to press a digit, use the press_digit tool and pick the option that \
leads to a live person (reception, appointments, operator). If unsure, press 0 or wait.
- If they suggest writing an email, going to the website, or calling back later, DO NOT agree. \
Politely say you'd like to settle it now by phone, ask to be connected to someone who can help, \
or to be kept on the line.
- If you reach voicemail that only records a message (not a hold queue), don't leave a message; \
silently end the call.
- Don't hang up right after the greeting or before the other party has answered. If you didn't \
catch something, ask them to repeat; never end the call because of poor audio.
- Once the other party has confirmed the objective, say goodbye in ONE short phrase and \
immediately end the call with the end_call tool. Never say "ending the call" out loud. Don't \
drag out the goodbye, don't repeat thanks.
- Be brief and polite, confirm details. If there are no openings, ask for alternatives.

## Additional rules for this type of call (may be empty)
{{playbook}}
Where these additional rules conflict with the rules above, they take priority.
"""

GENDER_NOTES = {
    "f": " The owner is a woman: when you speak about her, use feminine grammatical forms.",
    "m": " The owner is a man: when you speak about him, use masculine grammatical forms.",
    "": "",
}

SUMMARY_RU = (
    "Краткое саммари разговора СТРОГО на русском (1–2 предложения): цель, чем закончилось, "
    "ключевые договорённости. Только по-русски, даже если разговор был на другом языке."
)
FACTS_RU = (
    "Конкретные факты, которые удалось узнать в разговоре, СТРОГО по-русски, по одному на строку: "
    "цены, даты и время, условия, требования, имена, о чём договорились дальше. Пусто, если ничего "
    "конкретного не узнали."
)


def prompt(language: str, gender: str = "") -> str:
    return PROMPT.replace("__LANGUAGE__", LANGUAGE_NAMES[language]).replace(
        "__GENDER_NOTE__", GENDER_NOTES.get(gender, "")
    )


def llm_params(language: str, gender: str = "", tier: str | None = None) -> dict:
    return {
        "general_prompt": prompt(language, gender),
        "general_tools": [
            {
                "type": "end_call",
                "name": "end_call",
                "description": "End the call once the objective is confirmed, or on a voicemail that only records messages.",
            },
            {
                "type": "press_digit",
                "name": "press_digit",
                "description": "Press a digit in a phone menu to reach a live person.",
            },
        ],
        "model_config": {
            "type": "cascading",
            "primary": {"model": RETELL_MODEL, "tier": tier or VOICES[language].llm_tier},
            "temperature": 0,
        },
        # The callee speaks first on an outbound call; start ourselves if they stay silent.
        "start_speaker": "user",
        "begin_after_user_silence_ms": 3000,
    }


def agent_params(language: str, llm_id: str) -> dict:
    voice = VOICES[language]
    params = {
        "agent_name": f"zvonilka-{language}",
        "response_engine": {"type": "retell-llm", "llm_id": llm_id},
        "voice_id": voice.voice_id,
        "voice_speed": voice.speed,
        "language": voice.language_code,
        "stt_mode": voice.stt_mode,
        # Hold music does not reset the silence timer: with the default the call
        # dropped after 15 s with reason `inactivity` (spec 4.4).
        "max_call_duration_ms": TWO_HOURS_MS,
        "end_call_after_silence_ms": TWO_HOURS_MS,
        "reminder_trigger_ms": 30_000,
        "reminder_max_count": 1,
        "ambient_sound": "coffee-shop",
        "ambient_sound_volume": voice.ambient_volume,
        "enable_backchannel": True,
        "backchannel_frequency": 0.3,
        "responsiveness": 1,
        "interruption_sensitivity": 0.6,
        "enable_expressive_mode": True,
        "enable_dynamic_voice_speed": False,
        "enable_dynamic_responsiveness": False,
        "post_call_analysis_data": [
            {"type": "string", "name": "summary_ru", "description": SUMMARY_RU},
            {"type": "string", "name": "facts_ru", "description": FACTS_RU, "required": False},
        ],
    }
    if voice.voice_model:
        params["voice_model"] = voice.voice_model
    return params
