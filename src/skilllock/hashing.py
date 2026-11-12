"""Hashing, exactly as section 5 of the specification defines it.

The canonical directory hash is a `sha256sum`-shaped manifest so it can be
reproduced by hand:

    find . -type f | sort | xargs sha256sum | sha256sum

That reproducibility is the point. When someone reports a hash mismatch on a
machine without this tool, they can check it with standard tools.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Section 5.2: excluded from both the file list and the directory hash.
EXCLUDED_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}

# SKILL.md is a dotfile? No — but the rule allows dotfiles to be excluded
# *except* this one, so it is named explicitly to make the intent obvious.
ALWAYS_INCLUDE = {"SKILL.md"}


@dataclass(frozen=True)
class FileHash:
    path: str
    digest: str


def normalise_hash(value: str) -> str:
    """Return a `sha256:<hex>` string, accepting bare hex too."""
    value = value.strip().lower()
    if value.startswith("sha256:"):
        value = value[len("sha256:") :]
    return f"sha256:{value}"


def is_excluded(relative: Path) -> bool:
    """Apply section 5.2."""
    parts = relative.parts
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    if relative.name in EXCLUDED_NAMES:
        return True
    if relative.suffix in EXCLUDED_SUFFIXES:
        return True
    # A dotfile anywhere in the path is excluded, unless it is the skill entry
    # point itself.
    if relative.name in ALWAYS_INCLUDE:
        return False
    if any(part.startswith(".") for part in parts):
        return True
    return False


def hash_file(path: Path) -> str:
    """Hash one file's raw bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def collect_files(skill_dir: Path) -> list[FileHash]:
    """Every included file in the skill, sorted by path bytes."""
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"not a directory: {skill_dir}")

    entries: list[FileHash] = []
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir)
        if is_excluded(relative):
            continue
        entries.append(
            FileHash(
                path=str(relative).replace("\\", "/"),
                digest=hash_file(path),
            )
        )

    entries.sort(key=lambda e: e.path.encode("utf-8"))
    return entries


def directory_hash(entries: list[FileHash]) -> str:
    """Section 5.4: hash of the canonical manifest form."""
    lines = []
    for entry in sorted(entries, key=lambda e: e.path.encode("utf-8")):
        hex_digest = entry.digest.split(":", 1)[1]
        lines.append(f"{hex_digest}  {entry.path}\n")
    payload = "".join(lines).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def hash_skill(skill_dir: Path) -> tuple[str, list[FileHash]]:
    """Return (directory hash, per-file hashes) for a skill directory."""
    entries = collect_files(skill_dir)
    return directory_hash(entries), entries