"""
Test suite for the Task Manager application.

Most tests pass.  test_get_pending_tasks_excludes_completed() is the
canary that exposes the known bug in TaskManager.get_pending_tasks().
"""
import pytest
from task_manager.manager import TaskManager
from task_manager.models import Task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def manager() -> TaskManager:
    """Return a fresh TaskManager for each test."""
    return TaskManager()


@pytest.fixture()
def seeded_manager() -> TaskManager:
    """
    A TaskManager pre-populated with four tasks in different states:
      - task 1: completed  (Write unit tests)
      - task 2: in_progress (Fix login bug)
      - task 3: pending    (Update README)
      - task 4: pending    (Refactor DB layer)
    """
    m = TaskManager()
    t1 = m.add_task("Write unit tests", priority=1)
    t2 = m.add_task("Fix login bug", priority=1)
    t3 = m.add_task("Update README", priority=2)
    m.add_task("Refactor DB layer", priority=3)

    m.complete_task(t1.id)
    m.start_task(t2.id)
    _ = t3  # still pending

    return m


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

class TestAddTask:
    def test_add_task_returns_task_instance(self, manager):
        task = manager.add_task("My task")
        assert isinstance(task, Task)

    def test_add_task_sets_title(self, manager):
        task = manager.add_task("Buy groceries")
        assert task.title == "Buy groceries"

    def test_add_task_default_status_is_pending(self, manager):
        task = manager.add_task("Some task")
        assert task.status == "pending"

    def test_add_task_default_priority_is_medium(self, manager):
        task = manager.add_task("Some task")
        assert task.priority == 2

    def test_add_multiple_tasks_get_unique_ids(self, manager):
        t1 = manager.add_task("Task A")
        t2 = manager.add_task("Task B")
        assert t1.id != t2.id

    def test_all_tasks_count_increases(self, manager):
        manager.add_task("Task A")
        manager.add_task("Task B")
        assert len(manager.get_all_tasks()) == 2


# ---------------------------------------------------------------------------
# Task completion
# ---------------------------------------------------------------------------

class TestCompleteTask:
    def test_complete_task_changes_status(self, manager):
        task = manager.add_task("Deploy app")
        manager.complete_task(task.id)
        assert task.status == "completed"

    def test_complete_task_sets_completed_at(self, manager):
        task = manager.add_task("Deploy app")
        manager.complete_task(task.id)
        assert task.completed_at is not None

    def test_complete_nonexistent_task_returns_none(self, manager):
        result = manager.complete_task(999)
        assert result is None

    def test_completed_tasks_list(self, seeded_manager):
        completed = seeded_manager.get_completed_tasks()
        assert len(completed) == 1
        assert completed[0].title == "Write unit tests"


# ---------------------------------------------------------------------------
# Task start / in-progress
# ---------------------------------------------------------------------------

class TestStartTask:
    def test_start_task_changes_status_to_in_progress(self, manager):
        task = manager.add_task("Code review")
        manager.start_task(task.id)
        assert task.status == "in_progress"

    def test_start_nonexistent_task_returns_none(self, manager):
        result = manager.start_task(999)
        assert result is None


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestGetById:
    def test_get_existing_task(self, manager):
        task = manager.add_task("Existing task")
        found = manager.get_by_id(task.id)
        assert found is task

    def test_get_missing_task_returns_none(self, manager):
        assert manager.get_by_id(42) is None


# ---------------------------------------------------------------------------
# High-priority filtering
# ---------------------------------------------------------------------------

class TestHighPriorityTasks:
    def test_high_priority_returns_only_priority_1(self, seeded_manager):
        hp = seeded_manager.get_high_priority_tasks()
        assert all(t.priority == 1 for t in hp)

    def test_high_priority_count(self, seeded_manager):
        hp = seeded_manager.get_high_priority_tasks()
        assert len(hp) == 2  # "Write unit tests" and "Fix login bug"


# ---------------------------------------------------------------------------
# Pending tasks — THIS TEST EXPOSES THE BUG
# ---------------------------------------------------------------------------

class TestGetPendingTasks:
    def test_pending_tasks_excludes_completed(self, seeded_manager):
        """
        EXPECTED: get_pending_tasks() returns only tasks that are NOT
        yet completed (i.e. status != "completed").

        With the seeded_manager we have:
          - 1 completed task  → must NOT appear in pending list
          - 1 in_progress task
          - 2 pending tasks

        The method should return 3 tasks (in_progress + pending).

        BUG: The method compares against "complete" instead of "completed",
        so completed tasks are NOT filtered out and all 4 tasks are returned.
        This test will FAIL until the bug is fixed.
        """
        pending = seeded_manager.get_pending_tasks()

        # The completed task must not appear in the pending list
        titles = [t.title for t in pending]
        assert "Write unit tests" not in titles, (
            "Completed task 'Write unit tests' should NOT appear in pending list"
        )

        # Exactly 3 tasks should be returned (in_progress + 2 pending)
        assert len(pending) == 3, (
            f"Expected 3 pending/in-progress tasks, got {len(pending)}: {titles}"
        )

    def test_pending_tasks_empty_when_all_completed(self, manager):
        """
        When every task is completed, get_pending_tasks() must return [].

        BUG: Because the filter is broken, even a fully-completed task list
        returns all tasks instead of an empty list.
        This test will also FAIL until the bug is fixed.
        """
        t1 = manager.add_task("Alpha")
        t2 = manager.add_task("Beta")
        manager.complete_task(t1.id)
        manager.complete_task(t2.id)

        pending = manager.get_pending_tasks()
        assert pending == [], (
            f"Expected no pending tasks after completing all, got: {pending}"
        )

    def test_no_tasks_returns_empty_pending_list(self, manager):
        """Edge case: no tasks at all → pending list is empty (passes even with bug)."""
        assert manager.get_pending_tasks() == []


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_total_count(self, seeded_manager):
        s = seeded_manager.summary()
        assert s["total"] == 4

    def test_summary_completed_count(self, seeded_manager):
        s = seeded_manager.summary()
        assert s["completed"] == 1

    def test_summary_pending_count_reflects_bug(self, seeded_manager):
        """
        With the bug present, summary['pending'] will be 4 (all tasks),
        not the correct value of 3.  This assertion checks the CORRECT
        expected value and will FAIL while the bug exists.
        """
        s = seeded_manager.summary()
        assert s["pending"] == 3, (
            f"Expected pending=3 in summary, got {s['pending']}. "
            "This failure is caused by the bug in get_pending_tasks()."
        )
