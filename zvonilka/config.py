"""Configuration from the environment: owner profile, bot LLM, Retell, Google."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LANGUAGES = ("es", "en", "ru")

# Provider defaults (spec 5.4). Model names change; check api-docs.deepseek.com.
PROVIDERS = {
    "deepseek": {
        "key_var": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-flash",
        "memory_model": "deepseek-flash",
        "disable_thinking": True,
    },
    "anthropic": {
        "key_var": "ANTHROPIC_API_KEY",
        "base_url": None,
        "model": "claude-sonnet-5-5",
        "memory_model": "claude-haiku-5-5",
        "disable_thinking": False,
    },
}


class ConfigError(Exception):
    pass


def _get(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def _require(env: Mapping[str, str], name: str) -> str:
    value = _get(env, name)
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


@dataclass(frozen=True)
class OwnerProfile:
    """Everything about the owner that the bot and the robot use (spec 9)."""

    name: str
    surname: str
    name_ru: str
    surname_ru: str
    phone: str
    timezone: ZoneInfo
    gender: str  # "f", "m" or "" if not specified
    calendar_ids: tuple[str, ...]

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> OwnerProfile:
        tz_name = _require(env, "TIMEZONE")
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ConfigError(f"TIMEZONE {tz_name!r} is not a valid time zone, e.g. Europe/Madrid") from e
        gender = _get(env, "OWNER_GENDER").lower()[:1]
        calendars = tuple(c.strip() for c in _get(env, "GOOGLE_CALENDAR_IDS").split(",") if c.strip())
        return cls(
            name=_require(env, "OWNER_NAME"),
            surname=_get(env, "OWNER_SURNAME"),
            name_ru=_get(env, "OWNER_NAME_RU"),
            surname_ru=_get(env, "OWNER_SURNAME_RU"),
            phone=_require(env, "OWNER_PHONE"),
            timezone=tz,
            gender=gender if gender in ("f", "m") else "",
            calendar_ids=calendars or ("primary",),
        )

    def caller_name(self, language: str) -> str:
        # TTS reads Latin script in Russian with the wrong stress (spec 4.2).
        if language == "ru" and self.name_ru:
            return self.name_ru
        return self.name

    def caller_full_name(self, language: str) -> str:
        if language == "ru" and self.name_ru:
            return f"{self.name_ru} {self.surname_ru}".strip()
        return f"{self.name} {self.surname}".strip()


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key: str
    base_url: str | None
    model: str
    memory_model: str
    disable_thinking: bool

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> LLMSettings:
        provider = (_get(env, "LLM_PROVIDER") or "deepseek").lower()
        if provider not in PROVIDERS:
            raise ConfigError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, got {provider!r}")
        defaults = PROVIDERS[provider]
        key_var = defaults["key_var"]
        api_key = _get(env, key_var)
        if not api_key:
            raise ConfigError(f"LLM_PROVIDER is {provider}, but {key_var} is not set")
        return cls(
            provider=provider,
            api_key=api_key,
            base_url=_get(env, "LLM_BASE_URL") or defaults["base_url"],
            model=_get(env, "LLM_MODEL") or defaults["model"],
            memory_model=_get(env, "LLM_MEMORY_MODEL") or defaults["memory_model"],
            disable_thinking=defaults["disable_thinking"],
        )


@dataclass(frozen=True)
class RetellSettings:
    api_key: str
    from_number: str
    agent_ids: dict[str, str]  # language -> agent id, only configured ones

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RetellSettings:
        agents = {lang: _get(env, f"RETELL_AGENT_ID_{lang.upper()}") for lang in LANGUAGES}
        return cls(
            api_key=_get(env, "RETELL_API_KEY"),
            from_number=_get(env, "RETELL_FROM_NUMBER"),
            agent_ids={lang: agent for lang, agent in agents.items() if agent},
        )

    @property
    def enabled(self) -> bool:
        # Spec 9: without these the place_call tool is not registered.
        return bool(self.api_key and self.from_number and self.agent_ids)


@dataclass(frozen=True)
class GoogleSettings:
    client_id: str
    client_secret: str
    refresh_token: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> GoogleSettings:
        return cls(
            client_id=_get(env, "GOOGLE_CLIENT_ID"),
            client_secret=_get(env, "GOOGLE_CLIENT_SECRET"),
            refresh_token=_get(env, "GOOGLE_REFRESH_TOKEN"),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)


@dataclass(frozen=True)
class Config:
    telegram_token: str
    allowed_chat_ids: frozenset[int]
    owner: OwnerProfile
    llm: LLMSettings
    retell: RetellSettings
    google: GoogleSettings
    db_path: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        return cls(
            telegram_token=_require(env, "TELEGRAM_BOT_TOKEN"),
            allowed_chat_ids=_parse_chat_ids(_require(env, "ALLOWED_CHAT_IDS")),
            owner=OwnerProfile.from_env(env),
            llm=LLMSettings.from_env(env),
            retell=RetellSettings.from_env(env),
            google=GoogleSettings.from_env(env),
            db_path=Path(_get(env, "DB_PATH") or "data/zvonilka.db"),
        )


def _parse_chat_ids(raw: str) -> frozenset[int]:
    try:
        return frozenset(int(part) for part in raw.split(",") if part.strip())
    except ValueError as e:
        raise ConfigError(f"ALLOWED_CHAT_IDS must be comma-separated numbers, got {raw!r}") from e
