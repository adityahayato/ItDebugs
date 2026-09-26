========================================================================
  ItDebugs - Investigation Report
========================================================================
  Generated : 2026-09-26 01:23:59
  Repository: C:\Users\ASUS\Desktop\IBM Bob 2.0 Hackathon\demo\buggy-project


------------------------------------------------------------------------
  BUG REPORT
------------------------------------------------------------------------

  Completed tasks are appearing in the pending task list.


------------------------------------------------------------------------
  REPOSITORY STRUCTURE
------------------------------------------------------------------------

  buggy-project/
  +-- task_manager
  |   +-- __init__.py
  |   +-- cli.py
  |   +-- manager.py
  |   +-- models.py
  +-- tests
  |   +-- __init__.py
  |   +-- test_task_manager.py
  +-- README.md
  +-- requirements.txt

  Relevant source files:
  - task_manager\cli.py
  - task_manager\manager.py
  - task_manager\models.py
  - task_manager\__init__.py
  - tests\__init__.py

  Test files:
  - tests\test_task_manager.py


------------------------------------------------------------------------
  TEST EXECUTION RESULTS
------------------------------------------------------------------------

  Total tests  : 22
  Passed       : 19
  Failed/Error : 3

  Failing tests:
    FAIL: tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_excludes_completed
    FAIL: tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_empty_when_all_completed
    FAIL: tests/test_task_manager.py::TestSummary::test_summary_pending_count_reflects_bug

  Failure details:

    tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_excludes_completed
    tests\test_task_manager.py:169: in test_pending_tasks_excludes_completed
        assert "Write unit tests" not in titles, (
    E   AssertionError: Completed task 'Write unit tests' should NOT appear in pending list
    E   assert 'Write unit tests' not in ['Write unit tests', 'Fix login bug', 'Update README', 'Refactor DB layer']

    tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_empty_when_all_completed
    tests\test_task_manager.py:192: in test_pending_tasks_empty_when_all_completed
        assert pending == [], (
    E   AssertionError: Expected no pending tasks after completing all, got: [Task(id=1, title='Alpha', status='completed'), Task(id=2, title='Beta', status='completed')]
    E   assert [Task(id=1, t...='completed')] == []
    E     
    E     Left contains 2 more items, first extra item: Task(id=1, title='Alpha', status='completed')
    E     
    E     Full diff:
    E     - []
    E     + [
    E     +     Task(id=1, title='Alpha', status='completed'),
    E     +     Task(id=2, title='Beta', status='completed'),
    E     + ]

    tests/test_task_manager.py::TestSummary::test_summary_pending_count_reflects_bug
    tests\test_task_manager.py:221: in test_summary_pending_count_reflects_bug
        assert s["pending"] == 3, (
    E   AssertionError: Expected pending=3 in summary, got 4. This failure is caused by the bug in get_pending_tasks().
    E   assert 4 == 3
    =========================== short test summary info ===========================
    FAILED tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_excludes_completed
    FAILED tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_empty_when_all_completed
    FAILED tests/test_task_manager.py::TestSummary::test_summary_pending_count_reflects_bug
    ======================== 3 failed, 19 passed in 0.07s =========================


------------------------------------------------------------------------
  EVIDENCE DISCOVERED
------------------------------------------------------------------------

  [1] FAILING_TEST — tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_excludes_completed
      Test `test_pending_tasks_excludes_completed` FAILED

      tests\test_task_manager.py:169: in test_pending_tasks_excludes_completed
          assert "Write unit tests" not in titles, (
      E   AssertionError: Completed task 'Write unit tests' should NOT appear in pending list
      E   assert 'Write unit tests' not in ['Write unit tests', 'Fix login bug', 'Update README', 'Refactor DB layer']

  [2] FAILING_TEST — tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_empty_when_all_completed
      Test `test_pending_tasks_empty_when_all_completed` FAILED

      tests\test_task_manager.py:192: in test_pending_tasks_empty_when_all_completed
          assert pending == [], (
      E   AssertionError: Expected no pending tasks after completing all, got: [Task(id=1, title='Alpha', status='completed'), Task(id=2, title='Beta', status='completed')]
      E   assert [Task(id=1, t...='completed')] == []
      E     
      E     Left contains 2 more items, first extra item: Task(id=1, title='Alpha', status='completed')
      E     
      E     Full diff:
      E     - []
      E     + [
      E     +     Task(id=1, title='Alpha', status='completed'),
      E     +     Task(id=2, title='Beta', status='completed'),
      E     + ]

  [3] FAILING_TEST — tests/test_task_manager.py::TestSummary::test_summary_pending_count_reflects_bug
      Test `test_summary_pending_count_reflects_bug` FAILED

      tests\test_task_manager.py:221: in test_summary_pending_count_reflects_bug
          assert s["pending"] == 3, (
      E   AssertionError: Expected pending=3 in summary, got 4. This failure is caused by the bug in get_pending_tasks().
      E   assert 4 == 3
      =========================== short test summary info ===========================
      FAILED tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_excludes_completed
      FAILED tests/test_task_manager.py::TestGetPendingTasks::test_pending_tasks_empty_when_all_completed
      FAILED tests/test_task_manager.py::TestSummary::test_summary_pending_count_reflects_bug
      ======================== 3 failed, 19 passed in 0.07s =========================

  [4] GREP_MATCH — task_manager\cli.py:14
      Keyword 'Write unit tests' found in source code

          t1 = manager.add_task("Write unit tests", "Cover all edge cases", priority=1)

  [5] GREP_MATCH — task_manager\cli.py:15
      Keyword 'Fix login bug' found in source code

          t2 = manager.add_task("Fix login bug", "Users are logged out unexpectedly", priority=1)

  [6] GREP_MATCH — task_manager\cli.py:16
      Keyword 'Update README' found in source code

          t3 = manager.add_task("Update README", "Document new CLI flags", priority=2)

  [7] GREP_MATCH — task_manager\cli.py:17
      Keyword 'Refactor DB layer' found in source code

          t4 = manager.add_task("Refactor DB layer", "Reduce query duplication", priority=3)

  [8] GREP_MATCH — task_manager\cli.py:29
      Keyword 'completed' found in source code

          print(f"Completed tasks: {len(manager.get_completed_tasks())}")

  [9] GREP_MATCH — task_manager\manager.py:35
      Keyword 'completed' found in source code

              """Mark a task as completed. Returns the task or None if not found."""

  [10] GREP_MATCH — task_manager\manager.py:38
      Keyword 'completed' found in source code

                  task.mark_completed()

  [11] GREP_MATCH — task_manager\manager.py:64
      Keyword 'completed' found in source code

              """Return only tasks that have not been started or completed yet.

  [12] GREP_MATCH — task_manager\manager.py:67
      Keyword 'completed' found in source code

              instead of the correct status string "completed".  This means

  [13] GREP_MATCH — task_manager\cli.py:28
      Keyword 'pending' found in source code

          print(f"\nPending tasks  : {len(manager.get_pending_tasks())}")

  [14] GREP_MATCH — task_manager\manager.py:4
      Keyword 'pending' found in source code

      BUG: get_pending_tasks() uses the wrong status string in its filter condition,

  [15] GREP_MATCH — task_manager\manager.py:42
      Keyword 'pending' found in source code

              """Move a task from pending to in_progress."""

  [16] GREP_MATCH — task_manager\manager.py:63
      Keyword 'pending' found in source code

          def get_pending_tasks(self) -> List[Task]:

  [17] GREP_MATCH — task_manager\manager.py:69
      Keyword 'pending' found in source code

              returns all tasks rather than just the pending ones.

  [18] CODE_INSPECTION — task_manager\cli.py:2
      Relevant section around line 2

         1 | """
         2 | Simple CLI entry-point for the Task Manager.
         3 | 
         4 | Usage:
         5 |     python -m task_manager.cli
         6 | """

  [19] CODE_INSPECTION — task_manager\cli.py:5
      Relevant section around line 5

         1 | """
         2 | Simple CLI entry-point for the Task Manager.
         3 | 
         4 | Usage:
         5 |     python -m task_manager.cli
         6 | """
         7 | from .manager import TaskManager
         8 | 
         9 | 

  [20] CODE_INSPECTION — task_manager\cli.py:7
      Relevant section around line 7

         3 | 
         4 | Usage:
         5 |     python -m task_manager.cli
         6 | """
         7 | from .manager import TaskManager
         8 | 
         9 | 
        10 | def run_demo() -> None:
        11 |     manager = TaskManager()

  [21] CODE_INSPECTION — task_manager\manager.py:2
      Relevant section around line 2

         1 | """
         2 | Core task management logic.
         3 | 
         4 | BUG: get_pending_tasks() uses the wrong status string in its filter condition,
         5 | causing it to return all tasks regardless of their status.
         6 | """

  [22] CODE_INSPECTION — task_manager\manager.py:4
      Relevant section around line 4

         1 | """
         2 | Core task management logic.
         3 | 
         4 | BUG: get_pending_tasks() uses the wrong status string in its filter condition,
         5 | causing it to return all tasks regardless of their status.
         6 | """
         7 | from typing import List, Optional
         8 | from .models import Task

  [23] CODE_INSPECTION — task_manager\manager.py:5
      Relevant section around line 5

         1 | """
         2 | Core task management logic.
         3 | 
         4 | BUG: get_pending_tasks() uses the wrong status string in its filter condition,
         5 | causing it to return all tasks regardless of their status.
         6 | """
         7 | from typing import List, Optional
         8 | from .models import Task
         9 | 

  [24] CODE_INSPECTION — task_manager\models.py:2
      Relevant section around line 2

         1 | """
         2 | Data models for the Task Manager application.
         3 | """
         4 | from dataclasses import dataclass, field
         5 | from datetime import datetime
         6 | from typing import Optional

  [25] CODE_INSPECTION — task_manager\models.py:10
      Relevant section around line 10

         6 | from typing import Optional
         7 | 
         8 | 
         9 | @dataclass
        10 | class Task:
        11 |     """Represents a single task in the task manager."""
        12 | 
        13 |     id: int
        14 |     title: str

  [26] CODE_INSPECTION — task_manager\models.py:11
      Relevant section around line 11

         7 | 
         8 | 
         9 | @dataclass
        10 | class Task:
        11 |     """Represents a single task in the task manager."""
        12 | 
        13 |     id: int
        14 |     title: str
        15 |     description: str



------------------------------------------------------------------------
  LIKELY ROOT CAUSE
------------------------------------------------------------------------

  Summary    : `get_pending_tasks()` uses an incorrect string literal in its filter/comparison condition, causing it to never match the expected status and returning wrong results.
  Location   : task_manager\manager.py  (line 71)
  Confidence : MEDIUM

  Explanation:
    The method `get_pending_tasks` in `task_manager\manager.py` contains a suspicious comparison.

  Faulty code:
    return [t for t in self._tasks if t.status != "complete"]  # BUG: should be "completed"

  Suggested fix (not yet applied):
    Review the comparison expression on line 71 of `task_manager\manager.py`.
    Verify that the string literal being compared against exactly matches the status/value strings used elsewhere in the codebase.
    Correct the literal to the canonical value.


------------------------------------------------------------------------
  SUGGESTED NEXT STEPS
------------------------------------------------------------------------

  1. Inspect `task_manager\manager.py` at line 71.
  2. Verify the string literal in the comparison matches the canonical status values used in the rest of the codebase.
  3. Write a minimal failing test that reproduces the bug in isolation.
  4. Apply the one-line fix and re-run the full test suite to confirm all 3 previously failing tests now pass.
  5. Review any other methods in the same class that perform similar status string comparisons to rule out related issues.


------------------------------------------------------------------------
  INVESTIGATION NOTES
------------------------------------------------------------------------

  - Keywords used for evidence gathering: Write unit tests, Fix login bug, Update README, Refactor DB layer, Alpha, completed, Beta, pending, tasks, appearing, task, list

========================================================================
  End of Report
========================================================================