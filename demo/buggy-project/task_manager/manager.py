"""
Core task management logic.

BUG: get_pending_tasks() uses the wrong status string in its filter condition,
causing it to return all tasks regardless of their status.
"""
from typing import List, Optional
from .models import Task


class TaskManager:
    """Manages a collection of tasks."""

    def __init__(self) -> None:
        self._tasks: List[Task] = []
        self._next_id: int = 1

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_task(self, title: str, description: str = "", priority: int = 2) -> Task:
        """Create and store a new task, returning it."""
        task = Task(
            id=self._next_id,
            title=title,
            description=description,
            priority=priority,
        )
        self._tasks.append(task)
        self._next_id += 1
        return task

    def complete_task(self, task_id: int) -> Optional[Task]:
        """Mark a task as completed. Returns the task or None if not found."""
        task = self.get_by_id(task_id)
        if task is not None:
            task.mark_completed()
        return task

    def start_task(self, task_id: int) -> Optional[Task]:
        """Move a task from pending to in_progress."""
        task = self.get_by_id(task_id)
        if task is not None:
            task.mark_in_progress()
        return task

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_by_id(self, task_id: int) -> Optional[Task]:
        """Return the task with the given id, or None."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    def get_all_tasks(self) -> List[Task]:
        """Return all tasks."""
        return list(self._tasks)

    def get_pending_tasks(self) -> List[Task]:
        """Return only tasks that have not been started or completed yet.

        NOTE: Intentional bug — the filter compares against "complete"
        instead of the correct status string "completed".  This means
        tasks whose status is "completed" are NOT excluded, so the method
        returns all tasks rather than just the pending ones.
        """
        return [t for t in self._tasks if t.status != "complete"]

    def get_completed_tasks(self) -> List[Task]:
        """Return only tasks that have been completed."""
        return [t for t in self._tasks if t.status == "completed"]

    def get_high_priority_tasks(self) -> List[Task]:
        """Return tasks with priority == 1 (high)."""
        return [t for t in self._tasks if t.is_high_priority()]

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a summary dict with counts by status."""
        return {
            "total": len(self._tasks),
            "pending": len(self.get_pending_tasks()),
            "completed": len(self.get_completed_tasks()),
            "high_priority": len(self.get_high_priority_tasks()),
        }
