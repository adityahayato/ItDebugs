"""
itdebugs/investigate.py
=======================
CLI entry point for the ItDebugs investigation engine.

Usage
-----
    python -m itdebugs.investigate \\
        --repo  demo/buggy-project \\
        --bug   "Completed tasks are appearing in the pending task list."

    # Use the orchestrated multi-agent pipeline (default):
    python -m itdebugs.investigate --repo demo/buggy-project \\
        --bug "Completed tasks are appearing in the pending task list." \\
        --mode orchestrated

    # Use the legacy single-class engine:
    python -m itdebugs.investigate --repo demo/buggy-project \\
        --bug "Completed tasks are appearing in the pending task list." \\
        --mode legacy

Options
-------
  --repo  PATH          Path to the repository to investigate (required)
  --bug   TEXT          Natural-language bug description (required)
  --mode  MODE          'orchestrated' (default) or 'legacy'
  --out   FILE          Write the report to this file in addition to stdout
  --timeout SECONDS     Pytest timeout (default: 60)
  --verbose             Print progress messages to stderr
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python -m itdebugs.investigate` from the project root
# without installing the package.
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from itdebugs.engine.investigator import Investigator
from itdebugs.engine.reporter import render_text
from itdebugs.orchestrator import Orchestrator


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="itdebugs",
        description="ItDebugs - agentic developer debugging assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--repo",
        required=True,
        metavar="PATH",
        help="Path to the repository root to investigate.",
    )
    p.add_argument(
        "--bug",
        required=True,
        metavar="TEXT",
        help="Natural-language description of the bug to investigate.",
    )
    p.add_argument(
        "--mode",
        choices=["orchestrated", "legacy"],
        default="orchestrated",
        metavar="MODE",
        help=(
            "Investigation mode: 'orchestrated' (default) runs the multi-agent "
            "pipeline; 'legacy' runs the original single-class engine."
        ),
    )
    p.add_argument(
        "--out",
        metavar="FILE",
        default=None,
        help="Optional path to write the report to (plain text / Markdown).",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SECONDS",
        help="Wall-clock timeout for the pytest run (default: 60).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print investigation progress to stderr.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """
    Entry point.  Returns an exit code:
      0  investigation completed successfully (even if no root cause found)
      1  investigation failed (could not scan repo, tests couldn't run, etc.)
      2  bad arguments
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    if not repo.exists():
        print(f"[ItDebugs] ERROR: repository path does not exist: {repo}", file=sys.stderr)
        return 2

    if args.mode == "orchestrated":
        # ── Multi-agent orchestrated pipeline ─────────────────────────────
        orchestrator = Orchestrator(
            repo_path=str(repo),
            bug_description=args.bug,
            test_timeout=args.timeout,
            verbose=args.verbose,
        )
        report = orchestrator.run()

    else:
        # ── Legacy single-class engine (unchanged) ─────────────────────────
        print(f"\n[ItDebugs] Starting investigation (legacy mode) ...", file=sys.stderr)
        print(f"  Repository : {repo.resolve()}", file=sys.stderr)
        print(f"  Bug report : {args.bug}\n", file=sys.stderr)

        investigator = Investigator(
            repo_path=str(repo),
            bug_description=args.bug,
            test_timeout=args.timeout,
            verbose=args.verbose,
        )
        report = investigator.investigate()

    text = render_text(report)

    # Always print to stdout
    print(text)

    # Optionally write to file
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(text, encoding="utf-8")
        print(f"\n[ItDebugs] Report written to: {out_path.resolve()}", file=sys.stderr)

    if not report.investigation_successful:
        print(f"\n[ItDebugs] Investigation FAILED: {report.error_message}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
