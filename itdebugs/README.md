# ItDebugs

> **Agentic developer debugging assistant**
> Milestone 1 — Investigation Engine

ItDebugs helps developers investigate real software bugs by automatically analyzing a repository, understanding a bug report, collecting evidence, identifying the likely root cause, and proposing a fix.

---

## What it does (Milestone 1)

Given a **repository path** and a **natural-language bug description**, the investigation engine:

1. Scans the repository structure and identifies relevant source and test files
2. Runs the project's test suite safely in a subprocess
3. Captures and parses failing tests
4. Greps the source code for keywords derived from the bug description and failing tests
5. Extracts relevant method bodies for deeper inspection
6. Infers the most likely root cause from the assembled evidence
7. Produces a structured, human-readable investigation report

The engine is **read-only** with respect to the target project — it never modifies the code under investigation.

---

## Project layout

```
itdebugs/
├── __init__.py
├── investigate.py          ← CLI entry point
├── requirements.txt
├── README.md
└── engine/
    ├── __init__.py
    ├── repo_scanner.py     ← filesystem inspection
    ├── test_runner.py      ← safe subprocess pytest execution + result parsing
    ├── code_reader.py      ← source code reading, grep, block extraction
    ├── reporter.py         ← structured report dataclasses + text renderer
    └── investigator.py     ← orchestration of the full investigation workflow
```

---

## Installation

```bash
pip install -r itdebugs/requirements.txt
```

No external dependencies beyond `pytest` (which is also required by the target project to run its tests).

---

## Usage

```bash
python -m itdebugs.investigate \
    --repo  demo/buggy-project \
    --bug   "Completed tasks are appearing in the pending task list." \
    --verbose
```

### Options

| Flag | Description |
|------|-------------|
| `--repo PATH` | Path to the repository root to investigate (required) |
| `--bug TEXT` | Natural-language bug description (required) |
| `--out FILE` | Write the report to a file in addition to stdout |
| `--timeout N` | Pytest wall-clock timeout in seconds (default: 60) |
| `--verbose` | Print step-by-step progress to stderr |

---

## Demo

Run the investigation against the bundled buggy demo project:

```bash
python -m itdebugs.investigate \
    --repo demo/buggy-project \
    --bug  "Completed tasks are appearing in the pending task list." \
    --verbose \
    --out  report.md
```

Expected output highlights:
- **3 failing tests** identified
- **Evidence** collected: grep matches, code sections, failure details
- **Root cause** identified: incorrect string literal in `get_pending_tasks()` filter condition
- **Suggested fix** described (not applied)

---

## What's NOT here yet

| Component | Status |
|-----------|--------|
| FastAPI REST server | Not started — Milestone 2 |
| React frontend | Not started — Milestone 3 |
| Auto-fix agent | Not started — Milestone 4 |
| Multi-agent / parallel analysis | Not started — Milestone 5 |

---

## Running the engine's own unit tests

```bash
pytest itdebugs/tests/ -v
```

*(Test suite to be added in the next milestone.)*
