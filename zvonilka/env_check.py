"""Which variables are set, without printing their values.

    python -m zvonilka.env_check            # .env in the current directory
    python -m zvonilka.env_check .env.aeza  # another file
    python -m zvonilka.env_check -          # only the process environment (in a container)
"""

from __future__ import annotations

import os
import sys

from dotenv import dotenv_values

from zvonilka.config import Config, ConfigError

GROUPS = {
    "Telegram": ["TELEGRAM_BOT_TOKEN", "ALLOWED_CHAT_IDS", "TIMEZONE"],
    "Bot LLM": ["LLM_PROVIDER", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "LLM_MODEL", "LLM_MEMORY_MODEL", "LLM_BASE_URL"],
    "Retell": ["RETELL_API_KEY", "RETELL_FROM_NUMBER", "RETELL_AGENT_ID_ES", "RETELL_AGENT_ID_EN", "RETELL_AGENT_ID_RU"],
    "Owner": ["OWNER_NAME", "OWNER_SURNAME", "OWNER_NAME_RU", "OWNER_SURNAME_RU", "OWNER_PHONE", "OWNER_GENDER"],
    "Google Calendar": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "GOOGLE_CALENDAR_IDS"],
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    source = args[0] if args else ".env"
    if source == "-":
        env = dict(os.environ)
    elif os.path.exists(source):
        env = {k: v or "" for k, v in dotenv_values(source).items()}
    else:
        print(f"{source} not found", file=sys.stderr)
        return 1

    print(f"Source: {'process environment' if source == '-' else source}\n")
    for group, names in GROUPS.items():
        print(group)
        for name in names:
            print(f"  {'✓' if env.get(name, '').strip() else '·'} {name}")
    print()

    try:
        config = Config.from_env(env)
    except ConfigError as e:
        print(f"✗ config: {e}")
        return 1
    print(f"✓ config ok: provider {config.llm.provider}, model {config.llm.model}")
    if config.retell.enabled:
        print(f"✓ calls enabled: {', '.join(config.retell.agent_ids)}")
    else:
        missing = [n for n in ("RETELL_API_KEY", "RETELL_FROM_NUMBER") if not env.get(n, "").strip()]
        if not config.retell.agent_ids:
            missing.append("RETELL_AGENT_ID_<LANG>")
        print(f"· calls disabled, missing: {', '.join(missing)}")
    print("✓ calendar enabled" if config.google.enabled else "· calendar disabled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
