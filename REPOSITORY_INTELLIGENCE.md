# ItDebugs — Repository Intelligence

> Milestone 3 — Repository Profiling, File Inventory & Relevance Selection

---

## Why Repository Intelligence is needed

The previous investigation engine worked well on the small demo project but relied on
scanning *all* Python files indiscriminately. For a real-world repository with hundreds
or thousands of files this approach:

- reads irrelevant files and adds noise to evidence
- does not know which language the project uses
- does not know where tests live until pytest actually runs
- cannot prioritise which files to inspect first

Repository Intelligence solves this by running a lightweight **profiling and ranking pass**
before any deep analysis begins. The result: the investigation agents receive a small,
pre-ranked list of candidate files most likely to contain the bug, regardless of repository size.

---

## How repository profiling works

The `RepositoryProfiler` inspects a repository in two passes:

### Pass 1 — File inventory (`FileInventory`)

Walks the directory tree using `os.walk` and records lightweight metadata for every file:

| Field | Description |
|-------|-------------|
| `relative_path` | Path relative to repo root |
| `size_bytes` | File size — no content read yet |
| `extension` | Lowercase extension (`.py`, `.ts`, etc.) |
| `language` | Detected from extension |
| `category` | Source / Test / Config / Dependency / Docs / Generated / Unknown |
| `is_binary` | Sniffs first 512 bytes for null bytes |

No file content is read during this pass. Binary, oversized, and excluded files are skipped.

### Pass 2 — Profile assembly (`RepositoryProfiler`)

Uses only filenames and directory names (still no content) to detect:

- **Languages** — by file extension counts
- **Test frameworks** — from config filenames (`pytest.ini`, `jest.config.js`, etc.)
- **Package managers** — from manifest filenames (`requirements.txt`, `package.json`, etc.)
- **Frameworks / tools** — from known filename signatures
- **Entry points** — `__main__.py`, `main.py`, `app.py`, `index.js`, etc.
- **Source and test directories** — from the most common parent dirs of source/test files

The output is a `RepositoryProfile` dataclass.

---

## How large repositories are handled

All traversal is controlled by `InventoryConfig`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `max_files` | 5,000 | Stop counting after this many files |
| `max_file_size_bytes` | 2 MB | Oversized files are flagged as binary |
| `max_depth` | 12 | Maximum directory recursion depth |
| `include_binary` | False | Binary files are skipped entirely |
| `extra_excluded_dirs` | `set()` | Add project-specific dirs to skip |

Default excluded directories include: `.git`, `__pycache__`, `node_modules`, `.venv`,
`venv`, `dist`, `build`, `coverage`, `.pytest_cache`, and many more.

Errors (permission denied, deleted files) are silently skipped — a single unreadable
file never crashes the investigation.

---

## How relevance ranking works

The `RelevanceSelector` scores every file in the inventory against the bug description
using additive, deterministic signals:

| Signal | Points | Condition |
|--------|--------|-----------|
| Keyword in file path | +2.0 per keyword | Filename/directory matches a bug-description keyword |
| Keyword in parent directory | +1.0 per keyword | Parent dir contains a bug keyword |
| Is source file | +0.5 | Category is SOURCE |
| Is test file | +0.3 | Category is TEST |
| In known source directory | +1.0 | File lives in a detected source dir |
| In known test directory | +0.8 | File lives in a detected test dir |
| Is likely entry point | +1.5 | Filename is `main.py`, `__main__.py`, etc. |
| Content scan hit | +3.0 per keyword | Keyword found in first 8 KB of file (only for small text files) |

Content scanning is bounded by `RelevanceConfig`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `max_candidates` | 20 | Maximum files returned |
| `max_files_evaluated` | 2,000 | Evaluation cap for large inventories |
| `max_content_scan_bytes` | 64 KB | Only scan files smaller than this |
| `content_read_bytes` | 8 KB | Bytes actually read per file |
| `max_content_hits_per_file` | 5 | Cap to prevent high-frequency-word noise |
| `min_score` | 0.5 | Minimum score to include in results |

Files are sorted by `total_score` descending. The top `max_candidates` are returned.

No LLM is used. Relevance is entirely deterministic.

---

## How candidate files flow into the agents

```
RepositoryAnalyst
      |
      +-- calls RepositoryProfiler  --> RepositoryProfile
      |         FileInventory       --> List[FileRecord]
      |         RelevanceSelector   --> List[CandidateFile]
      |
      +--> ctx.repo_profile         (RepositoryProfile)
      +--> ctx.candidate_files      (List[CandidateFile], ranked)
      +--> ctx.relevant_files       (List[str], candidate paths)
      +--> ctx.repo_structure       (RepoStructure, for backward compat)
      |
      v
CodeAnalyst
      |  reads ctx.candidate_files (pre-ranked) as the primary source list
      |  falls back to ctx.repo_structure.source_files if candidates empty
      v
EvidenceAgent, RootCauseAgent, VerificationAgent
      (all consume ctx.relevant_files / ctx.evidence as before)
```

The `InvestigationContext` now carries:

| Field | Type | Set by |
|-------|------|--------|
| `repo_profile` | `RepositoryProfile` | RepositoryAnalyst |
| `repo_index` | `RepositoryIndex` | RepositoryAnalyst |
| `candidate_files` | `List[CandidateFile]` | RepositoryAnalyst |
| `relevant_files` | `List[str]` | RepositoryAnalyst (paths from candidates) |

---

## Configurable limits

```python
from itdebugs.intelligence import InventoryConfig, RelevanceConfig, RepositoryProfiler, RelevanceSelector

# Custom inventory: skip vendor dir, allow up to 10,000 files
inv_cfg = InventoryConfig(
    extra_excluded_dirs={"vendor", "third_party"},
    max_files=10_000,
    max_file_size_bytes=5 * 1024 * 1024,  # 5 MB
)

# Custom relevance: return top 30 candidates, no content scan
rel_cfg = RelevanceConfig(
    max_candidates=30,
    max_content_scan_bytes=0,   # disable content scanning
    min_score=1.0,
)

profiler = RepositoryProfiler(config=inv_cfg)
profile = profiler.profile("/path/to/repo")

selector = RelevanceSelector(config=rel_cfg)
candidates = selector.select(profile, "the bug description goes here")
```

---

## Module layout

```
itdebugs/intelligence/
├── __init__.py          public API + all exports
├── models.py            RepositoryProfile, FileRecord, CandidateFile, RepositoryIndex, ...
├── inventory.py         FileInventory + InventoryConfig (filesystem walk, no content)
├── profiler.py          RepositoryProfiler (language/framework detection, dir inference)
└── relevance.py         RelevanceSelector + RelevanceConfig (scoring, ranking)
```

---

## Future extension points for LLM-based relevance

The `RelevanceSelector._execute` scoring loop is the only place that needs to change to add LLM support:

```python
# Current: deterministic scoring
score.add(3.0 * content_hits, f"content scan: {content_hits} keyword hit(s)")

# Future: LLM-semantic scoring
semantic_score = llm.score_file_relevance(
    file_content=content_snippet,
    bug_description=bug_description,
)
score.add(semantic_score, f"LLM relevance: {semantic_score:.1f}")
```

The rest of the pipeline (agents, orchestrator, report) is unaffected because they
only read `CandidateFile.total_score` and `CandidateFile.record.relative_path`.

Similarly, `RepositoryProfiler` could be augmented with LLM-based analysis of
README files, docstrings, or comments to infer architectural intent without
changing any downstream code.

---

## CLI output

The orchestrator prints a Repository Intelligence summary after the Repository Analyst completes:

```
------------------------------------------------------------
  Repository Intelligence
------------------------------------------------------------
  Languages     : Python
  Frameworks    : none detected
  Test framework: pytest
  Pkg managers  : pip
  Source files  : 4
  Test files    : 2
  Dependencies  : requirements.txt
  Candidate files: 6
------------------------------------------------------------
```

With `--verbose`, the ranked candidate files and their scores are also shown:

```
  Ranked candidate files:
     1. [ 19.5]  task_manager\manager.py  (+2.0: path keywords: ['task']; ...)
     2. [ 18.1]  tests\test_task_manager.py  (+2.0: path keywords: ['task']; ...)
     ...
```
