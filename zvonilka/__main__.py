"""Run the bot: `uv run zvonilka` or `python -m zvonilka`."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from zvonilka.config import Config, ConfigError

log = logging.getLogger("zvonilka")


def main() -> int:
    load_dotenv()
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        config = Config.from_env()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    log.info("bot LLM: provider=%s model=%s memory_model=%s", config.llm.provider, config.llm.model, config.llm.memory_model)
    if config.retell.enabled:
        log.info("calls enabled for languages: %s", ", ".join(config.retell.agent_ids))
    else:
        log.warning("calls disabled: set RETELL_API_KEY, RETELL_FROM_NUMBER and at least one RETELL_AGENT_ID_<LANG>")
    if not config.google.enabled:
        log.info("calendar disabled: the robot will agree to times only tentatively")

    from zvonilka.bot import build_application

    build_application(config).run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
