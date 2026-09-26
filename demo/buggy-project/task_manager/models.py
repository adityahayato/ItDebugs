"""
Data models for the Task Manager application.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Task:
    """Represents a single task in the task manager."""

    id: int
    title: str
    description: str
    status: str = "pending"       # "pending" | "in_progress" | "completed"
    priority: int = 2             # 1 = high, 2 = medium, 3 = low
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def is_high_priority(self) -> bool:
        return self.priority == 1

    def mark_in_progress(self) -> None:
        if self.status == "pending":
            self.status = "in_progress"

    def mark_completed(self) -> None:
        self.status = "completed"
        self.completed_at = datetime.now()

    def __repr__(self) -> str:  # pragma: no cover
        return f"Task(id={self.id}, title={self.title!r}, status={self.status!r})"
