"""Room rule domain model.

RFC-0001: Meeting room domain model and rule engine.
Rules express fixed, weekly, temporary, maintenance, and activity blocks that can prevent bookings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .common import RuleTimeWindow, RuleType, TargetType


@dataclass(slots=True)
class RoomRule:
    """A rule that can make a room or composite unavailable.

    RFC-0001: Fixed rules are part of the domain invariant and must not be
    deleted or overwritten by ordinary user configuration.
    """

    id: str
    target_type: TargetType
    target_id: str
    rule_type: RuleType
    match_key: str
    reason: str
    actor_id: str
    protected: bool = False
    time_windows: list[RuleTimeWindow] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def update_from(
        self,
        *,
        rule_type: RuleType | None = None,
        match_key: str | None = None,
        reason: str | None = None,
        time_windows: list[RuleTimeWindow] | None = None,
        updated_at: datetime,
    ) -> "RoomRule":
        """Return an updated copy while preserving rule identity."""

        old = RoomRule(
            id=self.id,
            target_type=self.target_type,
            target_id=self.target_id,
            rule_type=self.rule_type,
            match_key=self.match_key,
            reason=self.reason,
            actor_id=self.actor_id,
            protected=self.protected,
            time_windows=list(self.time_windows),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        if rule_type is not None:
            self.rule_type = rule_type
        if match_key is not None:
            self.match_key = match_key
        if reason is not None:
            self.reason = reason
        if time_windows is not None:
            self.time_windows = list(time_windows)
        self.updated_at = updated_at
        return old

    def matches(self, start_at: datetime, end_at: datetime) -> bool:
        """Return True when any rule time window overlaps the candidate window."""

        return any(window.matches(start_at, end_at) for window in self.time_windows)

    def to_summary(self) -> dict[str, object]:
        """Return a compact rule summary for domain responses."""

        return {
            "id": self.id,
            "target_type": self.target_type.value,
            "target_id": self.target_id,
            "rule_type": self.rule_type.value,
            "match_key": self.match_key,
            "reason": self.reason,
            "protected": self.protected,
        }
