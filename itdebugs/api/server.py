"""
ItDebugs API Server
===================

Connects the ItDebugs web UI to the real debugging engine.

Flow:

    Browser repository
          ↓
    Upload repository
          ↓
    ItDebugs investigation
          ↓
    IBM Granite reasoning
          ↓
    Root cause + proposed patch
          ↓
    User approval
          ↓
    Patch application
          ↓
    Targeted tests
          ↓
    Full regression tests
          ↓
    Verified repair
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from itdebugs.engine.test_runner import run_tests
from itdebugs.multi_bug import investigate_repository
from itdebugs.patcher import PatchApplicator, PatchGenerator


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="ItDebugs API",
    version="1.1.0",
    description="Backend API for the ItDebugs developer intelligence tool.",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# STORAGE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

SESSION_DIR = BASE_DIR / ".sessions"
HISTORY_FILE = BASE_DIR / "history.json"

SESSION_DIR.mkdir(parents=True, exist_ok=True)


# Active sessions in memory.
#
# session_id -> {
#     "repo_root": Path,
#     "repository": str,
#     "patches": [...],
#     "groups": [...],
#     "status": str
# }
SESSIONS: dict[str, dict] = {}


# ============================================================
# HISTORY HELPERS
# ============================================================

def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []

    try:
        return json.loads(
            HISTORY_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return []


def save_history(history: list[dict]) -> None:
    HISTORY_FILE.write_text(
        json.dumps(
            history,
            indent=2,
        ),
        encoding="utf-8",
    )


def add_history(entry: dict) -> None:
    history = load_history()

    history.insert(
        0,
        entry,
    )

    # Keep the most recent 50 investigations.
    history = history[:50]

    save_history(history)


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health_check():
    return {
        "status": "online",
        "service": "ItDebugs",
        "version": "1.1.0",
    }


@app.get("/")
def root():
    return {
        "name": "ItDebugs",
        "status": "online",
        "message": "Developer intelligence backend is running.",
    }


# ============================================================
# SERIALIZATION HELPERS
# ============================================================

def safe_value(value):
    """
    Convert dataclasses / objects into JSON-safe values.
    """

    if value is None:
        return None

    if is_dataclass(value):
        return asdict(value)  # type: ignore[arg-type]

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [
            safe_value(item)
            for item in value
        ]

    if isinstance(value, dict):
        return {
            str(key): safe_value(val)
            for key, val in value.items()
        }

    return str(value)


def serialize_test_summary(summary):
    return {
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "errors": summary.errors,
        "timed_out": summary.timed_out,
        "collection_error": summary.collection_error,
        "failed_tests": [
            {
                "node_id": test.node_id,
                "file": test.file,
                "failure_message": test.failure_message,
            }
            for test in summary.failed_tests
        ],
    }


def serialize_root_cause(root_cause):
    if root_cause is None:
        return None

    return {
        "file": getattr(
            root_cause,
            "file",
            "",
        ),
        "line": getattr(
            root_cause,
            "line_range",
            "",
        ),
        "line_range": getattr(
            root_cause,
            "line_range",
            "",
        ),
        "faulty_code": getattr(
            root_cause,
            "faulty_code",
            "",
        ),
        "suggested_fix": getattr(
            root_cause,
            "suggested_fix",
            "",
        ),
        "explanation": getattr(
            root_cause,
            "explanation",
            "",
        ),
        "confidence": getattr(
            root_cause,
            "confidence",
            "",
        ),
    }


# ============================================================
# REPOSITORY UPLOAD
# ============================================================

async def reconstruct_repository(
    files: list[UploadFile],
    temp_root: Path,
) -> Path:
    """
    Reconstruct the browser-selected repository
    inside the server session directory.
    """

    repository_root: Path | None = None

    ignored_parts = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
    }

    for upload in files:

        relative_path = (
            upload.filename or ""
        ).replace("\\", "/")

        if not relative_path:
            continue

        parts = [
            part
            for part in Path(relative_path).parts
            if part not in ("", ".", "..")
        ]

        if not parts:
            continue

        if any(
            part in ignored_parts
            for part in parts
        ):
            continue

        safe_relative_path = Path(*parts)

        destination = (
            temp_root /
            safe_relative_path
        ).resolve()

        root_resolved = temp_root.resolve()

        if not str(destination).startswith(
            str(root_resolved)
        ):
            continue

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        content = await upload.read()

        destination.write_bytes(
            content
        )

        if repository_root is None:
            repository_root = (
                temp_root /
                parts[0]
            )

    if repository_root is None:
        raise HTTPException(
            status_code=400,
            detail="The uploaded repository was empty.",
        )

    return repository_root


# ============================================================
# INVESTIGATE
# ============================================================

@app.post("/api/investigate")
async def investigate(
    files: list[UploadFile] = File(...),
    timeout: int = Form(60),
):
    """
    Analyze the uploaded repository.

    IMPORTANT:
    The repository is intentionally kept alive after this request
    because the next UI action may be:

        Approve & Repair
    """

    if not files:
        raise HTTPException(
            status_code=400,
            detail="No repository files were provided.",
        )

    timeout = max(
        10,
        min(timeout, 300),
    )

    session_id = uuid.uuid4().hex

    session_root = (
        SESSION_DIR /
        session_id
    )

    session_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        repository_root = await reconstruct_repository(
            files,
            session_root,
        )

        # ----------------------------------------------------
        # REAL ITDEBUGS ENGINE
        # ----------------------------------------------------

        result = investigate_repository(
            repository_root,
            timeout=timeout,
            verbose=False,
        )

        patch_generator = PatchGenerator()

        reports = []
        patch_objects = []
        groups_data = []

        for index, report in enumerate(
            result.reports,
            start=1,
        ):

            root_cause = getattr(
                report,
                "root_cause",
                None,
            )

            root_cause_data = serialize_root_cause(
                root_cause
            )

            patch_data = None
            patch_object = None

            if root_cause is not None:

                patch_object = patch_generator.generate(
                    str(repository_root),
                    root_cause,
                )

                patch_data = {
                    "file_path": patch_object.file_path,
                    "target_line": patch_object.target_line,
                    "original_line": patch_object.original_line,
                    "replacement_line": patch_object.replacement_line,
                    "diff": patch_object.diff_text,
                    "can_apply": patch_object.can_apply,
                    "generation_note": patch_object.generation_note,
                }

            group_data = None

            if index <= len(result.groups):

                group = result.groups[index - 1]

                group_data = {
                    "group_id": group.group_id,
                    "key": group.key,
                    "test_count": group.test_count,
                    "failures": [
                        {
                            "node_id": failure.node_id,
                            "file": failure.file,
                            "failure_message": failure.failure_message,
                        }
                        for failure in group.failures
                    ],
                }

                groups_data.append(
                    group_data
                )

            reports.append(
                {
                    "bug_id": index,
                    "success": bool(
                        report.investigation_successful
                    ),
                    "root_cause": root_cause_data,
                    "patch": patch_data,
                    "report": str(report),
                    "group": group_data,
                }
            )

            patch_objects.append(
                patch_object
            )

        # ----------------------------------------------------
        # SAVE SESSION
        # ----------------------------------------------------

        SESSIONS[session_id] = {
            "repo_root": repository_root,
            "repository": repository_root.name,
            "patches": patch_objects,
            "groups": groups_data,
            "reports": reports,
            "status": "awaiting_approval",
            "timeout": timeout,
        }

        # ----------------------------------------------------
        # HISTORY
        # ----------------------------------------------------

        add_history(
            {
                "id": session_id,
                "repository": repository_root.name,
                "status": "investigated",
                "tests": {
                    "total": result.test_run.total,
                    "passed": result.test_run.passed,
                    "failed": result.test_run.failed,
                    "errors": result.test_run.errors,
                },
                "bug_count": result.bug_count,
            }
        )

        return {
            "success": bool(
                result.investigation_successful
            ),

            "session_id": session_id,

            "repository": repository_root.name,

            "repository_path": str(
                repository_root
            ),

            "status": "awaiting_approval",

            "test_summary": serialize_test_summary(
                result.test_run
            ),

            "bug_count": result.bug_count,

            "reports": reports,

            "errors": result.errors,
        }

    except HTTPException:
        shutil.rmtree(
            session_root,
            ignore_errors=True,
        )
        raise

    except Exception as exc:

        shutil.rmtree(
            session_root,
            ignore_errors=True,
        )

        raise HTTPException(
            status_code=500,
            detail=f"ItDebugs analysis failed: {exc}",
        ) from exc


# ============================================================
# SESSION
# ============================================================

@app.get("/api/session/{session_id}")
def get_session(session_id: str):

    session = SESSIONS.get(
        session_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Investigation session not found.",
        )

    return {
        "session_id": session_id,
        "repository": session["repository"],
        "status": session["status"],
        "reports": session["reports"],
    }


# ============================================================
# APPROVAL MODEL
# ============================================================

class RepairApproval(BaseModel):
    session_id: str
    bug_id: int = 1


# ============================================================
# APPROVE & REPAIR
# ============================================================

@app.post("/api/repair/approve")
def approve_repair(
    request: RepairApproval,
):
    """
    Apply the approved patch.

    This is the ONLY endpoint that modifies the
    reconstructed repository.
    """

    session = SESSIONS.get(
        request.session_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Investigation session not found.",
        )

    if session["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is currently '{session['status']}'."
            ),
        )

    bug_index = request.bug_id - 1

    patches = session["patches"]

    if bug_index < 0 or bug_index >= len(patches):
        raise HTTPException(
            status_code=404,
            detail="Bug/patch not found.",
        )

    patch = patches[bug_index]

    if patch is None:
        raise HTTPException(
            status_code=400,
            detail="No patch was generated for this bug.",
        )

    if not patch.can_apply:
        raise HTTPException(
            status_code=400,
            detail=patch.generation_note,
        )

    repo_root = session["repo_root"]

    applicator = PatchApplicator(
        str(repo_root)
    )

    # --------------------------------------------------------
    # APPLY
    # --------------------------------------------------------

    apply_result = applicator.apply(
        patch
    )

    if not apply_result.success:

        session["status"] = "repair_failed"

        return {
            "success": False,
            "status": "repair_failed",
            "stage": "apply",
            "message": apply_result.message,
        }

    # --------------------------------------------------------
    # TARGETED TESTS
    # --------------------------------------------------------

    groups = session["groups"]

    if bug_index < len(groups):

        group = groups[bug_index]

        node_ids = [
            failure["node_id"]
            for failure in group["failures"]
        ]

    else:
        node_ids = []

    targeted = run_tests(
        repo_root,
        extra_args=node_ids or None,
        timeout=session["timeout"],
    )

    # --------------------------------------------------------
    # TARGETED TESTS FAILED
    # --------------------------------------------------------

    if targeted.failed > 0:

        restore_messages = applicator.restore(
            patch.file_path
        )

        session["status"] = "repair_failed"

        return {
            "success": False,
            "status": "repair_failed",
            "stage": "targeted_tests",
            "message": (
                "The proposed fix was applied, "
                "but the affected tests still fail."
            ),
            "targeted_tests": serialize_test_summary(
                targeted
            ),
            "rollback": restore_messages,
        }

    # --------------------------------------------------------
    # FULL REGRESSION
    # --------------------------------------------------------

    full_run = run_tests(
        repo_root,
        timeout=session["timeout"],
    )

    original_failure_ids = set(
        node_ids
    )

    new_failures = [
        test
        for test in full_run.failed_tests
        if test.node_id not in original_failure_ids
    ]

    # --------------------------------------------------------
    # REGRESSION
    # --------------------------------------------------------

    if new_failures:

        restore_messages = applicator.restore(
            patch.file_path
        )

        session["status"] = "regression"

        return {
            "success": False,
            "status": "regression",
            "stage": "full_regression",
            "message": (
                "The patch introduced new test failures. "
                "The change was rolled back."
            ),
            "targeted_tests": serialize_test_summary(
                targeted
            ),
            "full_tests": serialize_test_summary(
                full_run
            ),
            "new_failures": [
                test.node_id
                for test in new_failures
            ],
            "rollback": restore_messages,
        }

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    applicator.cleanup_backups()

    session["status"] = "repaired"

    # Create downloadable repaired repository.
    archive_base = (
        SESSION_DIR /
        f"{request.session_id}_repaired"
    )

    archive_path = shutil.make_archive(
        str(archive_base),
        "zip",
        root_dir=repo_root.parent,
        base_dir=repo_root.name,
    )

    add_history(
        {
            "id": request.session_id,
            "repository": session["repository"],
            "status": "repaired",
            "tests": {
                "total": full_run.total,
                "passed": full_run.passed,
                "failed": full_run.failed,
                "errors": full_run.errors,
            },
            "bug_count": len(
                session["reports"]
            ),
        }
    )

    return {
        "success": True,
        "status": "repaired",
        "message": (
            "Repair approved, applied, and verified successfully."
        ),
        "patch": {
            "file_path": patch.file_path,
            "target_line": patch.target_line,
            "original_line": patch.original_line,
            "replacement_line": patch.replacement_line,
            "diff": patch.diff_text,
        },
        "targeted_tests": serialize_test_summary(
            targeted
        ),
        "full_tests": serialize_test_summary(
            full_run
        ),
        "download": (
            f"/api/download/"
            f"{request.session_id}"
        ),
    }


# ============================================================
# REJECT REPAIR
# ============================================================

@app.post("/api/repair/reject")
def reject_repair(
    request: RepairApproval,
):

    session = SESSIONS.get(
        request.session_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Investigation session not found.",
        )

    session["status"] = "rejected"

    add_history(
        {
            "id": request.session_id,
            "repository": session["repository"],
            "status": "repair_rejected",
            "bug_count": len(
                session["reports"]
            ),
        }
    )

    return {
        "success": True,
        "status": "rejected",
        "message": (
            "Repair rejected. "
            "No source code was modified."
        ),
    }


# ============================================================
# RUN TESTS
# ============================================================

class TestRequest(BaseModel):
    session_id: str


@app.post("/api/tests")
def run_repository_tests(
    request: TestRequest,
):

    session = SESSIONS.get(
        request.session_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Investigation session not found.",
        )

    result = run_tests(
        session["repo_root"],
        timeout=session["timeout"],
    )

    return {
        "success": True,
        "summary": serialize_test_summary(
            result
        ),
    }


# ============================================================
# HISTORY
# ============================================================

@app.get("/api/history")
def get_history():
    return {
        "history": load_history()
    }


# ============================================================
# REPOSITORIES
# ============================================================

@app.get("/api/repositories")
def get_repositories():

    repositories = []

    for session_id, session in SESSIONS.items():

        repositories.append(
            {
                "session_id": session_id,
                "name": session["repository"],
                "status": session["status"],
            }
        )

    return {
        "repositories": repositories
    }


# ============================================================
# SETTINGS
# ============================================================

DEFAULT_SETTINGS = {
    "test_timeout": 60,
    "max_repair_iterations": 5,
    "auto_run_tests": True,
    "require_approval": True,
}


@app.get("/api/settings")
def get_settings():

    return {
        "settings": DEFAULT_SETTINGS
    }


# ============================================================
# DOWNLOAD REPAIRED REPOSITORY
# ============================================================

@app.get("/api/download/{session_id}")
def download_repaired_repository(
    session_id: str,
):

    session = SESSIONS.get(
        session_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found.",
        )

    archive = (
        SESSION_DIR /
        f"{session_id}_repaired.zip"
    )

    if not archive.exists():
        raise HTTPException(
            status_code=404,
            detail="No repaired repository is available.",
        )

    return FileResponse(
        path=archive,
        filename=(
            f"{session['repository']}_"
            f"repaired.zip"
        ),
        media_type="application/zip",
    )


# ============================================================
# CLEAN SESSION
# ============================================================

@app.delete("/api/session/{session_id}")
def delete_session(
    session_id: str,
):

    session = SESSIONS.pop(
        session_id,
        None,
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found.",
        )

    session_root = (
        SESSION_DIR /
        session_id
    )

    shutil.rmtree(
        session_root,
        ignore_errors=True,
    )

    return {
        "success": True,
        "message": "Investigation session removed.",
    }