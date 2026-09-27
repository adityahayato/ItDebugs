# ItDebugs — Architecture

> Agentic developer debugging assistant
> Version: 0.1 (Milestone 1 — Investigation Engine)

---

## Overview

ItDebugs is a Python-based agentic system that investigates software bugs in developer repositories. The system is designed in clear, incrementally deliverable milestones so that each stage produces a fully working, testable product.

```
┌──────────────────────────────────────────────────────────────────┐
│                          ItDebugs                                │
│                                                                  │
│   ┌────────────┐    ┌────────────────────────────────────────┐   │
│   │    CLI     │    │         Investigation Engine           │   │
│   │ (Milestone │───▶│ ┌──────────┐ ┌──────────┐ ┌────────┐  │   │
│   │    1)      │    │ │   Repo   │ │  Test    │ │  Code  │  │   │
│   └────────────┘    │ │ Scanner  │ │  Runner  │ │ Reader │  │   │
│                     │ └────┬─────┘ └────┬─────┘ └───┬────┘  │   │
│   ┌────────────┐    │      └────────────┴────────────┘       │   │
│   │  FastAPI   │    │                  │                      │   │
│   │   Server  │───▶│         Investigator                    │   │
│   │(Milestone 2)   │         (Orchestrator)                   │   │
│   └────────────┘    │                  │                      │   │
│                     │         ┌────────▼──────┐               │   │
│   ┌────────────┐    │         │   Reporter    │               │   │
│   │  React UI  │    │         │ (Structured   │               │   │
│   │(Milestone 3)   │         │   Report)     │               │   │
│   └────────────┘    │         └───────────────┘               │   │
│                     └────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Milestones

| # | Name | Status | Description |
|---|------|--------|-------------|
| 1 | Investigation Engine | ✅ **Complete** | Core Python engine: scan, test, grep, infer, report |
| 2 | FastAPI Server | ⬜ Planned | REST API wrapping the engine; async endpoints |
| 3 | React Frontend | ⬜ Planned | Browser UI for submitting bugs and viewing reports |
| 4 | Auto-Fix Agent | ⬜ Planned | Engine extension that proposes and applies patches |
| 5 | Multi-Agent System | ⬜ Planned | Parallel specialized agents (test agent, code agent, fix agent) |

---

## Milestone 1 — Investigation Engine (current)

### Inputs

```
repo_path        : path to the repository root
bug_description  : natural-language description of the bug
```

### Investigation workflow (5 steps)

```
Step 1 ─ SCAN          repo_scanner.py
          │              Walk filesystem, build RepoStructure:
          │              python files, test files, package dirs, tree
          ▼
Step 2 ─ TEST          test_runner.py
          │              subprocess pytest --tb=short -v
          │              parse: TestRunSummary, TestResult[]
          ▼
Step 3 ─ KEYWORDS      investigator.py
          │              extract meaningful terms from bug description
          │              + failing test names + failure messages
          ▼
Step 4 ─ EVIDENCE      code_reader.py + investigator.py
          │              grep source files for keywords
          │              extract relevant code sections
          │              collect failing test bodies
          ▼
Step 5 ─ ROOT CAUSE    investigator.py
          │              analyse evidence for bug patterns:
          │                - wrong string literal in comparison
          │                - mismatched status values
          │                - off-by-one, wrong operator
          │              return RootCauseHypothesis
          ▼
        REPORT          reporter.py
                         render InvestigationReport as text / Markdown
```

### Key data types

```
RepoStructure
  ├── python_files: FileInfo[]
  ├── test_files: FileInfo[]
  ├── source_files: FileInfo[]
  ├── package_dirs: str[]
  └── directory_tree: str

TestRunSummary
  ├── results: TestResult[]
  ├── failed_tests: TestResult[]
  ├── raw_output: str
  └── total/passed/failed counts

TestResult
  ├── node_id, outcome, file
  ├── class_name, test_name
  └── failure_message

EvidenceItem
  ├── category (failing_test | grep_match | code_inspection)
  ├── description, location
  └── snippet

RootCauseHypothesis
  ├── summary, file, line_range
  ├── explanation, confidence
  ├── faulty_code
  └── suggested_fix

InvestigationReport
  ├── repo_path, bug_description, timestamp
  ├── relevant_files[], test_files[]
  ├── tests_total/passed/failed
  ├── failing_test_ids[], failing_test_details[]
  ├── evidence: EvidenceItem[]
  ├── root_cause: RootCauseHypothesis
  └── suggested_next_steps[]
```

### Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `repo_scanner.py` | Pure filesystem introspection. No execution. Returns `RepoStructure`. |
| `test_runner.py` | Launches pytest in a subprocess with timeout. Returns `TestRunSummary`. Never imports target code. |
| `code_reader.py` | Reads source files, greps for patterns, extracts named code blocks. No execution. |
| `reporter.py` | Pure data + rendering. Defines report dataclasses and `render_text()`. No I/O. |
| `investigator.py` | Orchestrates steps 1–5. Owns keyword extraction and root-cause inference logic. |
| `investigate.py` | CLI glue — argument parsing, entry point, file output. |

---

## Design principles

**1. Read-only investigation**
The engine never modifies the target repository. It only reads files and runs the existing test suite.

**2. Subprocess isolation**
pytest is always invoked in a separate subprocess. A crashing or hanging test suite cannot bring down the investigator.

**3. No external LLM dependency (Milestone 1)**
The root-cause inference is rule-based and pattern-matching. This makes the engine fast, deterministic, and budget-free. LLM integration is planned for Milestone 4+.

**4. Structured output first**
All results are captured as Python dataclasses before rendering. This allows the CLI (Milestone 1), the API (Milestone 2), and the UI (Milestone 3) to consume the same data without re-parsing.

**5. Incremental milestones**
Each milestone produces a fully working, independently testable product. No milestone requires a subsequent one to be useful.

---

## Planned Milestone 2 — FastAPI Server

```
POST /api/investigate
  Body: { repo_path: string, bug_description: string }
  Returns: InvestigationReport (JSON)

GET  /api/report/{id}
  Returns: previously computed report

Architecture additions:
  - itdebugs/server/app.py          FastAPI application
  - itdebugs/server/models.py       Pydantic request/response models
  - itdebugs/server/routes.py       Route handlers
  - Background task queue for long-running investigations
```

---

## Planned Milestone 3 — React Frontend

```
Single-page app:
  - BugSubmitForm    →  POST /api/investigate
  - ReportViewer     ←  GET  /api/report/{id}
  - EvidencePanel    showing grep matches + code sections
  - RootCauseSummary highlighting the faulty file/line
  - NextStepsPanel   with suggested actions
```

---

## Planned Milestone 4 — Auto-Fix Agent

```
Investigation engine extension:
  - Reads RootCauseHypothesis from the report
  - Generates a minimal code patch (diff)
  - Applies the patch to a temporary copy of the repository
  - Re-runs the test suite to verify the fix
  - Returns a FixProposal with before/after diff and test results
```

---

## Planned Milestone 5 — Multi-Agent System

```
Parallel specialized agents:
  - RepoAgent       scans structure and files
  - TestAgent       runs tests, analyses failures
  - CodeAgent       deep code inspection, AST analysis
  - HypothesisAgent synthesises evidence into root cause
  - FixAgent        generates and verifies patches
  Coordinator: orchestrates agents, merges results
```

---

## Repository layout

```
IBM Bob 2.0 Hackathon/          ← workspace root
├── ARCHITECTURE.md             ← this document
├── itdebugs/                   ← Milestone 1 (current)
│   ├── __init__.py
│   ├── investigate.py          ← CLI entry point
│   ├── requirements.txt
│   ├── README.md
│   └── engine/
│       ├── __init__.py
│       ├── repo_scanner.py
│       ├── test_runner.py
│       ├── code_reader.py
│       ├── reporter.py
│       └── investigator.py
└── demo/
    └── buggy-project/          ← demo target for the engine
        ├── task_manager/       ← application with intentional bug
        ├── tests/              ← pytest suite (3 tests intentionally fail)
        ├── requirements.txt
        └── README.md
```
