"""Domain objects shared between the tool loop, calls, and the scheduler."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class CallRequest:
    """A validated call brief: the arguments of place_call after checks (spec 5.2)."""

    business_name: str
    to_number: str
    language: str
    objective: str
    details: str
    scenario: str = "general"
    scenario_fields: dict[str, str] = field(default_factory=dict)
    when: datetime | None = None
    availability_from: date | None = None

    def full_details(self) -> str:
        """Details for the robot, with the scenario's required fields spelled out."""
        if not self.scenario_fields:
            return self.details
        fields = "; ".join(f"{name}: {value}" for name, value in self.scenario_fields.items())
        return f"{self.details}\n{fields}" if self.details else fields

    def to_json(self) -> str:
        data = asdict(self)
        data["when"] = self.when.isoformat() if self.when else None
        data["availability_from"] = self.availability_from.isoformat() if self.availability_from else None
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> CallRequest:
        data = json.loads(raw)
        data["when"] = datetime.fromisoformat(data["when"]) if data.get("when") else None
        data["availability_from"] = (
            date.fromisoformat(data["availability_from"]) if data.get("availability_from") else None
        )
        return cls(**data)


@dataclass(frozen=True)
class ScheduledCall:
    id: int
    chat_id: int
    run_at: datetime  # aware, UTC
    status: str  # pending / started / done / failed / cancelled / missed
    request: CallRequest
