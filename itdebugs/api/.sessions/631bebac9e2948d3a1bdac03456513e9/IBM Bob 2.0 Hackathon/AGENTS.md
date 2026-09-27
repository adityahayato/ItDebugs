# ItDebugs — Agent Architecture

> Version: 0.2 (Milestone 2 — Multi-Agent Orchestration)

---

## Overview

ItDebugs uses a pipeline of six specialised agents coordinated by a central Orchestrator.
Each agent has a single, well-defined responsibility and communicates through a shared
`InvestigationContext` object rather than calling each other directly.

```
Bug Report + Repository Path
          |
          v
  +------------------+
  |  Orchestrator    |  coordinates agents, builds final report
  +------------------+
          |
     (sequential)
          |
  +-------+--------+--------+-----------+---------------+-----------------+
  |                |        |           |               |                 |
  v                v        v           v               v                 v
[1] Repo      [2] Test  [3] Code   [4] Evidence   [5] Root Cause  [6] Verification
Analyst       Analyst   Analyst    Agent          Agent           Agent
```

---

## The InvestigationContext

```python
@dataclass
class InvestigationContext:
    # Input
    repo_path: str
    bug_description: str
    test_timeout: int

    # Populated by agents (in order)
    repo_structure: Optional[RepoStructure]       # set by RepositoryAnalyst
    test_run: Optional[TestRunSummary]             # set by TestAnalyst
    failing_tests: List[TestResult]                # set by TestAnalyst
    keywords: List[str]                            # set by TestAnalyst
    relevant_files: List[str]                      # set by CodeAnalyst
    suspicious_locations: List[str]                # set by CodeAnalyst
    evidence: List[EvidenceItem]                   # set by EvidenceAgent
    root_cause: Optional[RootCauseHypothesis]      # set by RootCauseAgent
    verification: Optional[VerificationResult]     # set by VerificationAgent
    report: Optional[InvestigationReport]          # set by Orchestrator
    errors: List[str]                              # appended by any agent
    agent_notes: List[str]                         # appended by any agent
```

The context is the single source of truth throughout the pipeline.
Agents do not call each other; they read from and write to the context.

---

## Agent Responsibilities

### 1. Repository Analyst (`agents/repo_analyst.py`)

| | |
|---|---|
| **Input from context** | `repo_path` |
| **Output to context** | `repo_structure`, initial `relevant_files` |
| **Engine calls** | `engine.repo_scanner.scan_repository` |
| **Does NOT** | Run tests, read file contents, modify source |

Scans the repository filesystem and builds a structural model.
Populates `repo_structure` with file lists, package directories, README
and config files, and a directory tree.

---

### 2. Test Analyst (`agents/test_analyst.py`)

| | |
|---|---|
| **Input from context** | `repo_structure`, `bug_description` |
| **Output to context** | `test_run`, `failing_tests`, `keywords` |
| **Engine calls** | `engine.test_runner.run_tests`, `engine.repo_scanner.find_test_directories` |
| **Does NOT** | Modify source, apply fixes |

Runs the test suite in a subprocess (safe, timeout-protected) and parses
the results.  Also extracts investigation keywords from the bug description
and failure messages for downstream grep searches.

---

### 3. Code Analyst (`agents/code_analyst.py`)

| | |
|---|---|
| **Input from context** | `repo_structure`, `failing_tests`, `keywords` |
| **Output to context** | Refined `relevant_files`, `suspicious_locations` |
| **Engine calls** | `engine.code_reader.grep`, `engine.code_reader.extract_block`, `engine.code_reader.extract_relevant_sections` |
| **Does NOT** | Run tests, modify source |

Scores source files by keyword density to identify the most relevant ones.
Extracts method bodies referenced in failing tests and looks for suspicious
patterns (wrong string literals in comparisons, mismatched value names).

---

### 4. Evidence Agent (`agents/evidence_agent.py`)

| | |
|---|---|
| **Input from context** | `failing_tests`, `keywords`, `relevant_files`, `suspicious_locations`, `repo_structure` |
| **Output to context** | `evidence` (List[EvidenceItem]) |
| **Engine calls** | `engine.code_reader.grep`, `engine.code_reader.extract_relevant_sections` |
| **Does NOT** | Modify source, apply fixes |

Aggregates evidence from all prior phases into a clean, deduplicated list.
Evidence categories:
- `failing_test` — failure messages and assertion outputs
- `grep_match` — keyword matches in source files
- `code_inspection` — relevant code sections around suspicious locations

---

### 5. Root Cause Agent (`agents/root_cause_agent.py`)

| | |
|---|---|
| **Input from context** | `evidence`, `failing_tests`, `repo_structure` |
| **Output to context** | `root_cause` (RootCauseHypothesis) |
| **Engine calls** | `engine.investigator._infer_root_cause` |
| **Does NOT** | Modify source, apply fixes |

Synthesises the collected evidence into a root-cause hypothesis.
Delegates the pattern-matching inference to the existing engine function.
Produces: affected file and line, faulty code snippet, suggested fix
description, confidence level.

**The suggested fix is NEVER applied automatically.**

---

### 6. Verification Agent (`agents/verification_agent.py`)

| | |
|---|---|
| **Input from context** | `evidence`, `failing_tests`, `root_cause` |
| **Output to context** | `verification` (VerificationResult) |
| **Engine calls** | None (pure reasoning over already-collected data) |
| **Does NOT** | Modify source, apply fixes |

Reviews the proposed root cause for consistency with the available evidence.
Produces: consistency verdict, confidence assessment, supporting evidence list,
contradiction list, and gap list.  Does NOT automatically fix the bug.

---

## Information Flow Diagram

```
+--------------------------------------------------+
| InvestigationContext                             |
|                                                  |
| repo_path ─────────────────────┐                 |
| bug_description ───────────────+──> RepositoryAnalyst
|                                |         |        |
|                                |    repo_structure|
|                                |    relevant_files|
|                                |         |        |
|                                +──> TestAnalyst   |
|                                          |        |
|                                    test_run       |
|                                    failing_tests  |
|                                    keywords       |
|                                          |        |
|                                     CodeAnalyst   |
|                                          |        |
|                               relevant_files(refined)
|                               suspicious_locations|
|                                          |        |
|                                    EvidenceAgent  |
|                                          |        |
|                                      evidence     |
|                                          |        |
|                                  RootCauseAgent   |
|                                          |        |
|                                     root_cause    |
|                                          |        |
|                                 VerificationAgent |
|                                          |        |
|                                    verification   |
|                                          |        |
+------------------------------------------+--------+
                                           |
                                    Orchestrator
                                    assembles
                                  InvestigationReport
```

---

## Orchestrator

`itdebugs/orchestrator.py`

The Orchestrator:
1. Constructs `InvestigationContext` with the user's inputs
2. Instantiates all six agents
3. Runs them in sequence, printing a visible banner before each step
4. Catches and logs any agent-level errors (pipeline keeps running)
5. Assembles the final `InvestigationReport` from the completed context
6. Returns the report (never raises)

---

## BaseAgent Contract

```python
class BaseAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    def run(self, ctx: InvestigationContext) -> InvestigationContext:
        # Logs start, calls _execute, catches exceptions, logs finish
        ...

    @abstractmethod
    def _execute(self, ctx: InvestigationContext) -> None:
        # Agent-specific logic; mutates ctx in place; may raise
        ...
```

Every agent:
- Has a unique `name`
- Accepts `InvestigationContext` as its only input
- Mutates the context in-place and returns it
- Never raises from `run()` — exceptions are captured in `ctx.errors`

---

## Why This Architecture Supports Parallel Execution

The current implementation is sequential.  The design is ready for parallelism
because:

### 1. Agents are decoupled through the shared context
No agent calls another directly.  They only read/write the context object.
The Orchestrator is the only coordinator.

### 2. Dependency analysis

| Agent | Depends on |
|-------|-----------|
| RepositoryAnalyst | Nothing (reads only the filesystem) |
| TestAnalyst | `repo_structure` |
| CodeAnalyst | `repo_structure`, `failing_tests`, `keywords` |
| EvidenceAgent | `failing_tests`, `keywords`, `relevant_files`, `repo_structure` |
| RootCauseAgent | `evidence`, `failing_tests`, `repo_structure` |
| VerificationAgent | `evidence`, `failing_tests`, `root_cause` |

Steps 2 and 3 are the first parallelisable pair (both only need step 1).

### 3. To enable parallel execution

```python
# In Orchestrator.run(), replace the sequential loop with:
import concurrent.futures

# After RepositoryAnalyst:
with concurrent.futures.ThreadPoolExecutor() as pool:
    futures = [
        pool.submit(TestAnalyst(verbose).run, ctx_snapshot),
        pool.submit(CodeAnalyst(verbose).run, ctx_snapshot),
    ]
    results = [f.result() for f in futures]
    ctx = merge_contexts(results)  # merge non-conflicting fields
```

Each parallel agent would receive a read-only snapshot of the context;
their outputs (new list items) would be merged by the orchestrator.

---

## How to Replace an Agent with an LLM

Each agent's logic lives entirely in `_execute(ctx)`.  To substitute an LLM:

```python
class LLMRootCauseAgent(RootCauseAgent):
    def _execute(self, ctx: InvestigationContext) -> None:
        prompt = build_prompt(ctx.evidence, ctx.bug_description)
        response = call_llm_api(prompt)
        ctx.root_cause = parse_response_to_hypothesis(response)
```

The rest of the pipeline (Verification Agent, report rendering, CLI) is
completely unaffected because it only reads `ctx.root_cause`, not the
implementation that produced it.

The same pattern applies to any other agent:
- Replace `TestAnalyst._execute` to call an LLM for test categorisation
- Replace `VerificationAgent._execute` for semantic consistency checking
- Replace `EvidenceAgent._execute` for LLM-ranked evidence prioritisation

---

## File Layout

```
itdebugs/
├── agents/
│   ├── __init__.py            exports all agents + context types
│   ├── base.py                BaseAgent abstract class
│   ├── context.py             InvestigationContext + VerificationResult
│   ├── repo_analyst.py        RepositoryAnalyst
│   ├── test_analyst.py        TestAnalyst
│   ├── code_analyst.py        CodeAnalyst
│   ├── evidence_agent.py      EvidenceAgent
│   ├── root_cause_agent.py    RootCauseAgent
│   └── verification_agent.py  VerificationAgent
├── engine/                    (unchanged — engine modules reused by agents)
│   ├── repo_scanner.py
│   ├── test_runner.py
│   ├── code_reader.py
│   ├── reporter.py
│   └── investigator.py        (legacy single-class path, still works)
├── tests/
│   └── test_agents.py         unit + integration tests
├── orchestrator.py            Orchestrator class
└── investigate.py             CLI (--mode orchestrated|legacy)
```

---

## CLI Usage

```bash
# Orchestrated pipeline (default)
python -m itdebugs.investigate \
    --repo  demo/buggy-project \
    --bug   "Completed tasks are appearing in the pending task list." \
    --verbose

# Legacy single-class engine
python -m itdebugs.investigate \
    --repo  demo/buggy-project \
    --bug   "Completed tasks are appearing in the pending task list." \
    --mode  legacy
```

Both modes produce the same `InvestigationReport` format.
