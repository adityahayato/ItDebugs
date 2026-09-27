"""
itdebugs/patcher.py
====================
Patch generation and safe application for the ItDebugs repair loop.

Components
----------
PatchGenerator
    Converts a :class:`RootCauseHypothesis` into a concrete, human-readable
    unified diff that can be displayed for developer approval.

    Generation strategy (tried in order until one succeeds):
      1. Literal replacement — if ``faulty_code`` is a single non-empty line
         and ``suggested_fix`` describes changing one string to another,
         produce an exact line replacement.
      2. Wrong-literal detection — scan the target file for the ``faulty_code``
         snippet and replace the first match.
      3. Line-number replacement — use ``line_range`` to identify the target
         line and apply the best available substitution.

PatchApplicator
    Applies a :class:`ProposedPatch` to the repository.
    - Creates a ``.bak`` backup of each modified file before writing.
    - Provides ``restore()`` to roll back every file to its backup.
    - Never silently modifies files.

ProposedPatch
    Structured description of a single-file patch, including the unified diff
    text shown to the developer for approval.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from itdebugs.engine.reporter import RootCauseHypothesis


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class ProposedPatch:
    """
    A concrete code change proposed for developer review.

    Attributes
    ----------
    file_path : str
        Relative path (within the repository) of the file to modify.
    target_line : int
        1-based line number of the change.
    original_line : str
        The exact current text of that line (no trailing newline).
    replacement_line : str
        The replacement text for that line (no trailing newline).
    diff_text : str
        Human-readable unified diff shown to the developer.
    hypothesis : RootCauseHypothesis
        The source hypothesis this patch was derived from.
    can_apply : bool
        True when the patch is concrete enough to apply automatically.
    generation_note : str
        Explains how the patch was generated (for transparency).
    """

    file_path: str
    target_line: int
    original_line: str
    replacement_line: str
    diff_text: str
    hypothesis: RootCauseHypothesis
    can_apply: bool
    generation_note: str = ""


@dataclass
class ApplyResult:
    """Result of applying a patch."""

    success: bool
    file_path: str
    backup_path: str
    message: str
    bytes_written: int = 0


# ---------------------------------------------------------------------------
# PatchGenerator
# ---------------------------------------------------------------------------

class PatchGenerator:
    """
    Derives a :class:`ProposedPatch` from a :class:`RootCauseHypothesis`.
    """

    def generate(
        self,
        repo_root: str,
        hypothesis: RootCauseHypothesis,
    ) -> ProposedPatch:
        """
        Return the best patch we can derive from *hypothesis*.

        Parameters
        ----------
        repo_root:
            Absolute path to the repository root.
        hypothesis:
            Root-cause hypothesis from the investigation pipeline.
        """
        root = Path(repo_root)
        rel_path = hypothesis.file.replace("\\", "/")
        abs_path = root / rel_path

        # Parse target line number
        try:
            target_line = int(str(hypothesis.line_range).split("-")[0].strip())
        except (ValueError, AttributeError):
            target_line = 0

        # Read the target file
        try:
            source_lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return self._unpatchable(
                hypothesis, rel_path, target_line,
                reason=f"Could not read file: {exc}"
            )

        # ── Strategy 1: find faulty code in file, replace with fixed version ──
        faulty = (hypothesis.faulty_code or "").strip()
        if faulty:
            patch = self._strategy_find_and_replace(
                rel_path, source_lines, hypothesis, faulty, target_line
            )
            if patch is not None:
                return patch

        # ── Strategy 2: infer replacement from suggested_fix text ──────────
        if faulty and target_line > 0:
            patch = self._strategy_infer_fix(
                rel_path, source_lines, hypothesis, faulty, target_line
            )
            if patch is not None:
                return patch

        # ── Strategy 2b: extract replacement from explanation field ─────────
        if faulty and target_line > 0:
            patch = self._strategy_from_explanation(
                rel_path, source_lines, hypothesis, faulty, target_line
            )
            if patch is not None:
                return patch

        # ── Strategy 2c: scan file for dominant similar literal ───────────
        if faulty and target_line > 0:
            patch = self._strategy_scan_dominant_literal(
                rel_path, source_lines, hypothesis, faulty, target_line, root
            )
            if patch is not None:
                return patch

        # ── Strategy 3: target line number only ──────────────────────────────
        if target_line > 0 and 1 <= target_line <= len(source_lines):
            original = source_lines[target_line - 1]
            return self._unpatchable(
                hypothesis, rel_path, target_line,
                reason=(
                    "Could not generate a concrete replacement. "
                    "Manual edit required at the line shown below."
                ),
                original_line=original,
            )

        return self._unpatchable(
            hypothesis, rel_path, target_line,
            reason="Insufficient information to generate a concrete patch."
        )

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _strategy_find_and_replace(
        self,
        rel_path: str,
        source_lines: list[str],
        hypothesis: RootCauseHypothesis,
        faulty: str,
        hint_line: int,
    ) -> Optional[ProposedPatch]:
        """
        Search for the exact faulty code string in the file and replace it
        with a version derived from the suggested fix.
        """
        # Try to extract a string-literal replacement from the fix description
        replacement = self._extract_literal_replacement(hypothesis, faulty)
        if replacement is None:
            return None

        # Find the faulty line (prefer near hint_line)
        candidates = []
        for i, line in enumerate(source_lines, start=1):
            if faulty in line:
                candidates.append(i)

        if not candidates:
            return None

        # Pick the line closest to the hinted line number
        if hint_line > 0:
            target = min(candidates, key=lambda n: abs(n - hint_line))
        else:
            target = candidates[0]

        original_line = source_lines[target - 1]
        new_line = original_line.replace(faulty, replacement, 1)

        if new_line == original_line:
            return None

        diff = self._make_diff(rel_path, source_lines, target, new_line)

        return ProposedPatch(
            file_path=rel_path,
            target_line=target,
            original_line=original_line,
            replacement_line=new_line,
            diff_text=diff,
            hypothesis=hypothesis,
            can_apply=True,
            generation_note=(
                f"Strategy: literal replacement of '{faulty}' "
                f"-> '{replacement}' on line {target}."
            ),
        )

    def _strategy_infer_fix(
        self,
        rel_path: str,
        source_lines: list[str],
        hypothesis: RootCauseHypothesis,
        faulty: str,
        target_line: int,
    ) -> Optional[ProposedPatch]:
        """
        Try to infer the fix by extracting the first string-literal that
        appears in the suggested_fix description but not in the faulty code.
        """
        suggested = hypothesis.suggested_fix or ""

        # Find all quoted strings in the fix suggestion
        fix_literals = re.findall(r'"([^"]+)"|\'([^\']+)\'', suggested)
        fix_strings = [q[0] or q[1] for q in fix_literals]

        # Find all quoted strings in the faulty code
        faulty_literals = re.findall(r'"([^"]+)"|\'([^\']+)\'', faulty)
        faulty_strings = {q[0] or q[1] for q in faulty_literals}

        # A new string in the fix that isn't in the faulty code is the replacement
        new_strings = [s for s in fix_strings if s not in faulty_strings]
        if not new_strings:
            return None

        # Find which faulty string should be replaced
        if not faulty_strings:
            return None

        old_str = next(iter(faulty_strings))   # take the first
        new_str = new_strings[0]

        if 1 <= target_line <= len(source_lines):
            original_line = source_lines[target_line - 1]
        else:
            return None

        if old_str not in original_line:
            return None

        new_line = original_line.replace(f'"{old_str}"', f'"{new_str}"', 1)
        if new_line == original_line:
            new_line = original_line.replace(f"'{old_str}'", f"'{new_str}'", 1)
        if new_line == original_line:
            return None

        diff = self._make_diff(rel_path, source_lines, target_line, new_line)

        return ProposedPatch(
            file_path=rel_path,
            target_line=target_line,
            original_line=original_line,
            replacement_line=new_line,
            diff_text=diff,
            hypothesis=hypothesis,
            can_apply=True,
            generation_note=(
                f"Strategy: inferred replacement '{old_str}' -> '{new_str}' "
                f"from suggested_fix text (line {target_line})."
            ),
        )

    def _strategy_from_explanation(
        self,
        rel_path: str,
        source_lines: list[str],
        hypothesis: RootCauseHypothesis,
        faulty: str,
        target_line: int,
    ) -> Optional[ProposedPatch]:
        """
        Extract the replacement from the explanation field.

        The RootCauseAgent often writes things like:
          "similar literals found: ['completed', 'completed', ...]"
        in the explanation.  Pick the most frequent non-faulty literal.
        """
        explanation = hypothesis.explanation or ""

        # Quoted strings in the faulty code
        faulty_quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', faulty)
        faulty_strings = {q[0] or q[1] for q in faulty_quoted}
        if not faulty_strings:
            return None

        # All quoted/single-quoted strings in the explanation
        expl_quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', explanation)
        expl_strings = [q[0] or q[1] for q in expl_quoted]

        # Exclude the faulty strings themselves
        candidates = [s for s in expl_strings if s not in faulty_strings]
        if not candidates:
            return None

        # Pick the most frequent candidate
        from collections import Counter
        counts = Counter(candidates)
        best = counts.most_common(1)[0][0]

        old_str = next(iter(faulty_strings))
        if 1 <= target_line <= len(source_lines):
            original_line = source_lines[target_line - 1]
        else:
            return None

        if old_str not in original_line:
            return None

        new_line = original_line.replace(f'"{old_str}"', f'"{best}"', 1)
        if new_line == original_line:
            new_line = original_line.replace(f"'{old_str}'", f"'{best}'", 1)
        if new_line == original_line:
            return None

        diff = self._make_diff(rel_path, source_lines, target_line, new_line)
        return ProposedPatch(
            file_path=rel_path,
            target_line=target_line,
            original_line=original_line,
            replacement_line=new_line,
            diff_text=diff,
            hypothesis=hypothesis,
            can_apply=True,
            generation_note=(
                f"Strategy: explanation-based replacement '{old_str}' -> '{best}' "
                f"on line {target_line}."
            ),
        )

    def _strategy_scan_dominant_literal(
        self,
        rel_path: str,
        source_lines: list[str],
        hypothesis: RootCauseHypothesis,
        faulty: str,
        target_line: int,
        root: Path,
    ) -> Optional[ProposedPatch]:
        """
        Scan Python source files in the repo to find which string literal
        dominates for a given token.  For example, if the faulty code uses
        "complete" but every other occurrence uses "completed", replace with
        "completed".
        """
        faulty_quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', faulty)
        faulty_strings = {q[0] or q[1] for q in faulty_quoted}
        if not faulty_strings:
            return None

        old_str = next(iter(faulty_strings))

        # Scan all .py files in the repo for quoted variants of old_str
        from collections import Counter
        counts: Counter = Counter()
        for py_file in root.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            found = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
            for a, b in found:
                s = a or b
                # Consider strings that look like variants of old_str
                # (startswith match, or one contains the other)
                if s != old_str and (
                    s.startswith(old_str) or old_str.startswith(s)
                ):
                    counts[s] += 1

        if not counts:
            return None

        best = counts.most_common(1)[0][0]

        if 1 <= target_line <= len(source_lines):
            original_line = source_lines[target_line - 1]
        else:
            return None

        if old_str not in original_line:
            return None

        new_line = original_line.replace(f'"{old_str}"', f'"{best}"', 1)
        if new_line == original_line:
            new_line = original_line.replace(f"'{old_str}'", f"'{best}'", 1)
        if new_line == original_line:
            return None

        diff = self._make_diff(rel_path, source_lines, target_line, new_line)
        return ProposedPatch(
            file_path=rel_path,
            target_line=target_line,
            original_line=original_line,
            replacement_line=new_line,
            diff_text=diff,
            hypothesis=hypothesis,
            can_apply=True,
            generation_note=(
                f"Strategy: codebase-scan replacement '{old_str}' -> '{best}' "
                f"on line {target_line}."
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_literal_replacement(
        hypothesis: RootCauseHypothesis,
        faulty: str,
    ) -> Optional[str]:
        """
        Look for a pattern like:
          - "complete" should be "completed"
          - change "complete" to "completed"
          - replace "complete" with "completed"
          - != "complete"  →  != "completed"

        Returns the replacement string if found, else None.
        """
        fix_text = (hypothesis.suggested_fix or "") + " " + (hypothesis.explanation or "")

        # Quoted strings in the fix text
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', fix_text)
        fix_strings = [q[0] or q[1] for q in quoted]

        # Quoted strings in the faulty code
        faulty_quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', faulty)
        faulty_strings = {q[0] or q[1] for q in faulty_quoted}

        # String in the fix that is NOT in the faulty code
        new_strings = [s for s in fix_strings if s not in faulty_strings]
        old_strings = list(faulty_strings)

        if len(new_strings) == 1 and len(old_strings) == 1:
            # Exactly one replacement: old -> new
            old, new = old_strings[0], new_strings[0]
            # Quick sanity: lengths shouldn't differ by more than 50%
            if abs(len(old) - len(new)) <= max(len(old), len(new)) // 2 + 2:
                return new

        return None

    @staticmethod
    def _make_diff(
        rel_path: str,
        source_lines: list[str],
        target_line: int,
        new_line: str,
    ) -> str:
        """Build a unified-diff-style string for display."""
        context_before = max(0, target_line - 3)
        context_after = min(len(source_lines), target_line + 2)

        lines = []
        lines.append(f"--- a/{rel_path}")
        lines.append(f"+++ b/{rel_path}")

        # hunk header
        n_lines_old = context_after - context_before
        n_lines_new = n_lines_old
        lines.append(
            f"@@ -{context_before + 1},{n_lines_old} "
            f"+{context_before + 1},{n_lines_new} @@"
        )

        for i in range(context_before, context_after):
            line = source_lines[i]
            if i == target_line - 1:
                lines.append(f"-{line}")
                lines.append(f"+{new_line}")
            else:
                lines.append(f" {line}")

        return "\n".join(lines)

    @staticmethod
    def _unpatchable(
        hypothesis: RootCauseHypothesis,
        rel_path: str,
        target_line: int,
        reason: str,
        original_line: str = "",
    ) -> ProposedPatch:
        diff = (
            f"# Cannot generate automatic patch\n"
            f"# File   : {rel_path}\n"
            f"# Line   : {target_line}\n"
            f"# Reason : {reason}\n"
        )
        if original_line:
            diff += f"# Current: {original_line}\n"
        return ProposedPatch(
            file_path=rel_path,
            target_line=target_line,
            original_line=original_line,
            replacement_line="",
            diff_text=diff,
            hypothesis=hypothesis,
            can_apply=False,
            generation_note=reason,
        )


# ---------------------------------------------------------------------------
# PatchApplicator
# ---------------------------------------------------------------------------

class PatchApplicator:
    """
    Applies a :class:`ProposedPatch` to the repository after developer approval.

    Safety guarantees
    -----------------
    - Creates a ``.bak`` backup of each file before writing.
    - ``restore()`` rolls every modified file back to its backup.
    - Verifies that the original line still matches before writing.
    - Never modifies files unless ``apply()`` is explicitly called.
    """

    def __init__(self, repo_root: str) -> None:
        self._root = Path(repo_root)
        self._backups: dict[str, Path] = {}   # rel_path -> backup abs_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(self, patch: ProposedPatch) -> ApplyResult:
        """
        Apply *patch* to the repository.

        Returns an :class:`ApplyResult` describing success or failure.
        Never raises.
        """
        if not patch.can_apply:
            return ApplyResult(
                success=False,
                file_path=patch.file_path,
                backup_path="",
                message="Patch is not applicable (can_apply=False).",
            )

        abs_path = self._root / patch.file_path

        if not abs_path.exists():
            return ApplyResult(
                success=False,
                file_path=patch.file_path,
                backup_path="",
                message=f"Target file not found: {abs_path}",
            )

        # Read current content
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ApplyResult(
                success=False,
                file_path=patch.file_path,
                backup_path="",
                message=f"Could not read file: {exc}",
            )

        lines = text.splitlines(keepends=True)
        idx = patch.target_line - 1

        if not (0 <= idx < len(lines)):
            return ApplyResult(
                success=False,
                file_path=patch.file_path,
                backup_path="",
                message=(
                    f"Target line {patch.target_line} out of range "
                    f"(file has {len(lines)} lines)."
                ),
            )

        # Verify the line we're about to replace is what we expect
        current = lines[idx].rstrip("\r\n")
        if current != patch.original_line:
            return ApplyResult(
                success=False,
                file_path=patch.file_path,
                backup_path="",
                message=(
                    f"Line {patch.target_line} has changed since the patch "
                    f"was generated.  Expected:\n  {patch.original_line!r}\n"
                    f"Found:\n  {current!r}"
                ),
            )

        # Create backup
        backup_path = abs_path.with_suffix(abs_path.suffix + ".bak")
        try:
            shutil.copy2(abs_path, backup_path)
        except OSError as exc:
            return ApplyResult(
                success=False,
                file_path=patch.file_path,
                backup_path="",
                message=f"Could not create backup: {exc}",
            )

        self._backups[patch.file_path] = backup_path

        # Apply the change
        eol = "\n"
        if lines[idx].endswith("\r\n"):
            eol = "\r\n"
        lines[idx] = patch.replacement_line + eol

        new_text = "".join(lines)
        try:
            abs_path.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            # Restore from backup before returning
            shutil.copy2(backup_path, abs_path)
            return ApplyResult(
                success=False,
                file_path=patch.file_path,
                backup_path=str(backup_path),
                message=f"Write failed (backup restored): {exc}",
            )

        return ApplyResult(
            success=True,
            file_path=patch.file_path,
            backup_path=str(backup_path),
            message=(
                f"Applied patch to {patch.file_path} "
                f"(line {patch.target_line}). "
                f"Backup: {backup_path.name}"
            ),
            bytes_written=len(new_text.encode("utf-8")),
        )

    def restore(self, file_path: Optional[str] = None) -> list[str]:
        """
        Restore files from their backups.

        Parameters
        ----------
        file_path:
            If given, restore only that file.  Otherwise restore all.

        Returns
        -------
        List of messages (one per restored file).
        """
        messages = []
        targets = (
            [file_path]
            if file_path is not None
            else list(self._backups.keys())
        )

        for rel in targets:
            # Normalise separators so Windows backslash paths match stored keys
            rel_normalised = rel.replace("\\", "/") if rel else rel
            bak = self._backups.get(rel_normalised) or self._backups.get(rel)
            if bak is None or not bak.exists():
                messages.append(f"No backup found for {rel}.")
                continue
            abs_path = self._root / rel
            try:
                shutil.copy2(bak, abs_path)
                bak.unlink(missing_ok=True)
                self._backups.pop(rel_normalised, None)
                self._backups.pop(rel, None)
                messages.append(f"Restored {rel} from backup.")
            except OSError as exc:
                messages.append(f"Failed to restore {rel}: {exc}")

        return messages

    def cleanup_backups(self) -> None:
        """Delete all backup files (called on successful repair)."""
        for bak in list(self._backups.values()):
            try:
                bak.unlink(missing_ok=True)
            except OSError:
                pass
        self._backups.clear()
