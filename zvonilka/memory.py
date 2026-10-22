"""/memory: merge an instruction into the owner's list of facts (spec 7.2)."""

from __future__ import annotations

import re

from zvonilka.llm import LLM

MERGE_SYSTEM = (
    "You maintain a list of short facts about the owner of a personal assistant. Apply the "
    "instruction to the current list: add new facts, change facts the instruction updates, "
    "remove facts the instruction explicitly cancels, and keep every other fact unchanged. "
    "Return ONLY the updated list: one short fact per line, no numbering, no comments, no "
    "preamble. Keep each fact in the language it was written in."
)

MAX_FACTS = 200
MAX_FACT_LENGTH = 300
_BULLET = re.compile(r"^(?:[-*•]|\d+[.)])\s+")


class MemoryMergeError(Exception):
    pass


def clean_facts(text: str) -> str:
    """Reject answers that aren't a list of facts; the caller keeps the old memory."""
    if "```" in text:
        raise MemoryMergeError("the model returned formatted text instead of a list of facts")
    facts = [_BULLET.sub("", line.strip()) for line in text.strip().splitlines()]
    facts = [fact for fact in facts if fact]
    if not facts:
        raise MemoryMergeError("the model returned an empty list")
    if len(facts) > MAX_FACTS or any(len(fact) > MAX_FACT_LENGTH for fact in facts):
        raise MemoryMergeError("the model returned something that doesn't look like a list of short facts")
    return "\n".join(facts)


async def merge_memory(llm: LLM, current: str, instruction: str) -> str:
    prompt = f"Current list:\n{current.strip() or '(empty)'}\n\nInstruction:\n{instruction.strip()}"
    reply = await llm.create(
        system=MERGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        model=llm.settings.memory_model,
        max_tokens=2048,
    )
    return clean_facts(reply.text)
