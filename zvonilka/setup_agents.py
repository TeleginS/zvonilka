"""Create the Retell voice agents once and print their ids for .env (spec 4.1).

    uv run zvonilka-setup-agents            # all languages without an id in .env
    uv run zvonilka-setup-agents es ru      # only these
    uv run zvonilka-setup-agents --force es # create even if an id is set
"""

from __future__ import annotations

import argparse
import os
import sys

import retell
from dotenv import load_dotenv
from retell import Retell

from zvonilka import robot
from zvonilka.config import LANGUAGES, RetellSettings


def create_llm(client: Retell, language: str, gender: str):
    try:
        return client.llm.create(**robot.llm_params(language, gender))
    except retell.BadRequestError as e:
        # Not every model offers the fast tier; fall back rather than fail.
        if "tier" not in str(e).lower() or robot.VOICES[language].llm_tier == "standard":
            raise
        print(f"[{language}] fast tier rejected ({e}); using standard", file=sys.stderr)
        return client.llm.create(**robot.llm_params(language, gender, tier="standard"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("languages", nargs="*", help="es, en, ru (default: all)")
    parser.add_argument("--force", action="store_true", help="create even if RETELL_AGENT_ID_<LANG> is set")
    args = parser.parse_args(argv)
    unknown = [lang for lang in args.languages if lang not in LANGUAGES]
    if unknown:
        parser.error(f"unknown languages: {', '.join(unknown)}; use {', '.join(LANGUAGES)}")

    load_dotenv()
    settings = RetellSettings.from_env(os.environ)
    if not settings.api_key:
        print("RETELL_API_KEY is not set", file=sys.stderr)
        return 1
    gender = os.environ.get("OWNER_GENDER", "").strip().lower()[:1]
    client = Retell(api_key=settings.api_key)

    created = []
    for language in args.languages or LANGUAGES:
        if settings.agent_ids.get(language) and not args.force:
            print(f"[{language}] RETELL_AGENT_ID_{language.upper()} is already set, skipping (use --force)")
            continue
        llm = create_llm(client, language, gender)
        agent = client.agent.create(**robot.agent_params(language, llm.llm_id))
        created.append(f"RETELL_AGENT_ID_{language.upper()}={agent.agent_id}")
        print(f"[{language}] created agent {agent.agent_id} (llm {llm.llm_id})")

    if created:
        print("\nAdd to .env:\n" + "\n".join(created))
    return 0


if __name__ == "__main__":
    sys.exit(main())
