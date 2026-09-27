"""
Simple CLI entry-point for the Task Manager.

Usage:
    python -m task_manager.cli
"""
from .manager import TaskManager


def run_demo() -> None:
    manager = TaskManager()

    # Seed some tasks
    t1 = manager.add_task("Write unit tests", "Cover all edge cases", priority=1)
    t2 = manager.add_task("Fix login bug", "Users are logged out unexpectedly", priority=1)
    t3 = manager.add_task("Update README", "Document new CLI flags", priority=2)
    t4 = manager.add_task("Refactor DB layer", "Reduce query duplication", priority=3)

    # Mark some done / in progress
    manager.complete_task(t1.id)
    manager.start_task(t2.id)

    print("=== Task Manager Demo ===\n")
    print("All tasks:")
    for task in manager.get_all_tasks():
        print(f"  [{task.status:12s}] #{task.id} {task.title!r} (priority {task.priority})")

    print(f"\nPending tasks  : {len(manager.get_pending_tasks())}")
    print(f"Completed tasks: {len(manager.get_completed_tasks())}")
    print(f"\nSummary: {manager.summary()}")


if __name__ == "__main__":
    run_demo()
