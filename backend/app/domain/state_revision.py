"""State revision tracking.

RFC-0001: Meeting room domain model and rule engine.
Every successful write increments this lightweight single-process revision.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StateRevisionStore:
    """Monotonic state revision counter for local SQLite-style writes."""

    revision: int = 0

    def current(self) -> int:
        return self.revision

    def increment(self) -> int:
        self.revision += 1
        return self.revision
