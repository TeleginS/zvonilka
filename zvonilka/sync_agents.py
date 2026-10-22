"""Apply the prompt, model, voice, and settings from zvonilka/robot.py to the
existing Retell agents. Idempotent; run after every prompt change (spec 4.1).

    uv run zvonilka-sync-agents
"""

from __future__ import annotations

import os
import sys

import retell
from dotenv import load_dotenv
from retell import Retell

from zvonilka import robot
from zvonilka.config import RetellSettings


def sync_llm(client: Retell, llm_id: str, language: str, gender: str) -> None:
    try:
        client.llm.update(llm_id, **robot.llm_params(language, gender))
    except retell.BadRequestError as e:
        if "tier" not in str(e).lower() or robot.VOICES[language].llm_tier == "standard":
            raise
        print(f"[{language}] fast tier rejected ({e}); using standard", file=sys.stderr)
        client.llm.update(llm_id, **robot.llm_params(language, gender, tier="standard"))


def main() -> int:
    load_dotenv()
    settings = RetellSettings.from_env(os.environ)
    if not settings.api_key or not settings.agent_ids:
        print("RETELL_API_KEY and at least one RETELL_AGENT_ID_<LANG> must be set", file=sys.stderr)
        return 1
    gender = os.environ.get("OWNER_GENDER", "").strip().lower()[:1]
    client = Retell(api_key=settings.api_key)

    for language, agent_id in settings.agent_ids.items():
        agent = client.agent.retrieve(agent_id)
        llm_id = getattr(agent.response_engine, "llm_id", None)
        if not llm_id:
            print(f"[{language}] agent {agent_id} doesn't use a Retell LLM, skipping", file=sys.stderr)
            continue
        sync_llm(client, llm_id, language, gender)
        client.agent.update(agent_id, **robot.agent_params(language, llm_id))
        print(f"[{language}] synced agent {agent_id} (llm {llm_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
