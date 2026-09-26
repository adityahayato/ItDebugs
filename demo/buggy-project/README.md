# Task Manager — ItDebugs Demo Project

A small command-line task management library used as the **demo target** for the **ItDebugs** agentic debugging assistant.

---

## What the application does

`task_manager` is a Python library (with a thin CLI demo) that lets a developer:

- **Create** tasks with a title, description, and priority level (high / medium / low)
- **Start** a task, moving it from `pending` → `in_progress`
- **Complete** a task, moving it to `completed` with a timestamp
- **Query** tasks by status or priority (`get_pending_tasks`, `get_completed_tasks`, `get_high_priority_tasks`)
- **Summarise** the current workload with a count breakdown

It is intentionally small so that an AI debugging agent can ingest the entire codebase in one pass.

---

## Project layout

```
demo/buggy-project/
├── task_manager/
│   ├── __init__.py
│   ├── models.py       # Task dataclass
│   ├── manager.py      # TaskManager class (core logic)
│   └── cli.py          # Quick demo runner
├── tests/
│   ├── __init__.py
│   └── test_task_manager.py
├── requirements.txt
└── README.md
```

---

## Installation & running

```bash
# from the repo root
cd demo/buggy-project

# install deps (only pytest)
pip install -r requirements.txt

# run the CLI demo
python -m task_manager.cli

# run the test suite
pytest tests/ -v
```

---

## Reported bug

**Summary:** `get_pending_tasks()` does not correctly exclude completed tasks.

**Symptom:** After marking one or more tasks as completed, calling `get_pending_tasks()` still returns those completed tasks in the result list. The pending count is always equal to the total task count, regardless of how many tasks have been finished.

**Affected method:** `TaskManager.get_pending_tasks` in `task_manager/manager.py`

---

## Expected behaviour

`get_pending_tasks()` should return **only** tasks whose status has not reached a terminal state — i.e., tasks that still need to be worked on.  
For example, given four tasks where one is completed and one is in progress, `get_pending_tasks()` should return **3** tasks (the in-progress one plus the two that haven't started yet).

---

## Actual behaviour

`get_pending_tasks()` returns **all** tasks, including those already marked completed.  
The filter condition appears to be comparing against an incorrect value, causing it to never match any task's status and therefore never exclude anything.

---

## Failing tests

Run `pytest tests/ -v` to see the failures. The tests that expose the bug are:

| Test | What it checks |
|------|----------------|
| `TestGetPendingTasks::test_pending_tasks_excludes_completed` | Completed tasks must not appear in the pending list |
| `TestGetPendingTasks::test_pending_tasks_empty_when_all_completed` | If all tasks are done, pending list must be empty |
| `TestSummary::test_summary_pending_count_reflects_bug` | Summary `pending` count must equal 3, not 4 |

All other tests in the suite pass, which helps narrow the fault to the filtering logic in `get_pending_tasks()`.

---

## Notes for ItDebugs

This project is designed to be analysed by the ItDebugs investigation engine. The bug is a **single-line logic error** in one method. The engine should:

1. Read the failing test output to understand the expected vs. actual behaviour
2. Trace which method is under test
3. Inspect the method's implementation
4. Identify the incorrect value in the filter condition
5. Propose the minimal one-line fix
