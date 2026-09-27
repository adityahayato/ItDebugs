"""
CLI entry point for the ItDebugs investigation engine.

Single-bug mode:

    python -m itdebugs.investigate \
        --repo demo/buggy-project \
        --bug "Completed tasks are appearing in the pending task list."

Automatic multi-bug mode:

    python -m itdebugs.investigate \
        --repo demo/buggy-project \
        --auto

Legacy mode:

    python -m itdebugs.investigate \
        --repo demo/buggy-project \
        --bug "Completed tasks are appearing in the pending task list." \
        --mode legacy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python -m itdebugs.investigate`
# from the project root without installing the package.
_HERE = Path(__file__).resolve().parent.parent

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from itdebugs.engine.investigator import Investigator
from itdebugs.engine.reporter import render_text
from itdebugs.multi_bug import (
    investigate_repository,
    render_multi_bug_report,
)
from itdebugs.orchestrator import Orchestrator
from itdebugs.repair_loop import RepairLoop


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
        metavar="TEXT",
        default=None,
        help=(
            "Natural-language description of one bug to investigate. "
            "Required unless --auto is used."
        ),
    )

    p.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Automatically discover all failing tests and investigate "
            "the resulting bug groups."
        ),
    )

    p.add_argument(
        "--repair",
        action="store_true",
        help=(
            "Autonomous repair loop: investigate failures, generate a "
            "patch, prompt for approval, apply the patch, retest, and "
            "repeat until all tests pass or max iterations are reached."
        ),
    )

    p.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        metavar="N",
        help="Maximum repair iterations (default: 5, used with --repair).",
    )

    p.add_argument(
        "--mode",
        choices=["orchestrated", "legacy"],
        default="orchestrated",
        metavar="MODE",
        help=(
            "Investigation mode for --bug: 'orchestrated' runs the "
            "multi-agent pipeline; 'legacy' runs the original engine."
        ),
    )

    p.add_argument(
        "--out",
        metavar="FILE",
        default=None,
        help="Optional path to write the report.",
    )

    p.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SECONDS",
        help="Pytest timeout (default: 60).",
    )

    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed investigation progress.",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    repo = Path(args.repo)

    if not repo.exists():
        print(
            f"[ItDebugs] ERROR: repository path does not exist: {repo}",
            file=sys.stderr,
        )
        return 2

    # ================================================================
    # AUTOMATIC MULTI-BUG MODE
    # ================================================================

    if args.auto:
        result = investigate_repository(
            repo,
            timeout=args.timeout,
            verbose=args.verbose,
        )

        text = render_multi_bug_report(result)

        print(text)

        if args.out:
            out_path = Path(args.out)
            out_path.write_text(
                text,
                encoding="utf-8",
            )

            print(
                f"\n[ItDebugs] Report written to: "
                f"{out_path.resolve()}",
                file=sys.stderr,
            )

        if not result.investigation_successful:
            return 1

        return 0

    # ================================================================
    # REPAIR MODE
    # ================================================================

    if args.repair:
        loop = RepairLoop(
            repo_path=str(repo),
            max_iterations=args.max_iterations,
            test_timeout=args.timeout,
            verbose=args.verbose,
        )
        repair_result = loop.run()
        summary = repair_result.summary()
        print(summary)

        if args.out:
            out_path = Path(args.out)
            out_path.write_text(summary, encoding="utf-8")
            print(
                f"\n[ItDebugs] Report written to: {out_path.resolve()}",
                file=sys.stderr,
            )

        return 0 if repair_result.all_green else 1

    # ================================================================
    # SINGLE-BUG MODE
    # ================================================================

    if not args.bug:
        parser.error(
            "--bug is required unless --auto is specified."
        )

    if args.mode == "orchestrated":

        orchestrator = Orchestrator(
            repo_path=str(repo),
            bug_description=args.bug,
            test_timeout=args.timeout,
            verbose=args.verbose,
        )

        report = orchestrator.run()

    else:

        print(
            "\n[ItDebugs] Starting investigation "
            "(legacy mode) ...",
            file=sys.stderr,
        )

        print(
            f"  Repository : {repo.resolve()}",
            file=sys.stderr,
        )

        print(
            f"  Bug report : {args.bug}\n",
            file=sys.stderr,
        )

        investigator = Investigator(
            repo_path=str(repo),
            bug_description=args.bug,
            test_timeout=args.timeout,
            verbose=args.verbose,
        )

        report = investigator.investigate()

    text = render_text(report)

    print(text)

    if args.out:
        out_path = Path(args.out)

        out_path.write_text(
            text,
            encoding="utf-8",
        )

        print(
            f"\n[ItDebugs] Report written to: "
            f"{out_path.resolve()}",
            file=sys.stderr,
        )

    if not report.investigation_successful:
        print(
            f"\n[ItDebugs] Investigation FAILED: "
            f"{report.error_message}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())