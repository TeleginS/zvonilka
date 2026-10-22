"""Call scenarios: intake for the bot, playbook for the robot (spec 4.7, 5.5).

Each scenario is a file `scenarios/<name>.md`: YAML frontmatter with a one-line
description and the required place_call fields, then an `## Intake` section and
a `## Playbook` section. `general` is built in and has neither.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"
GRILLING_SKILL = REPO_ROOT / ".agents" / "skills" / "grilling" / "SKILL.md"

GENERAL = "general"

# The grilling skill is written for a coding agent; these rules adapt it to the
# bot and take priority over it (spec 5.5).
ADAPTATION_RULES = """\
- The design tree is the call brief, not an open-ended plan. Ask only about the
  required fields and the decisions listed in the scenario's intake, and not
  "relentlessly": usually one round, at most two.
- Facts come from the user's message, the owner's memory, and the calendar;
  never ask the user for them. You have no sub-agents; look facts up yourself.
- Keep the round format (❓ Q1 … ➡️ recommendation), in Russian, as plain text.
  A reply of «да» accepts all recommendations; the user can also answer single
  questions by number.
- The final "confirm we've reached a shared understanding" is the «Да / Нет»
  confirmation of place_call, which the system shows by itself. Don't ask for
  a separate text confirmation: once the round is answered, call place_call.
- If the user gave facts about themselves during intake (job, income, pets),
  after the call is placed offer in one line to save them with /memory.
"""


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    required_fields: dict[str, str] = field(default_factory=dict)
    intake: str = ""
    playbook: str = ""


GENERAL_SCENARIO = Scenario(name=GENERAL, description="every other call")


class ScenarioError(Exception):
    pass


class Scenarios:
    def __init__(self, scenarios: list[Scenario], grilling: str):
        self._by_name = {GENERAL: GENERAL_SCENARIO} | {s.name: s for s in scenarios}
        self._grilling = grilling

    @classmethod
    def load(cls, directory: Path = SCENARIOS_DIR, grilling_path: Path = GRILLING_SKILL) -> Scenarios:
        scenarios = [parse_scenario(path.stem, path.read_text()) for path in sorted(directory.glob("*.md"))]
        try:
            grilling = strip_frontmatter(grilling_path.read_text())
        except FileNotFoundError:
            log.warning("grilling skill not found at %s; intake uses the adaptation rules only", grilling_path)
            grilling = ""
        return cls(scenarios, grilling)

    @property
    def names(self) -> list[str]:
        return list(self._by_name)

    def get(self, name: str) -> Scenario:
        try:
            return self._by_name[name]
        except KeyError:
            raise ScenarioError(f"unknown scenario {name!r}; known: {', '.join(self._by_name)}") from None

    def catalog(self) -> str:
        """One line per scenario, for the system prompt."""
        return "\n".join(f"- {s.name}: {s.description}" for s in self._by_name.values())

    def guide(self, name: str) -> str:
        """What get_scenario_guide returns: method, adaptation, scenario intake."""
        scenario = self.get(name)
        if scenario.name == GENERAL:
            return "The general scenario has no intake: call place_call directly."
        parts = []
        if self._grilling:
            parts += ["# How to question the user (the grilling method)", self._grilling]
        parts += ["# Adaptation for this bot (these rules take priority)", ADAPTATION_RULES]
        parts += [f"# Scenario: {scenario.name}", scenario.intake]
        if scenario.required_fields:
            fields = "\n".join(f"- {key}: {desc}" for key, desc in scenario.required_fields.items())
            parts += ["# Required place_call.scenario_fields", fields]
        return "\n\n".join(p.strip() for p in parts if p.strip())


_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SECTION = re.compile(r"^##\s+(intake|playbook)\s*$", re.IGNORECASE | re.MULTILINE)


def strip_frontmatter(text: str) -> str:
    return _FRONTMATTER.sub("", text, count=1).strip()


def parse_scenario(name: str, text: str) -> Scenario:
    match = _FRONTMATTER.match(text)
    if not match:
        raise ScenarioError(f"scenario {name}: missing frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end():]
    sections: dict[str, str] = {}
    headers = list(_SECTION.finditer(body))
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        sections[header.group(1).lower()] = body[header.end():end].strip()
    required = meta.get("required_fields") or {}
    return Scenario(
        name=name,
        description=str(meta.get("description", "")).strip(),
        required_fields={str(k): str(v) for k, v in required.items()},
        intake=sections.get("intake", ""),
        playbook=sections.get("playbook", ""),
    )
