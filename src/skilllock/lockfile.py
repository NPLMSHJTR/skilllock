"""Read and write skilllock.toml according to specification version 1.

Reading uses `tomllib` on 3.11+ and falls back to a small parser on 3.9/3.10,
because a lockfile reader that requires the newest Python is a lockfile nobody
runs in CI on an older image.

Writing is hand-rolled on purpose. `tomli-w` would be a dependency, and the
format here is narrow enough that a writer is thirty lines. It also lets the
output be ordered deliberately, which matters: a lockfile that reorders itself
between runs produces noisy diffs and hides real changes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib as _tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.9 / 3.10
    _tomllib = None

SPEC_VERSION = 1
FILENAME = "skilllock.toml"


class LockfileError(Exception):
    """A lockfile that does not conform to the specification."""


@dataclass
class FileEntry:
    path: str
    hash: str


@dataclass
class Dependency:
    name: str
    constraint: str = "*"


@dataclass
class SkillEntry:
    name: str
    source: str
    revision: str
    path: str
    hash: str
    files: list[FileEntry] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)


@dataclass
class Lockfile:
    version: int = SPEC_VERSION
    skills: list[SkillEntry] = field(default_factory=list)

    def by_name(self, name: str) -> SkillEntry | None:
        return next((s for s in self.skills if s.name == name), None)

    def names(self) -> list[str]:
        return [s.name for s in self.skills]


# --- validation -------------------------------------------------------------


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise LockfileError(f"{where}: missing required field `{key}`")
    value = mapping[key]
    if isinstance(value, str) and not value.strip():
        raise LockfileError(f"{where}: field `{key}` is empty")
    return value


def validate(lock: Lockfile) -> None:
    """Enforce section 8 conformance points 1-3 and 6, on an in-memory file."""
    if lock.version != SPEC_VERSION:
        raise LockfileError(
            f"unsupported lockfile version {lock.version}; this tool implements "
            f"version {SPEC_VERSION}"
        )

    seen: set[str] = set()
    for skill in lock.skills:
        if skill.name in seen:
            raise LockfileError(f"duplicate skill name: {skill.name}")
        seen.add(skill.name)

        if not skill.revision.strip():
            raise LockfileError(f"{skill.name}: revision is empty")
        if skill.source.startswith("path:"):
            if skill.revision != "local":
                raise LockfileError(
                    f"{skill.name}: a path: source must use revision \"local\""
                )
        elif not _looks_immutable(skill.revision):
            raise LockfileError(
                f"{skill.name}: revision `{skill.revision}` is not an immutable "
                "identifier. A branch name defeats the purpose of a lockfile; "
                "use a full commit SHA or a release tag."
            )

        for dependency in skill.dependencies:
            if dependency.name not in seen and dependency.name not in {
                s.name for s in lock.skills
            }:
                raise LockfileError(
                    f"{skill.name}: dependency `{dependency.name}` has no entry "
                    "in this lockfile. The lockfile must record the resolved "
                    "closure."
                )


def _looks_immutable(revision: str) -> bool:
    """A full SHA, or something that looks like a version tag."""
    if len(revision) == 40 and all(c in "0123456789abcdef" for c in revision.lower()):
        return True
    # A tag such as v1.2.3 or 2026.11.12. Anything without a digit is treated as
    # a branch name, which is the case this check exists to reject.
    return any(c.isdigit() for c in revision)


# --- reading ----------------------------------------------------------------


def _parse_fallback(text: str) -> dict:
    """Minimal TOML reader for the subset this format uses.

    Handles: `key = value` scalars, `[[array.of.tables]]`, and nothing else.
    Enough for 3.9/3.10; `tomllib` is used everywhere it exists.
    """
    root: dict = {}
    current: dict | None = None
    current_path: list[str] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[[") and line.endswith("]]"):
            path = line[2:-2].strip().split(".")
            node = root
            for part in path[:-1]:
                node = node.setdefault(part, {})
                if isinstance(node, list):
                    node = node[-1]
            array = node.setdefault(path[-1], [])
            current = {}
            array.append(current)
            current_path = path
            continue

        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                parsed: object = value[1:-1]
            elif value in ("true", "false"):
                parsed = value == "true"
            else:
                try:
                    parsed = int(value)
                except ValueError:
                    parsed = value
            if current is None:
                root[key] = parsed
            else:
                current[key] = parsed

    del current_path
    return root


def _coerce(data: dict) -> Lockfile:
    version = data.get("version")
    if not isinstance(version, int):
        raise LockfileError("`version` must be an integer")

    # Spec section 8 point 1: an unknown version must be rejected before
    # anything else is inspected. A consumer that parses the body first will
    # report a confusing field error for a file it should refuse outright,
    # because the field names may mean something different in that version.
    if version != SPEC_VERSION:
        raise LockfileError(
            f"unsupported lockfile version {version}; this tool implements "
            f"version {SPEC_VERSION}"
        )

    lock = Lockfile(version=version)
    raw_skills = data.get("skill") or []
    if not isinstance(raw_skills, list):
        raise LockfileError("`skill` must be an array of tables")

    for index, raw in enumerate(raw_skills):
        where = f"skill[{index}]"
        if not isinstance(raw, dict):
            raise LockfileError(f"{where}: expected a table")

        files = []
        for file_index, raw_file in enumerate(raw.get("file") or []):
            files.append(
                FileEntry(
                    path=_require(raw_file, "path", f"{where}.file[{file_index}]"),
                    hash=_require(raw_file, "hash", f"{where}.file[{file_index}]"),
                )
            )

        dependencies = []
        for dep_index, raw_dep in enumerate(raw.get("dependency") or []):
            dependencies.append(
                Dependency(
                    name=_require(
                        raw_dep, "name", f"{where}.dependency[{dep_index}]"
                    ),
                    constraint=raw_dep.get("constraint", "*"),
                )
            )

        lock.skills.append(
            SkillEntry(
                name=_require(raw, "name", where),
                source=_require(raw, "source", where),
                revision=_require(raw, "revision", where),
                path=_require(raw, "path", where),
                hash=_require(raw, "hash", where),
                files=files,
                dependencies=dependencies,
            )
        )

    return lock


def read(path: Path) -> Lockfile:
    """Parse and validate a lockfile."""
    text = path.read_text(encoding="utf-8")
    if _tomllib is not None:
        try:
            data = _tomllib.loads(text)
        except _tomllib.TOMLDecodeError as exc:
            raise LockfileError(f"not valid TOML: {exc}") from exc
    else:  # pragma: no cover
        data = _parse_fallback(text)

    lock = _coerce(data)
    validate(lock)
    return lock


# --- writing ----------------------------------------------------------------


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render(lock: Lockfile) -> str:
    """Serialise a lockfile. Deterministic ordering, so diffs mean something."""
    lines = [
        "# Generated by skilllock. Do not edit by hand.",
        "# Format: https://github.com/NPLMSHJTR/skilllock/blob/main/spec/lockfile-v1.md",
        "",
        f"version = {lock.version}",
    ]

    for skill in sorted(lock.skills, key=lambda s: s.name):
        lines.append("")
        lines.append("[[skill]]")
        lines.append(f"name = {_quote(skill.name)}")
        lines.append(f"source = {_quote(skill.source)}")
        lines.append(f"revision = {_quote(skill.revision)}")
        lines.append(f"path = {_quote(skill.path)}")
        lines.append(f"hash = {_quote(skill.hash)}")

        for entry in sorted(skill.files, key=lambda f: f.path):
            lines.append("")
            lines.append("  [[skill.file]]")
            lines.append(f"  path = {_quote(entry.path)}")
            lines.append(f"  hash = {_quote(entry.hash)}")

        for dependency in sorted(skill.dependencies, key=lambda d: d.name):
            lines.append("")
            lines.append("  [[skill.dependency]]")
            lines.append(f"  name = {_quote(dependency.name)}")
            lines.append(f"  constraint = {_quote(dependency.constraint)}")

    return "\n".join(lines) + "\n"


def write(lock: Lockfile, path: Path) -> None:
    path.write_text(render(lock), encoding="utf-8", newline="\n")