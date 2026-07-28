"""ActiveContext dataclass for cross-rail context tracking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActiveContext:
    """A single active context record."""

    topic: str
    summary: str
    rail: str
    updated_at: str  # ISO-8601
    turn_count: int

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "summary": self.summary,
            "rail": self.rail,
            "updated_at": self.updated_at,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ActiveContext:
        return cls(
            topic=data["topic"],
            summary=data["summary"],
            rail=data["rail"],
            updated_at=data["updated_at"],
            turn_count=data["turn_count"],
        )
