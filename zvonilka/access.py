"""The single access check (spec 9). Multi-user access is planned in issue #1."""

from __future__ import annotations

from zvonilka.config import Config


def is_allowed(chat_id: int, config: Config) -> bool:
    return chat_id in config.allowed_chat_ids
