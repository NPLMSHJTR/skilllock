"""Verify a locked skill against the files on disk.

This is section 8 points 4 and 5: the directory hash and every per-file hash must
match, and a file present on disk that the lockfile does not list is a failure.

Why an unlisted file is a failure rather than a warning: a skill is instructions
for an agent. A file nobody locked is a file nobody reviewed, and it will still be
read. Refusing is the only safe default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .hashing import collect_files, directory_hash
from .lockfile import SkillEntry


@dataclass
class VerifyResult:
    skill: str
    ok: bool
    problems: list[str] = field(default_factory=list)
    checked: int = 0

    def summary(self) -> str:
        if self.ok:
            return f"{self.skill}: {self.checked} file(s) verified"
        return f"{self.skill}: {len(self.problems)} problem(s)"


def verify_skill(entry: SkillEntry, skill_dir: Path) -> VerifyResult:
    """Check one skill directory against one lockfile entry."""
    result = VerifyResult(skill=entry.name, ok=False)

    if not skill_dir.is_dir():
        result.problems.append(f"directory does not exist: {skill_dir}")
        return result

    actual = collect_files(skill_dir)
    actual_by_path = {f.path: f.digest for f in actual}
    locked_by_path = {f.path: f.hash for f in entry.files}

    result.checked = len(entry.files)

    # Point 5: a file on disk that the lockfile does not list.
    for path in sorted(set(actual_by_path) - set(locked_by_path)):
        result.problems.append(f"unlisted file present on disk: {path}")

    # A locked file that is missing.
    for path in sorted(set(locked_by_path) - set(actual_by_path)):
        result.problems.append(f"locked file is missing on disk: {path}")

    # Changed content.
    for path in sorted(set(locked_by_path) & set(actual_by_path)):
        if locked_by_path[path] != actual_by_path[path]:
            result.problems.append(f"content differs: {path}")

    # Point 4: the directory hash.
    computed = directory_hash(actual)
    if computed != entry.hash:
        result.problems.append(
            f"directory hash mismatch: lockfile says {entry.hash[:19]}…, "
            f"content hashes to {computed[:19]}…"
        )

    result.ok = not result.problems
    return result


def verify_all(
    skills: dict[str, Path], entries: list[SkillEntry]
) -> list[VerifyResult]:
    """Verify several skills. `skills` maps name to its directory on disk."""
    results: list[VerifyResult] = []
    for entry in entries:
        directory = skills.get(entry.name)
        if directory is None:
            results.append(
                VerifyResult(
                    skill=entry.name,
                    ok=False,
                    problems=["no directory provided to verify"],
                )
            )
            continue
        results.append(verify_skill(entry, directory))
    return results